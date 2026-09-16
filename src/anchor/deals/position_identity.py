"""Phase 7 Gate P7.8B -- one position identity across an Investment's Capital
Structures.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 3
(P-8) and Section 14.1 (DC-3); that document governs on any discrepancy. Pure:
no I/O, no clock, no randomness, no arithmetic, and no knowledge of storage,
routes or results.

**The rule.** Within one Investment, a ``position_id`` that appears in more than
one stored Capital Structure -- the Base structure and any Strategy's own --
names **one economic instrument**. Its ``PositionClass`` and its
``PositionScope`` are therefore the same wherever it appears.

Everything else about it may differ from Strategy to Strategy, because that is
what a Strategy is for: its name, its funding, its rate, its maturity, its
priority, its fees, its preferred terms and its shortfall resolution.

**Why.** ``POSITION(position_id)`` is a Decision Matrix perspective (DC-3): one
row of a Position matrix compares *the same position* across Strategy x Scenario
variants. If one id could be Mezzanine Debt under one Strategy and Preferred
Equity under another, or Unit-scoped under one and Investment-scoped under
another, that comparison would silently put two different instruments -- with
two different metric catalogs and two different structural bases -- in one row.
A different instrument gets a new ``position_id``; ids are never regenerated
here, and no conflict is repaired.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    PositionClass,
    PositionScope,
    ScopeKind,
)


class StructureOwnerKind(StrEnum):
    """Which stored structure a position was read from."""

    BASE = "base"
    STRATEGY = "strategy"


@dataclass(frozen=True, slots=True, kw_only=True)
class StructureOwner:
    """One Capital Structure's owner, as a conflict names it.

    ``owner_id`` is the Investment id for the Base structure and the Strategy id
    for a Strategy's own. ``label`` is analyst-facing presentation text (for
    example ``"the Base Capital Structure"`` or ``"Strategy 'Value-Add'"``): it
    only ever reaches a message, never a comparison."""

    kind: StructureOwnerKind
    owner_id: str
    label: str


class PositionIdentityIssueCode(StrEnum):
    """Stable, machine-readable reasons one ``position_id`` does not name one
    economic instrument."""

    POSITION_CLASS_CONFLICT = "position_class_conflict"
    POSITION_SCOPE_CONFLICT = "position_scope_conflict"


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionIdentityIssue:
    """One deterministic reason. ``position_id`` names the identity concerned and
    ``field`` locates the finding within a position."""

    code: PositionIdentityIssueCode
    message: str
    position_id: str
    field: str

    def __str__(self) -> str:
        return self.message


class PositionIdentityConflictError(ValueError):
    """A ``position_id`` that names two economic instruments within one
    Investment. Nothing is stored for it, and no id is regenerated: the analyst
    gives the different instrument its own id."""

    def __init__(self, issues: Iterable[PositionIdentityIssue]) -> None:
        ordered = tuple(issues)
        if not ordered:
            raise ValueError("PositionIdentityConflictError requires at least one issue.")
        if not all(isinstance(issue, PositionIdentityIssue) for issue in ordered):
            raise TypeError("issues must contain only PositionIdentityIssue instances.")
        self.issues = ordered
        super().__init__("\n".join(issue.message for issue in ordered))


def _scope_text(scope: PositionScope) -> str:
    """One scope, as a message states it."""

    if scope.kind is ScopeKind.UNIT:
        return f"Unit {scope.unit_id!r}"
    return "the Investment"


def _scope_key(scope: PositionScope) -> tuple[str, str]:
    """A scope's economic identity: its kind, and the Unit it names."""

    return scope.kind.value, scope.unit_id or ""


def position_identity_issues(
    structures: Iterable[tuple[StructureOwner, CapitalStructure]],
) -> tuple[PositionIdentityIssue, ...]:
    """Every cross-structure identity conflict among ``structures``, in a
    deterministic order that never depends on how they were listed: by
    ``position_id``, then class before scope.

    ``structures`` is every Capital Structure of one Investment -- its Base
    structure and each Strategy's own -- each with the owner a message names.
    Only stated structures take part: a Strategy that inherits the Base
    structure has none of its own, so it cannot conflict with it.
    """

    classes: dict[str, dict[PositionClass, list[str]]] = {}
    scopes: dict[str, dict[tuple[str, str], list[str]]] = {}
    labels: dict[str, dict[tuple[str, str], PositionScope]] = {}
    for owner, structure in structures:
        for position in structure.positions:
            if not isinstance(position, CapitalPosition):
                continue
            position_id = position.position_id
            classes.setdefault(position_id, {}).setdefault(position.position_class, []).append(
                owner.label
            )
            key = _scope_key(position.scope)
            scopes.setdefault(position_id, {}).setdefault(key, []).append(owner.label)
            labels.setdefault(position_id, {})[key] = position.scope

    issues: list[PositionIdentityIssue] = []
    for position_id in sorted(set(classes) | set(scopes)):
        by_class = classes.get(position_id, {})
        if len(by_class) > 1:
            stated = "; ".join(
                f"{position_class.value} in {', '.join(sorted(set(owners)))}"
                for position_class, owners in sorted(
                    by_class.items(), key=lambda entry: entry[0].value
                )
            )
            issues.append(
                PositionIdentityIssue(
                    code=PositionIdentityIssueCode.POSITION_CLASS_CONFLICT,
                    message=(
                        f"Position {position_id!r} is a different class in different Capital "
                        f"Structures of this Investment ({stated}). One position id names one "
                        "economic instrument, so its class is the same wherever it appears; a "
                        "different instrument needs its own position id."
                    ),
                    position_id=position_id,
                    field="position_class",
                )
            )
        by_scope = scopes.get(position_id, {})
        if len(by_scope) > 1:
            stated = "; ".join(
                f"{_scope_text(labels[position_id][key])} in {', '.join(sorted(set(owners)))}"
                for key, owners in sorted(by_scope.items())
            )
            issues.append(
                PositionIdentityIssue(
                    code=PositionIdentityIssueCode.POSITION_SCOPE_CONFLICT,
                    message=(
                        f"Position {position_id!r} is scoped differently in different Capital "
                        f"Structures of this Investment ({stated}). One position id names one "
                        "economic instrument, so its scope is the same wherever it appears; a "
                        "different instrument needs its own position id."
                    ),
                    position_id=position_id,
                    field="scope",
                )
            )
    return tuple(issues)


def require_coherent_position_identity(
    structures: Iterable[tuple[StructureOwner, CapitalStructure]],
) -> None:
    """Raise ``PositionIdentityConflictError`` on the first read of
    ``position_identity_issues``, or return. Nothing is repaired."""

    issues = position_identity_issues(structures)
    if issues:
        raise PositionIdentityConflictError(issues)
