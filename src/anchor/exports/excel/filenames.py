"""Excel Export 1 and 2 -- the download filename, sanitized independently of
the workbook.

A Deal name is analyst-authored text. It becomes part of a filename a browser
writes to disk, so it is reduced to characters that are safe on every common
filesystem and cannot express a path, a device or a header break.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

QUICK_AUDIT_SUFFIX = " - Quick Underwrite Audit.xlsx"
DETAILED_AUDIT_SUFFIX = " - Detailed Underwrite Audit.xlsx"
FALLBACK_DEAL_NAME = "Untitled Deal"

#: Longest Deal-name portion kept; the whole name stays well inside the
#: 255-character limit common filesystems impose.
_MAX_NAME_LENGTH = 100

#: Path separators, Windows-reserved punctuation and quotes. Replaced, never
#: passed through.
_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def sanitize_deal_name(name: str) -> str:
    """The filesystem-safe Deal-name portion of the download filename."""

    normalized = unicodedata.normalize("NFKC", name)
    # Control and format characters (CR, LF, NUL, bidi overrides...) are removed
    # outright: they are never part of a legible name.
    visible = "".join(
        character
        for character in normalized
        if unicodedata.category(character)[0] != "C"
    )
    replaced = _UNSAFE.sub("-", visible)
    collapsed = " ".join(replaced.split())
    # Leading/trailing dots and spaces are what make ".." or a hidden or
    # trailing-dot name; strip them after every other rule has run.
    trimmed = collapsed.strip(" .")[:_MAX_NAME_LENGTH].rstrip(" .")
    return trimmed or FALLBACK_DEAL_NAME


def quick_audit_filename(deal_name: str) -> str:
    """``<Deal Name> - Quick Underwrite Audit.xlsx``, sanitized."""

    return sanitize_deal_name(deal_name) + QUICK_AUDIT_SUFFIX


def detailed_audit_filename(deal_name: str) -> str:
    """``<Deal Name> - Detailed Underwrite Audit.xlsx``, sanitized.

    The same sanitisation as the Quick name -- the Deal name is the only
    analyst-authored part, and it is reduced identically -- so the two exports
    cannot drift apart on what is safe to write to disk."""

    return sanitize_deal_name(deal_name) + DETAILED_AUDIT_SUFFIX


def content_disposition(filename: str) -> str:
    """An ``attachment`` Content-Disposition for ``filename``.

    ``filename`` carries an ASCII-only fallback (every other character becomes
    ``_``) and ``filename*`` the exact UTF-8 name, per RFC 6266 / RFC 5987, so
    a non-ASCII Deal name neither breaks the header nor is silently lost."""

    ascii_fallback = "".join(
        character if 32 <= ord(character) < 127 and character not in '"\\' else "_"
        for character in filename
    )
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
