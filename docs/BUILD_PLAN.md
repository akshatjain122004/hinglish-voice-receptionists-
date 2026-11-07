# BUILD PLAN — Hinglish Voice Receptionist

> An AI receptionist that answers a small business's phone (clinic / salon / coaching centre), talks in Hindi, English or Hinglish, books appointments, answers FAQs and sends a WhatsApp confirmation.

**Pilot business:** Dental clinic (Udaipur)
**Budget:** ₹500–800 total
**Stack:** Python 3.11 · Pipecat · Sarvam AI (STT / LLM / TTS) · SQLite → Google Calendar · Chroma · WhatsApp Cloud API · Twilio / Plivo · FastAPI · Streamlit · Docker

---

## How to use this file

1. Work **one phase at a time, in order**.
2. Tick each task `[x]` as you finish it.
3. A phase is **complete only when** all of the following are true:
   - every task is ticked,
   - every **automated test** listed passes (`pytest` is green),
   - every **manual check** is done,
   - the **Phase complete when** gate is met.
4. Commit at the end of every phase: `git commit -m "phase N complete"` and tag it: `git tag phase-N`.

### Status board

| Phase | Name | Status |
|---|---|---|
| 0 | Project setup & scope | ✅ Complete (Sarvam live smoke test deferred) |
| 1 | Booking engine (no AI) | ✅ Complete |
| 2 | Text agent "brain" | ⬜ Not started |
| 3 | FAQ RAG | ⬜ Not started |
| 4 | Voice in the browser | ⬜ Not started |
| 5 | Hinglish + latency hardening | ⬜ Not started |
| 6 | WhatsApp confirmations & reminders | ⬜ Not started |
| 7 | Google Calendar sync | ⬜ Not started |
| 8 | Real phone calls | ⬜ Not started |
| 9 | Dashboard, logging & deploy | ⬜ Not started |
| 10 | Demo, docs & pilot | ⬜ Not started |

Legend: ⬜ Not started · 🟨 In progress · ✅ Complete

---

## Target folder structure

```
hinglish-receptionist/
├── app/
│   ├── config.py            # settings loaded from .env
│   ├── db.py                # SQLite models + session
│   ├── booking.py           # slot logic (pure Python, no AI)
│   ├── timeparse.py         # "kal shaam saade paanch" -> datetime
│   ├── tools.py             # tool functions exposed to the LLM
│   ├── agent.py             # LLM + tool-calling loop (text)
│   ├── prompts.py           # system prompt
│   ├── rag.py               # FAQ ingest + retrieve (Chroma)
│   ├── whatsapp.py          # WhatsApp Cloud API client
│   ├── calendar_sync.py     # Google Calendar adapter
│   ├── voice_bot.py         # Pipecat pipeline (browser + phone)
│   ├── server.py            # FastAPI: webhooks, websocket, health
│   └── metrics.py           # latency + call logging
├── dashboard/
│   └── streamlit_app.py
├── data/
│   ├── clinic.yaml          # name, hours, services, slot length
│   ├── faqs.md              # clinic FAQs
│   └── test_calls.yaml      # golden Hinglish test conversations
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evals/
├── scripts/
│   ├── chat_cli.py          # talk to the agent by typing
│   ├── ingest_faqs.py
│   ├── run_evals.py
│   └── latency_report.py
├── docs/
│   ├── BUILD_PLAN.md        # ← this file
│   └── architecture.md
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## Testing strategy (applies to every phase)

| Layer | What it checks | Tool | Runs |
|---|---|---|---|
| **Unit tests** | Pure functions: slot logic, time parsing, tool inputs/outputs | `pytest` | Every commit, offline, free |
| **Integration tests** | Agent + tools + DB together, with the **LLM mocked** | `pytest` + fake LLM | Every commit, offline, free |
| **Evals** | Real LLM on golden Hinglish conversations; pass rate threshold | `scripts/run_evals.py` | End of phase (costs a few paise) |
| **Latency benchmarks** | Time per stage (STT, LLM, TTS) and per turn | `scripts/latency_report.py` | Phases 4, 5, 8, 9 |
| **Manual checks** | Real voice / phone / WhatsApp behaviour | You + 2–3 friends | End of phase |

**Rules**
- Tests that call paid APIs are marked `@pytest.mark.live` and skipped by default. Run them with `pytest -m live`.
- Default `pytest` must run **offline, free and in under 30 seconds**.
- Never commit `.env`. Commit `.env.example` only.

`pyproject.toml` test config:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: calls real paid APIs (deselected by default)"]
addopts = "-m 'not live' -q"
asyncio_mode = "auto"
```

