"""Local-first cross-session memory layer. ADR-0022 (v0.2.3).

This package wraps `mem0ai` with our `Memory` adapter so consumers in
`apps/orchestrator` see a stable API regardless of upstream changes. See
`docs/v0.2.3_MEM0_PLAN.md` for the design + sign-off record.

IMPORTANT — telemetry kill-switch.

`mem0ai` brings `posthog` as a transitive and emits telemetry by default.
That's anti-pattern for a local-first / sovereignty-first project. We set
the disable env BEFORE any other module imports `mem0` so the SDK reads it
during its own module-level init. Do not move this `os.environ.setdefault`
call below the `from .adapter import …` line.
"""

from __future__ import annotations

import os

# Telemetry off: belt-and-suspenders. The env covers any submodule whose
# import path bypasses our explicit config; the per-instance config flag
# (set in `Memory.__init__`) covers any code path that reads from config
# instead of the env. See plan §R4.
os.environ.setdefault("MEM0_TELEMETRY", "False")

from .adapter import Memory  # noqa: E402 — env must be set first (see above)
from .config import MemoryConfig  # noqa: E402
from .types import Fact  # noqa: E402

__all__ = ["Fact", "Memory", "MemoryConfig"]
