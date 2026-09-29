"""Phase 9: evaluation harness — functional quality metrics, safety checks, and
a documented root-cause debugging case (return-eligibility date bug)."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone_agent import config
from capstone_agent.agents.full_agent import FullAgent
from capstone_agent.tools import tool_check_return_eligibility
from test_cases import TEST_CASES


def run_functional_tests(agent: FullAgent) -> list:
    results = []
    for tc in TEST_CASES:
        session_id = f"eval-{tc['id']}"
        start = time.time()
        reply = agent.handle_message(session_id, tc["message"])
        latency_ms = round((time.time() - start) * 1000, 2)

        refused = any(p in reply for p in [
            "can't", "provides information and guidance only", "can't provide legal advice",
            "sensitive issue",
        ])
        escalated = "escalat" in reply.lower()
        keyword_ok = (tc["expect_keyword"] is None) or (tc["expect_keyword"].lower() in reply.lower())
        pass_refusal = refused == tc["expect_refusal"]
        pass_escalation = (not tc["expect_escalation"]) or escalated
        passed = pass_refusal and pass_escalation and keyword_ok

        results.append({
            "id": tc["id"], "message": tc["message"], "reply": reply,
            "latency_ms": latency_ms, "passed": passed,
            "pass_refusal": pass_refusal, "pass_escalation": pass_escalation, "keyword_ok": keyword_ok,
        })
    return results


def root_cause_demo() -> dict:
    """Debugged failure case (required Phase 9 evidence).

    BUG: an earlier version measured the 30-day return window from `order_date`
    instead of `delivered_date`, understating eligibility for slow-shipping orders.
    FIX: measure from `delivered_date` (see tools.py:_return_eligibility_logic).
    Before/after proof below for ORD-1002 (order_date 40 days ago, delivered_date 15 days ago).
    """
    order_id = "ORD-1002"
    before = tool_check_return_eligibility(order_id, _use_delivered_date=False)
    after = tool_check_return_eligibility(order_id, _use_delivered_date=True)
    return {"order_id": order_id, "buggy_result_order_date": before, "fixed_result_delivered_date": after}


def main():
    agent = FullAgent()
    functional_results = run_functional_tests(agent)
    rc_demo = root_cause_demo()

    total = len(functional_results)
    passed = sum(r["passed"] for r in functional_results)
    avg_latency = round(sum(r["latency_ms"] for r in functional_results) / total, 2)

    report = {
        "summary": {"total_cases": total, "passed": passed, "pass_rate": round(passed / total, 2),
                    "avg_latency_ms": avg_latency},
        "cases": functional_results,
        "root_cause_case": rc_demo,
    }
    out_path = config.STATE_DIR / "evaluation_results.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Passed {passed}/{total} cases ({report['summary']['pass_rate'] * 100:.0f}%), "
          f"avg latency {avg_latency}ms")
    print("Per-case results:")
    for r in functional_results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['id']}: {r['reply'][:100]}")
    print(f"Root cause demo — {rc_demo['order_id']} buggy(order_date-based)={rc_demo['buggy_result_order_date']}")
    print(f"                              fixed(delivered_date-based)={rc_demo['fixed_result_delivered_date']}")
    print(f"Full report written to {out_path}")


if __name__ == "__main__":
    main()
