# Architecture notes

Design choices and discoveries worth remembering, added as phases progress.

## Phase 0

- **Sarvam TTS: `bulbul:v2` is deprecated.** The API rejects it with
  `Model 'bulbul:v2' has been deprecated. Please use 'bulbul:v3' instead.`
  `bulbul:v3` also has a different speaker list than v2 (e.g. `anushka` is not
  valid on v3; `priya`, `neha`, `pooja` etc. are). `CLAUDE.md`'s "use Bulbul v2
  while developing" guidance is outdated — use `bulbul:v3` with one of its
  supported speakers instead. Smoke-tested 2026-11-07 with speaker `priya`,
  `target_language_code="hi-IN"`; output saved to `reports/sarvam_smoke_test.wav`.

## Phase 4

- **STT: `saaras:v4` in `mode="codemix"`**, language left as auto-detect (`None`). `codemix` is
  Sarvam's mode built specifically for Hinglish speech (as opposed to `transcribe`/`translate`/
  `translit`, which assume one language), matching this project's actual callers better than
  pinning `language="hi-IN"`.
- **TTS: `bulbul:v3` with speaker `shreya`**, not the SDK default `shubh`. `shubh` reads male;
  `app/prompts.py`'s fallback copy is already written in feminine voice ("...WhatsApp kar
  **dungi**"), so a female speaker was picked to match the persona already baked into the prompts.
  Picked `shreya` over the initial pick (`priya`) after listening to short samples of six v3
  speakers (`priya`, `neha`, `pooja`, `ishita`, `kavya`, `shreya`) generated via
  `POST https://api.sarvam.ai/text-to-speech` with the actual bot greeting — a user preference call,
  not a technical one; all of bulbul:v3's Indian-named speakers are genuinely Indian-accented voices
  (Sarvam is an India-focused TTS provider), so this was about tone/personality, not accent.
- **Pipecat 1.15.0 moved VAD off `TransportParams`.** Older Pipecat docs attach
  `vad_analyzer=SileroVADAnalyzer()` to the transport's params; in 1.15.0 that field doesn't exist
  on `TransportParams` any more. VAD is now its own pipeline stage,
  `VADProcessor(vad_analyzer=SileroVADAnalyzer())`, which is what `app/voice_bot.py`'s
  `build_pipeline()` uses — it also matches the BUILD_PLAN's own diagram (`transport.input → Silero
  VAD → Sarvam STT → ...`) more literally than the newer transport-params pattern would have.
- **The voice pipeline's "LLM" stage is the Phase 2/3 `Agent`, not a Pipecat LLM service.**
  `AgentProcessor` (a `FrameProcessor`) bridges STT's final `TranscriptionFrame` to
  `Agent.handle_turn()` and emits the reply as TTS text frames. This was a deliberate choice, not
  an oversight: Pipecat's native LLM services do their own tool-calling via an `OpenAILLMContext`,
  which would mean two separate tool-calling implementations (one in `app/agent.py`, tested since
  Phase 2; one inside Pipecat) that could drift apart. `AgentProcessor` keeps there being exactly
  one. `Agent` already keeps its own per-session history, so no separate Pipecat
  "user/assistant aggregator" stage was added.
- **Dev entry point uses Pipecat's runner (`pipecat-ai[runner]`), not a hand-built FastAPI route.**
  `scripts/run_voice_bot.py` calls `pipecat.runner.run.main()`, which auto-discovers the
  module-level `bot(runner_args)` function in `app/voice_bot.py` and serves Pipecat's prebuilt
  WebRTC client at `http://localhost:7860`. `bot()` builds the transport via
  `pipecat.runner.utils.create_transport()` (keyed by transport name — `"webrtc"` for now), so
  adding Twilio in Phase 8 should mean adding one more dict entry, not restructuring this file.
- **`app/metrics.py` has no pipecat imports, on purpose.** `TurnTimer`/`durations_ms()`/
  `turn_log_line()` only know timestamps (epoch seconds) and JSON, so they're trivially unit-testable
  with synthetic data (`tests/unit/test_metrics.py`) without touching the frame-processing stack.
  `TurnTracker` is a plain mutable holder shared between two pipeline stages that otherwise have no
  reference to each other: `AgentProcessor` (marks `speech_end`/`stt_final`/`llm_first_token`) and a
  new `TTSLatencyMarker` processor placed right after `tts` in `build_pipeline()` (marks
  `tts_first_audio` and logs the completed turn, since it's the last stage to know the turn is done).
  `speech_end` comes from `VADUserStoppedSpeakingFrame.timestamp` itself rather than re-stamping on
  arrival, since VAD already records when it made that determination.
- **`llm_first_token` and `tts_first_audio` aren't real streaming measurements yet.**
  `SarvamLLMClient.chat()` and `SarvamHttpTTSService` are both single-shot (one HTTP call, one
  complete response), not streaming, so "first token" and "first audio byte" both land at "the whole
  thing is ready." The measurement plumbing exists now so Phase 5's streaming work (task 5.1) can
  slot in without changing `TurnTimer`'s shape — only when each mark actually happens.
