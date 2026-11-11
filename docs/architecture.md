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
  **Superseded by Phase 5.1** (below): `SarvamLLMClient.chat()` no longer exists — `stream_chat()`
  replaced it, and `llm_first_token` now marks on the first real streamed chunk.

## Phase 5

- **5.5: Silero VAD's `stop_secs` raised from Pipecat's default 0.2s to 0.7s**
  (`app/voice_bot.py`'s `VAD_STOP_SECS`/`_vad_params()`). Root cause, confirmed in the Phase 4 live
  test: `stop_secs` is the trailing silence VAD waits before it finalizes a stop, and
  `SarvamSTTService` finalizes the transcript on exactly that signal (see
  `pipecat.services.sarvam.stt`'s `VADUserStoppedSpeakingFrame` handling); a caller's "haan, kar do"
  had a 0.6s gap between the two words, well past the 0.2s default, so VAD fired a stop after "haan"
  alone and the agent only ever saw an isolated, unconfirmable fragment — it escalated to a human
  instead of booking. 0.7s survives that specific gap with a small margin.
  - **Latency tradeoff, not free:** this delay sits *before* `VADUserStoppedSpeakingFrame` is even
    created, so it is invisible to `TurnTracker`/`latency_report.py` — `speech_end` is stamped from
    the frame's own creation timestamp, which is already `stop_secs` after the caller's last word.
    Raising `stop_secs` from 0.2s to 0.7s adds ~0.5s of real, caller-perceived latency that Phase 4's
    `reports/latency_phase4.md` numbers never counted. This is why the value is provisional: Phase
    5's manual check (10 calls, 3 different people, recording awkward-pause Y/N) is what actually
    tells us whether 0.7s is too long, too short, or right, not a unit test.
  - `start_secs`/`confidence`/`min_volume` were left at Pipecat's defaults — no evidence from the
    Phase 4 test pointed at them, so changing them without a reproduced problem would just be
    guessing.
- **5.1: LLM streaming + sentence-by-sentence TTS, no custom sentence-splitter needed.**
  `app/llm_streaming.py` holds the only genuinely new logic — merging Sarvam's
  fragmented streaming tool-call deltas (id/name once, `arguments` as many small
  string fragments, all keyed by index) into finished tool calls. Everything else
  reuses existing machinery: `Agent.handle_turn()` forwards content deltas live via a
  new `on_reply_chunk` callback, gated off the moment a tool-call delta appears in that
  round — suppression starts at that point, but doesn't retroactively un-speak content
  already forwarded earlier in the same round. If a round ever mixes spoken content
  with a *trailing* tool-call delta (not standard OpenAI-API behavior, and not
  something Sarvam's docs suggest happens), those already-forwarded sentences would
  reach TTS before the tool-call detour — a documented, accepted limitation (see
  `docs/superpowers/specs/2026-11-09-voice-streaming-design.md`'s "Open limitation"
  section), not something this design engineers around. And pipecat's `TTSService` already
  buffers incoming text into sentences before synthesizing
  (`TextAggregationMode.SENTENCE`, its existing default) — it only needed to actually
  *receive* text incrementally, which it now does.
  - `AgentProcessor` pushes a `TextFrame` per chunk instead of one `TextFrame` per full
    reply, and marks `TurnTracker.llm_first_token` on the first chunk only (same
    overwrite-guard pattern `TTSLatencyMarker` already used for `tts_first_audio`).
  - **Correctness fix, not just a latency change:** `Agent.handle_turn()`'s fallback
    path (hitting `max_tool_rounds`) returns `FALLBACK_MESSAGE` without ever calling
    `on_reply_chunk` — `AgentProcessor` pushes that reply as a `TextFrame` directly if
    no chunk was streamed for the turn, or the caller would hear nothing instead of the
    apology.
  - TTS stays on `SarvamHttpTTSService` (called once per sentence now, via pipecat's
    own aggregation, not once per full reply) rather than switching to Sarvam's
    WebSocket streaming TTS API. **Correction from this note's original wording:**
    task 5.2's research found the swap isn't needed for barge-in either (see below) —
    `TTSService._handle_interruption()` is generic across HTTP and WebSocket TTS
    services, so this remains purely optional, relevant only if raw audio latency
    itself becomes a target later.
- **5.2: Barge-in.** Stopping TTS mid-reply turned out to need almost no new code:
  Pipecat's base `TTSService._handle_interruption()` (shared by `SarvamHttpTTSService`
  and the WebSocket `SarvamTTSService`) already resets text aggregation and drops
  queued/in-flight audio on receiving an `InterruptionFrame` — nothing in the pipeline
  was actually *broadcasting* one when the caller started talking. The whole task is
  one new processor plus one new flag on the existing `AgentProcessor`:
  - **`BargeInProcessor`** (`app/voice_bot.py`), inserted right after `VADProcessor` in
    `build_pipeline()`: on `VADUserStartedSpeakingFrame` it calls
    `self.broadcast_interruption()` and otherwise forwards every frame unchanged. No new
    VAD tuning — Silero's `start_secs=0.2s` default (untouched by `VAD_STOP_SECS`) already
    debounces a single-blip false trigger before this frame is even created.
  - **Never cancel a booking halfway.** Pipecat's default interruption handling cancels
    whatever task is currently processing a frame in a processor. If the caller starts
    talking again while `AgentProcessor` is mid-`handle_turn()` — e.g. waiting on the
    LLM's next round right after a `book_appointment` tool call already committed — a
    naive cancellation there would abandon that tool's result before `Agent` records it
    in history, even though the booking itself already happened. The fix uses Pipecat's
    own mechanism for this (the same one its internal Flows manager uses for "context
    must land even if interrupted"): `AgentProcessor` sets `frame.interruptible = False`
    on the `TranscriptionFrame` it's about to process. Pipecat's `_start_interruption()`
    checks exactly this flag and, when it's `False`, leaves the current processing task
    running to natural completion instead of cancelling it.
  - **No leftover speech from an interrupted turn.** Letting `handle_turn()` run to
    completion means it would otherwise keep pushing `TextFrame` chunks for TTS to speak
    even after the caller has started talking again. `AgentProcessor` tracks a separate
    `self._interrupted` flag, set `True` by an `InterruptionFrame` arriving mid-turn (via
    Pipecat's own input-frame task, which runs concurrently with the uninterruptible
    process task above) and reset `False` at the start of every new turn. The
    `on_reply_chunk` callback and the final non-streamed-reply push both check it and
    drop the content instead of forwarding it once set.
  - **Decision:** `Agent`'s conversation history (and the `CallLog` transcript) always
    keep the *full* reply text, even when the caller only heard part of it before
    interrupting. This is the simplest option and is acceptable because the
    confirm-before-booking rule (non-negotiable rule #3) means any misunderstanding gets
    caught on the next read-back, not silently compounded.
  - Tested in `tests/integration/test_barge_in.py`: `BargeInProcessor` broadcasts on
    `VADUserStartedSpeakingFrame`; an interruption mid-turn (engineered with a real
    `asyncio.sleep` in a scripted LLM, timed with Pipecat's `SleepFrame` test helper so
    the interruption lands *after* the turn has started rather than being reset away by
    the turn's own startup) still commits exactly one booking and records the tool
    result in history, while pushing zero `TextFrame`s for it; the next turn starts
    clean. Verified as a real regression guard, not an accidental pass, by temporarily
    removing `frame.interruptible = False` and confirming the booking test fails (the
    turn gets cut off before `LLMFullResponseEndFrame`, leaving TTS's turn context open)
    — see the task's close-out note in `docs/BUILD_PLAN.md` for the full before/after.
- **5.8: STT noise filtering strips by Unicode category, not `str.isalnum()`.**
  `app/stt_noise.py`'s `is_noise()` drops a transcript once it's under 2 code points
  after stripping whitespace and punctuation. The punctuation strip must use
  `unicodedata.category(ch)[0] != "P"`, not `.isalnum()` per character — Devanagari
  vowel signs and the candrabindu (the combining marks inside "हाँ") are category
  `Mc`/`Mn`, which `.isalnum()` treats as non-alphanumeric and would strip away,
  undercounting a real short Hindi "yes" and wrongly dropping it as noise.
- **5.3: Silence handling needed a dedicated processor, not Pipecat's `UserIdleController`.**
  That controller is the right shape (starts on `BotStoppedSpeakingFrame`, cancels on
  `BotStartedSpeakingFrame`/`UserStartedSpeakingFrame`, suppressed during
  `FunctionCallsStartedFrame`) but it's wired to Pipecat's native turn-taking/function-calling
  frame vocabulary, which this pipeline doesn't produce (the Phase 4 decision keeps tool-calling
  inside `Agent`, not a native Pipecat LLM service - see above). `SilenceProcessor` (`app/voice_bot.py`)
  uses this pipeline's actual frames instead: `LLMFullResponseStartFrame`/`LLMFullResponseEndFrame`
  (already pushed by `AgentProcessor` every turn) track whether a turn is in progress, and
  `VADUserStartedSpeakingFrame` resets it on caller speech. Tracking turn-in-progress this way,
  rather than just "was the bot silent for N seconds," is what keeps the timer from firing between
  two TTS clips of the *same* multi-sentence streamed reply, not only during a slow tool call.
  Reprompt/goodbye are pushed as `TTSSpeakFrame`s - Pipecat's primitive for "speak this now,
  independent of any LLM turn" - so neither touches `Agent`'s history.
  - **`end_call()` as a late-bound closure.** It needs `WorkerRunner`, which doesn't exist yet when
    `build_pipeline()` is called in `run_bot()`; solved with a closure over a `runner` variable
    assigned a few lines later (standard Python late-binding - `end_call()` is only ever actually
    invoked long after `runner` holds the real object).
  - **`CallLogger.end()` is now idempotent.** `end_call()` logs `outcome="dropped"` and cancels the
    runner, which tears down the transport and would otherwise trigger the existing
    `on_client_disconnected` handler's own `call_logger.end()` right after - silently overwriting
    the dropped outcome with the default `""`. Guarding `end()` to no-op once `ended_at` is already
    set fixes this for any future double-end path too, not just this one.
- **5.4: tool calls run via `asyncio.to_thread`, racing a filler timer instead of
  cancelling anything.** `tools.call_tool` was a plain synchronous call inside
  `Agent.handle_turn()`'s loop with no `await` anywhere in it, so a 700ms filler timer
  genuinely could never have gotten a turn to run alongside it - confirmed, not just
  suspected, before fixing. Each tool call now runs as
  `asyncio.to_thread(tools.call_tool, ...)`, raced against
  `asyncio.wait({task}, timeout=filler_threshold_secs)`: if the timeout wins,
  `on_slow_tool()` fires once (never cancelling the task - the tool keeps running and
  its real result is always awaited afterward), gated by a `filler_fired` flag scoped
  to that one `handle_turn()` call, which is what makes "at most one filler per turn"
  fall out for free even across two independently-slow tool rounds. `app/db.py`'s
  engine already had `check_same_thread=False` (needed for the test `db` fixture's
  `StaticPool`), so running SQLite calls from the thread pool needed no further change.
  `filler_threshold_secs` is an `Agent.__init__` parameter (default
  `app.agent.FILLER_THRESHOLD_SECS = 0.7`), the same instance-configurable-timing-knob
  pattern as `SilenceProcessor.silence_timeout` from 5.3, so tests don't have to wait
  out the real 700ms. The filler phrase itself is a `TTSSpeakFrame`, same primitive as
  5.3's reprompt/goodbye, so it never touches `Agent`'s history either.
- **5.6: Sarvam TTS's `text_transforms` hook needed no new processor at all.**
  `TTSService.__init__`'s `text_filters` is deprecated since 1.14.0 (removed in 2.0.0);
  its replacement, `text_transforms` (`list[(text_type, async (text, text_type) -> text)]`,
  registered on `SarvamHttpTTSService` in `run_bot()`), already receives the
  **aggregated** sentence rather than a partial streamed chunk, and - per its own
  docstring - only changes what reaches the synthesizer, never the context/history. Both
  of 5.6's hard parts (don't normalise `"17:"` before `"30"` arrives; don't let the
  normalised form leak into `Agent`'s history or `CallLog`) are solved by Pipecat's own
  mechanism, not new code.
  - `app/speech.py`'s `normalise_for_speech`/`detect_lang` deliberately have **no general
    0-99 Hindi number-word table** - that vocabulary is famously irregular past the teens,
    and nothing in this domain needs it: times are always on `clinic.yaml`'s 15-minute
    slot grid (so only hour words 1-12, via the existing saade/paune/sava/baje idiom),
    prices are all round hundreds/thousands (only ones+teens for the hundreds/thousands
    digit), and phone numbers are read **digit-by-digit in pairs** (a comma pause between
    pairs, not two-digit number words) - a deliberate reading of "pairs" as pacing, chosen
    specifically to avoid that irregular table.
  - **A real, previously-documented LLM slip almost shipped a duplicate-word bug.** Phase
    3's close-out note observed replies occasionally writing digits anyway ("10 baje").
    The first version of the time regex didn't account for a reply writing *both* the
    digits and the Hindi marker word together, and produced "das baje baje". Fixed by
    extending the regex to consume a redundant leading `sava`/`paune`/`saade` or trailing
    `baje` into the match itself (dropped, since the digits are the source of truth),
    rather than leaving the original word in place next to the newly-spoken one.
  - `detect_lang` is a narrow heuristic scoped to exactly this one decision (which
    number-word style to use for a sentence), not general language identification -
    Devanagari script, or any of ~45 common Hindi/Hinglish marker words (reusing
    `app.timeparse`'s own vocabulary), else English.
- **5.7: sarvam-105b's reasoning mode was on by default, this whole project, undocumented.**
  Researched against Sarvam's own docs (not guessed) before writing any code: `reasoning_effort`
  defaults server-side to `"low"` - not off - and reasoning tokens "count toward your completion
  tokens and bill," streaming first via `delta.reasoning_content` *before* any real content. Every
  request this project has ever made silently paid that latency and cost. Fixed by sending
  `"reasoning_effort": None` explicitly in `SarvamLLMClient.stream_chat()`'s request body - omitting
  the field is not the same as disabling it; Sarvam's default only turns off on an explicit `null`.
  - **Sarvam's API has no prompt-caching parameter at all** (checked both the general chat-completions
    guide and the model-specific page) - the "cache" half of this task is dropped, per the plan's own
    instruction for exactly this outcome.
  - **A second finding fell out of the same research pass:** Sarvam's streaming API sends a usage
    trailer chunk (`prompt_tokens`/`completion_tokens`) automatically on every request, no
    `stream_options.include_usage` opt-in needed (unlike OpenAI) - `SarvamLLMClient._parse_sse_line`
    was already receiving this chunk and silently discarding it (an existing test's own assertion
    proved it produced no delta). `ChatDelta` gained a `usage` field; `Agent.handle_turn(...,
    on_usage=...)` forwards each round's usage (a later round's call overwrites an earlier one's
    effect on purpose - the *last* round is the one whose generation `llm_first_token` actually
    measured); `TurnTracker.mark_usage()`/`TurnTimer.prompt_tokens`/`completion_tokens` log it next to
    every turn. These double as exactly the per-call usage counters task 9.7's budget guard will need
    later.
  - **Prompt shortening kept more than the task's literal wording suggested, deliberately.** The
    "spoken numbers" sub-clause was removed outright - 100% redundant now that 5.6's
    `normalise_for_speech` rewrites digits regardless of what the model writes. The phone-handling
    line was **shortened, not deleted**: code enforcement (ignoring a hallucinated phone argument,
    since Phase 2) only protects a tool call from the wrong number, it does nothing to stop the model
    asking the caller for it in conversation - the prompt line is the only thing preventing that, so
    it stayed, just terser.
- **5.0: `TTSLatencyMarker` resets on a turn boundary, not a TTS-clip boundary.** It used to reset its
  "already marked" flag on every `TTSStartedFrame`, which fires once per *sentence* since 5.1's
  streaming TTS - a 3-sentence reply was genuinely logged (and would be counted by
  `latency_report.py`) as 3 separate "turns." Fixed by resetting on `LLMFullResponseStartFrame`
  instead (pushed once per turn, before any TTS clip). Known, accepted side effect: a 5.4 filler
  phrase played mid-turn now becomes what gets marked as "first audio" for that turn, since it's the
  first `TTSAudioRawFrame` to arrive - arguably more honest, not a bug, since it's literally the first
  sound the caller hears. 5.3's reprompt/goodbye are unaffected (they play outside any
  `LLMFullResponseStartFrame`/`EndFrame` span).
  - `app.metrics.latency_summary()` gained a `vad_stop_secs` parameter: when given, it adds a
    `perceived_total_ms` stage (`total_latency_ms`'s own p50/p95 plus the fixed offset) next to the
    comparable-with-Phase-4 number, since `speech_end` is stamped `VAD_STOP_SECS` after the caller's
    actual last word and `total_latency_ms` alone understates the real wait.
  - **`scripts/latency_report.py` had the identical stale-hardcoded-title bug Phase 3 already fixed
    once, in a sibling script, caught before it could bite again.** Its `REPORT_PATH`/`REPORT_TITLE`
    were still `"Phase 4"` - the next run (Phase 5's upcoming manual call check) would have silently
    produced the wrong file. Now takes the phase number as an optional CLI arg, defaulting to `"5"`.
    (`scripts/run_evals.py` has the same unfixed pattern - its report title parameter exists but the
    script itself still hardcodes `"Phase 3"` - left alone since fixing a different script wasn't in
    scope here, flagged for whoever touches it next.)
  - **The suggested test-fixture-scoping fix for the suite's ~26-30s runtime doesn't actually change
    anything today, verified rather than assumed.** The real-embedding fixture
    (`test_rag_retrieval.py`'s `faq_persist_dir`) was already `scope="module"`, and it's the only
    place in the suite that loads the real model - with one consuming module, "module" and "session"
    scope are identical (confirmed via `pytest --durations`: one ~19-25s setup cost either way).
    Raised to `scope="session"` anyway as a zero-cost safety net for a hypothetical future second
    consumer; left as a local fixture rather than moved to `conftest.py`, since session scope alone
    wouldn't make it visible across files and there's no second consumer yet to justify that move.
    The runtime itself isn't fixable by fixture scoping - it's the inherent, already-amortized cost of
    loading a real multilingual embedding model on CPU once per run.
