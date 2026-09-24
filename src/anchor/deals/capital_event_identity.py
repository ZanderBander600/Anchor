"""Refinance & Capital Events V1 Stage 2 -- one capital-event identity across an
Investment's Capital Structures.

Restates ``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 6.1 (P-8
carried over) and Section 15.1; that document governs on any discrepancy. Pure:
no I/O, no clock, no randomness, no arithmetic, and no knowledge of storage,
routes or results.

**The rule.** Within one Investment, an ``event_id`` that appears in more than
one stored Capital Structure -- the Base structure and any Strategy's own --
names **one economic event**. Its ``kind`` and its exact ``scope`` are
therefore the same wherever it appears. A conflict is refused with
``capital_event_kind_conflict`` or ``capital_event_scope_conflict``.

Everything else about the event may differ from Strategy to Strategy, because
that is what a Strategy is for: its timing, its constraints, the debt it
retires, its replacement financing, its costs and its label.

**Identity is ``event_id``, never ``label``.** Two events with one label and two
ids are two events; one id with two labels is one event, renamed.

This is the capital-event sibling of ``anchor.deals.position_identity`` (P7.8B's
position P-8), kept in its own module so the accepted position rule and its
error keep exactly their meaning. Both are asked of every structure the store
is about to write, on every lifecycle path that writes one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..capital_structure.contracts import CapitalStructure, PositionScope, ScopeKind
from ..capital_structure.events import CapitalStructureWithEvents
from .position_identity import StructureOwner


class CapitalEventIdentityIssueCode(StrEnum):
    """Stable, machine-readable reasons one ``event_id`` does not name one
    economic event (Section 15.1)."""

    CAPITAL_EVENT_KIND_CONFLICT = "capital_event_kind_conflict"
    CAPITAL_EVENT_SCOPE_CONFLICT = "capital_event_scope_conflict"


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalEventIdentityIssue:
    """One deterministic reason. ``event_id`` names the identity concerned and
    ``field`` locates the finding within an event."""

    code: CapitalEventIdentityIssueCode
    message: str
    event_id: str
    field: str

    def __str__(self) -> str:
        return self.message


class CapitalEventIdentityConflictError(ValueError):
    """An ``event_id`` that names two economic events within one Investment.
    Nothing is stored for it, and no id is regenerated: the analyst gives the
    different event its own id."""

    def __init__(self, issues: Iterable[CapitalEventIdentityIssue]) -> None:
        ordered = tuple(issues)
        if not ordered:
            raise ValueError("CapitalEventIdentityConflictError requires at least one issue.")
        if not all(isinstance(issue, CapitalEventIdentityIssue) for issue in ordered):
            raise TypeError("issues must contain only CapitalEventIdentityIssue instances.")
        self.issues = ordered
        super().__init__("\n".join(issue.message for issue in ordered))


def _scope_text(scope: PositionScope) -> str:
    if scope.kind is ScopeKind.UNIT:
        return f"Unit {scope.unit_id!r}"
    return "the Investment"


def _scope_key(scope: PositionScope) -> tuple[str, str]:
    return scope.kind.value, scope.unit_id or ""


def capital_event_identity_issues(
    structures: Iterable[tuple[StructureOwner, CapitalStructure]],
) -> tuple[CapitalEventIdentityIssue, ...]:
    """Every cross-structure event identity conflict among ``structures``, in
    a deterministic order that never depends on how they were listed: by
    ``event_id``, then kind before scope.

    A structure that states no event -- a plain ``CapitalStructure`` -- takes no
    part, so every structure authored before this gate is judged exactly as
    before."""

    kinds: dict[str, dict[str, list[str]]] = {}
    scopes: dict[str, dict[tuple[str, str], list[str]]] = {}
    stated_scopes: dict[str, dict[tuple[str, str], PositionScope]] = {}
    for owner, structure in structures:
        if not isinstance(structure, CapitalStructureWithEvents):
            continue
        for event in structure.events:
            event_id = event.event_id
            kinds.setdefault(event_id, {}).setdefault(event.kind.value, []).append(owner.label)
            key = _scope_key(event.scope)
            scopes.setdefault(event_id, {}).setdefault(key, []).append(owner.label)
            stated_scopes.setdefault(event_id, {})[key] = event.scope

    issues: list[CapitalEventIdentityIssue] = []
    for event_id in sorted(set(kinds) | set(scopes)):
        by_kind = kinds.get(event_id, {})
        if len(by_kind) > 1:
            stated = "; ".join(
                f"{kind} in {', '.join(sorted(set(owners)))}" for kind, owners in sorted(by_kind.items())
            )
            issues.append(
                CapitalEventIdentityIssue(
                    code=CapitalEventIdentityIssueCode.CAPITAL_EVENT_KIND_CONFLICT,
                    message=(
                        f"Capital event {event_id!r} is a different kind of event in different Capital "
                        f"Structures of this Investment ({stated}). One event id names one economic event, "
                        "so its kind is the same wherever it appears; a different event needs its own id."
                    ),
                    event_id=event_id,
                    field="kind",
                )
            )
        by_scope = scopes.get(event_id, {})
        if len(by_scope) > 1:
            stated = "; ".join(
                f"{_scope_text(stated_scopes[event_id][key])} in {', '.join(sorted(set(owners)))}"
                for key, owners in sorted(by_scope.items())
            )
            issues.append(
                CapitalEventIdentityIssue(
                    code=CapitalEventIdentityIssueCode.CAPITAL_EVENT_SCOPE_CONFLICT,
                    message=(
                        f"Capital event {event_id!r} is scoped differently in different Capital Structures "
                        f"of this Investment ({stated}). One event id names one economic event, so its scope "
                        "is the same wherever it appears; a different event needs its own id."
                    ),
                    event_id=event_id,
                    field="scope",
                )
            )
    return tuple(issues)


def require_coherent_capital_event_identity(
    structures: Iterable[tuple[StructureOwner, CapitalStructure]],
) -> None:
    """Raise ``CapitalEventIdentityConflictError`` on the first read of
    ``capital_event_identity_issues``, or return. Nothing is repaired."""

    issues = capital_event_identity_issues(structures)
    if issues:
        raise CapitalEventIdentityConflictError(issues)
