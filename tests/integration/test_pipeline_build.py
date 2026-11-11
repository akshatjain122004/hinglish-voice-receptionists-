"""`build_pipeline` wires transport/VAD/STT/agent/TTS in the order the
BUILD_PLAN diagram specifies. All stages are fakes here — this test is about
our wiring, not about Sarvam, Silero or SmallWebRTC's own correctness."""

from unittest.mock import MagicMock

from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.filters.identity_filter import IdentityFilter

from app.agent import Agent
from app.metrics import TurnTracker
from app.voice_bot import AgentProcessor, BargeInProcessor, TTSLatencyMarker, build_pipeline
from tests.fixtures.fake_llm import FakeLLM


class _FakeTransport:
    """Just enough of Pipecat's transport interface for `build_pipeline`."""

    def __init__(self) -> None:
        self.input_processor = IdentityFilter(name="transport-input")
        self.output_processor = IdentityFilter(name="transport-output")

    def input(self) -> IdentityFilter:
        return self.input_processor

    def output(self) -> IdentityFilter:
        return self.output_processor


def test_build_pipeline_wires_stages_in_plan_order():
    agent = Agent(FakeLLM(responses=[]))
    transport = _FakeTransport()
    vad_analyzer = MagicMock()
    stt = IdentityFilter(name="stt")
    tts = IdentityFilter(name="tts")

    pipeline = build_pipeline(transport, agent, vad_analyzer=vad_analyzer, stt=stt, tts=tts)

    # Pipeline wraps our stages with its own source/sink processors.
    stages = pipeline._processors[1:-1]

    assert stages[0] is transport.input_processor
    assert isinstance(stages[1], VADProcessor)
    assert isinstance(stages[2], BargeInProcessor)
    assert stages[3] is stt
    assert isinstance(stages[4], AgentProcessor)
    assert stages[4].agent is agent
    assert stages[5] is tts
    assert stages[6] is transport.output_processor


def test_build_pipeline_adds_tts_latency_marker_when_turn_tracker_given():
    agent = Agent(FakeLLM(responses=[]))
    transport = _FakeTransport()
    vad_analyzer = MagicMock()
    stt = IdentityFilter(name="stt")
    tts = IdentityFilter(name="tts")
    turn_tracker = TurnTracker()

    pipeline = build_pipeline(
        transport, agent, vad_analyzer=vad_analyzer, stt=stt, tts=tts, turn_tracker=turn_tracker
    )

    stages = pipeline._processors[1:-1]
    assert len(stages) == 8
    assert isinstance(stages[6], TTSLatencyMarker)
    assert stages[6].turn_tracker is turn_tracker
    assert stages[7] is transport.output_processor
