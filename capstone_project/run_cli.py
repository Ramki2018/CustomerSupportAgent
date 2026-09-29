"""Interactive CLI entry point for the full Capstone AI Support Resolution Agent.

Usage:
    python run_cli.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from capstone_agent.agents.full_agent import FullAgent


def main():
    agent = FullAgent()
    session_id = "cli-session"
    print("AI Support Resolution Agent (type 'exit' to quit, 'feedback <1-5> <comment>' to rate)")
    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            break
        if message.lower().startswith("feedback "):
            parts = message.split(" ", 2)
            rating = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 3
            comment = parts[2] if len(parts) > 2 else ""
            agent.record_feedback(session_id, rating, comment)
            print("Thanks for the feedback!")
            continue
        reply = agent.handle_message(session_id, message)
        print(f"Agent: {reply}")


if __name__ == "__main__":
    main()
