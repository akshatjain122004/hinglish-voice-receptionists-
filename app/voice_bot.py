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

from collections.abc import Callable
from typing import Any

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.agent import Agent

OnToolCall = Callable[[str, dict[str, Any], dict[str, Any]], None]


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
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.session_id = session_id
        self.on_tool_call = on_tool_call

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            reply = await self.agent.handle_turn(
                self.session_id, frame.text, on_tool_call=self.on_tool_call
            )
            await self.push_frame(LLMFullResponseStartFrame(), direction)
            await self.push_frame(TextFrame(reply), direction)
            await self.push_frame(LLMFullResponseEndFrame(), direction)
            return

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
) -> Pipeline:
    """Assembles the voice pipeline in the BUILD_PLAN's stage order."""
    return Pipeline(
        [
            transport.input(),
            VADProcessor(vad_analyzer=vad_analyzer),
            stt,
            AgentProcessor(agent, session_id=session_id, on_tool_call=on_tool_call),
            tts,
            transport.output(),
        ]
    )
