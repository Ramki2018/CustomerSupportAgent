"""Phase 8: deployment-ready HTTP API for the FullAgent.

Run with (from project root, after `pip install -r requirements.txt`):
    uvicorn deployment.app:app --reload
"""
import sys
import time
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import subprocess
import sys

from capstone_agent.agents.full_agent import FullAgent
from capstone_agent.logging_utils import get_logger

logger = get_logger("deployment")
app = FastAPI(title="AI Support Resolution Agent")
agent = FullAgent()


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
    """Graceful failure handling: agent errors never surface as raw 500s to the user."""
    try:
        reply = agent.handle_message(req.session_id, req.message)
        return {"session_id": req.session_id, "reply": reply}
    except Exception as exc:
        logger.error(f"Agent failure for session {req.session_id}: {exc}")
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
    agent.record_feedback(req.session_id, req.rating, req.comment)
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
