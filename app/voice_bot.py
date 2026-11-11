"""Bridges Pipecat's voice pipeline to the Phase 2/3 text agent.

The BUILD_PLAN's pipeline diagram is:

    transport.input -> Silero VAD -> Sarvam STT -> user aggregator
        -> LLM (with tools from Phase 2) -> Sarvam TTS
        -> transport.output -> assistant aggregator

`Agent` (app/agent.py) already *is* the "user aggregator -> LLM (with tools)"
step: it keeps per-session history and runs the tool-calling loop, tested
against a `FakeLLM` in Phase 2/3. `AgentProcessor` below is only the bridge
between Pipecat's STT/TTS frames and that existing, already-tested loop — it
must never reimplement tool-calling itself (see
tests/integration/test_voice_text_equivalence.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import yaml
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamHttpTTSService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

from app.agent import FALLBACK_MESSAGE, Agent, SarvamLLMClient
from app.config import get_settings
from app.db import CallLog, get_session
from app.metrics import TurnTracker, ensure_file_sink
from app.speech import detect_lang, normalise_for_speech
from app.stt_noise import is_noise

OnToolCall = Callable[[str, dict[str, Any], dict[str, Any]], None]
OnTurn = Callable[[str, str], None]
EndCall = Callable[[], Awaitable[None]]

# BUILD_PLAN 5.3: after this many seconds of the bot waiting (not thinking,
# not speaking) for the caller to say something, SilenceProcessor reprompts
# once, then ends the call after a second silent window of the same length.
SILENCE_TIMEOUT_SECS = 5.0
SILENCE_REPROMPT_TEXT = "Hello, kya aap line par hain?"
SILENCE_GOODBYE_TEXT = "Theek hai, main call band kar rahi hoon. Dhanyavaad, alvida!"

# BUILD_PLAN 5.4: spoken when Agent.handle_turn()'s on_slow_tool fires (a
# single tool call running past app.agent.FILLER_THRESHOLD_SECS).
FILLER_TEXT = "Ek second, check karti hoon..."

CLINIC_PATH = Path(__file__).resolve().parent.parent / "data" / "clinic.yaml"

# Trailing silence (seconds) Silero VAD waits before finalizing a stop.
# Pipecat's default is 0.2s -- too short for natural Hinglish speech: the
# Phase 4 live test showed a caller's "haan, kar do" land as two separate
# VAD-detected utterances 0.6s apart, so the agent only ever saw an isolated,
# unconfirmable "haan" fragment and escalated to a human instead of booking.
# 0.7s survives that gap with margin. See docs/architecture.md's Phase 5 note
# for the latency tradeoff and why this is provisional pending Phase 5's
# multi-person manual call check.
VAD_STOP_SECS = 0.7


def placeholder_caller_phone(session_id: str) -> str:
    """A valid-shaped but fake caller phone, deterministic per session.

    A browser WebRTC call has no real phone number (that arrives with
    Twilio in Phase 8), but `Agent` still needs *some* `caller_phone` —
    `book_appointment`/`cancel_appointment`/`reschedule_appointment` all
    require one (see `app.tools.PHONE_INJECTED_TOOLS`); without it, every
    one of those calls raises `TypeError: missing 1 required keyword-only
    argument: 'phone'`, which the agent retries until it exhausts its tool
    rounds and falls back to a generic error. Derived from the session id
    (not random) so two concurrent browser testers get different phones —
    `booking.py` keys cancel/reschedule by phone, so sharing one fixed
    placeholder would let one tester's session see another's appointment.
    """
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    digits = str(int(digest[:12], 16))[-10:].zfill(10)
    return f"+91{digits}"


@dataclass
class CallLogger:
    """Saves one call's transcript to `CallLog`, one turn at a time.

    A browser call has no phone number (that arrives with Twilio in Phase 8),
    so `caller` is the WebRTC session id for now.
    """

    caller: str
    log_id: int | None = field(default=None, init=False)

    def start(self, *, now: datetime | None = None) -> None:
        with get_session() as session:
            entry = CallLog(caller=self.caller, started_at=now or datetime.now(UTC))
            session.add(entry)
            session.commit()
            session.refresh(entry)
            self.log_id = entry.id

    def record_turn(self, user_text: str, reply: str) -> None:
        if self.log_id is None:
            raise RuntimeError("CallLogger.record_turn called before start()")
        with get_session() as session:
            entry = session.get(CallLog, self.log_id)
            entry.transcript += f"Caller: {user_text}\nBot: {reply}\n"
            session.add(entry)
            session.commit()

    def end(self, outcome: str = "", *, now: datetime | None = None) -> None:
        if self.log_id is None:
            raise RuntimeError("CallLogger.end called before start()")
        with get_session() as session:
            entry = session.get(CallLog, self.log_id)
            if entry.ended_at is not None:
                # Already ended - e.g. SilenceProcessor's end_call() already
                # logged outcome="dropped" and is now tearing down the
                # transport, which would otherwise trigger the normal
                # on_client_disconnected handler's end() right after and
                # silently overwrite that outcome with the default "".
                return
            entry.ended_at = now or datetime.now(UTC)
            entry.outcome = outcome
            session.add(entry)
            session.commit()


class AgentProcessor(FrameProcessor):
    """Turns a final STT transcription into an `Agent` reply, as TTS text frames.

    One `AgentProcessor` serves one call: `session_id` is the key `Agent`
    uses to keep that call's conversation history separate from others.
    """

    def __init__(
        self,
        agent: Agent,
        *,
        session_id: str = "default",
        on_tool_call: OnToolCall | None = None,
        on_turn: OnTurn | None = None,
        turn_tracker: TurnTracker | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.session_id = session_id
        self.on_tool_call = on_tool_call
        self.on_turn = on_turn
        self.turn_tracker = turn_tracker
        # Set True by an InterruptionFrame that arrives mid-turn (see below) and
        # reset at the start of every new turn. Only suppresses *speaking* -
        # handle_turn() itself is never cancelled (see the `frame.interruptible =
        # False` note below), so a tool call already decided on (e.g. a booking)
        # always finishes and lands in history even if the caller stops hearing it.
        self._interrupted = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            self._interrupted = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, VADUserStoppedSpeakingFrame):
            if self.turn_tracker is not None:
                self.turn_tracker.mark_speech_end(frame.timestamp)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame) and not is_noise(frame.text):
            self._interrupted = False

            # Never cancel a booking halfway (BUILD_PLAN 5.2's #1 concern):
            # Pipecat's default interruption handling cancels whatever task is
            # currently processing a frame in this processor. If the caller
            # starts talking again while handle_turn() is still mid-loop (e.g.
            # awaiting the LLM's next round right after a book_appointment tool
            # call already committed), a cancellation there would abandon that
            # tool's result before it's recorded in history, even though the
            # booking itself already happened. Marking this frame uninterruptible
            # (see Frame.interruptible's docstring - this is Pipecat's own
            # mechanism for exactly this, also used internally by its Flows
            # manager) keeps this processor's task running to natural
            # completion; `self._interrupted` above is what actually stops the
            # *speaking*, via the on_reply_chunk guard below.
            frame.interruptible = False

            if self.turn_tracker is not None:
                self.turn_tracker.mark_stt_final(time.time())

            await self.push_frame(LLMFullResponseStartFrame(), direction)

            # Turn-scoped: tracks whether any content chunk was streamed for *this*
            # turn. This is a different scope from the tool-call suppression gate
            # inside Agent.handle_turn() (saw_tool_call_delta), which is round-scoped
            # (reset every tool-calling round within a turn). Known gap this doesn't
            # fix: a turn that streams some preamble content in an early round and
            # then exhausts max_tool_rounds in a later round (hitting FALLBACK_MESSAGE
            # via the *normal* return path, not an exception) still won't have the
            # fallback message pushed here, since first_chunk_seen is already True -
            # same gap as before this change, only the exception case below is fixed.
            first_chunk_seen = False

            async def on_reply_chunk(chunk: str) -> None:
                nonlocal first_chunk_seen
                if self._interrupted:
                    # Drop remaining chunks after an interruption (BUILD_PLAN
                    # 5.2's #2 concern) - handle_turn() keeps running so its
                    # tool calls and history update still complete, but nothing
                    # more of this turn's reply reaches TTS once the caller has
                    # started talking again.
                    return
                if self.turn_tracker is not None and not first_chunk_seen:
                    self.turn_tracker.mark_llm_first_token(time.time())
                first_chunk_seen = True
                await self.push_frame(TextFrame(chunk), direction)

            async def on_slow_tool() -> None:
                # BUILD_PLAN 5.4: a fixed phrase from code, not LLM-generated
                # content, so it's safe to speak even though this round
                # contains a tool call - the suppression gate above only ever
                # exists to stop *LLM* preambles from being spoken. Pushed as
                # a TTSSpeakFrame (bypasses the sentence aggregator - it would
                # otherwise sit waiting for punctuation that never arrives)
                # and skipped once the caller has already started talking
                # again, same reasoning as on_reply_chunk's guard.
                if not self._interrupted:
                    await self.push_frame(TTSSpeakFrame(text=FILLER_TEXT), direction)

            def on_usage(usage: dict[str, int]) -> None:
                # BUILD_PLAN 5.7a: the latest round's usage wins if a turn
                # has more than one (each tool-calling round has its own
                # trailer) - that's the round whose generation is what
                # llm_first_token/llm_latency_ms actually measured.
                if self.turn_tracker is not None:
                    self.turn_tracker.mark_usage(usage)

            turn_failed = False
            try:
                reply = await self.agent.handle_turn(
                    self.session_id,
                    frame.text,
                    on_tool_call=self.on_tool_call,
                    on_reply_chunk=on_reply_chunk,
                    on_slow_tool=on_slow_tool,
                    on_usage=on_usage,
                )
            except Exception:  # noqa: BLE001 - Sarvam's HTTP call is known-flaky
                # (httpx.ReadTimeout etc.); any exception here must still close out
                # the turn with a fallback, not propagate and leave TTS's turn
                # context open for the next caller turn.
                logger.exception("Agent.handle_turn failed mid-stream; falling back")
                reply = FALLBACK_MESSAGE
                turn_failed = True

            if (not first_chunk_seen or turn_failed) and not self._interrupted:
                # handle_turn() can return a reply (e.g. FALLBACK_MESSAGE, after
                # hitting max_tool_rounds) without ever streaming content through
                # on_reply_chunk - push it now so the caller still hears something.
                # Also pushed when handle_turn() raised mid-stream (turn_failed),
                # even if some chunks were already streamed before the failure.
                # Never pushed if the caller already started talking again
                # (self._interrupted) - same reasoning as the on_reply_chunk guard
                # above: don't start speaking a fresh reply over an interruption.
                if self.turn_tracker is not None and not first_chunk_seen:
                    self.turn_tracker.mark_llm_first_token(time.time())
                await self.push_frame(TextFrame(reply), direction)

            if self.on_turn is not None:
                self.on_turn(frame.text, reply)
            await self.push_frame(LLMFullResponseEndFrame(), direction)
            return

        await self.push_frame(frame, direction)


class BargeInProcessor(FrameProcessor):
    """Stops TTS immediately when the caller starts speaking.

    Sits right after `VADProcessor` in `build_pipeline()`. Pipecat's base
    `TTSService._handle_interruption()` (used by both the HTTP and WebSocket
    Sarvam TTS services) already resets text aggregation and drops
    queued/in-flight audio on receiving an `InterruptionFrame` - the only
    thing missing was something that actually broadcasts one when the caller
    starts talking, which is this processor's entire job. No new VAD tuning
    needed: `start_secs=0.2s` (Pipecat's Silero default, untouched by
    `VAD_STOP_SECS` above) already debounces a single-blip false trigger
    before `VADUserStartedSpeakingFrame` is even created.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            await self.broadcast_interruption()
        await self.push_frame(frame, direction)


