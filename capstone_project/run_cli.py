"""Interactive CLI entry point for the full Capstone AI Support Resolution Agent.

Usage:
    python run_cli.py            # chat with the agent
    python run_cli.py --debug    # also show route, grounding, ticket and the node path per turn
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from capstone_agent.agents.full_agent import FullAgent


def main():
    debug = "--debug" in sys.argv[1:]
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
        turn = agent.run_turn(session_id, message)
        print(f"Agent: {turn['reply']}")
        if debug:
            score = turn["retrieval_score"]
            print(
                f"  [route={turn['route'] or '-'} | grounding={turn['grounding'] or '-'} | "
                f"retrieval_score={'-' if score is None else f'{score:.2f}'} | "
                f"escalated={turn['escalated']} | ticket={turn['ticket_id'] or '-'}]\n"
                f"  [path: {' > '.join(turn['path'])}]"
            )


if __name__ == "__main__":
    main()
