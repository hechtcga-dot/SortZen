"""Running background work gently: lower priority for the working thread on Windows."""
from __future__ import annotations

import os
from contextlib import contextmanager

THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
THREAD_MODE_BACKGROUND_END = 0x00020000


@contextmanager
def gentle(on: bool):
    """While on, Windows gives this thread's processor and disk use the lowest priority."""
    if not on or os.name != "nt":
        yield
        return
    import ctypes

    kernel = ctypes.windll.kernel32
    thread = kernel.GetCurrentThread()
    started = bool(kernel.SetThreadPriority(thread, THREAD_MODE_BACKGROUND_BEGIN))
    try:
        yield
    finally:
        if started:
            kernel.SetThreadPriority(thread, THREAD_MODE_BACKGROUND_END)
