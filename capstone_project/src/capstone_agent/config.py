"""Central configuration for the Capstone AI Support Resolution Agent."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
KNOWLEDGE_BASE_DIR = DATA_DIR / "knowledge_base"
LOGS_DIR = ROOT_DIR / "logs"
STATE_DIR = ROOT_DIR / "state"

LOGS_DIR.mkdir(exist_ok=True)
STATE_DIR.mkdir(exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
USE_MOCK_LLM = os.getenv("USE_MOCK_LLM", "true" if not OPENAI_API_KEY else "false").lower() == "true"

MAX_TOOL_CALLS_PER_TURN = 3
RETRIEVAL_TOP_K = 3
RETURN_WINDOW_DAYS = 30
SHORT_TERM_MEMORY_TURNS = 6
