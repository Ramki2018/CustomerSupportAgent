"""Phase 8: deployment-ready HTTP API for the FullAgent.

Run with (from project root, after `pip install -r requirements.txt`):
    uvicorn deployment.app:app --reload
"""
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from capstone_agent import config
from capstone_agent.feedback import FeedbackStore
from capstone_agent.graph.app import build_graph
from capstone_agent.langchain_runtime import get_chat_model, warm_up_langchain_runtime
from capstone_agent.logging_utils import get_logger
from capstone_agent.logging_utils import sanitize_user_message
from capstone_agent.rag.embeddings import get_embedding_provider
from capstone_agent.rag.vector_store import get_default_vector_store

logger = get_logger("deployment")
graph = None
embedding_provider = None
vector_store = None
model_client = None
feedback_store = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize expensive resources on startup and clean up on shutdown.

    Uses FastAPI's Lifespan context manager instead of deprecated on_event.
    """
    global graph, embedding_provider, vector_store, model_client, feedback_store
    try:
        # 1) load env already happens via config import
        # 2) create Qdrant connection
        embedding_provider = get_embedding_provider()
        vector_store = get_default_vector_store()
        try:
            vector_store.ensure_collection()
            logger.info("Qdrant connection initialized on startup")
        except Exception:
            logger.warning("Qdrant connection could not be initialized during startup:\n" + traceback.format_exc())

        # 3) load embeddings
        logger.info("Embedding provider initialized on startup: %s", embedding_provider.__class__.__name__)

        # 4) load graph
        graph = build_graph()
        logger.info("LangGraph support graph initialized on startup")

        # 5) warm up model if needed
        model_client = get_chat_model()
        warm_up_langchain_runtime()
        if model_client is not None:
            logger.info("LangChain model client initialized on startup")

        feedback_store = FeedbackStore()
    except Exception:
        logger.error("Failed to initialize graph during startup:\n" + traceback.format_exc())
    try:
        yield
    finally:
        try:
            if graph is not None and hasattr(graph, "close"):
                graph.close()
                logger.info("Graph closed on shutdown")
        except Exception:
            logger.error("Error while shutting down FullAgent:\n" + traceback.format_exc())


app = FastAPI(title="AI Support Resolution Agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: str
    message: str


class FeedbackRequest(BaseModel):
    session_id: str
    rating: int
    comment: str = ""


@app.middleware("http")
async def log_latency(request: Request, call_next):
    """Captures latency/error logs for every request (Phase 8 requirement)."""
    start = time.time()
    request_id = str(uuid.uuid4())
    try:
        response = await call_next(request)
    except Exception:
        logger.error(f"[{request_id}] Unhandled error on {request.url.path}:\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": "internal_error", "request_id": request_id})
    latency_ms = round((time.time() - start) * 1000, 2)
    logger.info(f"[{request_id}] {request.method} {request.url.path} -> {response.status_code} ({latency_ms}ms)")
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    """Run the compiled graph and return either an answer or escalation payload."""
    if graph is None:
        return JSONResponse(status_code=503, content={
            "error": "graph_not_ready",
            "message": "Graph is initializing. Please try again shortly.",
        })

    try:
        sanitized_message = sanitize_user_message(req.message)
        result = graph.invoke({
            "session_id": req.session_id,
            "user_message": sanitized_message,
            "metadata": {"request_id": str(uuid.uuid4())},
        })
        if result.get("escalate"):
            return {
                "session_id": req.session_id,
                "reply": result.get("answer", "This case should be handled by a human support agent."),
                "escalation_context": result.get("escalation_context", {}),
            }
        return {
            "session_id": req.session_id,
            "reply": result.get("answer", ""),
            "citations": result.get("citations", []),
            "follow_up_suggestions": result.get("follow_up_suggestions", []),
        }
    except Exception as exc:
        logger.error(f"Graph failure for session {req.session_id}: {exc}")
        return JSONResponse(
            status_code=200,
            content={
                "session_id": req.session_id,
                "reply": ("Something went wrong on our end. I've logged this issue — you can try again, "
                          "or ask to be connected with a human agent."),
            },
        )


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    if feedback_store is None:
        return JSONResponse(status_code=503, content={
            "error": "feedback_not_ready",
            "message": "Feedback store is initializing. Please try again shortly.",
        })
    feedback_store.add(req.session_id, req.rating, req.comment)
    return {"status": "recorded"}


@app.post("/validate")
def validate(timeout_seconds: int = 60):
    """Run a lightweight project validation: check key files and run tests.

    - Checks for presence of README.md, requirements.txt, `src` and `tests` folders.
    - Runs pytest in the project root using `sys.executable -m pytest` and returns
      the captured output and return code. A timeout can be supplied (seconds).
    """
    project_root = Path(__file__).resolve().parents[1]
    # Basic structural checks
    required = ["README.md", "requirements.txt", "src", "tests"]
    missing = [p for p in required if not (project_root / p).exists()]

    # Run pytest using the current Python interpreter to ensure environment parity
    cmd = [sys.executable, "-m", "pytest", "-q", "--maxfail=1"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        # Truncate large outputs for safe JSON responses
        max_len = 10000
        if len(stdout) > max_len:
            stdout = stdout[:max_len] + "\n...[truncated]"
        if len(stderr) > max_len:
            stderr = stderr[:max_len] + "\n...[truncated]"

        return {
            "project_root": str(project_root),
            "missing": missing,
            "pytest": {"returncode": proc.returncode, "stdout": stdout, "stderr": stderr},
        }
    except subprocess.TimeoutExpired as exc:
        logger.error(f"Validation pytest timeout after {timeout_seconds}s")
        return JSONResponse(status_code=504, content={
            "error": "pytest_timeout",
            "missing": missing,
            "stdout": (exc.stdout or "")[:10000],
            "stderr": (exc.stderr or "")[:10000],
        })
    except Exception as exc:  # pragma: no cover - unexpected runtime errors
        logger.error(f"Validation error: {exc}")
        return JSONResponse(status_code=500, content={"error": "validation_failed", "details": str(exc)})


if __name__ == "__main__":
    # Allows `python deployment/app.py` (or an IDE "Run" button) to start the
    # server directly, in addition to `uvicorn deployment.app:app --reload`.
    # Passed as an object (not an import string) since `deployment` isn't on
    # sys.path when this file is run directly, so --reload isn't available here.
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
