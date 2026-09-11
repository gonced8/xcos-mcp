# SPDX-License-Identifier: GPL-3.0-only
"""Keep blocking filesystem and Scilab work outside the MCP event loop."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import os
from typing import Callable, TypeVar


T = TypeVar("T")
_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int(os.environ.get("XCOS_MAX_WORKERS", "4"))),
    thread_name_prefix="xcos-mcp",
)


async def run_blocking(function: Callable[..., T], /, *args, **kwargs) -> T:
    """Run one blocking call without relying on asyncio's default executor."""
    call = partial(function, *args, **kwargs)
    return await asyncio.get_running_loop().run_in_executor(_EXECUTOR, call)
