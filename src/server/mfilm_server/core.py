# SPDX-License-Identifier: GPL-2.0-only
"""ctypes binding to the shared C film core (libmf_core.so). The film look
lives only there; this module passes buffers, never pixels math."""
from __future__ import annotations

import ctypes
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
MF_OK, MF_E_INVALID_ARG, MF_E_UNSUPPORTED, MF_E_PROFILE_MISMATCH = 0, -1, -2, -3


class CoreError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def lib_path() -> Path:
    env = os.environ.get("MFILM_CORE_LIB")
    return Path(env) if env else REPO / "build" / "src" / "shared" / "film_core" / "libmf_core.so"


def bundle_path() -> Path:
    env = os.environ.get("MFILM_BUNDLE")
    return Path(env) if env else REPO / "profiles" / "mfilm-films.bin"


@lru_cache(maxsize=None)
def _lib() -> ctypes.CDLL:
    p = lib_path()
    if not p.is_file():
        raise CoreError("CORE_LIB_MISSING", f"{p} (build with: cmake -S . -B build && cmake --build build)")
    lib = ctypes.CDLL(str(p))
    u8p, f32p = ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_float)
    lib.mf_abi_version.restype = ctypes.c_int
    lib.mf_bundle_info.argtypes = [u8p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int), u8p]
    lib.mf_bundle_key.argtypes = [u8p, ctypes.c_size_t, ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t]
    lib.mf_develop_simple.argtypes = [u8p, ctypes.c_size_t, ctypes.c_char_p, f32p, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_uint64, ctypes.c_float, ctypes.c_float, ctypes.c_float,
                                      ctypes.c_float, ctypes.c_int, f32p, ctypes.c_char_p, ctypes.c_size_t]
    lib.mf_develop_simple.restype = ctypes.c_int
    return lib


def abi_version() -> int:
    return _lib().mf_abi_version()


class Bundle:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else bundle_path()
        self.data = self.path.read_bytes()
        self._buf = (ctypes.c_uint8 * len(self.data)).from_buffer_copy(self.data)
        n = ctypes.c_int()
        sha = (ctypes.c_uint8 * 32)()
        rc = _lib().mf_bundle_info(self._buf, len(self.data), ctypes.byref(n), sha)
        if rc != MF_OK:
            raise CoreError("INVALID_PROFILE_BUNDLE", str(self.path))
        self.sha256 = bytes(sha).hex()
        self.keys = []
        for i in range(n.value):
            buf = ctypes.create_string_buffer(32)
            _lib().mf_bundle_key(self._buf, len(self.data), i, buf, 32)
            self.keys.append(buf.value.decode())

    def develop(self, key: str, rgb: np.ndarray, *, seed: int, grain_scale=1.0, halation_scale=1.0,
                softness_scale=1.0, exposure_ev=0.0, reference_width=0) -> tuple[np.ndarray, float]:
        """rgb: HxWx3 float32 scene-linear sRGB (1.0 = white). Returns display sRGB 0..1 and scanner EV."""
        if key not in self.keys:
            raise CoreError("UNSUPPORTED_PROFILE", key)
        img = np.ascontiguousarray(rgb, dtype=np.float32).copy()
        h, w, _ = img.shape
        err = ctypes.create_string_buffer(256)
        ev = ctypes.c_float()
        rc = _lib().mf_develop_simple(self._buf, len(self.data), key.encode(),
                                      img.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), w, h,
                                      seed & 0xFFFFFFFFFFFFFFFF, grain_scale, halation_scale, softness_scale,
                                      exposure_ev, reference_width, ctypes.byref(ev), err, len(err))
        if rc != MF_OK:
            raise CoreError("UNSUPPORTED_PROFILE" if rc == MF_E_UNSUPPORTED else "DEVELOP_FAILED",
                            err.value.decode())
        return img, ev.value
