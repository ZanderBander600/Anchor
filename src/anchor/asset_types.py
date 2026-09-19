"""Asset Types 1 -- the controlled Asset Type vocabulary and the analyst-authored
Asset Subtype.

``docs/architecture/ASSET_TYPES_1_CLASSIFICATION.md`` governs; this module
restates it. Like every ``contracts`` module in the repository it performs no
calculation and no I/O -- it only describes and validates one piece of
**non-economic metadata**.

Three concepts, deliberately kept apart:

- **Asset Type** is a controlled classification. Exactly the ten wire values of
  ``AssetType`` are accepted; nothing is case-folded, trimmed into a match or
  guessed from free text, so ``"Multifamily"`` is refused rather than silently
  read as ``multifamily``.
- **Asset Subtype** is analyst-authored descriptive text ("Garden apartments",
  "Medical office", "Last-mile warehouse"). It is trimmed at both ends,
  whitespace-only means absent, and otherwise the analyst's wording and
  capitalization are preserved exactly. It is never mapped onto a predefined
  value. It is required when the type is ``other``, where it is the description
  of what the asset actually is.
- **Business Plan / Strategy** are existing, unrelated concepts. Nothing here
  reads or writes either.

Classification never enters an engine input, a financial fingerprint, a
cached-analysis provenance check or the AI grounding. Changing it changes no
number anywhere in Anchor.

``AssetClassificationError`` is deliberately **not** a ``ValueError``: a caller
that catches every validation failure by base class must not silently swallow
a classification refusal (the D5.5C lesson).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class AssetType(StrEnum):
    """The controlled Asset Type vocabulary. The value is the one canonical
    representation used by the database, the API and the frontend alike;
    renaming a value is a contract change."""

    MULTIFAMILY = "multifamily"
    OFFICE = "office"
    INDUSTRIAL = "industrial"
    RETAIL = "retail"
    HOSPITALITY = "hospitality"
    SELF_STORAGE = "self_storage"
    MANUFACTURED_HOUSING = "manufactured_housing"
    MIXED_USE = "mixed_use"
    LAND_DEVELOPMENT = "land_development"
    OTHER = "other"


#: The product label of every controlled type, in vocabulary order. The
#: frontend's ``assetTypes.ts`` declares the same pairs and a guard holds the
#: two to each other, so a label cannot drift between the two sides.
ASSET_TYPE_LABELS: dict[AssetType, str] = {
    AssetType.MULTIFAMILY: "Multifamily",
    AssetType.OFFICE: "Office",
    AssetType.INDUSTRIAL: "Industrial",
    AssetType.RETAIL: "Retail",
    AssetType.HOSPITALITY: "Hospitality",
    AssetType.SELF_STORAGE: "Self-Storage",
    AssetType.MANUFACTURED_HOUSING: "Manufactured Housing",
    AssetType.MIXED_USE: "Mixed-Use",
    AssetType.LAND_DEVELOPMENT: "Land/Development",
    AssetType.OTHER: "Other",
}

#: The longest Asset Subtype accepted, in characters, measured after trimming.
#: Long enough for "Class A suburban medical office with ambulatory surgery"
#: and short enough to stay one readable line in a library row.
MAX_ASSET_SUBTYPE_LENGTH = 80

#: How a record with no controlled classification is presented. A display
#: string only -- it is never stored and is not an ``AssetType``.
NOT_SPECIFIED_LABEL = "Not specified"


class AssetClassificationIssueCode(StrEnum):
    """Stable wire tokens for a classification refusal."""

    INVALID_ASSET_TYPE = "invalid_asset_type"
    INVALID_ASSET_SUBTYPE = "invalid_asset_subtype"
    ASSET_SUBTYPE_TOO_LONG = "asset_subtype_too_long"
    ASSET_SUBTYPE_REQUIRED = "asset_subtype_required"
    ASSET_SUBTYPE_WITHOUT_TYPE = "asset_subtype_without_type"


@dataclass(frozen=True, slots=True, kw_only=True)
class AssetClassificationIssue:
    """One classification refusal. ``field`` is the wire field the analyst
    must fix: ``asset_type`` or ``asset_subtype``."""

    code: AssetClassificationIssueCode
    message: str
    field: str


class AssetClassificationError(Exception):
    """A classification that cannot be recorded. Carries every issue found, so
    one round trip reports both fields when both are wrong."""

    def __init__(self, issues: tuple[AssetClassificationIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


_ALLOWED_VALUES = ", ".join(member.value for member in AssetType)


def _issue(code: AssetClassificationIssueCode, message: str, field: str) -> AssetClassificationIssue:
    return AssetClassificationIssue(code=code, message=message, field=field)


def _subtype_issues(raw: object) -> tuple[str | None, list[AssetClassificationIssue]]:
    """The normalized subtype and any issue with it. Never raises."""

    if raw is None:
        return None, []
    if not isinstance(raw, str):
        return None, [
            _issue(
                AssetClassificationIssueCode.INVALID_ASSET_SUBTYPE,
                "The asset subtype must be text, or left out.",
                "asset_subtype",
            )
        ]
    trimmed = raw.strip()
    if trimmed == "":
        return None, []
    if any(unicodedata.category(character) == "Cc" for character in trimmed):
        return None, [
            _issue(
                AssetClassificationIssueCode.INVALID_ASSET_SUBTYPE,
                "The asset subtype must be a single line of text without control characters.",
                "asset_subtype",
            )
        ]
    if len(trimmed) > MAX_ASSET_SUBTYPE_LENGTH:
        return None, [
            _issue(
                AssetClassificationIssueCode.ASSET_SUBTYPE_TOO_LONG,
                f"The asset subtype is limited to {MAX_ASSET_SUBTYPE_LENGTH} characters.",
                "asset_subtype",
            )
        ]
    return trimmed, []


@dataclass(frozen=True, slots=True, kw_only=True)
class AssetClassification:
    """One recorded classification: a controlled type and an optional,
    analyst-authored subtype.

    Always in normalized form: ``asset_subtype`` is either ``None`` or already
    trimmed, non-empty, single-line text of at most
    ``MAX_ASSET_SUBTYPE_LENGTH`` characters. A type of ``other`` always carries
    a subtype. Construction refuses anything else, so a stored or transported
    classification can never be in a state the analyst could not have
    authored."""

    asset_type: AssetType
    asset_subtype: str | None = None

    def __post_init__(self) -> None:
        issues: list[AssetClassificationIssue] = []
        if not isinstance(self.asset_type, AssetType):
            issues.append(
                _issue(
                    AssetClassificationIssueCode.INVALID_ASSET_TYPE,
                    f"The asset type must be one of: {_ALLOWED_VALUES}.",
                    "asset_type",
                )
            )
        normalized, subtype_issues = _subtype_issues(self.asset_subtype)
        issues.extend(subtype_issues)
        if not subtype_issues and normalized != self.asset_subtype:
            issues.append(
                _issue(
                    AssetClassificationIssueCode.INVALID_ASSET_SUBTYPE,
                    "The asset subtype must already be trimmed, and blank means absent.",
                    "asset_subtype",
                )
            )
        if self.asset_type is AssetType.OTHER and self.asset_subtype is None and not subtype_issues:
            issues.append(_other_requires_subtype())
        if issues:
            raise AssetClassificationError(tuple(issues))

    @property
    def label(self) -> str:
        return ASSET_TYPE_LABELS[self.asset_type]


def _other_requires_subtype() -> AssetClassificationIssue:
    return _issue(
        AssetClassificationIssueCode.ASSET_SUBTYPE_REQUIRED,
        "Describe the asset type: a subtype is required when the asset type is Other.",
        "asset_subtype",
    )


def parse_asset_classification(
    asset_type: object, asset_subtype: object
) -> AssetClassification | None:
    """The classification two wire values state, or ``None`` for "Not
    specified".

    - ``asset_type`` must be ``None`` or exactly one of the ``AssetType``
      values. No case-folding, trimming or near-match: a value that is not in
      the vocabulary is refused, never guessed.
    - ``asset_subtype`` is trimmed; ``None``, ``""`` and whitespace-only all
      mean absent. Anything longer than ``MAX_ASSET_SUBTYPE_LENGTH`` characters
      after trimming, or containing a control character, is refused.
    - ``other`` requires a subtype.
    - A subtype with no type is refused: a description of an unclassified
      asset would be a classification nobody chose.

    Raises ``AssetClassificationError`` carrying every issue found.
    """

    issues: list[AssetClassificationIssue] = []
    subtype, subtype_issues = _subtype_issues(asset_subtype)
    issues.extend(subtype_issues)

    resolved_type: AssetType | None = None
    if asset_type is not None:
        if isinstance(asset_type, str) and asset_type in AssetType._value2member_map_:
            resolved_type = AssetType(asset_type)
        else:
            issues.append(
                _issue(
                    AssetClassificationIssueCode.INVALID_ASSET_TYPE,
                    f"The asset type must be one of: {_ALLOWED_VALUES}; got {asset_type!r}.",
                    "asset_type",
                )
            )

    if asset_type is None and subtype is not None:
        issues.append(
            _issue(
                AssetClassificationIssueCode.ASSET_SUBTYPE_WITHOUT_TYPE,
                "Choose an asset type before describing a subtype.",
                "asset_subtype",
            )
        )
    if resolved_type is AssetType.OTHER and subtype is None and not subtype_issues:
        issues.append(_other_requires_subtype())

    if issues:
        raise AssetClassificationError(tuple(issues))
    if resolved_type is None:
        return None
    return AssetClassification(asset_type=resolved_type, asset_subtype=subtype)


def asset_type_label(asset_type: AssetType | None) -> str:
    """The product label for a type, or ``NOT_SPECIFIED_LABEL`` for none."""

    return NOT_SPECIFIED_LABEL if asset_type is None else ASSET_TYPE_LABELS[asset_type]
