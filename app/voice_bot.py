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

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import yaml
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
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

from app.agent import Agent, SarvamLLMClient
from app.config import get_settings
from app.db import CallLog, get_session
from app.metrics import TurnTracker

OnToolCall = Callable[[str, dict[str, Any], dict[str, Any]], None]
OnTurn = Callable[[str, str], None]

CLINIC_PATH = Path(__file__).resolve().parent.parent / "data" / "clinic.yaml"


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

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStoppedSpeakingFrame):
            if self.turn_tracker is not None:
                self.turn_tracker.mark_speech_end(frame.timestamp)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            if self.turn_tracker is not None:
                self.turn_tracker.mark_stt_final(time.time())
            reply = await self.agent.handle_turn(
                self.session_id, frame.text, on_tool_call=self.on_tool_call
            )
            if self.turn_tracker is not None:
                # Not literally the first streamed token - Agent/SarvamLLMClient
                # don't stream yet (that's Phase 5's job), so this is when the
                # full reply became available.
                self.turn_tracker.mark_llm_first_token(time.time())
            if self.on_turn is not None:
                self.on_turn(frame.text, reply)
            await self.push_frame(LLMFullResponseStartFrame(), direction)
            await self.push_frame(TextFrame(reply), direction)
            await self.push_frame(LLMFullResponseEndFrame(), direction)
            return

        await self.push_frame(frame, direction)


class TTSLatencyMarker(FrameProcessor):
    """Marks the first TTS audio byte of a turn, and logs the completed turn.

    Sits right after the TTS stage. Only the first `TTSAudioRawFrame`
    following each `TTSStartedFrame` is marked, so a multi-sentence reply
    doesn't re-log partway through.
    """

    def __init__(
        self, turn_tracker: TurnTracker, *, session_id: str = "default", **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.turn_tracker = turn_tracker
        self.session_id = session_id
        self._marked_this_utterance = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSStartedFrame):
            self._marked_this_utterance = False
        elif isinstance(frame, TTSAudioRawFrame) and not self._marked_this_utterance:
            self._marked_this_utterance = True
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
) -> Pipeline:
    """Assembles the voice pipeline in the BUILD_PLAN's stage order.

    `TTSLatencyMarker` is only added when `turn_tracker` is given, since it's
    the thing that needs one to do anything.
    """
    stages = [
        transport.input(),
        VADProcessor(vad_analyzer=vad_analyzer),
        stt,
        AgentProcessor(
            agent,
            session_id=session_id,
            on_tool_call=on_tool_call,
            on_turn=on_turn,
            turn_tracker=turn_tracker,
        ),
        tts,
    ]
    if turn_tracker is not None:
        stages.append(TTSLatencyMarker(turn_tracker, session_id=session_id))
    stages.append(transport.output())
    return Pipeline(stages)


def _greeting() -> str:
    """Namaste! <clinic> mein aapka swagat hai... with the clinic's own name."""
    clinic = yaml.safe_load(CLINIC_PATH.read_text())
    return f"Namaste! {clinic['name']} mein aapka swagat hai. Main aapki kya madad kar sakti hoon?"


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    """Runs the voice pipeline for one call over an already-built transport.

    STT uses `saaras:v4` in `codemix` mode (built for Hinglish, not plain
    `hi-IN`) and TTS uses `bulbul:v3` with a female speaker (`shreya`) to match
    the receptionist persona already baked into `app/prompts.py` (e.g.
    "...WhatsApp kar dungi") — see `docs/architecture.md` for both choices.
    """
    settings = get_settings()
    agent = Agent(SarvamLLMClient(settings.sarvam_api_key))
    call_logger = CallLogger(caller=runner_args.session_id)
    call_logger.start()
    turn_tracker = TurnTracker()

    async with aiohttp.ClientSession() as session:
        stt = SarvamSTTService(api_key=settings.sarvam_api_key, mode="codemix")
        tts = SarvamHttpTTSService(
            api_key=settings.sarvam_api_key,
            aiohttp_session=session,
            settings=SarvamHttpTTSService.Settings(voice="shreya"),
        )
        vad_analyzer = SileroVADAnalyzer()

        pipeline = build_pipeline(
            transport,
            agent,
            vad_analyzer=vad_analyzer,
            stt=stt,
            tts=tts,
            session_id=runner_args.session_id,
            on_turn=call_logger.record_turn,
            turn_tracker=turn_tracker,
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
