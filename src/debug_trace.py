# =============================================================================
# Debug session tracing (agent instrumentation)
# =============================================================================
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_SESSION_ID = "d99c7a"
_RUN_ID = "pre-fix"
_DEBUG_PATHS = (
    Path("/log/debug-d99c7a.ndjson"),
    Path(
        "/home/pyler/Projects/Infoteh/Infoteh-Main-Project/projects/NMEA-API-Service/.cursor/debug-d99c7a.log"
    ),
)


def debug_log(
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    hypothesis_id: str = "",
) -> None:
    payload = {
        "sessionId": _SESSION_ID,
        "runId": _RUN_ID,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    for path in _DEBUG_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
            return
        except OSError:
            continue
