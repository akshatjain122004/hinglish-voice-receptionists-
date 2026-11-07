"""Chat with the receptionist agent by typing. Prints each tool call in grey.

Usage:
    python scripts/chat_cli.py
"""

from __future__ import annotations

import asyncio

from app.agent import Agent, SarvamLLMClient
from app.config import get_settings

GREY = "\033[90m"
RESET = "\033[0m"
SESSION_ID = "cli"


def _print_tool_call(name: str, arguments: dict, result: dict) -> None:
    print(f"{GREY}  [{name}({arguments}) -> {result}]{RESET}")


async def main() -> None:
    settings = get_settings()
    llm = SarvamLLMClient(api_key=settings.sarvam_api_key)
    agent = Agent(llm)

    print("Receptionist CLI. Type in Hindi, English or Hinglish. Ctrl+C to quit.\n")
    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue

        reply = await agent.handle_turn(SESSION_ID, user_text, on_tool_call=_print_tool_call)
        print(f"bot> {reply}")


if __name__ == "__main__":
    asyncio.run(main())
