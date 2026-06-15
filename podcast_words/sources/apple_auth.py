"""macOS bearer-token helper for Apple Podcasts amp-api requests."""

from __future__ import annotations

import platform
import subprocess

from podcast_words.config import PROJECT_ROOT

FETCH_TRANSCRIPT_BIN = PROJECT_ROOT / "tools" / "apple" / "FetchTranscript"


class AppleUnsupportedError(RuntimeError):
    """Raised when Apple amp-api access cannot run on this machine."""


def _macos_version() -> tuple[int, int]:
    release = platform.mac_ver()[0]
    parts = release.split(".")
    major = int(parts[0]) if parts and parts[0] else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    return major, minor


def ensure_supported() -> None:
    """Raise AppleUnsupportedError unless this machine can call Apple amp-api."""
    if platform.system() != "Darwin":
        raise AppleUnsupportedError(
            "Apple amp-api access is only supported on macOS (15.5+)."
        )
    major, minor = _macos_version()
    if (major, minor) < (15, 5):
        raise AppleUnsupportedError(
            f"Apple amp-api access requires macOS 15.5+, found {major}.{minor}."
        )
    if not FETCH_TRANSCRIPT_BIN.exists():
        raise AppleUnsupportedError(
            f"FetchTranscript binary not found at {FETCH_TRANSCRIPT_BIN}. "
            "Build it from tools/apple/ (see tools/apple/README.md)."
        )


def get_bearer_token(*, use_cache: bool = True) -> str:
    """Return a Bearer token for amp-api.podcasts.apple.com."""
    ensure_supported()
    args = [str(FETCH_TRANSCRIPT_BIN), "--bearer-token-only"]
    if use_cache:
        args.append("--cache-bearer-token")
    result = subprocess.run(
        args,
        cwd=FETCH_TRANSCRIPT_BIN.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    token = (result.stdout or "").strip()
    if result.returncode != 0 or not token.startswith("ey"):
        stderr = (result.stderr or "").strip()
        raise AppleUnsupportedError(
            "Failed to obtain Apple Bearer token."
            + (f" {stderr}" if stderr else "")
        )
    return token