class SilenceProcessor(FrameProcessor):
    """Reprompts after ~5s of silence, then ends the call after a second one.

    Placed after `AgentProcessor` and before `tts` in `build_pipeline()`: it
    needs `LLMFullResponseStartFrame`/`LLMFullResponseEndFrame` (pushed
    downstream by `AgentProcessor`) to know when a turn - including every TTS
    clip of a multi-sentence streamed reply, not just the first - has
    actually finished, and `BotStartedSpeakingFrame`/`BotStoppedSpeakingFrame`
    (emitted upstream *and* downstream by the base output transport, so they
    reach every earlier pipeline stage regardless of this processor's exact
    position) to know when the bot is actually making sound.

    The timer only ever starts on a `BotStoppedSpeakingFrame` that arrives
    while no turn is in progress - this is what keeps it from firing while
    the agent is thinking or running a slow tool (e.g. `answer_faq`'s
    embedding lookup), or during the gap between two TTS clips of the same
    streamed reply: both of those are "bot stopped speaking" moments that
    happen *before* `LLMFullResponseEndFrame`, so `_turn_in_progress` is still
    True and no timer starts.
    """

    def __init__(
        self,
        *,
        silence_timeout: float = SILENCE_TIMEOUT_SECS,
        reprompt_text: str = SILENCE_REPROMPT_TEXT,
        goodbye_text: str = SILENCE_GOODBYE_TEXT,
        end_call: EndCall | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._silence_timeout = silence_timeout
        self._reprompt_text = reprompt_text
        self._goodbye_text = goodbye_text
        self._end_call = end_call
        self._turn_in_progress = False
        self._reprompted = False
        self._timer_task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._turn_in_progress = True
            await self._cancel_timer()
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._turn_in_progress = False
        elif isinstance(frame, BotStartedSpeakingFrame):
            await self._cancel_timer()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if not self._turn_in_progress:
                await self._start_timer()
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            # The caller proved they're on the line - any *future* silence
            # starts fresh from the first warning, not straight to goodbye.
            self._reprompted = False
            await self._cancel_timer()

        await self.push_frame(frame, direction)

    async def cleanup(self) -> None:
        await self._cancel_timer()
        await super().cleanup()

    async def _start_timer(self) -> None:
        await self._cancel_timer()
        self._timer_task = self.create_task(self._timer_handler())

    async def _cancel_timer(self) -> None:
        if self._timer_task is not None:
            await self.cancel_task(self._timer_task)
            self._timer_task = None

    async def _timer_handler(self) -> None:
        await asyncio.sleep(self._silence_timeout)
        self._timer_task = None
        if not self._reprompted:
            # First silent window: reprompt, then arm a second, identical
            # window - if the caller still says nothing, the *next* expiry
            # ends the call. Pushed as a TTSSpeakFrame, not through the LLM,
            # so it's never added to Agent's history (BUILD_PLAN 5.3).
            self._reprompted = True
            await self.push_frame(
                TTSSpeakFrame(text=self._reprompt_text), FrameDirection.DOWNSTREAM
            )
        else:
            await self.push_frame(TTSSpeakFrame(text=self._goodbye_text), FrameDirection.DOWNSTREAM)
            if self._end_call is not None:
                await self._end_call()


class TTSLatencyMarker(FrameProcessor):
    """Marks the first TTS audio byte of a turn, and logs the completed turn.

    Sits right after the TTS stage. Only the first `TTSAudioRawFrame` of the
    whole *turn* is marked - BUILD_PLAN 5.0b: resetting on every
    `TTSStartedFrame` (as this used to) re-arms on every TTS clip, and since
    5.1's streaming synthesizes sentence by sentence, a 3-sentence reply has
    3 `TTSStartedFrame`s, so it was logging (and counting, in
    `latency_report.py`) one "turn" per sentence instead of one per real
    turn. Resetting on `LLMFullResponseStartFrame` instead (pushed once per
    turn by `AgentProcessor`, win before any TTS clip) ties the reset to a
    turn boundary, not a clip boundary - first audio is what the caller
    actually waits for.
    """

    def __init__(
        self, turn_tracker: TurnTracker, *, session_id: str = "default", **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.turn_tracker = turn_tracker
        self.session_id = session_id
        self._marked_this_turn = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._marked_this_turn = False
        elif isinstance(frame, TTSAudioRawFrame) and not self._marked_this_turn:
            self._marked_this_turn = True
            self.turn_tracker.mark_tts_first_audio(time.time(), session_id=self.session_id)

        await self.push_frame(frame, direction)


def build_pipeline(
    transport: Any,
    agent: Agent,
    *,
    vad_analyzer: Any,
    stt: FrameProcessor,
    tts: FrameProcessor,
    session_id: str = "default",
    on_tool_call: OnToolCall | None = None,
    on_turn: OnTurn | None = None,
    turn_tracker: TurnTracker | None = None,
    end_call: EndCall | None = None,
) -> Pipeline:
    """Assembles the voice pipeline in the BUILD_PLAN's stage order.

    `BargeInProcessor` sits right after VAD (BUILD_PLAN 5.2), so a caller
    interruption is broadcast before STT/the agent/TTS ever see the frame
    that triggered it. `SilenceProcessor` (BUILD_PLAN 5.3) sits right after
    `AgentProcessor`, since it needs to see `LLMFullResponseStartFrame`/
    `LLMFullResponseEndFrame` to know when a turn is actually finished.
    `TTSLatencyMarker` is only added when `turn_tracker` is given, since it's
    the thing that needs one to do anything.
    """
    stages = [
        transport.input(),
        VADProcessor(vad_analyzer=vad_analyzer),
        BargeInProcessor(),
        stt,
        AgentProcessor(
            agent,
            session_id=session_id,
            on_tool_call=on_tool_call,
            on_turn=on_turn,
            turn_tracker=turn_tracker,
        ),
        SilenceProcessor(end_call=end_call),
        tts,
    ]
    if turn_tracker is not None:
        stages.append(TTSLatencyMarker(turn_tracker, session_id=session_id))
    stages.append(transport.output())
    return Pipeline(stages)


def _vad_params() -> VADParams:
    """The tuned VAD params for `SileroVADAnalyzer`; see `VAD_STOP_SECS`."""
    return VADParams(stop_secs=VAD_STOP_SECS)


def _greeting() -> str:
    """Namaste! <clinic> mein aapka swagat hai... with the clinic's own name."""
    clinic = yaml.safe_load(CLINIC_PATH.read_text())
    return f"Namaste! {clinic['name']} mein aapka swagat hai. Main aapki kya madad kar sakti hoon?"


async def _speak_normalised(text: str, text_type: str | Any) -> str:
    """BUILD_PLAN 5.6: registered as `SarvamHttpTTSService`'s `text_transforms`
    hook (Pipecat's current, non-deprecated TTS text-rewrite mechanism - see
    `app/speech.py`'s module docstring for why this needed no custom
    sentence-buffering processor). Pipecat already hands this the
    *aggregated* sentence, never a partial streamed chunk, and only what
    reaches the synthesizer is changed - `Agent`'s history and `CallLog`'s
    transcript (and the evals, which grade that same original text) never
    see the rewrite.
    """
    return normalise_for_speech(text, detect_lang(text))


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    """Runs the voice pipeline for one call over an already-built transport.

    STT uses `saaras:v4` in `codemix` mode (built for Hinglish, not plain
    `hi-IN`) and TTS uses `bulbul:v3` with a female speaker (`shreya`) to match
    the receptionist persona already baked into `app/prompts.py` (e.g.
    "...WhatsApp kar dungi") — see `docs/architecture.md` for both choices.
    """
    # Lazy, not at module/script startup: pipecat.runner.run.main() resets
    # logging (logger.remove() + its own stderr sink) after that code runs,
    # which would silently wipe a sink added any earlier (see
    # app.metrics.configure_file_sink's docstring).
    ensure_file_sink()

    settings = get_settings()
    agent = Agent(
        SarvamLLMClient(settings.sarvam_api_key),
        caller_phone=placeholder_caller_phone(runner_args.session_id),
    )
    call_logger = CallLogger(caller=runner_args.session_id)
    call_logger.start()
    turn_tracker = TurnTracker()
    runner: WorkerRunner | None = None  # assigned below; end_call() closes over it

    async def end_call() -> None:
        """BUILD_PLAN 5.3: hung up after a second silent window.

        A single hook so Phase 8's Twilio transport can later plug in a real
        hang-up (task 8.5) without SilenceProcessor's timer logic changing at
        all - here, "ending the call" just means logging the outcome and
        cancelling this call's own worker/runner.
        """
        call_logger.end(outcome="dropped")
        if runner is not None:
            await runner.cancel()

    async with aiohttp.ClientSession() as session:
        stt = SarvamSTTService(api_key=settings.sarvam_api_key, mode="codemix")
        tts = SarvamHttpTTSService(
            api_key=settings.sarvam_api_key,
            aiohttp_session=session,
            settings=SarvamHttpTTSService.Settings(voice="shreya"),
            text_transforms=[("*", _speak_normalised)],
        )
        vad_analyzer = SileroVADAnalyzer(params=_vad_params())

        pipeline = build_pipeline(
            transport,
            agent,
            vad_analyzer=vad_analyzer,
            stt=stt,
            tts=tts,
            session_id=runner_args.session_id,
            on_turn=call_logger.record_turn,
            turn_tracker=turn_tracker,
            end_call=end_call,
        )

        worker = PipelineWorker(pipeline, params=PipelineParams())
        runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
        await runner.add_workers(worker)

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport: BaseTransport, client: Any) -> None:
            logger.info("Caller connected")
            await worker.queue_frame(TextFrame(_greeting()))

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport: BaseTransport, client: Any) -> None:
            logger.info("Caller disconnected")
            call_logger.end()
            await runner.cancel()

        await runner.run()


async def bot(runner_args: RunnerArguments) -> None:
    """Pipecat dev-runner entry point: one call, started from the browser."""
    transport = await create_transport(
        runner_args,
        {"webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True)},
    )
    await run_bot(transport, runner_args)
