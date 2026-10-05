"""Runs the required 3-5 forced interactions demo script and saves the transcript
to state/demo_transcript.json for use as submission evidence."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent import config
from capstone_agent.agents.full_agent import FullAgent
from capstone_agent.feedback import FeedbackStore

FORCED_INTERACTIONS = [
    ("What is your return policy?", "RAG-grounded FAQ answer."),
    ("What is the status of order ORD-1002?", "Tool usage: get_order_status."),
    ("Can you check the status of that order and tell me if I can return it?",
     "Multi-step planning + memory (resolves 'that order' -> ORD-1002 and reuses earlier status/eligibility context)."),
    ("What about order ORD-9999?", "Failed/incorrect tool call handled gracefully (unknown order)."),
    ("Please process a refund for me right now.", "Safety refusal + forced escalation."),
]


def main():
    agent = FullAgent()
    # Demo-only feedback store, reset each run, so the demo is deterministic and never changes
    # the prompt variant used by the real feedback file (state/feedback.json).
    demo_feedback = config.STATE_DIR / "demo_feedback.json"
    demo_feedback.unlink(missing_ok=True)
    agent.feedback_store = FeedbackStore(path=demo_feedback)
    session_id = "demo-forced"
    transcript = []
    for message, note in FORCED_INTERACTIONS:
        reply = agent.handle_message(session_id, message)
        transcript.append({"user": message, "agent": reply, "note": note})
        print(f"USER: {message}\nNOTE: {note}\nAGENT: {reply}\n")
    agent.record_feedback(session_id, rating=4, comment="Good, but a bit too long sometimes")
    live = not config.USE_MOCK_LLM and bool(config.OPENAI_API_KEY)
    out_path = config.STATE_DIR / ("demo_transcript_openai.json" if live else "demo_transcript.json")
    out_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    print(f"Transcript saved to {out_path}")


if __name__ == "__main__":
    main()

