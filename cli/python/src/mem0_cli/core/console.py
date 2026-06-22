"""Shared Rich console instances.

Renderers and the execution wrapper use these module-level consoles so the
whole CLI shares stdout/stderr streams.  Tests patch exactly these two names
(``stdout_console`` / ``err_console``) to capture output without touching
global state.
"""

from __future__ import annotations

from rich.console import Console

stdout_console = Console()
err_console = Console(stderr=True)
