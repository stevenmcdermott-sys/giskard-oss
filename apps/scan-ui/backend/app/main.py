"""FastAPI app: serves the SPA, streams scan progress over SSE.

Scans run one at a time per server process: attacker/judge LLM wiring
mutates giskard-checks' process-global default generator for the duration
of the run (see scan_runner.py), so a second concurrent scan would corrupt
the first's results. A single asyncio.Lock enforces this; a second request
while one is running gets an immediate 409 rather than silently queuing.
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from giskard.checks import SuiteResult

from .config import PROVIDER_LABELS, ScanRequest
from .scan_runner import run_scan
from .store import get as get_result
from .store import put as put_result

app = FastAPI(title="Giskard Scan UI")

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_scan_lock = asyncio.Lock()


def _sse_pack(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, default=str)}\n\n".encode("utf-8")


def _flatten_error(exc: BaseException) -> str:
    """Turn an ExceptionGroup / chained exception into one readable message.

    ``asyncio.TaskGroup`` wraps failures in ``ExceptionGroup``, and
    ``giskard.agents.WorkflowError`` wraps the real provider error (e.g. an
    auth failure) as ``__cause__`` behind a generic "Step processing failed"
    -- both would otherwise hide the actionable message from the user.
    """
    if isinstance(exc, ExceptionGroup):
        return "; ".join(_flatten_error(e) for e in exc.exceptions)

    parts = [str(exc) or type(exc).__name__]
    seen = {id(exc)}
    cause = exc.__cause__
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        parts.append(str(cause) or type(cause).__name__)
        cause = cause.__cause__
    return " -> ".join(parts)


@app.get("/api/providers")
async def providers() -> dict[str, str]:
    return dict(PROVIDER_LABELS)


@app.post("/api/scan")
async def scan(req: ScanRequest) -> StreamingResponse:
    if _scan_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="A scan is already running on this server. Please wait for it to finish.",
        )
    # No 'await' between the locked() check and acquire(): asyncio.Lock.acquire()
    # only suspends when contended, so this pair is effectively atomic here.
    await _scan_lock.acquire()

    async def event_stream():
        scan_id = uuid.uuid4().hex
        try:
            async for event in run_scan(req):
                if event["type"] == "done":
                    suite_result: SuiteResult = event["result"]
                    put_result(scan_id, suite_result)
                    yield _sse_pack(
                        {
                            "type": "done",
                            "scan_id": scan_id,
                            "passed_count": suite_result.passed_count,
                            "failed_count": suite_result.failed_count,
                            "errored_count": suite_result.errored_count,
                            "skipped_count": suite_result.skipped_count,
                            "pass_rate": suite_result.pass_rate,
                            "duration_ms": suite_result.duration_ms,
                        }
                    )
                else:
                    yield _sse_pack(event)
        except Exception as exc:
            # Surface the failure to the client as a normal SSE event instead
            # of a silently truncated stream.
            yield _sse_pack({"type": "error", "message": _flatten_error(exc)})
        finally:
            _scan_lock.release()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/scan/{scan_id}/report")
async def scan_report(scan_id: str) -> HTMLResponse:
    result = get_result(scan_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Scan result not found (server may have restarted)."
        )
    return HTMLResponse(
        result.to_html(title="Giskard Scan Report"),
        headers={
            "Content-Disposition": 'attachment; filename="giskard-scan-report.html"'
        },
    )


app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
