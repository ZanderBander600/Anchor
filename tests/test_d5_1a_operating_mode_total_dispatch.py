"""D5.1A -- ``OperatingMode`` dispatch is TOTAL across every backend consumer.

This file is the successor to Sprint D's HD-D4-9 deferral guardrails. Those
tests protected the codebase by keeping ``OperatingMode.LEASE_LEVEL`` *absent*,
because dispatch was exhaustive-by-omission: every consumer tested one member
and let the other fall through an implicit ``else``, and the ``else`` differed
by module -- Quick in ``api.py``, Detailed in ``ai/contracts.py``,
``ai/presentation.py``, ``deals/contracts.py`` and ``deals/store.py``. A third
member would not have created a third branch; it would have silently joined
whichever branch the ``else`` happened to be, answering a Lease-Level request
with Quick numbers under a Lease-Level label.

D5.1A removes the hazard rather than continuing to avoid it, so the guardrail
inverts: the invariant is no longer "the member is absent" but **"every valid
member has an explicit behavior, everywhere"**.

**Why this is enforced structurally rather than by type-checking.** Python's
``match`` is not exhaustive at compile time and ``StrEnum`` gets no
``assert_never`` treatment from the runtime, so nothing except a test can prove
that adding a member did not leave a site silently under-handled. That is
precisely the failure mode HD-D4-9 was written about, so it gets a test rather
than a convention.

**The ordering this file also protects.** Total dispatch had to exist *before*
the third member was published -- the reverse order means publishing a member
into eight silent fallthroughs and then repairing them, with a window in which
``/analyze`` answers Lease-Level with Quick economics. ``test_ordering_*``
below pins the property that makes the order verifiable after the fact.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from anchor.contracts import OperatingMode

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
_ANCHOR_DIR = _SRC_DIR / "anchor"

#: The backend modules that dispatch on ``OperatingMode``. Named explicitly
#: rather than discovered, so that a *new* mode-aware module is a deliberate
#: addition to this list and its review, not a silent omission from the audit.
_AUDITED = (
    _ANCHOR_DIR / "api.py",
    _ANCHOR_DIR / "deals" / "contracts.py",
    _ANCHOR_DIR / "deals" / "store.py",
    _ANCHOR_DIR / "ai" / "contracts.py",
    _ANCHOR_DIR / "ai" / "presentation.py",
)

_MEMBER_NAMES = {member.name for member in OperatingMode}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _member_names_in(node: ast.AST) -> set[str]:
    """The ``OperatingMode`` member names an expression names literally.

    Matches ``OperatingMode.QUICK`` (an ``Attribute`` on a ``Name``) rather than
    any bare identifier, so a local variable that merely happens to be called
    ``quick`` is never mistaken for a dispatch.
    """

    found: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "OperatingMode"
            and child.attr in _MEMBER_NAMES
        ):
            found.add(child.attr)
    return found


def _if_chain_dispatch_sites(tree: ast.Module) -> list[tuple[ast.If, set[str]]]:
    """Every ``if``/``elif`` chain that dispatches on ``OperatingMode``.

    Only the *head* of a chain is returned, paired with the members named across
    the whole chain -- an ``elif`` is an ``If`` nested in the parent's ``orelse``
    and must not be counted as a second, separately-incomplete site.
    """

    heads: list[tuple[ast.If, set[str]]] = []
    nested: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            for stmt in node.orelse:
                if isinstance(stmt, ast.If):
                    nested.add(id(stmt))

    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or id(node) in nested:
            continue
        members: set[str] = set()
        tail: ast.If = node
        while True:
            members |= _member_names_in(tail.test)
            if tail.orelse and len(tail.orelse) == 1 and isinstance(tail.orelse[0], ast.If):
                tail = tail.orelse[0]
                continue
            break
        if members:
            heads.append((node, members))
    return heads


def _if_chain_tail(head: ast.If) -> ast.If:
    tail = head
    while tail.orelse and len(tail.orelse) == 1 and isinstance(tail.orelse[0], ast.If):
        tail = tail.orelse[0]
    return tail


def _match_dispatch_sites(tree: ast.Module) -> list[tuple[ast.Match, set[str]]]:
    """Every ``match`` statement whose cases name ``OperatingMode`` members."""

    sites: list[tuple[ast.Match, set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Match):
            continue
        members: set[str] = set()
        for case in node.cases:
            members |= _member_names_in(case.pattern)
        if members:
            sites.append((node, members))
    return sites


def _raises(body: list[ast.stmt]) -> bool:
    return any(isinstance(stmt, ast.Raise) for stmt in ast.walk(ast.Module(body=body, type_ignores=[])))


def _has_wildcard_case(match_node: ast.Match) -> ast.match_case | None:
    for case in match_node.cases:
        if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None:
            return case
    return None


# =============================================================================
# 1. No implicit two-mode dispatch survives
#
# The inverse of D4's ``test_hd_d4_9_the_exhaustive_dispatch_hazard_is_recorded``,
# which asserted that at least eight such sites *existed* and told its reader
# that converting them to total dispatch was the trigger to revisit the
# deferral. This is that conversion, pinned.
#
# Deliberately NOT a ban on every ``if`` mentioning ``OperatingMode``: a boolean
# check that is not a dispatch (for example a guard that only ever runs for one
# mode and has no alternative branch) remains legitimate. What is banned is the
# specific dangerous shape -- a chain that tests one or more members and then
# lets everything else fall into a sibling mode's behavior.
# =============================================================================


@pytest.mark.parametrize("source_file", _AUDITED, ids=lambda p: p.name)
def test_no_if_chain_falls_through_to_a_sibling_mode(source_file: Path) -> None:
    """An ``if``/``elif`` chain dispatching on mode must end in a raise.

    An ``else`` that *does* something (rather than raising) is the hazard: it
    means "every mode I did not name behaves like this one".
    """

    offenders: list[str] = []
    for head, members in _if_chain_dispatch_sites(_tree(source_file)):
        tail = _if_chain_tail(head)
        if not tail.orelse:
            # No ``else`` at all: nothing falls through to a sibling mode. The
            # chain simply does not act for unnamed modes, which is safe.
            continue
        if not _raises(tail.orelse):
            offenders.append(
                f"{source_file.name}:{head.lineno} tests {sorted(members)} "
                "and falls through to a non-raising else"
            )

    assert offenders == [], (
        "implicit two-mode dispatch survives -- an unnamed OperatingMode would "
        "silently receive another mode's behavior:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("source_file", _AUDITED, ids=lambda p: p.name)
def test_every_if_chain_dispatch_names_every_operating_mode(source_file: Path) -> None:
    """A mode-dispatching ``if`` chain that raises must still name every member
    explicitly -- a member handled *only* by the final raise is unhandled."""

    offenders: list[str] = []
    for head, members in _if_chain_dispatch_sites(_tree(source_file)):
        tail = _if_chain_tail(head)
        if not tail.orelse or not _raises(tail.orelse):
            continue  # covered by the test above
        missing = _MEMBER_NAMES - members
        if missing:
            offenders.append(
                f"{source_file.name}:{head.lineno} never names {sorted(missing)}"
            )

    assert offenders == [], (
        "a valid OperatingMode member is handled only by a generic refusal:\n  "
        + "\n  ".join(offenders)
    )


# =============================================================================
# 2. Every ``match`` dispatch is total AND exhaustive over the live enum
#
# Two separate properties, because they fail for different reasons:
#   * a missing ``case _`` means an unknown member falls out of the match with
#     no behavior at all (in an expression context, silently ``None``);
#   * a missing ``case OperatingMode.X`` means a *valid, current* member is
#     answered by the generic refusal rather than by its own implementation.
# Python checks neither at compile time.
# =============================================================================


@pytest.mark.parametrize("source_file", _AUDITED, ids=lambda p: p.name)
def test_every_match_dispatch_has_a_raising_wildcard(source_file: Path) -> None:
    offenders: list[str] = []
    for node, members in _match_dispatch_sites(_tree(source_file)):
        wildcard = _has_wildcard_case(node)
        if wildcard is None:
            offenders.append(f"{source_file.name}:{node.lineno} has no 'case _'")
        elif not _raises(wildcard.body):
            offenders.append(
                f"{source_file.name}:{node.lineno} has a 'case _' that does not raise"
            )

    assert offenders == [], (
        "a mode dispatch can complete without handling the mode:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("source_file", _AUDITED, ids=lambda p: p.name)
def test_every_match_dispatch_names_every_operating_mode(source_file: Path) -> None:
    """Every member of the *live* enum has its own ``case``.

    This is the test that fails the day a member is added without wiring it up,
    which is the entire reason D4 refused to add one. It reads
    ``OperatingMode`` at runtime, so it needs no maintenance when the enum
    grows -- the enum itself is the specification.
    """

    offenders: list[str] = []
    for node, members in _match_dispatch_sites(_tree(source_file)):
        missing = _MEMBER_NAMES - members
        if missing:
            offenders.append(
                f"{source_file.name}:{node.lineno} never names {sorted(missing)}"
            )

    assert offenders == [], (
        "a valid OperatingMode member has no explicit arm and would be answered "
        "by the generic refusal:\n  " + "\n  ".join(offenders)
    )


# =============================================================================
# 3. The audit actually found something
#
# A structural guardrail whose finder silently matches nothing is worse than no
# guardrail: it passes forever while proving nothing. These pin that the AST
# helpers above are still locating real dispatch sites, so a future refactor
# that renames or restructures dispatch cannot quietly empty the audit.
# =============================================================================


def test_the_audit_still_finds_dispatch_in_every_audited_module() -> None:
    per_module = {
        path.name: len(_if_chain_dispatch_sites(_tree(path)))
        + len(_match_dispatch_sites(_tree(path)))
        for path in _AUDITED
    }
    empty = sorted(name for name, count in per_module.items() if count == 0)
    assert empty == [], (
        f"the dispatch finder located nothing in {empty}; the audit is no longer "
        "proving anything about those modules"
    )


def test_the_audit_covers_every_module_that_names_a_mode_member() -> None:
    """No mode-dispatching backend module escapes ``_AUDITED``.

    Construction sites (``operating_mode=OperatingMode.QUICK``) are excluded:
    naming a member to *build* a value is not dispatch, and those are total by
    construction.
    """

    audited = {path.resolve() for path in _AUDITED}
    unaudited: list[str] = []
    for path in sorted(_ANCHOR_DIR.rglob("*.py")):
        if "__pycache__" in str(path) or path.resolve() in audited:
            continue
        tree = _tree(path)
        if _if_chain_dispatch_sites(tree) or _match_dispatch_sites(tree):
            unaudited.append(str(path.relative_to(_SRC_DIR)).replace("\\", "/"))

    assert unaudited == [], (
        f"these modules dispatch on OperatingMode but are not audited: {unaudited}"
    )


# =============================================================================
# 4. Ordering -- total dispatch preceded publication
#
# D5.1A's load-bearing sequencing invariant. The property is stated as a
# structural one so it stays checkable long after the commit that established
# it: every dispatch site is exhaustive over the live enum, which means that
# *at every point in time*, including the moment a member was added, no site
# was left silently under-handled. A gate that added a member first and repaired
# fallthrough afterwards cannot satisfy this at the commit that added it.
# =============================================================================


def test_ordering_no_member_exists_without_an_arm_at_every_audited_site() -> None:
    """The whole-tree statement of the two per-module exhaustiveness tests.

    Phase 1 of D5.1A ran every test in this file with ``OperatingMode`` still at
    ``{QUICK, DETAILED}`` and all of them passed, proving the conversion was
    complete *before* ``LEASE_LEVEL`` was introduced. Phase 2 then added the
    member; this test is what would have failed had any arm been forgotten.
    """

    missing: list[str] = []
    for path in _AUDITED:
        tree = _tree(path)
        for head, members in _if_chain_dispatch_sites(tree):
            tail = _if_chain_tail(head)
            if tail.orelse and _raises(tail.orelse) and (_MEMBER_NAMES - members):
                missing.append(f"{path.name}:{head.lineno}")
        for node, members in _match_dispatch_sites(tree):
            if _MEMBER_NAMES - members:
                missing.append(f"{path.name}:{node.lineno}")

    assert missing == [], (
        "these dispatch sites do not name every current OperatingMode member: "
        f"{missing}"
    )
