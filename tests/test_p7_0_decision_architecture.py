"""Phase 7 Gate P7.0 -- architecture-only guards.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` governs once
ratified. P7.0 implements no calculation; these guards hold the two things it
does establish:

- **The anti-overfitting rule (Section 0).** Competition cases are acceptance
  archetypes, never production architecture, so no production source may name
  a case, a competition or a specific transaction.
- **The architecture document stays citable.** Later gates implement against
  its numbered sections, and every repository path it names must exist.
"""

from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ARCHITECTURE_DOC = _PROJECT_ROOT / "docs" / "architecture" / "P7_COMPETITION_DECISION_ARCHITECTURE.md"

#: Identifiers that would mean a case had leaked into production. Deliberately
#: specific: generic finance vocabulary ("vault", "competitive") stays legal. The
#: address token is bounded by anything but a hex digit or dash, so it matches
#: inside an identifier (``run_161C_waterfall``) and never inside a UUID or hash.
_CASE_IDENTIFIER = re.compile(
    r"cornell|soteria|cole[\s_-]*torres|vault[\s_-]*mode|(?<![0-9a-f-])161c(?![0-9a-f-])"
    r"|case[\s_-]*competition",
    re.IGNORECASE,
)

_PRODUCTION_ROOTS = (_PROJECT_ROOT / "src" / "anchor", _PROJECT_ROOT / "web" / "src")
_SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".json", ".html"}


def _production_sources() -> list[Path]:
    return sorted(
        path
        for root in _PRODUCTION_ROOTS
        for path in root.rglob("*")
        if path.is_file() and path.suffix in _SOURCE_SUFFIXES and ".test." not in path.name
    )


def _case_identifiers_in(text: str) -> list[str]:
    return [match.group(0) for match in _CASE_IDENTIFIER.finditer(text)]


def test_no_production_source_names_a_competition_case() -> None:
    sources = _production_sources()
    assert len(sources) > 50, "the production scan found almost nothing; its roots are wrong"
    leaks = {
        path.relative_to(_PROJECT_ROOT).as_posix(): hits
        for path in sources
        if (hits := _case_identifiers_in(path.read_text(encoding="utf-8", errors="replace")))
    }
    assert leaks == {}


def test_the_case_detector_catches_real_leaks_and_spares_finance_vocabulary() -> None:
    for leak in (
        "class VaultMode:",
        "CORNELL_SCENARIO",
        "SoteriaPosition",
        "cole_torres_portfolio",
        "run_161C_waterfall",
        "Waterfall161C",
        "the 161c deal",
    ):
        assert _case_identifiers_in(leak), leak
    for legal in (
        "key vault secret",
        "competitive leasing market",
        "0x161c9a",
        "e161c0ffee",
        "3f2a-161c-4b7d",
        "base case",
    ):
        assert not _case_identifiers_in(legal), legal


#: Every numbered section later gates cite, in order (Part AL plus the options,
#: decision record and gate record).
_REQUIRED_SECTIONS = (
    "0. Authority, Scope and Numbering",
    "1. Purpose",
    "2. Product Objective",
    "3. Permanent Principles",
    "4. Current Architecture Map",
    "5. Recommended Domain Hierarchy",
    "6. Definitions",
    "7. Strategy vs Scenario Convention",
    "8. Unit / Portfolio / Mixed-Use Convention",
    "9. Consolidation Rules",
    "10. Business Plan Scope",
    "11. Purchase Price, Basis and Valuation Timepoints",
    "12. Capital Structure Boundary",
    "13. Partnership Boundary",
    "14. Project vs. Investor Returns",
    "15. Fingerprints, Persistence and Migration",
    "16. AI Boundary",
    "17. Competition Acceptance Archetypes",
    "18. Competition-Ready Definition",
    "19. Recommended Gate Sequence",
    "20. Deferred Scope",
    "21. Open Questions Requiring Human Ratification",
    "22. Architecture Options Considered",
    "23. Decision Record",
    "24. P7.0 Gate Record",
)


def test_the_architecture_document_keeps_its_numbered_sections_in_order() -> None:
    headings = re.findall(r"^## (.+)$", _ARCHITECTURE_DOC.read_text(encoding="utf-8"), re.MULTILINE)
    found = [
        next((heading for heading in headings if heading.startswith(section)), None)
        for section in _REQUIRED_SECTIONS
    ]
    assert None not in found, [s for s, h in zip(_REQUIRED_SECTIONS, found) if h is None]
    assert [headings.index(heading) for heading in found] == sorted(headings.index(h) for h in found)


def test_every_repository_path_the_architecture_document_names_exists() -> None:
    text = _ARCHITECTURE_DOC.read_text(encoding="utf-8")
    paths = {
        path
        for path in re.findall(r"`((?:src|web|docs|tests)/[^`\s]*)`", text)
        if "*" not in path
    }
    assert len(paths) >= 5
    missing = sorted(path for path in paths if not (_PROJECT_ROOT / path).exists())
    assert missing == []
