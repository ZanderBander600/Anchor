"""Architecture guardrails for the Phase 10A OM ingestion layer (KD1/KTD1).

Confirms ``azure`` is imported only inside ``di_provider.py``, ``openai``
only inside ``classifier_provider.py``, that neither SDK (nor
``anchor.ai``) reaches ``engine/``, ``analysis/``, or any other
``ingestion/`` module, that ``engine`` alone never pulls either SDK into
``sys.modules``, that ``ingestion/`` reproduces no financial formula (no
``math`` import), and -- the runtime check KD1 actually depends on -- that
the payload the classifier provider receives never contains the raw PDF
bytes an upload carried.

Mirrors the style of ``test_ai_architecture.py``.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from anchor.ingestion import di_provider as di_provider_module
from anchor.ingestion.contracts import DocumentAnchor, StructuredDocument
from anchor.ingestion.orchestrator import extract_om

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENGINE_DIR = _PROJECT_ROOT / "src" / "anchor" / "engine"
_ANALYSIS_DIR = _PROJECT_ROOT / "src" / "anchor" / "analysis"
_INGESTION_DIR = Path(di_provider_module.__file__).parent


def _imported_module_names(source_file: Path) -> list[str]:
    """Every *absolute* module name a file imports (``import anchor.engine``
    / ``from anchor.engine import X``). Deliberately does not attempt to
    resolve a relative import (``from .contracts import X``) to an absolute
    dotted path -- every module in this codebase reaches a sibling
    top-level package (``anchor.engine``, ``anchor.analysis``, ``anchor.ai``)
    via an absolute import, never a relative one, so resolving only
    absolute imports is sufficient for every guardrail below and avoids
    silently mislabeling a same-package relative import (e.g.
    ``anchor/ingestion/orchestrator.py``'s ``from .contracts import X``) as
    a cross-package one."""

    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:
                names.append(node.module)
    return names


# =============================================================================
# SDK confinement -- azure only in di_provider.py, openai only in
# classifier_provider.py, neither anywhere else in ingestion/, engine/, or
# analysis/.
# =============================================================================


def test_azure_is_imported_only_inside_the_di_provider_module() -> None:
    for source_file in _INGESTION_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        has_azure_import = any(name.startswith("azure") for name in names)
        if source_file.name == "di_provider.py":
            continue
        assert not has_azure_import, f"{source_file} must not import azure"


def test_openai_is_imported_only_inside_the_classifier_provider_module() -> None:
    for source_file in _INGESTION_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        has_openai_import = any(name.startswith("openai") for name in names)
        if source_file.name == "classifier_provider.py":
            continue
        assert not has_openai_import, f"{source_file} must not import openai directly"


def test_engine_package_has_no_azure_or_openai_import() -> None:
    for source_file in _ENGINE_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(name.startswith("azure") for name in names), (
            f"{source_file} must not import azure"
        )
        assert not any(name.startswith("openai") for name in names), (
            f"{source_file} must not import openai"
        )


def test_analysis_package_has_no_azure_or_openai_import() -> None:
    for source_file in _ANALYSIS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(name.startswith("azure") for name in names), (
            f"{source_file} must not import azure"
        )
        assert not any(name.startswith("openai") for name in names), (
            f"{source_file} must not import openai"
        )


def test_engine_package_does_not_import_ingestion_package() -> None:
    for source_file in _ENGINE_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any("anchor.ingestion" in name for name in names), (
            f"{source_file} must not import anchor.ingestion"
        )


def test_analysis_package_does_not_import_ingestion_package() -> None:
    for source_file in _ANALYSIS_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any("anchor.ingestion" in name for name in names), (
            f"{source_file} must not import anchor.ingestion"
        )


def test_ingestion_package_does_not_import_ai_package() -> None:
    """KTD10: neither provider raises anchor.ai's exception hierarchy --
    ingestion never imports anchor.ai at all."""

    for source_file in _INGESTION_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any("anchor.ai" in name for name in names), (
            f"{source_file} must not import anchor.ai"
        )


def test_ingestion_package_does_not_import_engine_or_analysis() -> None:
    """Detailed Operating Model V2.1 Gate 12: the reverse direction of
    ``test_engine_package_does_not_import_ingestion_package``/
    ``test_analysis_package_does_not_import_ingestion_package`` above --
    OM ingestion (Quick or Detailed) never imports the deterministic
    engine or analysis packages either. Ingestion proposes candidate
    values only; it must have no way to reach NOI, debt, returns,
    sensitivity, or break-even calculation code even transitively."""

    for source_file in _INGESTION_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(name.startswith("anchor.engine") for name in names), (
            f"{source_file} must not import anchor.engine"
        )
        assert not any(name.startswith("anchor.analysis") for name in names), (
            f"{source_file} must not import anchor.analysis"
        )


def test_ingestion_package_reproduces_no_financial_formula() -> None:
    for source_file in _INGESTION_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert "math" not in names, f"{source_file} must not import math"


def test_engine_import_does_not_pull_in_azure_or_openai() -> None:
    environment = os.environ.copy()
    python_path_parts = [str(_PROJECT_ROOT / "src")]
    if existing_python_path := environment.get("PYTHONPATH"):
        python_path_parts.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import anchor.engine; "
            "assert 'azure' not in sys.modules; assert 'openai' not in sys.modules",
        ],
        cwd=_PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


# =============================================================================
# KD1 runtime check -- the classifier provider's actual received payload
# never contains raw PDF bytes, not merely an import-graph guarantee.
# =============================================================================


class _FakeDiProvider:
    """Simulates Azure DI extraction: receives raw pdf_bytes, returns a
    StructuredDocument built from unrelated, human-readable anchor text --
    exactly as the real provider would (Azure DI's OCR output, never the
    input bytes themselves)."""

    def __init__(self) -> None:
        self.received_pdf_bytes: bytes | None = None

    def analyze(self, pdf_bytes: bytes) -> StructuredDocument:
        self.received_pdf_bytes = pdf_bytes
        return StructuredDocument(
            anchors=(
                DocumentAnchor(anchor="paragraph:0", page=1, text="Purchase Price: $1,000,000"),
            )
        )


class _SpyClassifierProvider:
    """Captures exactly what the orchestrator hands to the classifier."""

    def __init__(self) -> None:
        self.received_system_prompt: str | None = None
        self.received_user_prompt: str | None = None
        self.received_document: StructuredDocument | None = None

    def classify(self, *, system_prompt: str, user_prompt: str, document: StructuredDocument):
        self.received_system_prompt = system_prompt
        self.received_user_prompt = user_prompt
        self.received_document = document
        from anchor.ingestion.contracts import (
            DealContext,
            ExtractionResult,
            FieldCandidates,
        )

        def _missing(field_id: str) -> FieldCandidates:
            return FieldCandidates(field_id=field_id)

        acquisition_field_ids = (
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
        fields = {field_id: _missing(field_id) for field_id in acquisition_field_ids}
        deal_context = DealContext(
            property_name=_missing("property_name"),
            address=_missing("address"),
            property_type=_missing("property_type"),
            unit_count_or_building_area=_missing("unit_count_or_building_area"),
            year_built=_missing("year_built"),
        )
        return ExtractionResult(**fields, deal_context=deal_context)


def test_classifier_never_receives_the_raw_pdf_bytes() -> None:
    pdf_bytes = b"%PDF-1.4 a very specific unique marker payload that must never leak 999888777"
    di_provider = _FakeDiProvider()
    classifier_provider = _SpyClassifierProvider()

    extract_om(pdf_bytes, di_provider=di_provider, classifier_provider=classifier_provider)

    assert di_provider.received_pdf_bytes == pdf_bytes
    assert classifier_provider.received_document is not None
    assert classifier_provider.received_user_prompt is not None
    assert classifier_provider.received_system_prompt is not None

    assert pdf_bytes not in classifier_provider.received_user_prompt.encode(
        "utf-8", errors="ignore"
    )
    assert pdf_bytes not in classifier_provider.received_system_prompt.encode(
        "utf-8", errors="ignore"
    )
    for anchor in classifier_provider.received_document.anchors:
        assert pdf_bytes not in anchor.text.encode("utf-8", errors="ignore")
