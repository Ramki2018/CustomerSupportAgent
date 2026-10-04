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
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "customer_support_policies")
QDRANT_LOCAL_PATH = Path(os.getenv("QDRANT_LOCAL_PATH", str(ROOT_DIR / ".qdrant")))
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "sentence_transformers")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

MAX_TOOL_CALLS_PER_TURN = 3
RETRIEVAL_TOP_K = 3
RETURN_WINDOW_DAYS = 30
SHORT_TERM_MEMORY_TURNS = 6

# LangSmith tracing: opt-in. Traces contain only PII-sanitized text, but they are sent to
# LangSmith's cloud, so tracing stays off unless a key is set AND tracing is switched on.
# Both the current (LANGSMITH_*) and legacy (LANGCHAIN_*) variable names are accepted.
_langsmith_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY", "")
_tracing_flag = os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2", "false")
LANGSMITH_ENABLED = bool(_langsmith_key) and _tracing_flag.lower() == "true"
os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "true" if LANGSMITH_ENABLED else "false"
if _langsmith_key:
    os.environ.setdefault("LANGSMITH_API_KEY", _langsmith_key)
os.environ.setdefault("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", "customer-support-agent"))
