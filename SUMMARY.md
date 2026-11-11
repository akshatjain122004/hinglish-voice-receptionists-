# Project Summary — Hinglish Voice Receptionist

**Purpose of this file:** a complete, detailed project history for anyone picking this
up cold — a senior developer, a future version of the author, or Claude Code in a new
session. It covers what the project is, what's been built, exactly how each piece was
built (including the bugs hit and how they were fixed), what's known-broken or
deferred, and what to do next. Written 2026-11-10, at the end of Phase 5's first two
tasks (5.1 and 5.5); updated 2026-11-11 after tasks 5.2 (barge-in) and 5.8 (STT noise)
landed.

Read this alongside `CLAUDE.md` (working conventions) and `docs/BUILD_PLAN.md` (the
authoritative, task-by-task plan with its own close-out notes per task — this file
summarizes and cross-references it, but `BUILD_PLAN.md` has finer detail on any one
task than fits here).

---

## 1. What this project is

An AI receptionist that answers a small business's phone — the pilot is a dental
clinic in Udaipur, India. It talks to callers in Hindi, English, or Hinglish
(code-mixed), checks appointment availability, books/cancels/reschedules
appointments, answers FAQs from the clinic's own notes, and sends WhatsApp
confirmations and reminders.

**Call flow (target architecture):**
```
Caller → Twilio/Plivo (audio stream) → Pipecat pipeline → Silero VAD → Sarvam STT
       → LLM agent with tools → Sarvam TTS → caller
```

**Example interaction:** caller says "Kal shaam ko cleaning ka slot milega?"
("Is a cleaning slot available tomorrow evening?")
1. Agent calls `check_slots(date=tomorrow, service="cleaning", part_of_day="evening")`.
2. It offers only the slots the tool actually returned — never invents one.
3. It reads back the details, waits for an explicit "haan"/"yes", then calls
   `book_appointment(...)`. A WhatsApp confirmation goes out in the background.

**Budget:** ₹500–800 total (Sarvam STT/TTS/LLM credits + hosting). This is a real
constraint — live API calls and evals cost real (small) amounts of money, so they're
only run when explicitly asked for, never automatically.

**Current phase:** Phase 5 (Hinglish + latency hardening), in progress. Tasks 5.1,
5.5, 5.2 (barge-in) and 5.8 (STT noise) are done; 5.0 (housekeeping), 5.3, 5.4, 5.6,
5.7, 5.9 are not started yet. See §5.6 below for exactly where that stands.

---

## 2. Tech stack

