"""LLM client wrapper.

Supports a real OpenAI backend and a deterministic offline `MockLLM` used by
default so the whole capstone runs end-to-end reproducibly without requiring
an API key (set USE_MOCK_LLM=false + OPENAI_API_KEY in .env to use a real model).
"""
import json
import re

from . import config
from .logging_utils import get_logger

logger = get_logger("llm_client")


class MockLLM:
    """Deterministic, rule-based stand-in for an LLM chat-completion API.

    Simulates: (1) tool-call decisions when an order ID is mentioned, and
    (2) grounded answers using whatever RAG context was injected into the
    system prompt. This keeps every phase of the capstone reproducible offline.
    """

    def chat(self, messages: list, tools: list | None = None) -> dict:
        last_message = messages[-1]
        if last_message["role"] == "tool":
            tool_name = last_message.get("name") or ""
            tool_data = self._parse_tool_result(last_message)
            last_user = self._last_user_message(messages)
            if (
                tool_name == "get_order_status"
                and tool_data.get("order_id")
                and re.search(r"return|refund eligib|can i return|eligible for a return", last_user, re.IGNORECASE)
            ):
                return self._tool_call("check_return_eligibility", {"order_id": tool_data["order_id"]})
            if tool_name == "check_return_eligibility":
                status_data = self._find_previous_tool_result(messages, "get_order_status")
                if status_data:
                    return {
                        "role": "assistant",
                        "content": self._compose_status_and_eligibility(status_data, tool_data),
                        "tool_calls": None,
                    }
            return self._compose_from_tool_result(last_message)

        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] == "user"]
        last_user = user_msgs[-1]["content"] if user_msgs else ""

        if tools:
            order_match = re.search(r"ORD-\d{3,}", last_user)
            if order_match:
                order_id = order_match.group(0)
                has_status_request = re.search(r"status|where is|track", last_user, re.IGNORECASE) is not None
                has_return_request = re.search(r"return|refund eligib|can i return|eligible for a return", last_user, re.IGNORECASE) is not None
                if has_status_request:
                    return self._tool_call("get_order_status", {"order_id": order_id})
                if has_return_request:
                    return self._tool_call("check_return_eligibility", {"order_id": order_id})
                return self._tool_call("get_order_status", {"order_id": order_id})

        style = "concise" if "concise" in system.lower() else "detailed"
        retrieved = self._extract_retrieved_context(messages)
        content = self._compose_answer(retrieved, style)
        return {"role": "assistant", "content": content, "tool_calls": None}

    @staticmethod
    def _last_user_message(messages: list) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return message.get("content") or ""
        return ""

    @staticmethod
    def _extract_retrieved_context(messages: list) -> str:
        markers = ("RETRIEVED CONTEXT:\n", "Retrieved context:\n", "POLICY CONTEXT:\n")
        for m in messages:
            content = m.get("content") or ""
            for marker in markers:
                if marker in content:
                    return content.split(marker, 1)[1]
        return ""

    @staticmethod
    def _tool_call(name: str, arguments: dict) -> dict:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "function": {"name": name, "arguments": json.dumps(arguments)}}],
        }

    @staticmethod
    def _parse_tool_result(tool_message: dict) -> dict:
        try:
            return json.loads(tool_message.get("content") or "{}")
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _find_previous_tool_result(messages: list, tool_name: str) -> dict:
        for message in reversed(messages[:-1]):
            if message.get("role") == "tool" and message.get("name") == tool_name:
                return MockLLM._parse_tool_result(message)
        return {}

    @staticmethod
    def _compose_status_and_eligibility(status_data: dict, eligibility_data: dict) -> str:
        status_line = (
            f"Order {status_data.get('order_id')} ({status_data.get('product')}) is currently "
            f"'{status_data.get('status')}'."
        )
        if eligibility_data.get("eligible"):
            return (
                f"{status_line} Good news — this order is within the "
                f"{eligibility_data.get('window_days')}-day return window "
                f"({eligibility_data.get('days_elapsed')} days since delivery), so it's eligible for return."
            )
        return (
            f"{status_line} This order is outside the "
            f"{eligibility_data.get('window_days')}-day return window "
            f"({eligibility_data.get('days_elapsed', 'N/A')} days since delivery), so it isn't eligible "
            f"for a standard return."
        )

    @staticmethod
    def _compose_answer(retrieved: str, style: str) -> str:
        if retrieved.strip():
            text_lines = [line.strip() for line in retrieved.splitlines() if line.strip()]
            policy_text = ""
            for line in text_lines:
                if line.startswith("TEXT:"):
                    policy_text = line.split("TEXT:", 1)[1].strip()
                    break
            if not policy_text:
                policy_text = text_lines[0][:280]
            base = f"Based on our policy documentation: {policy_text}"
        else:
            base = ("I don't have specific documentation on that topic, so I don't want to guess. "
                    "I can escalate this to a human support specialist if you'd like.")
        if style == "concise":
            return base
        return base + " Let me know if you'd like more detail or have another order to check."

    @staticmethod
    def _compose_from_tool_result(tool_message: dict) -> dict:
        data = MockLLM._parse_tool_result(tool_message)
        if "error" in data:
            content = f"I couldn't complete that automatically ({data['error']}). Escalating to a human agent."
        elif "ticket_id" in data or data.get("status") == "queued_for_human_review":
            content = (
                f"I couldn't complete that automatically. I've escalated this to a human agent "
                f"as ticket {data.get('ticket_id', 'unknown')}."
            )
        elif "eligible" in data:
            if data["eligible"]:
                content = (f"Good news — this order is within the {data['window_days']}-day return window "
                           f"({data['days_elapsed']} days since delivery), so it's eligible for return.")
            else:
                content = (f"This order is outside the {data['window_days']}-day return window "
                           f"({data.get('days_elapsed', 'N/A')} days since delivery), so it isn't eligible "
                           f"for a standard return.")
        elif "status" in data:
            content = f"Order {data.get('order_id')} ({data.get('product')}) is currently '{data['status']}'."
        else:
            content = "Here's what I found: " + json.dumps(data)
        return {"role": "assistant", "content": content, "tool_calls": None}


