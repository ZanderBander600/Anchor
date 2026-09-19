"""Excel Export 1 -- which Anchor build wrote a workbook.

Only identifiers are returned -- a version string and a commit hash -- never a
path, an environment value or anything else about the machine.
"""

from __future__ import annotations

import os
import re
from importlib import metadata
from pathlib import Path

#: Set by a packaged deployment that has no Git checkout.
SOURCE_COMMIT_VARIABLE = "ANCHOR_SOURCE_COMMIT"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def anchor_version() -> str:
    try:
        return metadata.version("anchor")
    except metadata.PackageNotFoundError:
        return "Not available"


def source_commit() -> str | None:
    """The commit Anchor is running from, when it can be determined.

    ``ANCHOR_SOURCE_COMMIT`` wins when it holds a full hash. Otherwise the
    local checkout's ``HEAD`` is read directly (no subprocess). Uncommitted
    changes cannot be seen this way, which the workbook states beside the
    value. Any other outcome is ``None`` ("Not available")."""

    configured = os.environ.get(SOURCE_COMMIT_VARIABLE, "").strip().lower()
    if _SHA.match(configured):
        return configured
    try:
        git_dir = _REPOSITORY_ROOT / ".git"
        if git_dir.is_file():
            pointer = git_dir.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git_dir = (_REPOSITORY_ROOT / pointer.removeprefix("gitdir:").strip()).resolve()
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if _SHA.match(head):
            return head
        if not head.startswith("ref: "):
            return None
        ref = head.removeprefix("ref: ").strip()
        common = git_dir
        common_pointer = git_dir / "commondir"
        if common_pointer.is_file():
            common = (git_dir / common_pointer.read_text(encoding="utf-8").strip()).resolve()
        for base in (git_dir, common):
            loose = base / ref
            if loose.is_file():
                value = loose.read_text(encoding="utf-8").strip()
                return value if _SHA.match(value) else None
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split(" ")
                if len(parts) == 2 and parts[1] == ref and _SHA.match(parts[0]):
                    return parts[0]
    except OSError:
        return None
    return None