- **Language:** Python 3.11, type hints on every function, `ruff` for lint + format.
- **Voice pipeline:** [Pipecat](https://github.com/pipecat-ai/pipecat) — handles the
  frame-based audio/text pipeline, VAD, transport (WebRTC for browser testing now,
  Twilio for real phone calls later).
- **STT / LLM / TTS provider:** [Sarvam AI](https://sarvam.ai) — an India-focused
  provider with strong Hindi/Hinglish support.
  - STT: `saaras:v4` model, `codemix` mode (built for Hinglish, not single-language).
  - LLM: `sarvam-105b`, via an OpenAI-compatible `/v2/chat/completions` endpoint.
  - TTS: `bulbul:v3`, speaker `shreya` (female, matches the persona in the prompts).
- **Data:** SQLite (via SQLModel) for appointments/call logs; will sync to Google
  Calendar later (Phase 7). Chroma for FAQ vector search (RAG).
- **Other integrations (not yet built):** WhatsApp Cloud API (Phase 6), Google
  Calendar (Phase 7), Twilio/Plivo for real phone numbers (Phase 8).
- **Web/dashboard:** FastAPI (webhooks, health check), Streamlit (owner dashboard,
  Phase 9 — not built yet).
- **Testing:** `pytest` + `pytest-asyncio`, `respx` for mocking HTTP, a hand-rolled
  `FakeLLM` for mocking the LLM. Offline suite must stay green, free, and under ~30s
  (currently ~26-27s, 253 tests).
- **Deployment (not yet built):** Docker, planned for an always-on VM (Phase 9).

---

## 3. Repository structure

```
Swagat AI/
├── app/
│   ├── config.py            # settings loaded from .env via pydantic-settings
│   ├── db.py                 # SQLModel tables: Appointment, CallLog, UnansweredQuestion
│   ├── booking.py             # slot logic — plain Python, the LLM never computes this
│   ├── timeparse.py           # "kal shaam saade paanch" -> datetime
│   ├── tools.py               # tool functions exposed to the LLM (check_slots, book_appointment, ...)
│   ├── agent.py               # LLMClient protocol, SarvamLLMClient, Agent (tool-calling loop)
│   ├── llm_streaming.py       # NEW (Phase 5.1): ChatDelta/ToolCallDelta/ToolCallAccumulator
│   ├── prompts.py             # the system prompt
│   ├── rag.py                 # FAQ ingest + retrieve (Chroma)
│   ├── evals.py               # golden-conversation eval grading logic
│   ├── whatsapp.py            # WhatsApp Cloud API client (Phase 6, not built yet)
│   ├── calendar_sync.py       # Google Calendar adapter (Phase 7, not built yet)
│   ├── voice_bot.py           # Pipecat pipeline: VAD -> STT -> AgentProcessor -> TTS
│   ├── server.py              # FastAPI: webhooks, websocket, /health (Phase 9, minimal so far)
│   └── metrics.py             # per-turn latency tracking + structured JSON logging
├── dashboard/
│   └── streamlit_app.py       # owner dashboard (Phase 9, not built yet)
├── data/
│   ├── clinic.yaml            # clinic name, hours, services, slot length
│   ├── faqs.md                 # clinic FAQs (18 currently)
│   ├── test_calls.yaml         # golden Hinglish/Hindi/English test conversations (35 cases)
│   └── app.db                  # the real SQLite DB — gitignored, has real Phase 4 booking data
├── tests/
│   ├── unit/                   # pure-function tests (booking, timeparse, metrics, llm_streaming, ...)
│   ├── integration/             # agent+tools+DB, voice pipeline, turn metrics
│   ├── evals/                   # live eval harness tests (marked @pytest.mark.live)
│   └── fixtures/                # FakeLLM, audio fixtures
├── scripts/
│   ├── chat_cli.py              # talk to the agent by typing (text path)
│   ├── run_voice_bot.py         # launch the Pipecat WebRTC dev server
│   ├── ingest_faqs.py            # rebuild the FAQ vector store
│   ├── run_evals.py              # run the golden-conversation evals against the real LLM
│   ├── latency_report.py          # p50/p95 latency per pipeline stage
│   └── smoke_test.sh              # (Phase 9, not built yet)
├── docs/
│   ├── BUILD_PLAN.md             # THE plan — read this for full detail on any task
│   ├── architecture.md            # design-decision log, organized by phase
│   ├── telephony.md               # (Phase 8, not built yet)
│   └── superpowers/
│       ├── specs/                 # design specs written during brainstorming (Phase 5.1 has one)
│       └── plans/                  # implementation plans (Phase 5.1 has one)
├── reports/                        # eval and latency reports, generated per phase
├── .github/workflows/ci.yml        # GitHub Actions: ruff + pytest on every push
├── pyproject.toml
├── CLAUDE.md                        # working conventions for AI-assisted development on this repo
└── SUMMARY.md                        # this file
```

---

## 4. Development conventions and non-negotiable rules

These are from `CLAUDE.md` — summarized here because they shaped every decision
below, but `CLAUDE.md` is the source of truth.

1. **The LLM never invents facts.** Slots, prices, timings, addresses come only from
   tool results, `clinic.yaml`, or `faqs.md`. Evals check for zero hallucinated slots.
2. **Booking logic is plain Python** (`app/booking.py`), never in prompts. `book()`
   re-checks availability inside a transaction — a slot can never double-book.
3. **Always confirm before booking** — read back service/date/time, wait for an
   explicit yes.
4. **Side effects (WhatsApp, Calendar) never break a booking** — background with
   retries; failure is logged and queued, the appointment still saves.
5. **Secrets only from environment variables**, via `app/config.py`. Never hardcoded,
   never logged, `.env` never committed.
6. **The default test suite is offline and free.** Every external API mocked with
   fakes or `respx`. Anything hitting a real paid API gets `@pytest.mark.live` and is
   skipped by default.
7. **Keep costs in mind.** Don't run live tests/evals/calls unless explicitly asked.
   Total budget ₹500–800.
8. **Timezone is `Asia/Kolkata` everywhere.** Phone numbers stored E.164
   (`+91XXXXXXXXXX`).
9. **Work one phase at a time, one task at a time**, following `BUILD_PLAN.md`'s
   order. Don't jump ahead without asking.
10. **Bug fix = write a failing test first, then fix.**
11. **Don't change `data/test_calls.yaml`'s expectations just to pass an eval** — fix
    the agent, or ask.
12. **Don't put business rules in the system prompt** that belong in code.

---

## 5. Progress by phase

### 5.0 — Phase 0: Project setup & scope — ✅ Complete

Repo created, folder structure laid out, Python 3.11 venv, all accounts created
(Sarvam, Google Cloud, Twilio trial, Meta for Developers/WhatsApp test number),
`.env.example` + `app/config.py` (pydantic-settings), `data/clinic.yaml` (hours,
services, durations), `data/faqs.md` (≥15 Q&As), `data/test_calls.yaml` (≥20 golden
conversations), ruff + GitHub Actions CI.

**Deferred, not blocking:** one live Sarvam TTS smoke-test call (costs a small
amount, not needed to start real work). Also discovered `bulbul:v2` is deprecated by
Sarvam (CLAUDE.md's original guidance to use it was outdated) — `bulbul:v3` is used
everywhere now.

### 5.1 — Phase 1: Booking engine (no AI) — ✅ Complete

Pure Python booking logic, deliberately built *before* any AI so the AI only ever
*calls* it — it can never invent or compute a slot itself.

- `app/db.py`: `Appointment`, `CallLog` SQLModel tables.
- `app/booking.py`: `get_free_slots()` (respects hours/lunch/weekly-off/duration/
  existing bookings), `book()` (re-checks availability inside a transaction —
  `SlotTakenError` on conflict), `cancel()`, `reschedule()`, `find_by_phone()`.
- `app/booking.py`: phone normalization (`98290 12345` / `+91-9829012345` /
  `09829012345` → all become `+919829012345`), past/>30-day booking rejection.
- **32 tests, 94% coverage on `booking.py`.** This is the most heavily tested file in
  the repo for good reason — it's where a real double-booking bug would live.

### 5.2 — Phase 2: Text agent "brain" — 🟨 code complete, gate not formally met

Chat with the receptionist by typing. Built the agent's tool-calling loop entirely
behind a `LLMClient` interface so tests never touch a real API.

- `app/timeparse.py`: Hinglish/Hindi/English date-time phrase parsing (40+ phrases
  tested: `aaj`/`kal`/`parso`, weekday names, `subah`/`dopahar`/`shaam`/`raat`,
  `saade paanch`/`paune chhe`/`sava das`, `5:30`/`5 baje`/"half past five").
- `app/tools.py`: `check_slots`, `book_appointment`, `cancel_appointment`,
  `reschedule_appointment`, `answer_faq` (stub until Phase 3), `transfer_to_human`.
  Every tool validates input and returns `{"ok": false, "error": ...}` on failure
  instead of raising into the LLM loop.
- `app/prompts.py`: the system prompt (polite, ≤2 sentences, never state an
  unreturned slot, confirm before booking, spoken-number style).
- `app/agent.py`: `Agent.handle_turn()` — the tool-calling loop (max 4 rounds per
  turn), `LLMClient` protocol + `SarvamLLMClient` real implementation, per-session
  conversation history.
- `scripts/chat_cli.py`: terminal chat, prints tool calls in grey.

**Real bugs found and fixed while live-testing against the real LLM:**
- `service` param had no enum → LLM guessed synonyms ("root canal") that never
  matched `clinic.yaml`'s keys and silently never booked. Fixed by adding an enum.
- Nearly every golden test case never states a phone number on the call — correctly
  so, since phone is channel identity (Twilio caller ID / WhatsApp sender), not
  something the LLM should ask for. Fixed: `phone` removed from LLM-facing tool
  schemas; `Agent` takes a session-level `caller_phone` instead.
- Eval harness defaulted `now` to real wall-clock time, so "kal" (tomorrow) could
  land on the clinic's weekly-off day depending what day you ran the eval —
  violating this project's own "fixed `now`, no `datetime.now()` in tested logic"
  rule, just not followed in the eval harness itself.
- Eval grading used exact string match for free-text tool args, failing functionally
  correct answers phrased differently than the golden expectation.
- One transient network timeout used to abort the *entire* eval batch; fixed so one
  flaky case fails alone.

**Eval pass rate journey (live, against the real Sarvam LLM):** 24% → 44% → 48% →
**56% (14/25)**, across 4 runs, fixing a real bug each round.

**Why the ≥85% gate isn't met, and why the project moved on anyway (explicit user
decision, 2026-11-07):** 6 of 11 remaining failures trace to `answer_faq` still being
the Phase 3 stub (structurally can't answer yet); 3 more fail because the agent
*correctly* inserts one more confirm-before-booking turn than the golden script
accounts for (the golden scripts were a turn short, not the agent being wrong). Per
CLAUDE.md's own "don't change test_calls.yaml to make an eval pass" rule, this was
raised with the user instead of silently adjusted — user chose to move to Phase 3 and
revisit after FAQ RAG landed.

**Still open from Phase 2 (deferred, not blocking):** manual `chat_cli.py` checks
(book/cancel/reschedule in Hindi/English/Hinglish, and the "5:15 book kar do when
5:15 isn't free" trick-question check).

### 5.3 — Phase 3: FAQ RAG — 🟨 code complete, gate not formally met

Answer clinic questions only from `faqs.md`; say "I'll confirm with staff" when the
answer isn't there.

- `scripts/ingest_faqs.py`: splits `faqs.md` by `##` heading, embeds with a small
  multilingual model, stores in a persistent Chroma collection. Re-ingests when
  `faqs.md`'s hash changes.
- `app/rag.py`: `retrieve(question, k=3)`.
- `answer_faq` tool: below-threshold score → `{"found": false}` → prompt makes the
  bot say it'll confirm with staff.
- Unanswered questions logged to an `unanswered` table for the owner to review later.

**Real bug found and fixed:** `rag.ingest` originally embedded each chunk as
`"{question}\n{answer}"`. For "Doctor kaun hain?" (who is the doctor), the answer
("BDS/MDS qualified dentist") shares almost no vocabulary with the question, so the
combined embedding scored below its *own* threshold against the question text —
i.e. the FAQ couldn't find itself. Switching to question-only embedding fixed that
but regressed 3 of 18 paraphrase tests that leaned on *answer* vocabulary. Fixed
properly by indexing **both** a question-only and question+answer variant per FAQ
(`<id>-q` / `<id>-qa`), deduped to the best-scoring variant at retrieve time.

**Retrieval test results:** 18/18 paraphrases correctly matched in top 3 (100%), 6/6
out-of-scope questions correctly rejected (100%) — after tuning
`FAQ_SCORE_THRESHOLD` to 0.565 (started at 0.5, raised twice to reject adversarial
near-misses like "MRI scan hota hai kya yahan" and "share market mein kya chal raha
hai" scoring against unrelated FAQs).

**Eval pass rate journey:** 53% → 63% → 67% → **73% (22/30)**, across 4 more live
runs, fixing real bugs each round:
- A stale hardcoded "Phase 2" report path was silently overwriting the Phase 2
  report file — fixed by parameterizing the report title.
- Eval grading's digit-matching (`check_must_mention`) didn't recognize *spoken*
  numbers ("paanch sau rupaye") as satisfying a check for "500" — the agent was
  likely right and being marked wrong for correctly following the no-digits prompt
  rule. Added spoken-number recognition to the grader.
- Confirmed (by live-tracing `booking_002/003/005` turn-by-turn against the real
  LLM) that several "failures" were the agent being *correct*: it insisted on an
  explicit yes before booking, and correctly asked for a missing date instead of
  guessing — the golden scripts were simply one exchange short. Fixed by completing
  those scripts, not by loosening any assertion.

**Why the ≥85% gate isn't met, and why the project moved on anyway (explicit user
decision, 2026-11-09):** remaining failures are pre-existing Phase-2-era issues
(verbose replies, a `check_slots` call missing `part_of_day` because the caller
didn't mention it until a later turn) plus grading-strictness artifacts, none
FAQ/RAG-specific. User chose to track the overall pass rate at the end of every
phase going forward rather than keep spending on live eval runs chasing non-RAG
issues now.

### 5.4 — Phase 4: Voice in the browser — 🟨 all tasks + manual checks done, gate not formally met

Talk to the agent through a laptop microphone via Pipecat + WebRTC.

- `app/voice_bot.py`: the actual pipeline —
  `transport.input() → VADProcessor(SileroVADAnalyzer) → SarvamSTTService →
  AgentProcessor → SarvamHttpTTSService → [TTSLatencyMarker] → transport.output()`.
- **`AgentProcessor`** is the key bridge: turns a final STT `TranscriptionFrame` into
  an `Agent.handle_turn()` call and emits the reply as TTS text frames. Deliberately
  *not* Pipecat's native LLM-service tool-calling — that would mean two independent
  tool-calling implementations (one here, one in Pipecat) that could drift apart.
  There is exactly one, reused by both the voice and text paths (enforced by
  `tests/integration/test_voice_text_equivalence.py`, which asserts the voice
  pipeline produces identical tool calls to the Phase 2 text agent for the same
  input).
- Greeting on connect, `CallLogger` (saves every voice session's transcript to
  `CallLog`), `app/metrics.py` (`TurnTracker`/`TurnTimer` — timestamps speech end →
  STT final → LLM first token → TTS first audio, one JSON line per turn).
- STT: `saaras:v4` / `codemix` (confirmed via a real multi-turn Hindi/English/Hinglish
  call that STT correctly handles code-switching mid-sentence).
- TTS: `bulbul:v3` / `shreya` — chosen by listening to 6 speaker samples of the
  actual bot greeting; a tone/personality choice, not technical (all are genuinely
  Indian-accented).
- Dev entry point uses Pipecat's own runner (`pipecat.runner.run.main()`), which
  auto-discovers `bot(runner_args)` and serves a prebuilt WebRTC client at
  `localhost:7860` — not a hand-built FastAPI route, so this doesn't need
  restructuring when Twilio support is added in Phase 8 (it's keyed by transport
  name already).

**Real bugs found during the first live call (2026-11-09):**
1. **VAD fragmentation.** The caller's "haan, kar do" landed as two separate
   VAD-detected utterances 0.6s apart (two separate STT finals), so the agent only
   ever saw an isolated, unconfirmable "haan" and escalated to a human instead of
   booking. Root cause confirmed via server debug log, not guessed. **This is what
   Phase 5 task 5.5 fixed** — see §5.6 below.
2. **Metrics never reaching disk.** `scripts/run_voice_bot.py` configured the file
   sink *before* `pipecat.runner.run.main()`, but `main()` calls `logger.remove()`
   at startup, wiping it. Fixed with a lazy `ensure_file_sink()` called from inside
   `run_bot()` (which only ever runs after that reset).
3. **Every voice booking was silently failing.** `run_bot()` constructed `Agent`
   with no `caller_phone` at all, so `book_appointment` (which requires `phone`)
   raised `TypeError` on every attempt — the agent retried across all 4 tool rounds
   and fell back to a generic error, which is exactly what the transcript showed
   even after the caller said "haan kar do". Fixed with
   `placeholder_caller_phone(session_id)` — deterministic per session (not shared),
   so concurrent testers don't collide on one phone number.
4. `TurnTracker` could produce physically-impossible negative stage durations from
   overlapping turns (next utterance arriving before the previous turn's marks
   finish) — fixed to drop and count them rather than skew p50/p95.

**After fixing all of the above: 5 real confirmed voice bookings** (verified against
the real SQLite DB). Latency measured (`reports/latency_phase4.md`, 28 completed
turns, 3 negative readings dropped):

| stage | n | p50 (ms) | p95 (ms) |
|---|---|---|---|
| stt_latency_ms | 25 | 162 | 4825 |
| llm_latency_ms | 20 | 2587 | 5620 |
| tts_latency_ms | 24 | 1366 | 1836 |
| total_latency_ms | 28 | 3192 | 9267 |

No target yet at this point (Phase 5 is where these get optimized) — but note `llm`
dominates the total, which is exactly what Phase 5.1 (streaming) targeted.

**Still open (not blocking further work, but the gate isn't formally complete):**
`tests/evals/test_stt_samples.py`'s **10 real `.wav` recordings of real human
voices** are the only missing piece. `app/stt_eval.py` and the test harness are
fully built and unit-tested with fakes; `tests/fixtures/audio/manifest.yaml` lists
the 10 sentences to record. **This genuinely cannot be done by an AI — it needs an
actual human voice.** If you're a developer picking this up: recording these 10
short clips and running `pytest -m live tests/evals/test_stt_samples.py` is the one
remaining action item to close Phase 4's gate.

### 5.5 — Phase 5: Hinglish + latency hardening — 🟨 IN PROGRESS (current phase)

**Goal:** make it feel like a real conversation — fast, interruptible, patient with
silence, good at language-mixing. Gate: p50 ≤1.5s / p95 ≤2.5s turn latency, ≥9/10
manual calls book correctly, barge-in + silence tests pass, eval pass rate ≥85%.

Nine tasks total (5.1–5.9). **Four done so far: 5.5, 5.1, 5.2 and 5.8**, following
BUILD_PLAN.md's own recommended order (`5.0 → 5.2 → 5.8 → 5.3 → 5.4 → 5.6 → 5.9 → 5.7
→ 5.11 → 5.10`) from 5.2 onward; 5.5 and 5.1 landed earlier, before that order was
written.

#### Task 5.5 — Tune the VAD so it doesn't cut people off — ✅ Done

**Commit:** `bb95b3f`.

Root cause (confirmed by reading `pipecat.audio.vad.vad_analyzer`'s state machine
and `pipecat.services.sarvam.stt`'s handling of `VADUserStoppedSpeakingFrame` —
not guessed): Pipecat's Silero VAD default `stop_secs` is 0.2s — the trailing
silence VAD waits before declaring the user has stopped talking — and
`SarvamSTTService` finalizes the transcript on exactly that signal. The 0.6s gap in
"haan, kar do" (Phase 4's live-test bug) is well past 0.2s, so VAD fired a stop
after "haan" alone.

**Fix:** raised `stop_secs` to 0.7s. `app/voice_bot.py`'s `VAD_STOP_SECS` constant +
`_vad_params()` helper (kept separate from the real `SileroVADAnalyzer` construction
so it's unit-testable without loading the ONNX model).

**Important, documented tradeoff:** this delay sits *before*
`VADUserStoppedSpeakingFrame` is even created — so it's **invisible** to
`TurnTracker`/`latency_report.py`. `speech_end` is stamped from the frame's own
creation timestamp, which is already `stop_secs` *after* the caller's last word.
Raising `stop_secs` from 0.2s to 0.7s added ~0.5s of real, caller-perceived latency
that Phase 4's measured numbers above never counted. **0.7s is explicitly
provisional** — it needs Phase 5's manual multi-person call check (task further
down this list, not yet done) to confirm it's not now too long. `start_secs`/
`confidence`/`min_volume` were left at Pipecat defaults — no evidence pointed at
them, so touching them would just be guessing.

Unit-tested in `tests/unit/test_voice_bot.py`
(`test_vad_params_uses_the_tuned_stop_secs`).

#### Task 5.1 — Stream LLM tokens + sentence-by-sentence TTS — ✅ Done

This was the big one — full brainstorming → spec → implementation plan →
subagent-driven execution cycle, documented in detail below because of how it was
built, not just what.

**Goal:** Phase 4 measured p95 total latency at ~9.3s, dominated by `llm_latency_ms`
(p95 5620ms) because the agent waited for the *entire* LLM reply before anything
downstream (TTS) could start. Stream the reply so the caller hears sentence 1 while
sentence 2 is still being generated.

**Key design-time discovery that simplified the whole task:** Pipecat's `TTSService`
base class *already* buffers incoming text and dispatches synthesis per completed
sentence (`TextAggregationMode.SENTENCE`, its existing default — true of
`SarvamHttpTTSService` too). It just never got a chance to help, because the old
code waited for the full reply and pushed it as one single `TextFrame` at the end.
**No custom sentence-splitter was needed anywhere in this project's code** — just
feed TTS the text incrementally and reuse Pipecat's own aggregator.

**Scoping decisions (confirmed with the user before building):**
- TTS stays on `SarvamHttpTTSService` (one HTTP call per sentence via Pipecat's own
  aggregation) rather than switching to Sarvam's separate WebSocket streaming TTS
  API. Lower risk, ships faster. *(Later found during 5.2's research — see §5.6 —
  that this swap isn't actually required for barge-in either, so it may never be
  needed at all unless lower raw audio latency specifically is wanted later.)*
- One streaming code path inside `Agent`, not two parallel implementations for
  voice vs. text — `Agent.handle_turn()` always consumes a stream; the text path's
  return value is unaffected.

**What got built** (spec: `docs/superpowers/specs/2026-11-09-voice-streaming-design.md`,
plan: `docs/superpowers/plans/2026-11-09-voice-streaming.md`):

1. **`app/llm_streaming.py`** (new) — pure, no HTTP/pipecat imports:
   - `ChatDelta(content, tool_call_deltas)`, `ToolCallDelta(index, id, name,
     arguments_fragment)` — one chunk of a streamed response.
   - `ToolCallAccumulator` — merges fragmented tool-call deltas (OpenAI-compatible
     streaming APIs send a tool call's `id`/`name` once and `arguments` as many
     small string fragments, all keyed by `index`) into finished `FinishedToolCall`s.
2. **`app/agent.py`** — `LLMClient.chat()` replaced by
   `stream_chat(messages, tools) -> AsyncIterator[ChatDelta]`. `Agent.handle_turn()`
   rewritten to consume the stream, with a new optional
   `on_reply_chunk: Callable[[str], Awaitable[None]]` parameter that fires live with
   each content delta — **but only once a round is confirmed tool-call-free**
   (`saw_tool_call_delta`, reset every round): nothing is ever spoken that might
   turn out to be a dropped tool-call preamble. `handle_turn()`'s return value is
   unchanged, so `chat_cli.py`/`run_evals.py` needed zero changes.
   `SarvamLLMClient.stream_chat()` does the real SSE parsing (`"data: {...}"` lines,
   `[DONE]` terminator, skips Sarvam's documented empty-`choices` usage trailer
   chunk).
3. **`app/voice_bot.py`** — `AgentProcessor` pushes a `TextFrame` per chunk live
   (instead of one `TextFrame` per full reply at the end), and marks
   `TurnTracker.llm_first_token` on the *first* chunk only (guarded, same pattern
   `TTSLatencyMarker` already used).
4. **`tests/fixtures/fake_llm.py`** — `FakeLLM.responses` now accepts either a plain
   `LLMResponse` (auto-wrapped into one chunk, so every one of ~15 pre-existing
   tests needed zero changes) or an explicit `list[ChatDelta]` for tests that need
   fine-grained chunk timing.

**How it was actually built — process detail, useful if you do this again:** this
went through the full `brainstorming → writing-plans → subagent-driven-development`
Superpowers workflow: a design spec was written and approved, then a 5-task
implementation plan, then each task was implemented by a fresh dispatched subagent,
reviewed by a separate subagent, and only moved on once clean. Built in an isolated
git worktree (`.worktrees/phase5-voice-streaming`, branched from local `main`) so
`main` was never touched until the whole thing was reviewed and merged. A **final
whole-branch review** ran after all 5 tasks, specifically looking for cross-task
issues no single task's review could see.

**Real bugs found and fixed during this build** (each one is informative about
what kind of mistakes recur in this codebase):
- **Pre-existing, pre-plan bug** (found before Task 1 even started):
  `test_voice_frame_produces_same_tool_call_as_text_agent` never requested the `db`
  test fixture, so it silently relied on the developer's real local `data/app.db`
  already having the right schema (from live Phase 4 voice-bot runs). On a fresh
  checkout — this worktree, or GitHub CI, which does a fresh checkout with no DB
  setup step — it failed with `no such table: appointment`. **This means the
  current CI workflow was almost certainly broken on `main` and nobody had
  noticed**, since CI likely hasn't run since this test was added in Phase 4. Fixed
  by adding the `db` fixture parameter (commit `683dc77`). **The exact same class of
  bug recurred twice more** later in this same build (once in a new test for Task 4,
  once implicitly) — worth remembering for any future test that exercises a real
  tool call.
- A test *I (the AI) wrote in the plan itself* had a wrong assertion — it expected
  tool-call suppression to persist across multiple LLM rounds within one turn, when
  the actual design (and the test's own docstring) is round-scoped, resetting each
  round. The implementation was correct; the test assertion was fixed instead.
- The streaming protocol change broke an *unrelated* test fixture
  (`_FlakyLLM` in `tests/unit/test_evals.py`, used to test that one flaky eval case
  doesn't crash the whole batch) that also implemented the old `LLMClient.chat()`
  protocol — missed by the pre-flight scan because it only searched for `.chat(`
  *call sites*, not other classes structurally implementing the old protocol.
  Fixed by converting it to `stream_chat()`.
- A narrow truthiness bug (`if not first_chunk_seen and reply:`) could skip pushing
  audio/marking metrics for a genuinely empty LLM reply. Fixed to
  `if not first_chunk_seen:`.
- **Final whole-branch review found two more real issues**, fixed in one follow-up
  commit (`5041c5b`):
  1. `AgentProcessor` had no exception safety around the streaming call — a
     mid-stream `httpx` failure (Sarvam is known to be flaky; this project has hit
     `ReadTimeout` multiple times in live testing) left `LLMFullResponseEndFrame`
     unpushed, which would leak a partial sentence into the *next* turn's TTS
     aggregation. Fixed: wrap `handle_turn()` in try/except, fall back to
     `FALLBACK_MESSAGE`, always close out the turn frame.
  2. `SarvamLLMClient._parse_sse_line` required the exact prefix `"data: "` (one
     space); any real-world format deviation would silently yield zero deltas with
     no warning — the caller would hear pure silence with no error anywhere. Fixed
     to accept `"data:"` with or without the space, and to log a warning if an
     entire stream yields nothing.

**Deliberately *not* fixed** (documented as accepted limitations, not bugs):
- If a round somehow mixed spoken content with a *trailing* tool-call delta (not
  standard OpenAI-API behavior, not something Sarvam's docs suggest happens),
  already-forwarded content would reach TTS before the tool-call detour. Spec's own
  "Open limitation" section; not engineered around, per YAGNI.
- A *non-exception* `max_tool_rounds` exhaustion that happens after some content was
  already streamed in an earlier round still won't push the fallback message (a
  separate, narrower case than the exception path that *was* fixed). Documented via
  a comment at `app/voice_bot.py`'s `first_chunk_seen` flag.
- A couple of unguarded dict/list subscripts (`ToolCallAccumulator.finish()`,
  `_parse_sse_line`'s `tc["index"]`) that would raise an opaque `KeyError` on a
  shape-violating provider response — inherited from the design, not a new gap.

**Final state:** 253 tests passing, merged to `main` (commit `5041c5b`), worktree
and branch cleaned up.

#### Task 5.2 — Barge-in — ✅ Done

**Commit:** not yet committed as of this writing (worked directly on `main`, not a
worktree, since this was a small bounded change per the project's own process
conventions). See `docs/BUILD_PLAN.md`'s close-out note under task 5.2 for the full
detail; this is the condensed version.

**Goal (from BUILD_PLAN.md):** when the caller starts speaking, stop TTS immediately
and drop the queued audio, without ever cancelling a booking (or any other tool call)
decided on mid-turn.

**Research (unchanged from the earlier design pass):** Pipecat's base `TTSService`
already has a generic `_handle_interruption()` that resets text aggregation and
discards queued audio for *any* TTS service (HTTP or WebSocket) on receiving an
`InterruptionFrame` — the TTS-service swap deferred during Task 5.1 was never
actually required for barge-in. The real gap was that nothing in the pipeline ever
broadcast an `InterruptionFrame` when the caller started talking.

**What got built:**
- **`BargeInProcessor`** (`app/voice_bot.py`), inserted right after `VADProcessor` in
  `build_pipeline()`: on `VADUserStartedSpeakingFrame` it calls
  `self.broadcast_interruption()`, forwarding every frame unchanged otherwise. No VAD
  retuning needed.
- **"Never cancel a booking halfway" — solved differently than first proposed.** The
  original plan said "shield `handle_turn()` and drop remaining text chunks." While
  implementing, found Pipecat already ships the real mechanism for this:
  `Frame.interruptible` (default `True`) — when `False`, `_start_interruption()`
  leaves that processor's in-flight task running instead of cancelling it. Pipecat's
  own Flows manager uses the identical pattern internally. `AgentProcessor` now sets
  `frame.interruptible = False` on the `TranscriptionFrame` before calling
  `handle_turn()`, which is simpler than manually shielding a coroutine and
  guarantees any tool call and its history entry always complete.
- **"No leftover speech" is a separate flag.** `AgentProcessor._interrupted`, set
  `True` by an `InterruptionFrame` arriving mid-turn (observed via Pipecat's separate
  input-frame task, which runs concurrently with the now-uninterruptible process
  task) and reset `False` at the start of every new turn. Both the streaming
  `on_reply_chunk` callback and the final non-streamed-reply push check it and drop
  content once set, instead of forwarding it to TTS.
- **Decision recorded in `docs/architecture.md`:** `Agent`'s history and the
  `CallLog` transcript always keep the *full* reply, even if the caller only heard
  part of it — acceptable because the confirm-before-booking rule catches any
  resulting misunderstanding on the next turn.

**A real race found and fixed *in the test*, not the implementation:** the first
version of `tests/integration/test_barge_in.py`'s "interrupt mid-booking" test sent
the `InterruptionFrame` immediately after the `TranscriptionFrame`, and it failed —
not because the barge-in code was wrong, but because Pipecat's input-frame task
processes a queued `InterruptionFrame` almost immediately, often *before* the process
task even starts the new turn, so `AgentProcessor`'s own turn-start reset
(`self._interrupted = False`) wiped out an interruption that arrived too early. Fixed
by using Pipecat's own `SleepFrame` test helper to delay the `InterruptionFrame` until
the turn had genuinely started. Then verified the test is a real regression guard (not
an accidental pass) by temporarily removing `frame.interruptible = False` and
confirming the booking test fails — the turn gets cut off before
`LLMFullResponseEndFrame`, leaving Pipecat's TTS turn context open, which is exactly
the failure mode this task exists to prevent.

**Also fixed while confirming the local offline suite was healthy before touching
anything (would have been checked as part of task 5.0a, not yet otherwise done):**
`tests/unit/test_tools.py` had three tests calling `book(...)` without a `now=`
override, so they depended on real wall-clock time staying before their hardcoded
`_a_free_slot()` date — the same "fixed `now`" bug class this project has hit before.
It started failing today (2026-11-11) because real time passed the hardcoded date.
Fixed by passing `now=NOW`, matching every other call site in that file.

**Final state:** 256 tests passing (253 + 3 new in `test_barge_in.py`), `ruff check`
and `ruff format` both clean. Not yet committed or pushed.

**Still open, not done in this task:** the actual caller-facing feel of barge-in
(does an interruption feel responsive, any false interruptions from background
noise/echo) can only be judged on a real call — that's Phase 5's multi-person manual
call check, still further down the task list.

#### Task 5.8 — Ignore STT noise — ✅ Done

**Goal (from BUILD_PLAN.md):** empty/<2-character transcripts (after stripping
punctuation) shouldn't reach the LLM, but a short real "yes" (`"haan"`, `"हाँ"`,
`"जी"`, `"ok"`) must still get through — it's a booking confirmation.

**What got built:** `app/stt_noise.py`'s `is_noise(text) -> bool` — a new pure
module (no pipecat imports, same split as `app/metrics.py`), wired into
`AgentProcessor` with a one-line swap: the old `frame.text.strip()` truthiness
check became `not is_noise(frame.text)`.

**Real bug caught before it shipped:** the first instinct was to strip anything
that isn't `str.isalnum()`. That's wrong for Devanagari — the vowel signs and
candrabindu inside "हाँ" are Unicode category `Mc`/`Mn` (combining marks), which
`.isalnum()` treats as non-alphanumeric, stripping "हाँ" down to a single code
point and wrongly dropping a real confirmation as noise. Fixed by stripping on
Unicode *category* (`unicodedata.category(ch)[0] != "P"`) instead, which keeps
combining marks attached to their letter while still dropping actual punctuation
(ASCII and Devanagari `।`/`॥` alike).

**Also caught a wrong test, not a wrong implementation:** the first version of an
integration test asserting "no TextFrame appears" for a dropped noise frame failed
— not because the filter was wrong, but because `TranscriptionFrame` is itself a
`TextFrame` subclass in Pipecat's own hierarchy, so the still-forwarded (but
turn-skipped) noisy frame tripped the same isinstance check. Fixed the test to
exclude the original `TranscriptionFrame` instance from that assertion.

**Tests:** `tests/unit/test_stt_noise.py` (the pure function — all the cases
BUILD_PLAN lists plus a few more) and two new cases in
`tests/integration/test_voice_text_equivalence.py` confirming the wiring: a noisy
transcript starts no turn at all, a short real word still does.

**Carried forward unchanged, as planned:** the cough-during-barge-in limitation
(barge-in fires on VAD start, before any transcript exists, so noise can still
interrupt the bot) is untouched by this task — tracked as a column in the manual
multi-person call check, not built around here.

#### Remaining Phase 5 tasks (not started)

- **5.3 — Silence handling:** ~5s silence → "Hello, kya aap line par hain?"; a
  second silence → say goodbye and end the session.
- **5.4 — Filler for slow tools:** a tool taking >700ms → "Ek second, check karti
  hoon…"
- **5.6 — Spoken-output normalization:** `17:30` → "saade paanch baje", `₹500` →
  "paanch sau rupaye", phone numbers in digit pairs. Pure, testable function.
- **5.7 — Shorten + cache the system prompt** to reduce LLM time-to-first-token.
- **5.9 — `transfer_to_human` takes a message + promises a callback** (a real call
  transfer only comes in Phase 8 with Twilio).

**Phase 5's complete-when gate** (not yet met): p50 ≤1.5s / p95 ≤2.5s turn latency,
≥9/10 manual calls book correctly, barge-in + silence tests pass, eval pass rate
≥85%. The latency numbers haven't been re-measured since 5.1 landed — that's a
natural next step once a few more tasks are in, to see how much the streaming work
actually moved the needle versus Phase 4's baseline.

### 5.6 — Phases 6–10 — ⬜ Not started

- **Phase 6:** WhatsApp confirmations & reminders (Cloud API, APScheduler reminders,
  delivery-status webhook).
- **Phase 7:** Google Calendar two-way sync (SQLite stays source of truth; Calendar
  sync runs in the background with retries).
- **Phase 8:** Real phone calls (Twilio Media Streams, Cloudflare Tunnel, caller-ID
  passthrough, human-transfer via `<Dial>`, signature validation).
- **Phase 9:** Dashboard (Streamlit), structured logging, Docker, 24/7 deploy,
  nightly backup, budget guard alert.
- **Phase 10:** Demo video, polished README, real pilot with 2-3 Udaipur clinics.

---

## 6. Architecture decision log (condensed from `docs/architecture.md`)

- **`bulbul:v2` is deprecated** — use `bulbul:v3`; the speaker list differs between
  versions (`priya`/`neha`/`pooja` etc. valid on v3, `anushka` is not).
- **STT mode `codemix`**, language left auto-detect — built specifically for
  Hinglish, better than pinning `hi-IN`.
- **TTS speaker `shreya`** — chosen by ear against the actual bot greeting, a
  persona/tone call, not technical.
- **Pipecat 1.15.0 moved VAD off `TransportParams`** — it's now its own pipeline
  stage (`VADProcessor(vad_analyzer=...)`), not a transport param as older Pipecat
  docs show.
- **The voice pipeline's "LLM stage" is the Phase 2 `Agent`, not a native Pipecat LLM
  service** — deliberate, to avoid two independent tool-calling implementations
  drifting apart.
- **`app/metrics.py` has zero pipecat imports on purpose** — trivially
  unit-testable with synthetic timestamps.
- **Silero VAD `stop_secs` raised 0.2s → 0.7s** (Phase 5.5) — fixes real
  conversational-pause cutoffs, at the cost of ~0.5s of real latency invisible to
  the metrics pipeline. Provisional pending manual multi-person testing.
- **LLM/TTS streaming (Phase 5.1) needed no custom sentence-splitter** — Pipecat's
  `TTSService` already buffers text into sentences; the fix was feeding it text
  incrementally, not writing new text-processing logic.
- **TTS stays HTTP, not WebSocket** — confirmed (during 5.2's research) that this
  choice doesn't block barge-in either; the generic Pipecat interruption mechanism
  works for any `TTSService` subclass. The WebSocket swap (`SarvamTTSService`/
  `InterruptibleTTSService`) remains purely optional, relevant only if raw audio
  latency specifically becomes a target later.

---

## 7. Known issues, gaps, and things to watch

**Blocking a phase gate, needs a human:**
- Phase 4: 10 real human-voice `.wav` recordings for `tests/evals/test_stt_samples.py`
  — the harness is built, this genuinely cannot be automated.

**Known-broken or fragile, not yet addressed:**
- GitHub Actions CI was very likely broken on `main` for some time (see the `db`
  fixture bug above) until Phase 5.1's prerequisite fix — worth confirming the next
  CI run is actually green.
- `docs/BUILD_PLAN.md`'s own eval-pass-rate gates for Phases 2 and 3 (≥85%) were
  never met (sat at 56% and 73% respectively) — the project moved on by explicit
  user decision each time, tracking the number at the end of every phase instead of
  blocking on it. Worth re-checking after more of Phase 5 lands, since none of the
  remaining failures were FAQ/RAG-specific.
- Offline test suite runtime has been creeping toward its ~30s budget since Phase 3
  (dual-variant RAG indexing added real embedding-model overhead); currently
  ~26-27s. Worth watching if more real-model tests get added.
- `TurnTracker` logs one row per TTS clip in `latency_report.py`'s output, so a
  multi-sentence reply contributes multiple `total_latency_ms` rows — any future
  latency report should read p50/p95 as directionally comparable before/after a
  change, not as a literal per-call number.

**Deliberately deferred (documented, not bugs):**
- Several Phase 5.1 edge cases around the tool-call-suppression safety gate (listed
  in §5.6 above) — all low-probability, all documented, none currently tested
  against because they'd require a provider response shape nothing currently
  produces.
- The WebSocket TTS swap, mentioned twice now — not needed for anything built so
  far.

---

## 8. Testing status

As of the last full run (post-merge on `main`, 2026-11-10): **253 tests passing, 0
failures, offline suite ~26-27s.** `ruff check` clean. No live tests run this
session (per the cost-conscious rule — only run `pytest -m live` when explicitly
asked).

Test layout:
- `tests/unit/` — pure functions: `booking.py`, `timeparse.py`, `tools.py`,
  `metrics.py`, `llm_streaming.py`, `evals.py`'s grading logic, `sarvam_llm_client`'s
  streaming parser, `voice_bot.py`'s small helpers.
- `tests/integration/` — `Agent` + tools + in-memory DB (`FakeLLM`), the full voice
  pipeline with fakes (`test_pipeline_build.py`, `test_voice_text_equivalence.py`,
  `test_turn_metrics.py`), RAG retrieval against a real (small) embedding model.
- `tests/evals/` — live, `@pytest.mark.live`, run only on request.

---

## 9. Budget tracker

| Item | Planned | Actual so far |
|---|---|---|
| Sarvam credits (STT/TTS/LLM) | ₹300–500 | Used across Phase 2-4 live testing + 5 real Phase 4 voice bookings; exact spend not tracked in this file, see `reports/` |
| Hosting | ₹0–400 | Not started (Phase 9) |
| Twilio / WhatsApp | ₹0 (trial/test tiers) | Accounts created, not yet used for real sends/calls |
| **Total target** | **≤ ₹800** | — |

No live API spend happened in this session (Phase 5.1/5.5/5.2-research were all
built and verified offline, against `respx`-mocked HTTP and `FakeLLM` — by design,
per the cost-conscious rule).

---

## 10. What a senior developer should probably do next

1. **Commit and push task 5.2's barge-in work** (not yet done as of this writing) —
   then actually check the GitHub Actions run, since local `main` is ~34 commits
   ahead of `origin/main` and CI hasn't run since Phase 0.
2. **Record the 10 STT sample `.wav` files** (Phase 4's one remaining gap) — this
   needs an actual human, 10 short Hinglish sentences, instructions already in
   `tests/fixtures/audio/manifest.yaml`.
3. **Finish task 5.0** (housekeeping: the latency-report honesty fix and the
   test-suite-budget check) — started but not completed this session; only the CI/
   offline-suite-health part got done, including a real pre-existing test bug fix
   (see §5.5's Task 5.2 notes above).
4. **After a few more Phase 5 tasks land**, re-run `scripts/latency_report.py`
   against a real voice session and compare to Phase 4's baseline table in §5.4 —
   that's the real test of whether 5.1's streaming work (and 5.5's VAD change)
   actually helped or whether the 0.5s `stop_secs` tradeoff ate the gains.
5. **Re-run the live evals** (`scripts/run_evals.py`) at some point after more of
   Phase 5 lands, to see if the streaming/latency work moved the stuck ~73% pass
   rate at all, per the user's own stated plan to track this across phases.
6. Everything else is exactly next in `docs/BUILD_PLAN.md`'s phase order: 5.3 → 5.4
   → 5.6 → 5.7 → 5.8 → 5.9 → Phase 5's manual multi-person call check → Phase 6.

---

## 11. Process notes (how this project is actually being worked on)

Worth knowing if you're a developer (human or AI) picking this up: larger, genuinely
architectural changes (like Task 5.1) go through a structured process —
brainstorm → write a design spec → write an implementation plan → execute the plan
with isolated, reviewed subagent dispatches per task → a final whole-branch review →
merge. Smaller, well-scoped changes to existing code (like Task 5.5, and the
proposed Task 5.2) skip the heavy spec/plan documents and just get a short design
discussion before implementation. Every non-trivial design choice gets written down
either in `docs/architecture.md` (durable technical decisions) or in a close-out
note directly under the relevant task in `docs/BUILD_PLAN.md` (what happened, what
broke, why a gate was or wasn't met) — so the *reasoning*, not just the *code*,
survives for whoever reads this next.