---

## Phase 0 — Project setup & scope

**Goal:** a clean repo, accounts ready, and the clinic's information written down.
**Time:** 1–2 days · **Cost:** ₹0

### Tasks
- [x] 0.1 Create the GitHub repo `hinglish-receptionist` with a `README.md`, `.gitignore` (Python) and MIT `LICENSE`.
- [x] 0.2 Create the folder structure above (empty files are fine).
- [x] 0.3 Create a virtualenv on Python 3.11 and add dependencies: `pipecat-ai[sarvam,silero,webrtc]`, `fastapi`, `uvicorn`, `sqlmodel`, `chromadb`, `httpx`, `pyyaml`, `python-dotenv`, `pydantic-settings`, `pytest`, `pytest-asyncio`, `ruff`.
- [x] 0.4 Create accounts: Sarvam AI (API key) ✅, Google Cloud (Calendar API enabled, service account created, calendar shared, `.env` configured) ✅, Twilio (trial account + SID/Auth Token in `.env`; buying a number deferred to Phase 8 since it needs a paid upgrade) ✅, Meta for Developers (new app "Swagat AI Receptionist" linked to an unrestricted business portfolio, WhatsApp test number + access token in `.env`) ✅.
- [x] 0.5 Write `.env.example` with every key name (no values) and `app/config.py`, which loads them with `pydantic-settings`.
- [x] 0.6 Write `data/clinic.yaml`: clinic name, address, working hours, lunch break, weekly off day, services with durations (cleaning 30 min, consultation 15 min, filling 45 min) and slot granularity (15 min).
- [x] 0.7 Write `data/faqs.md` with **at least 15 Q&As** (fees, timings, parking, payment modes, insurance, location, emergency, kids, etc.).
- [x] 0.8 Write `data/test_calls.yaml` with **at least 20 golden conversations** in Hinglish, Hindi and English. Include: normal booking, no slot available, FAQ, reschedule, cancel, caller changes language mid-call, unclear request, off-topic question, and the caller asking for a human.
- [x] 0.9 Add `ruff` and a GitHub Actions workflow that runs `ruff check` and `pytest` on every push.

### Automated tests
- [x] `tests/unit/test_config.py`: config loads from a temp `.env`; a missing required key raises an error.
- [x] `tests/unit/test_data_files.py`: `clinic.yaml` parses and has the required keys; `faqs.md` has ≥ 15 questions; `test_calls.yaml` has ≥ 20 cases, each with `id`, `turns` and `expected`.

```python
# tests/unit/test_data_files.py
import yaml, re, pathlib
DATA = pathlib.Path("data")

def test_clinic_yaml_has_required_keys():
    c = yaml.safe_load((DATA / "clinic.yaml").read_text())
    for key in ["name", "hours", "services", "slot_minutes", "weekly_off"]:
        assert key in c

def test_at_least_15_faqs():
    text = (DATA / "faqs.md").read_text()
    assert len(re.findall(r"^##\s", text, re.M)) >= 15

def test_golden_calls_well_formed():
    cases = yaml.safe_load((DATA / "test_calls.yaml").read_text())
    assert len(cases) >= 20
    for c in cases:
        assert {"id", "turns", "expected"} <= c.keys()
```

