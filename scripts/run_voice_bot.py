"""Talk to the receptionist by voice, in the browser.

Usage:
    python scripts/run_voice_bot.py

Opens a local server with Pipecat's prebuilt WebRTC client at
http://localhost:7860 — allow mic access and start talking.

Turn-latency metrics (see app.metrics) are logged lazily from inside
app.voice_bot.run_bot on the first call, not here: pipecat.runner.run.main()
resets logging at startup, which would wipe a sink added before it runs.
"""

from __future__ import annotations

from app.voice_bot import bot  # noqa: F401  (found by pipecat.runner.run._get_bot_module)

if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
