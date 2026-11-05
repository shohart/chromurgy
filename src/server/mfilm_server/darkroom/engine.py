# SPDX-License-Identifier: GPL-2.0-only
"""Process-wide handles on the film core. Loading a profile bundle hashes its 13 MB
with the core's reference SHA-256 (~6 s), so a long-lived web process loads it once."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .. import core


@lru_cache(maxsize=4)
def _load(path: str, mtime_ns: int, size: int) -> core.Bundle:
    return core.Bundle(Path(path))


def current_bundle() -> core.Bundle:
    p = core.bundle_path()
    try:
        st = p.stat()
    except OSError as e:
        raise core.CoreError("INVALID_PROFILE_BUNDLE", f"{p}: {e}") from None
    return _load(str(p), st.st_mtime_ns, st.st_size)
