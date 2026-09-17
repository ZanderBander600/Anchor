"""Phase 7 Gate P7.9 Stage 2 -- one partner identity across an Investment's
Partnerships.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 3
(P-8) and Section 14.1 (DC-3), and
``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 17.2; those
documents govern on any discrepancy. Pure: no I/O, no clock, no randomness, no
arithmetic, and no knowledge of storage, routes or results.

**The rule.** Within one Investment, a ``partner_id`` that appears in more than
one stored Partnership -- the Base Partnership and any Strategy's own -- names
**one investor**. Its ``PartnerRole`` is therefore the same wherever it
appears.

Everything else about the partner may differ from Strategy to Strategy,
because that is what a Strategy is for: its name, its commitment, its benchmark
share, its investor class, its split shares and whether it is a promote
participant. ``role`` never drives an allocation (Stage 1 reads it only to copy
it), so holding it fixed changes no economics; it keeps the investor itself
fixed.

**Why.** ``PARTNER(partner_id)`` is a Decision Matrix perspective (DC-3): one row
of a Partner matrix compares *the same investor* across Strategy x Scenario
variants. If one id could be the LP under one Strategy and the GP under
another, that row would silently compare two different investors. A different
investor gets a new ``partner_id``; ids are never regenerated here, and no
conflict is repaired.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..partnership.contracts import Partner, Partnership, PartnerRole
from .position_identity import StructureOwner


class PartnerIdentityIssueCode(StrEnum):
    """Stable, machine-readable reasons one ``partner_id`` does not name one
    investor."""

    PARTNER_ROLE_CONFLICT = "partner_role_conflict"


@dataclass(frozen=True, slots=True, kw_only=True)
class PartnerIdentityIssue:
    """One deterministic reason. ``partner_id`` names the identity concerned and
    ``field`` locates the finding within a partner."""

    code: PartnerIdentityIssueCode
    message: str
    partner_id: str
    field: str

    def __str__(self) -> str:
        return self.message


class PartnerIdentityConflictError(ValueError):
    """A ``partner_id`` that names two investors within one Investment. Nothing
    is stored for it, and no id is regenerated: the analyst gives the different
    investor its own id."""

    def __init__(self, issues: Iterable[PartnerIdentityIssue]) -> None:
        ordered = tuple(issues)
        if not ordered:
            raise ValueError("PartnerIdentityConflictError requires at least one issue.")
        if not all(isinstance(issue, PartnerIdentityIssue) for issue in ordered):
            raise TypeError("issues must contain only PartnerIdentityIssue instances.")
        self.issues = ordered
        super().__init__("\n".join(issue.message for issue in ordered))


def partner_identity_issues(
    partnerships: Iterable[tuple[StructureOwner, Partnership]],
) -> tuple[PartnerIdentityIssue, ...]:
    """Every cross-Partnership identity conflict among ``partnerships``, in a
    deterministic order that never depends on how they were listed: by
    ``partner_id``.

    ``partnerships`` is every stated Partnership of one Investment -- its Base
    Partnership and each Strategy's own -- each with the owner a message names.
    A Strategy that inherits the Base Partnership, or that states it has none,
    has no partner of its own, so it cannot conflict."""

    roles: dict[str, dict[str, list[str]]] = {}
    for owner, partnership in partnerships:
        for partner in partnership.partners:
            if not isinstance(partner, Partner) or not isinstance(partner.role, PartnerRole):
                continue
            roles.setdefault(partner.partner_id, {}).setdefault(partner.role.value, []).append(
                owner.label
            )

    issues: list[PartnerIdentityIssue] = []
    for partner_id in sorted(roles):
        by_role = roles[partner_id]
        if len(by_role) > 1:
            stated = "; ".join(
                f"{role} in {', '.join(sorted(set(owners)))}"
                for role, owners in sorted(by_role.items())
            )
            issues.append(
                PartnerIdentityIssue(
                    code=PartnerIdentityIssueCode.PARTNER_ROLE_CONFLICT,
                    message=(
                        f"Partner {partner_id!r} has a different role in different Partnerships "
                        f"of this Investment ({stated}). One partner id names one investor, so "
                        "its role is the same wherever it appears; a different investor needs "
                        "its own partner id."
                    ),
                    partner_id=partner_id,
                    field="role",
                )
            )
    return tuple(issues)


def require_coherent_partner_identity(
    partnerships: Iterable[tuple[StructureOwner, Partnership]],
) -> None:
    """Raise ``PartnerIdentityConflictError`` on the first read of
    ``partner_identity_issues``, or return. Nothing is repaired."""

    issues = partner_identity_issues(partnerships)
    if issues:
        raise PartnerIdentityConflictError(issues)
