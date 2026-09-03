"""Phase 10A OM ingestion contracts.

Like ``anchor.ai.contracts``, this module performs no extraction,
classification, or verification of its own -- it only describes the shapes
every other ingestion module produces or consumes: Azure DI's flattened,
anchor-addressable extraction payload (``StructuredDocument``), the
per-field candidate values GPT proposes from that payload
(``ExtractionCandidate``/``FieldCandidates``), and the assembled result for
one upload (``ExtractionResult``).

Neither provider (``di_provider``, ``classifier_provider``) defines its own
exception hierarchy -- both raise the one defined here
(``ExtractionError``/``ExtractionConfigurationError``/
``ExtractionProviderError``), so a failure from either provider maps to the
same FastAPI status codes (see ``anchor.api``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# The 9 existing AcquisitionInputs field ids (anchor.contracts), in the
# fixed order ExtractionResult exposes them. Duplicated here rather than
# imported from anchor.validation so the ingestion package stays
# self-contained, mirroring how anchor.ai avoids reaching into sibling
# packages for shared constants.
ACQUISITION_FIELD_IDS: tuple[str, ...] = (
    "purchase_price",
    "current_noi",
    "occupancy",
    "noi_growth",
    "hold_period",
    "exit_cap_rate",
    "ltv",
    "interest_rate",
    "amortization",
)

# The 5 fixed, read-only deal-context fields (R2/KD5). Never mapped into
# AcquisitionInputs or fed to the engine.
DEAL_CONTEXT_FIELD_IDS: tuple[str, ...] = (
    "property_name",
    "address",
    "property_type",
    "unit_count_or_building_area",
    "year_built",
)

# Detailed Operating Model V2.1 Gate 12: the eleven AcquisitionTerms Field
# IDs an OM may support (anchor.contracts.AcquisitionTerms /
# anchor.validation.TERMS_FIELD_IDS), and the eleven DetailedOperatingInputs
# Field IDs (anchor.validation.DETAILED_FIELD_IDS). Duplicated here rather
# than imported, for the same self-containment reason ACQUISITION_FIELD_IDS
# is duplicated above. Deliberately excludes current_noi/occupancy/
# noi_growth -- Detailed OM ingestion never proposes a value for a field
# the Detailed engine doesn't consume (see docs/detailed_operating_model_v2_1_architecture.md
# Section 4's current_noi/occupancy/noi_growth resolution).
DETAILED_TERMS_FIELD_IDS: tuple[str, ...] = (
    "purchase_price",
    "hold_period",
    "exit_cap_rate",
    "ltv",
    "interest_rate",
    "amortization",
    "acquisition_cost_pct",
    "financing_fee_pct",
    "disposition_cost_pct",
    "annual_capex_reserve",
    "io_period",
)

DETAILED_OPERATING_FIELD_IDS: tuple[str, ...] = (
    "gross_potential_rent",
    "other_income",
    "vacancy_credit_loss_pct",
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "other_operating_expenses",
    "management_fee_pct",
    "revenue_growth",
    "expense_growth",
)


class EvidenceStatus(StrEnum):
    """Exactly the five R5 evidence states -- no other member is valid."""

    STATED = "stated"
    INTERPRETED = "interpreted"
    CONFLICTING = "conflicting"
    UNVERIFIABLE = "unverifiable"
    MISSING = "missing"


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentAnchor:
    """One directly addressable piece of Azure DI's layout extraction: a
    paragraph or a single table cell, flattened to a stable anchor id, its
    page number, and its literal text.

    ``anchor`` is the id a classifier candidate's citation must resolve
    against (R6/KTD12) -- ``"paragraph:<i>"`` for the i-th paragraph Azure DI
    returned, or ``"table:<t>:cell:<row>:<col>"`` for one cell of the t-th
    table.
    """

    anchor: str
    page: int
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredDocument:
    """Azure DI's non-generative layout extraction (KD1/KTD3), flattened to
    a tuple of ``DocumentAnchor`` -- the only payload shape GPT ever
    receives (R3/R4). Carries no raw PDF bytes."""

    anchors: tuple[DocumentAnchor, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    """A candidate's cited evidence: the page it came from, the anchor id
    (see ``DocumentAnchor.anchor``) it cites, and the literal snippet text
    at that anchor (R6)."""

    page: int
    anchor: str
    snippet: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtractionCandidate:
    """One proposed value for one field, with its evidence status (R5) and
    verified provenance. A ``missing`` candidate is never constructed --
    ``missing`` is represented by ``FieldCandidates`` holding zero
    candidates (KD2) -- so ``provenance`` is ``None`` only for a candidate
    that failed provenance verification in a way that still carries a
    citation attempt worth showing (kept for U4 to decide; contracts.py
    imposes no such restriction itself)."""

    value: str
    status: EvidenceStatus
    provenance: Provenance | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FieldCandidates:
    """Zero, one, or many candidates for one field (R8). Zero candidates
    means the field is ``missing`` (R7); two or more means ``conflicting``
    (R8) unless the classifier has already resolved them to one status."""

    field_id: str
    candidates: tuple[ExtractionCandidate, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class DealContext:
    """The 5 fixed read-only deal-context fields (R2/KD5). Each is itself a
    ``FieldCandidates`` since context fields can also conflict (R8) -- never
    eligible to enter ``AcquisitionInputs``."""

    property_name: FieldCandidates
    address: FieldCandidates
    property_type: FieldCandidates
    unit_count_or_building_area: FieldCandidates
    year_built: FieldCandidates


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtractionResult:
    """One assembled extraction outcome for one uploaded OM: candidates for
    the 9 existing ``AcquisitionInputs`` fields, plus the 5 read-only deal-
    context fields. Carries no reference to the source PDF bytes (R13)."""

    purchase_price: FieldCandidates
    current_noi: FieldCandidates
    occupancy: FieldCandidates
    noi_growth: FieldCandidates
    hold_period: FieldCandidates
    exit_cap_rate: FieldCandidates
    ltv: FieldCandidates
    interest_rate: FieldCandidates
    amortization: FieldCandidates
    deal_context: DealContext


@dataclass(frozen=True, slots=True, kw_only=True)
class DetailedExtractionResult:
    """Detailed Operating Model V2.1 Gate 12: one assembled extraction
    outcome for one uploaded OM under Detailed Underwrite -- candidates for
    the eleven ``AcquisitionTerms`` fields plus the eleven
    ``DetailedOperatingInputs`` fields a document may support, twenty-two
    ``FieldCandidates`` total. A distinct contract from ``ExtractionResult``,
    not a merged/optional-everything superset of it -- mirrors the same
    non-overlapping-contract choice ``DetailedExcelIntakeReport`` already
    made relative to ``ExcelIntakeReport`` (Gate 10).

    Deliberately carries no ``current_noi``/``occupancy``/``noi_growth``
    field: Detailed Underwrite economics never consume them (see Section 4
    of ``docs/detailed_operating_model_v2_1_architecture.md``), so this
    contract offers no field an analyst could even attempt to approve one
    into. Deliberately carries no ``deal_context`` either -- out of this
    gate's stated target-field scope; a Detailed OM upload proposes
    underwriting assumptions only.

    Every field here is a ``FieldCandidates`` -- zero candidates means
    missing (never a fabricated zero), one or more means a genuine,
    provenance-verified proposal, exactly like ``ExtractionResult``. Never
    an ``OperatingProjection``, ``AcquisitionResults``, or any other
    calculated value -- OM ingestion parses proposed assumptions only.
    """

    purchase_price: FieldCandidates
    hold_period: FieldCandidates
    exit_cap_rate: FieldCandidates
    ltv: FieldCandidates
    interest_rate: FieldCandidates
    amortization: FieldCandidates
    acquisition_cost_pct: FieldCandidates
    financing_fee_pct: FieldCandidates
    disposition_cost_pct: FieldCandidates
    annual_capex_reserve: FieldCandidates
    io_period: FieldCandidates
    gross_potential_rent: FieldCandidates
    other_income: FieldCandidates
    vacancy_credit_loss_pct: FieldCandidates
    property_taxes: FieldCandidates
    insurance: FieldCandidates
    utilities: FieldCandidates
    repairs_maintenance: FieldCandidates
    other_operating_expenses: FieldCandidates
    management_fee_pct: FieldCandidates
    revenue_growth: FieldCandidates
    expense_growth: FieldCandidates


class ExtractionError(RuntimeError):
    """Base class for Phase 10A OM ingestion layer errors."""


class ExtractionConfigurationError(ExtractionError):
    """Raised when an ingestion provider is not configured -- missing Azure
    DI or OpenAI credentials."""


class ExtractionProviderError(ExtractionError):
    """Raised when a provider call itself fails, times out, or returns a
    response that cannot be converted to this module's contracts.

    The message is always a short, sanitized description -- never a raw
    provider stack trace, request/response body, or secret.
    """
