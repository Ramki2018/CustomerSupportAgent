"""Runs the required 3-5 forced interactions demo script and saves the transcript
to state/demo_transcript.json for use as submission evidence."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent import config
from capstone_agent.agents.full_agent import FullAgent

FORCED_INTERACTIONS = [
    ("What is your return policy?", "RAG-grounded FAQ answer."),
    ("Is order ORD-1002 eligible for a return?", "Tool usage: check_return_eligibility."),
    ("Can you check the status of that order and tell me if I can return it?",
     "Multi-step planning + memory (resolves 'that order' -> ORD-1002)."),
    ("What about order ORD-9999?", "Failed/incorrect tool call handled gracefully (unknown order)."),
    ("Please process a refund for me right now.", "Safety refusal + forced escalation."),
]


def main():
    agent = FullAgent()
    session_id = "demo-forced"
    transcript = []
    for message, note in FORCED_INTERACTIONS:
        reply = agent.handle_message(session_id, message)
        transcript.append({"user": message, "agent": reply, "note": note})
        print(f"USER: {message}\nNOTE: {note}\nAGENT: {reply}\n")
    agent.record_feedback(session_id, rating=4, comment="Good, but a bit too long sometimes")
    out_path = config.STATE_DIR / "demo_transcript.json"
    out_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    print(f"Transcript saved to {out_path}")


if __name__ == "__main__":
    main()
