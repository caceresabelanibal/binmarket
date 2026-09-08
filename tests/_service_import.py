"""Helper for importing a module from trading-engine/app or market-data/app
in tests.

Both services use the top-level package name `app` (that's fine in
production — each container only ever has one `app` on its path), but it
collides when both get imported in the same pytest process: whichever
service's `app` package Python cached first "wins", and the second file's
`from app.whatever import ...` silently resolves against the wrong service.
This clears any stale `app`/`app.*` entries from `sys.modules` before
importing, so each caller reliably gets its own service's module.
"""
from __future__ import annotations

import importlib
import os
import sys


def import_service_module(service_dir: str, module_name: str):
    """`service_dir` is "trading-engine" or "market-data"; `module_name` is
    the dotted path under that service's `app` package, e.g. "tick" or
    "backfill". Returns the imported module.
    """
    root = os.path.join(os.path.dirname(__file__), "..", service_dir)
    if root not in sys.path:
        sys.path.insert(0, root)

    for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[key]

    return importlib.import_module(f"app.{module_name}")
