"""Detailed Operating Model V2.1 Gate 10 -- explicit workbook schema/version
metadata, shared by the Quick and Detailed Excel readers.

An optional ``Meta`` worksheet carries a ``Key``/``Value`` table with up to
two rows: ``anchor_schema`` and ``schema_version``. When present, this
metadata is authoritative -- it is how a Detailed workbook identifies itself
so it can never be misread as Quick (or vice versa) by field-name
coincidence. When the ``Meta`` sheet is absent entirely, the workbook is a
legacy, schema-less Quick workbook (the original nine-field or the existing
fourteen-field format) -- this remains fully supported, unchanged: Gate 10
introduces schema metadata only for new workbook formats, never requires it
retroactively of an existing one.

This module knows nothing about ``AcquisitionInputs``/``AcquisitionTerms``/
``DetailedOperatingInputs`` or any financial validation -- it is a pure,
generic workbook-metadata reader, imported by both ``excel_reader.py``
(Quick) and ``detailed_excel_reader.py`` (Detailed) without either depending
on the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_META_SHEET = "Meta"
_ANCHOR_SCHEMA_KEY = "anchor_schema"
_SCHEMA_VERSION_KEY = "schema_version"

#: Canonical ``anchor_schema`` values Gate 10 knows about. A workbook may
#: carry a different, unrecognized value -- that is a schema this Anchor
#: version does not support, not a Quick/Detailed mismatch (see
#: ``detailed_excel_reader.py``'s ``UNSUPPORTED_SCHEMA`` handling).
QUICK_SCHEMA = "quick_acquisition"
DETAILED_SCHEMA = "detailed_acquisition"

#: The only Detailed schema version this Anchor version parses. A workbook
#: declaring ``anchor_schema = detailed_acquisition`` with any other
#: ``schema_version`` is rejected rather than silently parsed against the
#: wrong field set.
SUPPORTED_DETAILED_SCHEMA_VERSION = "2.1"


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkbookSchema:
    """The workbook's declared identity, or ``(None, None)`` when it carries
    none (a legacy, schema-less workbook)."""

    anchor_schema: str | None
    schema_version: str | None


def read_workbook_schema(workbook: Any) -> WorkbookSchema:
    """Reads the optional ``Meta`` sheet's ``anchor_schema``/``schema_version``
    Key/Value pair. Deliberately lenient about the sheet's exact shape --
    unlike the ``Inputs`` table, this is routing metadata, not a financial
    input: a key is read wherever it appears as a literal string in column A,
    with its value in column B; the first occurrence of each key wins.
    Absent, blank, or non-text keys/values are simply not recorded.
    ``schema_version`` is always returned as its string form (``str(value)``)
    so a numeric ``2.1`` workbook cell and a literal text ``"2.1"`` cell
    compare identically to callers.
    """

    if _META_SHEET not in workbook.sheetnames:
        return WorkbookSchema(anchor_schema=None, schema_version=None)

    worksheet = workbook[_META_SHEET]
    found: dict[str, str] = {}
    for row in worksheet.iter_rows(min_col=1, max_col=2):
        key_cell = row[0]
        value_cell = row[1] if len(row) > 1 else None
        key = key_cell.value
        if not isinstance(key, str):
            continue
        key = key.strip()
        if key not in (_ANCHOR_SCHEMA_KEY, _SCHEMA_VERSION_KEY) or key in found:
            continue
        value = value_cell.value if value_cell is not None else None
        if _is_blank(value):
            continue
        found[key] = str(value).strip()

    return WorkbookSchema(
        anchor_schema=found.get(_ANCHOR_SCHEMA_KEY),
        schema_version=found.get(_SCHEMA_VERSION_KEY),
    )