### Manual checks
- [x] `pytest` runs green locally.
- [x] The GitHub Actions run is green (verified CI #2 on `cf4041e` — success).
- [ ] Each API key works with one hello-world call (Sarvam TTS speaks one sentence to an `.wav` file). *Deferred — this is a live, paid API call; CLAUDE.md says not to run live tests unless asked.*

### ✅ Phase complete when
The repo builds in CI, all data files exist and are validated, and every account key has been smoke-tested. **Effectively complete** — all accounts and `.env` keys are in place and CI is green; only the live Sarvam hello-world smoke test remains, deferred until asked (it costs a small amount and isn't needed to start Phase 1/2 work).

---

## Phase 1 — Booking engine (no AI yet)

**Goal:** correct slot logic in plain Python. The AI will only *call* this; it must never invent slots.
**Time:** 3–4 days · **Cost:** ₹0

### Tasks
- [x] 1.1 `app/db.py`: SQLModel tables `Appointment(id, patient_name, phone, service, start, end, status, created_at)` and `CallLog(id, caller, started_at, ended_at, transcript, outcome)`.
- [x] 1.2 `booking.get_free_slots(date, service, part_of_day=None)`: respects working hours, lunch break, weekly off, service duration and existing bookings. Returns a sorted list of start times.
- [x] 1.3 `booking.book(phone, name, service, start)`: re-checks availability inside a transaction and raises `SlotTakenError` if the slot was taken in between.
- [x] 1.4 `booking.cancel(appointment_id | phone)` and `booking.reschedule(appointment_id, new_start)`.
- [x] 1.5 `booking.find_by_phone(phone)`: returns upcoming appointments.
- [x] 1.6 Phone number normalisation: `98290 12345`, `+91-9829012345` and `09829012345` all become `+919829012345`.
- [x] 1.7 Reject bookings in the past and more than 30 days ahead (configurable).

### Automated tests
- [x] `tests/unit/test_booking.py`, with at least these cases:

| # | Case | Expected |
|---|---|---|
| 1 | Empty day, cleaning (30 min) | Slots every 15 min within hours, none overlapping lunch |
| 2 | Weekly off day | `[]` |
| 3 | Existing 17:30 booking | 17:30 and overlapping starts excluded |
| 4 | Slot ending exactly at closing time | Included |
| 5 | Slot crossing closing time | Excluded |
| 6 | Book a free slot | Appointment saved, status `confirmed` |
| 7 | Book the same slot twice | Second call raises `SlotTakenError` |
| 8 | Book in the past | Raises `ValueError` |
| 9 | Cancel, then re-book the same slot | Works |
| 10 | Reschedule to a taken slot | Raises, original kept |
| 11 | `part_of_day="evening"` | Only slots between 16:00 and 20:00 |

- [x] `tests/unit/test_phone.py`: all formats normalise to E.164; garbage input raises an error.

```python
# tests/unit/test_booking.py (excerpt)
from datetime import date, datetime
import pytest
from app import booking

def test_double_booking_is_rejected(db):
    start = datetime(2026, 11, 10, 17, 30)
    booking.book("+919829012345", "Ravi", "cleaning", start)
    with pytest.raises(booking.SlotTakenError):
        booking.book("+919800000000", "Sita", "cleaning", start)

def test_evening_filter(db):
    slots = booking.get_free_slots(date(2026, 11, 10), "cleaning", "evening")
    assert slots and all(16 <= s.hour < 20 for s in slots)
```

(Use a `db` fixture in `tests/conftest.py` that creates an in-memory SQLite database for each test.)

### Manual checks
- [x] Run `python -m app.booking --demo` to print tomorrow's free slots, then book one and print again. The booked slot disappears.

### ✅ Phase complete when
All 11+ booking cases and the phone tests pass, and test coverage of `booking.py` is at least 90% (`pytest --cov=app.booking`). **Done** — 32 tests passing, 94% coverage on `app/booking.py`.

---

## Phase 2 — Text agent "brain"

**Goal:** chat with the receptionist by **typing** Hinglish. It books correctly through tools.
**Time:** 1 week · **Cost:** ~₹0–20 (Sarvam-105B tokens are very cheap)

### Tasks
- [x] 2.1 `app/timeparse.py`: turns Hinglish date and time phrases into datetimes. Cover at least: `aaj`, `kal`, `parso`, weekday names (`somvaar`/`Monday`), `subah`/`dopahar`/`shaam`/`raat`, `saade paanch`, `paune chhe`, `sava das`, `5:30`, `5 baje`, `half past five`.
- [x] 2.2 `app/tools.py`: define the tools with JSON schemas.
  - `check_slots(date, service, part_of_day?)`
  - `book_appointment(name, phone, service, start)`
  - `cancel_appointment(phone)`
  - `reschedule_appointment(phone, new_start)`
  - `answer_faq(question)` (a stub for now; real RAG comes in Phase 3)
  - `transfer_to_human(reason)`
- [ ] 2.3 `app/prompts.py`: the system prompt. It should:
  - be a polite clinic receptionist;
  - reply in the caller's language (Hinglish in, Hinglish out);
  - keep replies to at most 2 short sentences;
  - **never state a slot that a tool did not return**;
  - always confirm the details before booking;
  - collect the name before booking;
  - write numbers and times in a way that can be spoken.
- [ ] 2.4 `app/agent.py`: the tool-calling loop. Send the message, run any tool calls, feed the results back, and repeat (maximum 4 tool rounds per turn). Keep the conversation history per session.
- [ ] 2.5 The LLM client sits behind an interface (`LLMClient.chat(messages, tools)`) so tests can plug in a `FakeLLM`.
- [ ] 2.6 `scripts/chat_cli.py`: a terminal chat that prints each tool call in grey.
- [ ] 2.7 Guardrails: if a tool errors, the bot apologises and offers alternatives. If the request is off-topic, it gives a polite redirect.

### Automated tests
- [x] `tests/unit/test_timeparse.py`: **at least 30 parametrised phrases** with a fixed "now".

```python
import pytest
from datetime import datetime
from app.timeparse import parse

NOW = datetime(2026, 11, 9, 10, 0)  # Monday 10 AM

@pytest.mark.parametrize("text,expected", [
    ("kal shaam saade paanch", datetime(2026, 11, 10, 17, 30)),
    ("parso subah 10 baje",    datetime(2026, 11, 11, 10, 0)),
    ("aaj paune chhe",         datetime(2026, 11, 9, 17, 45)),
    ("Friday 4 pm",            datetime(2026, 11, 13, 16, 0)),
])
def test_parse(text, expected):
    assert parse(text, now=NOW) == expected
```

- [x] `tests/unit/test_tools.py`: each tool validates its input (bad date, unknown service, bad phone) and returns a JSON-serialisable result.
- [ ] `tests/integration/test_agent_flow.py`: uses a `FakeLLM` that returns scripted tool calls. Checks that:
  - the booking flow ends with exactly one `Appointment` in the DB;
  - when a tool raises `SlotTakenError`, the agent's next message offers other slots;
  - the loop stops after 4 tool rounds (no infinite loop).
- [ ] **Evals** `tests/evals/` + `scripts/run_evals.py` (`live`): run every golden case from `test_calls.yaml` against the real LLM. Each case checks:
  - the correct tool was called with the correct arguments;
  - no hallucinated slot (every time spoken appears in the tool output);
  - the reply language matches the caller's language;
  - the reply is ≤ 2 sentences.

  The script prints a pass-rate table and saves it to `reports/evals_phase2.md`.

### Manual checks
- [ ] Book, cancel and reschedule through `chat_cli.py` in pure Hindi, pure English and Hinglish.
- [ ] Try to trick it: "5:15 book kar do" when 5:15 isn't free. It must refuse and offer real slots.

### ✅ Phase complete when
Unit and integration tests pass, `timeparse` covers ≥ 30 phrases, and **the eval pass rate is ≥ 85%, with 0 hallucinated slots**.

---

## Phase 3 — FAQ RAG

**Goal:** answer clinic questions only from `faqs.md`, and say "I'll confirm with staff" when the answer isn't there.
**Time:** 2–3 days · **Cost:** ₹0

### Tasks
- [ ] 3.1 `scripts/ingest_faqs.py`: split `faqs.md` by `##` heading (one Q&A per chunk), embed the chunks with a small multilingual embedding model, and store them in a persistent Chroma collection.
- [ ] 3.2 `rag.retrieve(question, k=3)` returns chunks with scores.
- [ ] 3.3 `answer_faq` tool: if the top score is below a threshold, return `{"found": false}`. The prompt then makes the bot say "Main staff se confirm karke aapko WhatsApp kar dunga/dungi."
- [ ] 3.4 Log unanswered questions to an `unanswered` table. The owner sees these later and adds them to the FAQ.
- [ ] 3.5 Re-ingest when `faqs.md` changes (compare a file hash).

### Automated tests
- [ ] `tests/unit/test_rag_chunking.py`: 15 FAQs produce 15 chunks, each containing both the question and the answer.
- [ ] `tests/integration/test_rag_retrieval.py`: build a temporary Chroma collection, then check:
  - **at least 15 paraphrased queries** (Hinglish, Hindi and English) retrieve the right FAQ in the top 3 (e.g. "fees kitni hai cleaning ki?" → the cleaning fee FAQ);
  - **at least 5 out-of-scope questions** ("cricket score?", "MRI hota hai?") return `found: false`.
- [ ] Add 5 FAQ cases to `test_calls.yaml` and re-run the evals.

### Manual checks
- [ ] Ask 10 questions in the CLI. Answers match `faqs.md` word for word on facts (fees, timings).

### ✅ Phase complete when
Top-3 retrieval accuracy is ≥ 90% on the paraphrase set, out-of-scope rejection is 100%, and the overall eval pass rate is still ≥ 85%.

---

## Phase 4 — Voice in the browser

**Goal:** talk to the agent through your laptop microphone, with no phone bill.
**Time:** 1 week · **Cost:** ~₹50–150 of Sarvam credits

### Tasks
- [ ] 4.1 `app/voice_bot.py`: a Pipecat pipeline with `transport.input → Silero VAD → Sarvam STT → user aggregator → LLM (with tools from Phase 2) → Sarvam TTS → transport.output → assistant aggregator`.
- [ ] 4.2 Use Pipecat's **SmallWebRTC** transport plus its sample web client, so you talk from the browser.
- [ ] 4.3 Choose the STT model and language mode for code-mixed speech (e.g. Saaras with `hi-IN` / auto-detect) and record the choice in `docs/architecture.md`.
- [ ] 4.4 Choose a TTS voice and speaking pace that sound natural for a receptionist. Use Bulbul v2 while testing because it's cheaper.
- [ ] 4.5 Greeting on connect: "Namaste! [Clinic] mein aapka swagat hai. Main aapki kya madad kar sakti hoon?"
- [ ] 4.6 Save every session's transcript to `CallLog`.
- [ ] 4.7 `app/metrics.py`: timestamp each stage (speech end → STT final → LLM first token → TTS first audio byte) and log one JSON line per turn.

### Automated tests
- [ ] `tests/integration/test_pipeline_build.py`: the pipeline builds with mocked services, and the frame order is correct.
- [ ] `tests/integration/test_voice_text_equivalence.py`: feed **text frames** (bypassing STT) into the pipeline with a `FakeLLM`. The resulting tool calls match the Phase 2 text agent for the same input.
- [ ] `tests/unit/test_metrics.py`: given synthetic timestamps, per-stage durations are computed correctly.
- [ ] `live` test `tests/evals/test_stt_samples.py`: record **10 short `.wav` files** of yourself and friends saying Hinglish booking sentences and save them in `tests/fixtures/audio/`. The STT transcript must contain the key entities (day, time, service). Target: at least 8 of 10 pass.

### Manual checks
- [ ] Complete 5 full bookings by voice in the browser.
- [ ] Run `scripts/latency_report.py` over those sessions and record p50 and p95 latency in `reports/latency_phase4.md`.

### ✅ Phase complete when
You can book by voice end to end, the STT sample test passes at ≥ 8/10, and the latency numbers are measured and recorded (no target yet; you optimise in Phase 5).

---

## Phase 5 — Hinglish + latency hardening

**Goal:** make it feel like talking to a person: fast, interruptible, patient with silence, and good at language mixing.
**Time:** 1 week · **Cost:** ~₹50–100

### Tasks
- [ ] 5.1 Streaming everywhere: switch to the realtime/streaming STT, stream LLM tokens, and start TTS sentence by sentence.
- [ ] 5.2 **Barge-in:** when the caller starts speaking, stop TTS immediately and drop the queued audio.
- [ ] 5.3 **Silence handling:** after ~5 s of silence, say "Hello, kya aap line par hain?" After a second silence, say goodbye and end the session.
- [ ] 5.4 **Filler for slow tools:** if a tool takes more than 700 ms, say "Ek second, check karti hoon…"
- [ ] 5.5 Tune the VAD so it doesn't cut people off mid-sentence or wait too long. Note the final parameters in the docs.
- [ ] 5.6 **Spoken output normalisation:** `17:30` → "saade paanch baje", `₹500` → "paanch sau rupaye", and phone numbers read in pairs.
- [ ] 5.7 Shorten the system prompt and cache the static part of the context to reduce LLM time-to-first-token.
- [ ] 5.8 Handle STT noise: if the transcript is empty or under 2 characters, ignore it instead of sending it to the LLM.
- [ ] 5.9 Caller asks for a human: the `transfer_to_human` tool takes a message and promises a callback (a real transfer comes in Phase 8).

### Automated tests
- [ ] `tests/unit/test_speech_normalise.py`: at least 20 cases covering times, prices, dates and phone numbers.
- [ ] `tests/integration/test_barge_in.py`: simulate a user-speech frame during TTS output. The output is cancelled within one frame.
- [ ] `tests/integration/test_silence.py`: with a fake clock, a reprompt happens at 5 s and the call ends after the second silence.
- [ ] `tests/integration/test_filler.py`: a slow fake tool (1 s) produces a filler phrase before the answer.
- [ ] Evals: add **5 code-switching cases** (e.g. "mujhe tomorrow evening ka appointment chahiye, cleaning ke liye").

### Manual checks
- [ ] 10 voice calls with **3 different people** (different accents). Record each one in a table: booking success (Y/N), awkward pause (Y/N) and interruption handled (Y/N).
- [ ] Run `scripts/latency_report.py` and save the result to `reports/latency_phase5.md`.

### ✅ Phase complete when
- **p50 turn latency ≤ 1.5 s** and **p95 ≤ 2.5 s** (speech end → first audio byte);
- ≥ 9 of 10 manual calls end in a correct booking;
- barge-in and silence tests pass;
- the overall eval pass rate is ≥ 85%.

---

## Phase 6 — WhatsApp confirmations & reminders

**Goal:** every booking gets a WhatsApp confirmation, and a reminder goes out before the visit.
**Time:** 3 days · **Cost:** ₹0 (Meta test number)

### Tasks
- [ ] 6.1 Set up the WhatsApp Cloud API test number in Meta for Developers and add your own phone as a verified recipient.
- [ ] 6.2 Create and get approval for **utility** templates:
  - `appointment_confirmation` (name, service, date, time, clinic)
  - `appointment_reminder`
  - `appointment_cancelled`
- [ ] 6.3 `app/whatsapp.py`: `send_template(to, template, params)` with retries (3 attempts, exponential backoff) and logging of the message ID.
- [ ] 6.4 Hook it in: a successful `book`, `cancel` or `reschedule` triggers the matching template **in the background** so the call isn't slowed down.
- [ ] 6.5 Reminder scheduler (APScheduler): 3 hours before each appointment, send the reminder once. Store `reminder_sent_at` so it never sends twice.
- [ ] 6.6 FastAPI webhook `/whatsapp/webhook`: verify Meta's token and record delivery statuses (sent / delivered / read / failed).

### Automated tests
- [ ] `tests/unit/test_whatsapp_payload.py`: the template payload JSON matches Meta's format exactly (snapshot test).
- [ ] `tests/integration/test_whatsapp_hooks.py` with mocked HTTP (`respx`):
  - a booking sends exactly 1 confirmation;
  - a cancel sends 1 cancellation message;
  - a 500 error is retried 3 times and then logged as failed, and **the booking is still saved**.
- [ ] `tests/integration/test_reminders.py`: with a frozen clock, the reminder is sent at T-3h and never twice.
- [ ] `tests/integration/test_webhook.py`: verification handshake works and status updates are stored.
- [ ] `live` test: send a real confirmation to your verified number.

### Manual checks
- [ ] Book by voice, and the confirmation arrives on your phone within 10 seconds.

### ✅ Phase complete when
All WhatsApp tests pass, a real message arrives, and a WhatsApp failure never breaks a booking.

---

## Phase 7 — Google Calendar sync

**Goal:** the clinic sees appointments in the Google Calendar it already uses.
**Time:** 2–3 days · **Cost:** ₹0

### Tasks
- [ ] 7.1 Create a service account and share the clinic calendar with it.
- [ ] 7.2 `calendar_sync.py`: create, update and delete an event for each appointment, storing `gcal_event_id`.
- [ ] 7.3 Read busy times from Google Calendar too, so slots the doctor blocks manually (e.g. "Leave") are respected by `get_free_slots`.
- [ ] 7.4 SQLite stays the source of truth for bot bookings. Calendar sync runs in the background with retries.
- [ ] 7.5 Use the `Asia/Kolkata` timezone everywhere and store times as timezone-aware datetimes.

### Automated tests
- [ ] `tests/unit/test_calendar_mapping.py`: Appointment ↔ event mapping, with timezone checks.
- [ ] `tests/integration/test_calendar_busy.py` (mocked API): a manually blocked 17:00–18:00 removes those slots.
- [ ] `tests/integration/test_calendar_failure.py`: a Calendar API error doesn't block the booking, and the event is queued for retry.
- [ ] `live` test: create and delete a real event on a test calendar.

### Manual checks
- [ ] A voice booking appears in Google Calendar on your phone.
- [ ] Block a time in Calendar by hand, and the bot no longer offers it.

### ✅ Phase complete when
Two-way availability works, all tests pass, and every timezone check passes.

---

## Phase 8 — Real phone calls

**Goal:** people call a phone number and talk to the bot.
**Time:** 4–5 days · **Cost:** Twilio trial credit (free); a real Indian number later, through the pilot clinic

### Tasks
- [ ] 8.1 FastAPI endpoint `/twilio/voice` returns TwiML that opens a Media Stream to `/ws/twilio`.
- [ ] 8.2 Reuse the same pipeline with Pipecat's Twilio transport/serializer at 8 kHz, μ-law audio.
- [ ] 8.3 Expose your local server with a Cloudflare Tunnel and set the Twilio number's webhook to it.
- [ ] 8.4 Pass the caller's number from Twilio into the session, so the bot doesn't need to ask for it ("Kya isi number par WhatsApp bhej doon?").
- [ ] 8.5 End the call cleanly with Twilio's REST API when the conversation ends.
- [ ] 8.6 Human fallback: `transfer_to_human` forwards the call (TwiML `<Dial>`) to the clinic's mobile, or takes a message if it's after hours.
- [ ] 8.7 Validate Twilio's request signature on the webhook.
- [ ] 8.8 Write a short `docs/telephony.md` explaining how to move to an Indian number (Plivo/Exotel), including the KYC documents needed and that the number is registered under the clinic.

### Automated tests
- [ ] `tests/integration/test_twiml.py`: `/twilio/voice` returns valid TwiML with the correct stream URL.
- [ ] `tests/integration/test_twilio_signature.py`: a bad signature gets a 403 and a valid one gets a 200.
- [ ] `tests/integration/test_caller_id.py`: the caller number reaches the session and is normalised.
- [ ] `tests/integration/test_telephony_audio.py`: an 8 kHz μ-law fixture goes through the serializer and returns PCM of the expected length.

### Manual checks
- [ ] **10 real phone calls** (you plus friends, on different networks). Record booking success and latency for each.
- [ ] One call where you ask for a human: it forwards correctly.
- [ ] Run `scripts/latency_report.py` and save the result to `reports/latency_phase8.md`. The phone path adds network delay, so record the difference compared with the browser.

### ✅ Phase complete when
≥ 8 of 10 phone calls book correctly, p50 latency on the phone is ≤ 2 s, and all telephony tests pass.

---

## Phase 9 — Dashboard, logging & deploy

**Goal:** it runs 24/7, and the owner can see what's happening.
**Time:** 4–5 days · **Cost:** ₹0 (free-tier VM) or ~₹300–400/month VPS

### Tasks
- [ ] 9.1 `dashboard/streamlit_app.py` with password login. Pages:
  - Today's appointments
  - Call log with transcripts and outcome (booked / FAQ / transferred / dropped)
  - Unanswered questions (from Phase 3), with an "add to FAQ" helper
  - Basic stats: calls/day, booking rate, average latency
- [ ] 9.2 Structured JSON logging, plus a `/health` endpoint that checks the DB and the Sarvam key.
- [ ] 9.3 `Dockerfile` (slim Python image, non-root user) and `docker-compose.yml` (app + dashboard + persistent volume for SQLite and Chroma).
- [ ] 9.4 Deploy to an always-on host: an Oracle Cloud Always Free VM or a small VPS. **Don't use hosts that sleep**, because they break live call streams.
- [ ] 9.5 Cloudflare Tunnel (or Caddy with HTTPS) in front of the app, and update the Twilio and WhatsApp webhooks.
- [ ] 9.6 A nightly SQLite backup (cron that copies the file to Google Drive or keeps it compressed locally for 7 days).
- [ ] 9.7 A budget guard: track Sarvam usage per day and send an alert (WhatsApp to you) if spend goes over ₹50/day.
- [ ] 9.8 Secrets only through env vars on the server, never baked into the image.

### Automated tests
- [ ] `tests/integration/test_health.py`: `/health` returns 200 when healthy and 503 when the DB is unreachable.
- [ ] `tests/integration/test_dashboard_queries.py`: the stats queries return correct numbers for seeded data.
- [ ] `tests/unit/test_budget_guard.py`: crossing the threshold triggers exactly one alert per day.
- [ ] CI builds the Docker image (`docker build .` succeeds).
- [ ] **Smoke test script** `scripts/smoke_test.sh`, run against the deployed URL: `/health` returns 200, the TwiML endpoint responds, and the WhatsApp webhook verifies.

### Manual checks
- [ ] Restart the server, and data (appointments, Chroma) survives.
- [ ] Call the number at night with your laptop off, and it still answers.
- [ ] Leave it running for 48 hours, then check the logs for errors and memory growth.

### ✅ Phase complete when
It's deployed and answering calls with your laptop off, the smoke test passes, it runs 48 hours without crashing, and the dashboard shows real data.

---

## Phase 10 — Demo, docs & pilot

**Goal:** turn it into a portfolio piece and a real pilot.
**Time:** 1 week · **Cost:** ₹0

### Tasks
- [ ] 10.1 Record a **2-minute demo video**: a real Hinglish phone call → booking → WhatsApp message arriving → the event in Google Calendar → the dashboard.
- [ ] 10.2 Write a `README.md` with:
  - a one-paragraph pitch;
  - an architecture diagram;
  - features;
  - **latency numbers (p50/p95)** and **eval pass rates** from your reports;
  - a cost per minute;
  - quick start;
  - tests (`pytest` badge);
  - known limitations.
- [ ] 10.3 Write `docs/architecture.md`: the pipeline, why each tool was chosen, the latency budget per stage, and the failure modes and how each is handled.
- [ ] 10.4 Add the explainer page (`hinglish-voice-receptionist-explained.html`) to `docs/` and link it from the README.
- [ ] 10.5 Pilot: approach 2–3 clinics or salons in Udaipur and offer a free 2-week trial. Use the **clinic's KYC** for an Indian number (Plivo/Exotel).
- [ ] 10.6 During the pilot, review the unanswered questions and failed calls every 2 days, add them to `faqs.md` and `test_calls.yaml`, and re-run the evals.
- [ ] 10.7 Write a short pilot report: calls handled, booking rate, owner feedback and an improvements list.
- [ ] 10.8 Resume bullet plus a LinkedIn post with the demo video and real numbers.

### Automated tests
- [ ] The full suite is green: `pytest` (offline) **and** `pytest -m live` (once, before the demo).
- [ ] The final eval run is saved to `reports/evals_final.md`, with a **≥ 90% pass rate and 0 hallucinated slots**.

### Manual checks
- [ ] A friend who has never seen the project calls the number with no instructions and books successfully.
- [ ] The README quick start works on a clean machine (or a fresh Docker container).

### ✅ Phase complete when
The demo video is published, the README contains real numbers, the final evals are ≥ 90%, and at least one business has used it for a real trial.

---

## Overall quality bar (the "done" definition)

| Metric | Target |
|---|---|
| Booking success on real calls | ≥ 90% |
| Hallucinated slots / fees | 0 |
| p50 / p95 turn latency (phone) | ≤ 2 s / ≤ 3 s |
| Eval pass rate (golden set ≥ 30 cases) | ≥ 90% |
| FAQ retrieval top-3 accuracy | ≥ 90% |
| Offline test suite | Green, < 30 s |
| Uptime during pilot | ≥ 99% |
| AI cost per call minute | ≤ ₹1.5 |

---

## Budget tracker

| Item | Planned | Actual |
|---|---|---|
| Sarvam credits (STT / TTS / LLM) | ₹300–500 | |
| Hosting (free-tier VM or VPS, 1 month) | ₹0–400 | |
| Twilio trial | ₹0 | |
| WhatsApp test number | ₹0 | |
| Google Calendar, Chroma, Cloudflare Tunnel | ₹0 | |
| **Total** | **≤ ₹800** | |

Reference prices (Nov 2026; check before buying):
- Sarvam STT: ₹30 per hour of audio.
- Sarvam TTS: Bulbul v2 ₹15, v3 ₹30 per 10K characters.
- Sarvam-105B: ₹4 input / ₹16 output per 1M tokens.
- Sarvam new-account free credits: ₹100.
- WhatsApp utility message in India: ~₹0.115 outside the 24-hour window.

---

## Risk log

| Risk | Impact | Mitigation |
|---|---|---|
| STT mis-hears times or names | Wrong bookings | Always read details back and confirm before booking; send a WhatsApp confirmation |
| LLM invents a slot | Double booking | Slots come only from tools; `book()` re-checks; eval checks 0 hallucinations |
| High latency on phone | Callers hang up | Streaming, fillers, short replies, latency budget per stage |
| Sarvam credits run out | Bot goes silent | Budget guard alert; fallback message plus forward to a human |
| No Indian number without KYC | Can't pilot | Use the clinic's documents; Twilio trial for demos |
| Server down | Missed calls | Health check, auto-restart (`restart: always`), forward to the clinic's mobile |

---

## Daily workflow

```bash
git pull
source .venv/bin/activate
pytest                      # must stay green
# ... work on the next unchecked task ...
ruff check . && pytest
git commit -m "phase X.Y: <task>"
```

At the end of each phase: run the evals or latency report, fill in the gate, update the status board, `git tag phase-N`.
