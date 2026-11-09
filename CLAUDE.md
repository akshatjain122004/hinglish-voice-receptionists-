# CLAUDE.md — Hinglish Voice Receptionist

Guidance for Claude Code when working in this repository. Read this file and `docs/BUILD_PLAN.md` before making changes.

**Current phase:** 4 — Voice in the browser *(see `docs/BUILD_PLAN.md` status board for the full list; bump this the moment a phase's status board row flips to ✅ Complete. Phases 2 and 3 were both moved on from by explicit user decision with their gates not formally met — see the status board notes on those phases for why. The user is tracking the overall eval pass rate at the end of every phase going forward to see whether later phases move it without extra work)*.

## What this project is

An AI receptionist that answers a small business's phone (first pilot: a dental clinic in Udaipur). It talks to callers in Hindi, English or Hinglish, checks free slots, books, cancels and reschedules appointments, answers FAQs from the clinic's own notes, and sends WhatsApp confirmations and reminders.

**Call flow:**
Caller → Twilio/Plivo (audio stream) → Pipecat pipeline → Silero VAD → Sarvam STT → LLM agent with tools → Sarvam TTS → caller

**What the tools do:**
- check slots and book / cancel / reschedule (SQLite + Google Calendar)
- answer FAQs (Chroma RAG)
- send WhatsApp messages (Cloud API)
- hand the call to a human

**Example:** a caller says "Kal shaam ko cleaning ka slot milega?"
1. The agent calls `check_slots(date=tomorrow, service="cleaning", part_of_day="evening")`.
2. It offers only the slots the tool returned, e.g. "Kal saade paanch aur chhe baje free hai."
3. It confirms the details, then calls `book_appointment(...)`, and a WhatsApp confirmation goes out in the background.

## Working style

- **Follow `docs/BUILD_PLAN.md`.** Check the **Current phase** line above and the plan's status board before starting work. Work on the current phase only, one task at a time. Don't jump ahead to later phases or add features that aren't in the plan without asking.
- After finishing a task: run the tests, tick the checkbox in `BUILD_PLAN.md`, and suggest a commit message like `phase 2.3: system prompt`.
- A phase is complete only when every task is ticked, all its tests pass and its "Phase complete when" gate is met. When that happens, update the status board in `BUILD_PLAN.md` **and** bump the **Current phase** line at the top of this file to the next phase.
- Make small, focused changes. Explain *why* in a short note when you make a design choice, and record bigger choices in `docs/architecture.md`.
- If something in the plan is unclear or seems wrong, ask instead of guessing.

## Commands

```bash
source .venv/bin/activate          # Python 3.11
pip install -e ".[dev]"            # install
pytest                             # offline test suite (must stay green, < 30 s)
pytest -m live                     # tests that call real paid APIs (run only when asked)
pytest --cov=app                   # coverage
ruff check . && ruff format .      # lint + format
python scripts/chat_cli.py         # chat with the agent by typing
python scripts/ingest_faqs.py      # rebuild the FAQ vector store
python scripts/run_evals.py        # golden Hinglish evals (live, costs a few paise)
python scripts/latency_report.py   # p50/p95 latency per stage
uvicorn app.server:app --reload    # API server (webhooks, websocket, /health)
streamlit run dashboard/streamlit_app.py
docker compose up --build
```

## Project layout

```
app/          core code: config, db, booking, timeparse, tools, agent, prompts,
              rag, whatsapp, calendar_sync, voice_bot, server, metrics
dashboard/    Streamlit owner dashboard
data/         clinic.yaml, faqs.md, test_calls.yaml (golden conversations)
tests/        unit/, integration/, evals/, fixtures/ (incl. audio/)
scripts/      CLI chat, ingest, evals, latency report, smoke test
docs/         BUILD_PLAN.md, architecture.md, telephony.md
reports/      eval and latency reports generated per phase
```

## Non-negotiable rules

1. **The LLM never invents facts.** Slots, prices, timings and addresses come only from tool results, `clinic.yaml` or `faqs.md`. If a tool didn't return it, the bot doesn't say it. The evals check for zero hallucinated slots.
2. **Booking logic is plain Python** in `app/booking.py`, not in prompts. `book()` must re-check availability inside a transaction, so a slot can never be double-booked.
3. **Always confirm before booking.** Read the service, date and time back to the caller and get a "haan"/"yes" before calling `book_appointment`.
4. **Side effects never break a booking.** WhatsApp and Google Calendar calls run in the background with retries. If they fail, log the failure and queue a retry; the appointment stays saved.
5. **Secrets come only from environment variables** via `app/config.py`. Never hardcode keys, never print them in logs, never commit `.env`. Keep `.env.example` up to date when adding a new setting.
6. **The default test suite is offline and free.** Mock every external API (Sarvam, Twilio, WhatsApp, Google) with fakes or `respx`. Any test that hits a real paid API gets `@pytest.mark.live`.
7. **Keep costs in mind.** Use the cheaper model or voice while developing (e.g. Bulbul v2), don't add paid services without asking, and don't run live tests or evals unless asked. The total project budget is ₹500–800.
8. **Timezone is `Asia/Kolkata`.** Use timezone-aware datetimes everywhere. Store phone numbers in E.164 format (`+91XXXXXXXXXX`).

## Code conventions

- Python 3.11, type hints on every function, `ruff` for lint and format.
- Pydantic / SQLModel for data models; validate tool inputs with Pydantic.
- Use `async` for anything in the voice pipeline and for network I/O.
- The LLM sits behind an `LLMClient` interface so tests can use `FakeLLM`. Don't call a provider SDK directly from `agent.py`.
- Tool functions return small, JSON-serialisable dicts. On failure they return `{"ok": false, "error": "<reason>"}` instead of raising into the LLM loop.
- Log with structured JSON (`app/metrics.py`). Every voice turn logs the timestamps for speech end, STT final, LLM first token and TTS first audio.
- Keep functions small and pure where possible. Put the hard logic (slots, time parsing, speech normalisation) in pure functions with unit tests.

## Testing expectations

- Every new function in `booking.py`, `timeparse.py`, `tools.py` or the speech normalisation code gets unit tests in the same change.
- Bug fix = first write a failing test that reproduces it, then fix.
- Use `pytest.mark.parametrize` for language cases and cover Hinglish, Hindi (romanised) and English. Example:
  ```python
  @pytest.mark.parametrize("text,expected", [
      ("kal shaam saade paanch", datetime(2026, 11, 10, 17, 30, tzinfo=IST)),
      ("tomorrow 5:30 pm",       datetime(2026, 11, 10, 17, 30, tzinfo=IST)),
  ])
  ```
- Use a fixed `now` and a fake clock in tests (no `datetime.now()` inside tested logic; pass `now` in).
- When a real call fails in testing or the pilot, add it as a case in `data/test_calls.yaml`.

## Voice and conversation style (for prompts)

- The bot is a polite clinic receptionist. It replies in the caller's language: Hinglish in, Hinglish out.
- At most 2 short sentences per reply, because callers lose patience on the phone.
- Write output to be *spoken*, not read: "saade paanch baje", not "17:30"; "paanch sau rupaye", not "₹500".
- Ask one question at a time.
- When unsure, say so and offer a callback or WhatsApp follow-up ("Main staff se confirm karke WhatsApp kar dungi").
- Never give medical advice. For pain or emergencies, give the clinic's emergency number from `clinic.yaml`.

## Latency targets

| Path | p50 | p95 |
|---|---|---|
| Browser (speech end → first audio) | ≤ 1.5 s | ≤ 2.5 s |
| Phone | ≤ 2 s | ≤ 3 s |

Prefer streaming (STT, LLM tokens, sentence-by-sentence TTS), short prompts and fillers for slow tools. Don't add a step to the voice path without measuring its latency.

## Don't

- Don't change `data/test_calls.yaml` expectations just to make a failing eval pass. Fix the agent instead, or ask.
- Don't add new dependencies without saying why. Prefer what's already in `pyproject.toml`.
- Don't put business rules in the system prompt that belong in code.
- Don't run `pytest -m live`, the evals, real phone calls or WhatsApp sends unless the user asks.
- Don't delete data files, reports or the SQLite DB.
