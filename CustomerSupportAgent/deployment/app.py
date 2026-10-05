"""Phase 8: deployment-ready HTTP API for the FullAgent.

`/chat` runs the same `FullAgent` that the demo and evaluation exercise, so the
deployed behaviour (safety, retrieval, tools, memory, adaptation) matches the
submitted evidence.

Run with (from project root, after `pip install -r requirements.txt`):
    uvicorn deployment.app:app --reload
"""
import hmac
import os
import sys
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from support_agent.agents.full_agent import FullAgent
from support_agent.logging_utils import get_logger
from support_agent.rag.vector_store import get_default_vector_store

logger = get_logger("deployment")
agent = None
_auth_warned = False
# FullAgent keeps per-session memory and JSON-file state in-process, so calls are serialized.
agent_lock = threading.Lock()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Protect /chat and /feedback with a shared secret sent in the `X-API-Key` header.

    The key comes from the `API_KEY` environment variable. When it is unset, auth is disabled for local
    development (with a warning), except when `APP_ENV=production`, where the endpoints refuse all requests
    rather than run open.
    """
    global _auth_warned
    expected = os.getenv("API_KEY", "")
    if not expected:
        if os.getenv("APP_ENV", "").lower() == "production":
            logger.error("API_KEY is not set in production; refusing request")
            raise HTTPException(status_code=503, detail="auth_not_configured")
        if not _auth_warned:
            logger.warning("API_KEY is not set; /chat and /feedback are unauthenticated (development mode)")
            _auth_warned = True
        return
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode("utf-8"), expected.encode("utf-8")):
        logger.warning("Rejected request with a missing or invalid API key")
        raise HTTPException(status_code=401, detail="invalid_api_key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the agent on startup."""
    global agent
    try:
        try:
            get_default_vector_store().ensure_collection()
            logger.info("Qdrant connection initialized on startup")
        except Exception:
            logger.warning("Qdrant unavailable at startup; retrieval will use its fallback:\n" + traceback.format_exc())

        agent = FullAgent()
        logger.info("FullAgent initialized on startup")
    except Exception:
        logger.error("Failed to initialize agent during startup:\n" + traceback.format_exc())
    yield


app = FastAPI(title="AI Support Resolution Agent", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)


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
    return {"status": "ok" if agent is not None else "starting"}


@app.post("/chat", dependencies=[Depends(require_api_key)])
def chat(req: ChatRequest):
    """Run one turn through the support graph and return the reply plus how it was produced."""
    if agent is None:
        return JSONResponse(status_code=503, content={
            "error": "agent_not_ready",
            "message": "Agent is initializing. Please try again shortly.",
        })

    try:
        with agent_lock:
            result = agent.run_turn(req.session_id, req.message)
        return {
            "session_id": req.session_id,
            "reply": result["reply"],
            "escalated": result["escalated"],
            "ticket_id": result["ticket_id"],
            "sources": result["sources"],
            "grounding": result["grounding"],
            "retrieval_score": result["retrieval_score"],
            "route": result["route"],
            "path": result["path"],
        }
    except Exception as exc:
        request_id = str(uuid.uuid4())
        logger.error(f"[{request_id}] Agent failure for session {req.session_id}: {exc}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={
            "error": "agent_failure",
            "request_id": request_id,
            "message": "Something went wrong on our end. Please try again, or ask to be connected with a human agent.",
        })


@app.post("/feedback", dependencies=[Depends(require_api_key)])
def feedback(req: FeedbackRequest):
    if agent is None:
        return JSONResponse(status_code=503, content={
            "error": "agent_not_ready",
            "message": "Agent is initializing. Please try again shortly.",
        })
    with agent_lock:
        agent.record_feedback(req.session_id, req.rating, req.comment)
    return {"status": "recorded"}


if __name__ == "__main__":
    # Allows `python deployment/app.py` (or an IDE "Run" button) to start the
    # server directly, in addition to `uvicorn deployment.app:app --reload`.
    # Passed as an object (not an import string) since `deployment` isn't on
    # sys.path when this file is run directly, so --reload isn't available here.
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
