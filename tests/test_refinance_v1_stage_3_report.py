"""Refinance & Capital Events V1 Stage 3 -- the refinance-aware report.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 12.5, 16.3 and
25.1. Stage 3 removed the temporary ``refinance_reporting_not_available`` gate;
a selected Capital Structure that configures a refinance now previews and
publishes as a refinance-aware report:

1. The headline return is Common Equity after Capital Structure, never the
   acquisition-loan levered figure (R-P rules 1-3).
2. Each refinance states the cash it returned to, or required from, Common
   Equity, under a heading that says which way it moved (F5/F6/F7).
3. The Refinance section shows the sizing operands, the binding constraint,
   the bridge and the recurring / event / total Common Equity decomposition.
4. Dependency disclosures are exact: a DSCR-only refinance discloses no
   valuation; an LTV refinance discloses the value it measured against.
5. An unexecuted refinance previews honestly as unavailable and is refused at
   publication with ``refinance_result_unavailable``.
6. Published artifacts are frozen; a report with no refinance is unchanged.

Every expected figure is Section 18 hand arithmetic.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

import _refinance_v1_stage_3_fixtures as s3  # type: ignore[import-not-found]
import _refinance_v1_stage_2_fixtures as fx  # type: ignore[import-not-found]
from _p7_6_fixtures import detailed_deal, lease_level_deal  # type: ignore[import-not-found]
from anchor.deals import store
from anchor.memo.publication import PublicationRefusedError
from anchor.reporting.pdf import render_memo_pdf

EXECUTED = "Executed"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "anchor.db"
    monkeypatch.setenv("ANCHOR_DB_PATH", str(path))
    return path


def _package(db: Path, structure_of: Any, *, name: str = "Harbor Point", timepoint: bool = False) -> Any:
    deal, investment_id = s3.refinance_deal(db, structure_of, name=name)
    if timepoint:
        s3.with_value_timepoint(db, investment_id, deal.id)
    return s3.preview(db, investment_id)


def _strings(package: Any) -> list[str]:
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif hasattr(value, "__dataclass_fields__"):
            for field in value.__dataclass_fields__:
                walk(getattr(value, field))

    walk(package)
    return found


# =============================================================================
# 1-2. The headline is refinance-adjusted and states the event cash
# =============================================================================


def test_f5_headline_is_common_equity_and_states_the_distribution(db: Path) -> None:
    package = _package(db, s3.f5_structure)
    labels = [metric.label for metric in package.key_metrics]

    assert "Levered IRR" not in labels and "Equity Multiple" not in labels
    assert s3.metric(package, "Common Equity IRR").note == "After Capital Structure"
    # 9,180,000 returned on 4,000,000 invested = 2.295x.
    assert s3.metric(package, "Common Equity Multiple").value == "2.30x"
    # N = 8,000,000 - 5,520,000 - 80,000 - 40,000.
    cash = s3.metric(package, "Cash Returned to Common Equity")
    assert (cash.value, cash.note) == ("$2,360,000", "End of Year 2")
    assert s3.metric(package, "DSCR (Year 1)").note == "Acquisition loan"


def test_f6_a_contribution_is_headed_as_one_and_shown_as_a_magnitude(db: Path) -> None:
    package = _package(db, s3.f6_structure)

    # N = 5,000,000 - 5,520,000 - 80,000 - 40,000 = -640,000.
    contribution = s3.metric(package, "Common Equity Contribution Required")
    assert contribution.value == "$640,000"
    assert "Cash Returned to Common Equity" not in [metric.label for metric in package.key_metrics]
    # -4.0m, +560k, -80k, +550k, +550k, +8.05m changes sign three times.
    irr = s3.metric(package, "Common Equity IRR")
    assert irr.value is None and irr.unavailable is not None
    assert irr.unavailable.reason_code == "multiple_sign_changes"
    assert "changes sign more than once" in irr.unavailable.reason
    assert irr.unavailable.label not in {"0", "$0", "-", ""}


def test_f7_an_exact_zero_event_is_a_real_zero(db: Path) -> None:
    package = _package(db, s3.f7_structure)

    # N = 5,640,000 - 5,520,000 - 80,000 - 40,000 = 0.
    assert s3.metric(package, "Cash Returned to Common Equity").value == "$0"
    bridge = s3.rows(s3.table(s3.section(package, "Refinance"), "Refinance Bridge"))
    assert bridge["Direction"][1] == "Zero"


def test_the_acquisition_levered_figures_appear_only_under_their_reference_label(db: Path) -> None:
    package = _package(db, s3.f5_structure)
    returns = {metric.label: metric for metric in s3.section(package, "Returns").metrics}

    assert list(returns)[0] == "Common Equity IRR (after Capital Structure)"
    assert returns["Levered IRR"].note == s3.REFERENCE
    assert returns["Equity Multiple"].note == s3.REFERENCE
    assert returns["Unlevered IRR"].note == "Property level"
    projection = s3.table(s3.section(package, "Operating Projection"), "Operating Projection")
    assert "Acquisition Debt Service" in projection.headers
    assert all("Acquisition" in header for header in projection.headers if "Levered" in header)


# =============================================================================
# 3. The Refinance section
# =============================================================================


def test_f5_the_bridge_reconciles_line_by_line(db: Path) -> None:
    section = s3.section(_package(db, s3.f5_structure), "Refinance")
    bridge = s3.rows(s3.table(section, "Refinance Bridge"))

    assert bridge["Gross proceeds – Replacement loan"][1] == "$8,000,000"
    assert bridge["Less payoff – Acquisition loan"][1] == "$5,520,000"
    assert bridge["Less replacement-lender fees"][1] == "$80,000"
    assert bridge["Less retiring-lender fees"][1] == "$0"
    assert bridge["Less third-party costs"][1] == "$40,000"
    assert bridge["Net refinance cash to Common Equity"][1] == "$2,360,000"
    assert bridge["Direction"][1] == "Distribution"


def test_f5_the_sizing_table_names_the_dscr_operands_and_binding_constraint(db: Path) -> None:
    section = s3.section(_package(db, s3.f5_structure), "Refinance")
    sizing = s3.table(section, "Sizing")

    # 800,000 / 2.00 = 400,000 of service; at 5% interest-only = 8,000,000.
    assert sizing.rows == (
        (
            "Minimum DSCR",
            "Year 3 forward NOI $800,000 at 2.00x, less continuing senior service $0; first-year service 5.0000% per dollar",
            "$8,000,000",
            "Binding",
        ),
    )
    facts = {metric.label: metric.value for metric in section.metrics}
    assert facts["Status"] == EXECUTED
    assert facts["Binding Constraint"] == "Minimum DSCR"
    assert facts["Achieved DSCR"] == "2.00x"
    assert facts["Achieved LTV"] == "Not applicable"
    assert facts["First Payment"] == "Model Month 25"
    assert facts["First-Year Debt Service"] == "$400,000"
    assert facts["Scope"] == "Harbor Point"


def test_f5_common_equity_decomposes_into_recurring_and_event_cash(db: Path) -> None:
    section = s3.section(_package(db, s3.f5_structure), "Refinance")
    flows = s3.rows(s3.table(section, "Common Equity Cash Flow"))

    assert flows["Year 0"][1:] == ("-$4,000,000", "$0", "-$4,000,000")
    # Years 1-2 carry the acquisition loan: 800,000 - 240,000.
    assert flows["Year 1"][1:] == ("$560,000", "$0", "$560,000")
    assert flows["Year 2"][1:] == ("$560,000", "$2,360,000", "$2,920,000")
    # Years 3-5 carry the replacement: 800,000 - 400,000; Year 5 adds
    # 12,500,000 of sale less the 8,000,000 replacement balance.
    assert flows["Year 3"][1:] == ("$400,000", "$0", "$400,000")
    assert flows["Year 5"][1:] == ("$4,900,000", "$0", "$4,900,000")


def test_f4_a_three_way_tie_is_disclosed_as_a_tie(db: Path) -> None:
    section = s3.section(_package(db, s3.f4_structure, timepoint=True), "Refinance")

    assert [row[3] for row in s3.table(section, "Sizing").rows] == ["Binding (tie)"] * 3
    binding = {metric.label: metric for metric in section.metrics}["Binding Constraint"]
    assert (binding.value, binding.note) == ("Fixed maximum proceeds, Maximum LTV, Minimum DSCR", "Tie")
    # 8,000,000 / 12,500,000.
    assert {metric.label: metric.value for metric in section.metrics}["Achieved LTV"] == "64.00%"


# =============================================================================
# 4. Dependency disclosures are exact
# =============================================================================


def _disclosure_titles(package: Any) -> list[str]:
    return [item.title for item in s3.section(package, "Refinance").disclosures]


def test_a_dscr_only_refinance_discloses_no_valuation(db: Path) -> None:
    titles = _disclosure_titles(_package(db, s3.f5_structure))

    assert "Forward NOI dependency – Year-2 refinance" in titles
    assert not any(title.startswith("Valuation dependency") for title in titles)


def test_an_ltv_refinance_discloses_the_value_it_measured_against(db: Path) -> None:
    package = _package(db, s3.f4_structure, timepoint=True)
    valuation = s3._one(
        [item for item in s3.section(package, "Refinance").disclosures if item.title.startswith("Valuation dependency")],
        "Valuation dependency",
    )

    assert "“Year-2 value”" in valuation.detail
    assert "$12,500,000" in valuation.detail
    assert "End of Year 2".lower() in valuation.detail.lower()


def test_the_base_scenario_carries_no_scenario_rate_limitation(db: Path) -> None:
    titles = _disclosure_titles(_package(db, s3.f5_structure))

    assert not any("Scenario" in title for title in titles)


# =============================================================================
# 5. An unexecuted refinance
# =============================================================================


def test_an_unexecuted_refinance_previews_as_unavailable_never_zero(db: Path) -> None:
    # An LTV refinance whose valuation does not exist.
    package = _package(db, s3.f4_structure)

    for label in ("Common Equity IRR", "Common Equity Multiple", "Cash Returned to Common Equity"):
        metric = s3.metric(package, label)
        assert metric.value is None and metric.unavailable is not None
        assert metric.unavailable.reason_code == "refinance_unavailable"
        # The note says why and where to look; it never repeats the label.
        assert metric.note == "Refinance did not execute – see Refinance."
    section = s3.section(package, "Refinance")
    assert {metric.label: metric.value for metric in section.metrics}["Status"] == "Unavailable"
    # No minimum was taken, so the known capacities were not compared -- they
    # are not "not binding" (browser QA finding).
    assert [row[3] for row in s3.table(section, "Sizing").rows] == ["Not compared", "Unavailable", "Not compared"]
    assert "Levered IRR" not in [metric.label for metric in package.key_metrics]
    # The replacement that did not execute is still a stated position.
    positions = s3.table(s3.section(package, "Capital Structure"), "Capital Positions")
    assert [row[0] for row in positions.rows] == ["Replacement loan"]
    assert "$0" not in positions.rows[0][2:]


def test_an_unexecuted_refinance_is_refused_at_publication(db: Path) -> None:
    _, investment_id = s3.refinance_deal(db, s3.f4_structure)
    s3.draft(db, investment_id)

    assert s3.refusal_codes(db, investment_id) == ["refinance_result_unavailable"]
    with pytest.raises(PublicationRefusedError):
        s3.publish(db, investment_id)
    assert tuple(store.list_memo_versions(investment_id, db_path=db)) == ()


# =============================================================================
# 6. Publication, freezing and compatibility
# =============================================================================


def test_an_executed_refinance_publishes_a_frozen_refinance_aware_artifact(db: Path) -> None:
    deal, investment_id = s3.refinance_deal(db, s3.f5_structure)
    version = s3.publish(db, investment_id)
    artifact = store.get_memo_version_artifact(investment_id, version.version_id, db_path=db)
    assert artifact is not None
    frozen = artifact.package()
    pdf = artifact.pdf_bytes

    assert s3.metric(frozen, "Cash Returned to Common Equity").value == "$2,360,000"
    assert "Refinance" in [section.title for section in frozen.sections]

    # Changing the refinance afterwards changes the draft preview, never the
    # published version.
    store.set_deal_capital_structure(deal.id, s3.f6_structure(deal.id), db_path=db)
    again = store.get_memo_version_artifact(investment_id, version.version_id, db_path=db)
    assert again is not None
    assert again.pdf_bytes == pdf
    assert s3.metric(again.package(), "Cash Returned to Common Equity").value == "$2,360,000"
    assert s3.metric(s3.preview(db, investment_id), "Common Equity Contribution Required").value == "$640,000"


def test_the_pdf_prints_the_refinance_section(db: Path) -> None:
    import pypdf

    pdf = render_memo_pdf(_package(db, s3.f5_structure))
    text = " ".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    flat = " ".join(text.split())

    for phrase in ("Refinance Bridge", "Cash Returned to Common Equity", "$2,360,000", "Acquisition financing"):
        assert phrase in flat, phrase


def test_no_internal_identity_reaches_the_report(db: Path) -> None:
    deal, investment_id = s3.refinance_deal(db, s3.f4_structure)
    s3.with_value_timepoint(db, investment_id, deal.id)
    strings = " ".join(_strings(s3.preview(db, investment_id)))

    for identity in (
        fx.EVENT_ID,
        fx.REPLACEMENT_ID,
        fx.TIMEPOINT_ID,
        deal.id,
        "legacy_acquisition_loan",
        "authored_position",
        "refinance_proceeds",
        "capital_event_id",
    ):
        assert identity not in strings, identity


def test_a_report_without_a_refinance_is_unchanged(db: Path) -> None:
    deal = fx.base_deal(db, name="Plain")
    investment_id, _ = store.set_deal_capital_structure(deal.id, fx.closing_mezz_only(deal.id), db_path=db)
    assert investment_id is not None
    package = s3.preview(db, investment_id)
    strings = " ".join(_strings(package))

    assert "Refinance" not in [section.title for section in package.sections]
    assert s3.REFERENCE not in strings
    assert "Common Equity Contribution Required" not in strings
    assert "Cash Returned to Common Equity" not in strings


@pytest.mark.parametrize("maker", [detailed_deal, lease_level_deal], ids=["detailed", "lease_level"])
def test_detailed_and_lease_level_reports_are_refinance_aware(maker: Any, db: Path) -> None:
    deal = maker(db, name="Mode")
    investment_id, _ = store.set_deal_capital_structure(deal.id, s3.f5_structure(deal.id), db_path=db)
    assert investment_id is not None
    package = s3.preview(db, investment_id)
    bridge = s3.rows(s3.table(s3.section(package, "Refinance"), "Refinance Bridge"))

    assert "Levered IRR" not in [metric.label for metric in package.key_metrics]
    assert s3.metric(package, "Common Equity IRR").note == "After Capital Structure"
    # The headline states the bridge's own net figure, unchanged.
    assert s3.metric(package, "Cash Returned to Common Equity").value == bridge["Net refinance cash to Common Equity"][1]
    assert s3.refusal_codes(db, investment_id) == []
