"""Phase 7 Gate P7.9 -- share allocation.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 6 and
11.1 (ratified); that document governs on any discrepancy.

**The remainder partner.** An amount ``X`` is divided by a share table: every
partner except the remainder partner receives ``share x X``, and the remainder
partner receives ``X`` less the canonical-order sum of the others. The
remainder partner holds the largest share, ties going to the lowest
``partner_id``. Each allocation reconciles to ``X`` up to one floating-point
subtraction, a zero-share partner never receives residue, and a 100% share
yields ``X`` exactly.

Three share tables: the commitment shares (contributions), each tier's split
(explicit, or pro rata by cumulative contributions) and the promote benchmark.
The benchmark is read from ``promote_benchmark`` only -- never from the
commitments.
"""

from __future__ import annotations

from collections.abc import Mapping

from .contracts import Partnership

Shares = Mapping[str, float]


def remainder_partner(shares: Shares) -> str:
    """The partner with the largest share; ties go to the lowest id."""

    return min(shares, key=lambda partner_id: (-shares[partner_id], partner_id))


def allocate(amount: float, shares: Shares) -> dict[str, float]:
    """``amount`` divided by ``shares`` with the remainder-partner rule. The
    result is keyed in canonical (partner id) order."""

    remainder = remainder_partner(shares)
    allocated: dict[str, float] = {}
    others = 0.0
    for partner_id in sorted(shares):
        if partner_id == remainder:
            continue
        part = shares[partner_id] * amount
        allocated[partner_id] = part
        others = others + part
    allocated[remainder] = amount - others
    return {partner_id: allocated[partner_id] for partner_id in sorted(allocated)}


def commitment_shares(partnership: Partnership) -> dict[str, float]:
    """The contribution rule's shares: ``PRO_RATA_BY_COMMITMENT``."""

    return {partner.partner_id: float(partner.commitment_share) for partner in partnership.partners}


def benchmark_shares(partnership: Partnership) -> dict[str, float]:
    """The stated no-promote benchmark (PW-6, Q2), and nothing else."""

    return {share.partner_id: float(share.share) for share in partnership.promote_benchmark.shares}


def pro_rata_by_contribution_shares(cumulative_contributions: Shares) -> dict[str, float] | None:
    """Each partner's share of cumulative actual contributions (Section 6.2),
    or ``None`` when nothing has been contributed: the caller refuses, and no
    other table is substituted."""

    total = 0.0
    for partner_id in sorted(cumulative_contributions):
        total = total + cumulative_contributions[partner_id]
    if total <= 0.0:
        return None
    return {
        partner_id: cumulative_contributions[partner_id] / total
        for partner_id in sorted(cumulative_contributions)
    }