class OpenAILLM:
    """Thin wrapper around the OpenAI chat completions API (used when a real key is set)."""

    def __init__(self):
        try:
            from openai import OpenAI
        except Exception as exc:  # ImportError or packaging issues
            logger.exception("OpenAI package import failed")
            raise
        try:
            self._client = OpenAI(api_key=config.OPENAI_API_KEY)
        except Exception as exc:
            logger.exception("Failed to instantiate OpenAI client: %s", exc)
            raise

    def chat(self, messages: list, tools: list | None = None) -> dict:
        try:
            response = self._client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
            )
            choice = response.choices[0].message
            tool_calls = [
                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in (choice.tool_calls or [])
            ]
            return {"role": "assistant", "content": choice.content, "tool_calls": tool_calls or None}
        except Exception as exc:
            # Log the error and return an informative assistant message so the
            # rest of the system can continue (or fall back) without crashing.
            logger.exception("OpenAI API chat call failed: %s", exc)
            return {
                "role": "assistant",
                "content": (
                    "(OpenAI error) I couldn't call the OpenAI API right now. "
                    "Please check your OPENAI_API_KEY or network, or run with USE_MOCK_LLM=true."
                ),
                "tool_calls": None,
            }


def get_llm_client():
    if config.USE_MOCK_LLM or not config.OPENAI_API_KEY:
        logger.info("Using MockLLM (offline mode). Set OPENAI_API_KEY and USE_MOCK_LLM=false to use OpenAI.")
        return MockLLM()
    try:
        return OpenAILLM()
    except Exception:
        logger.warning("Falling back to MockLLM due to OpenAI client initialization failure.")
        return MockLLM()
