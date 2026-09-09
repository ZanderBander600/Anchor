"""D5.8A -- two pieces of AI product language human review asked us to fix.

Both are naming defects, not calculation defects. Nothing here changes a number,
a formula, or which fields reach the model; the fix is entirely in what the
model is told those already-computed fields *mean*.

**1. "Recurring cash flow".** The report described a negative Year 1 figure as
negative *recurring* cash flow. Year 1 of a Lease-Level hold routinely carries
substantial Tenant Improvements and Leasing Commissions, and Anchor's engine
subtracts them below NOI before every owner cash-flow series -- so a figure
depressed by lease-up capital is the opposite of recurring. The correct reading
is "Year 1 levered cash flow is negative as initial lease-up and leasing capital
requirements outweigh operating cash flow."

**2. "Negative operating distributions".** The report described a negative
``cumulative_operating_distributions_by_year`` value as a negative distribution.
The authoritative field is the running total of
``calculate_recurring_levered_cash_flows`` (``anchor/engine/returns.py``) -- a
cash-flow series. Anchor models no distribution decision, no waterfall and no
capital call, so neither "negative distribution" nor "capital call" nor
"additional equity" is a thing the contract supports. Its correct financial name
is cumulative levered (operating) cash flow.

The tests below tie each rule to the authoritative source field it describes, so
a future contract change that made either rule wrong shows up here rather than
in a report.
"""

from __future__ import annotations

import dataclasses
import re

from anchor.ai.prompts import build_system_prompt
from anchor.engine.contracts import AcquisitionResults, OwnerReturnMetrics

from anchor.engine.returns import (
    calculate_cumulative_operating_distributions_by_year,
    calculate_recurring_levered_cash_flows,
)


def flat(text: str) -> str:
    """The prompt with its line wrapping collapsed.

    The rules below are checked for the sentences they contain, not for where
    ``textwrap`` happened to break them. A re-wrap is an editing artifact, and a
    test that failed on one would teach the next author to stop touching the
    prompt rather than to keep the rule.
    """

    return " ".join(text.split())


# =============================================================================
# The authoritative source field -- inspected, not assumed
# =============================================================================


def test_the_field_the_rule_names_is_the_field_that_exists() -> None:
    """Rule 36 talks about ``cumulative_operating_distributions_by_year``. If
    that field were ever renamed or removed, the rule would be describing
    nothing, and this fails rather than leaving a dangling instruction in the
    prompt."""

    names = {field.name for field in dataclasses.fields(AcquisitionResults)}
    assert "cumulative_operating_distributions_by_year" in names
    assert "cumulative_operating_distributions_by_year" in {
        field.name for field in dataclasses.fields(OwnerReturnMetrics)
    }
    assert "cumulative_operating_distributions_by_year" in build_system_prompt()


def test_the_field_is_a_running_total_of_levered_cash_flow_not_a_distribution() -> None:
    """**Required test 48's premise, verified against the engine.**

    The rule calls the field cumulative levered cash flow. That is not a
    stylistic preference: it is what the function computes -- the running sum of
    the recurring levered cash flows, which are NOI less CapEx reserve, less
    below-NOI operating capital, less debt service. A negative value is simply a
    cumulative cash flow that has not yet turned positive.
    """

    levered = calculate_recurring_levered_cash_flows(
        noi_by_year=(1_000_000.0, 1_100_000.0),
        capex_by_year=(50_000.0, 50_000.0),
        annual_debt_service=(900_000.0, 900_000.0),
        # A heavy first-year leasing-capital draw -- exactly the case the
        # misleading wording arose from.
        operating_capital_by_year=(1_200_000.0, 0.0),
    )
    cumulative = calculate_cumulative_operating_distributions_by_year(
        recurring_levered_cash_flows=levered
    )

    # Year 1 is negative, and it is negative because of the leasing capital.
    assert levered[0] < 0
    assert cumulative[0] == levered[0]
    # It is a running total, not an independent series: year 2 is year 1 plus
    # year 2's cash flow, with no distribution rule of any kind applied.
    assert cumulative[1] == levered[0] + levered[1]
    # Nothing floors it at zero, which is what a "distribution" would have to
    # do -- an owner cannot be paid a negative amount.
    assert cumulative[0] < 0


def test_a_negative_first_year_here_is_capital_driven_not_operational() -> None:
    """**Required test 47's premise.** Remove the leasing capital and the same
    year is positive: the negative figure is the capital draw, not the
    property's ongoing operations."""

    without_leasing_capital = calculate_recurring_levered_cash_flows(
        noi_by_year=(1_000_000.0, 1_100_000.0),
        capex_by_year=(50_000.0, 50_000.0),
        annual_debt_service=(900_000.0, 900_000.0),
        operating_capital_by_year=(0.0, 0.0),
    )
    assert without_leasing_capital[0] > 0


# =============================================================================
# 47. "Recurring cash flow" is refused for a TI/LC-driven figure
# =============================================================================


def test_47_the_prompt_forbids_calling_a_leasing_capital_year_recurring() -> None:
    """**Required test 47.**

    Grounding is behavioural: the model is told which fields already have
    leasing capital netted out of them, told not to call such a figure
    recurring, and given the sentence that says what it actually is.
    """

    prompt = build_system_prompt()

    prose = flat(prompt)

    assert "CASH-FLOW NAMING RULES" in prose
    assert 'Never call such a figure "recurring cash flow"' in prose
    for forbidden_phrase in (
        '"recurring cash flow"',
        '"recurring income"',
        '"run-rate cash flow"',
    ):
        assert forbidden_phrase in prose, f"the rule does not forbid {forbidden_phrase}"
    assert "never describe a negative one as recurring or ongoing" in prose
    # The approved replacement wording is supplied, not merely the prohibition.
    assert (
        "Year 1 levered cash flow is negative as initial lease-up and leasing "
        "capital requirements outweigh operating cash flow." in prose
    )


def test_47_the_rule_names_the_fields_that_carry_leasing_capital() -> None:
    """The prohibition is anchored to the specific supplied fields, so the model
    can tell which figures it applies to rather than guessing."""

    prompt = build_system_prompt()
    for field_name in (
        "levered_cash_on_cash_by_year",
        "unlevered_cash_yield_by_year",
        "cumulative_operating_distributions_by_year",
        "tenant_improvements_by_year",
        "leasing_commissions_by_year",
    ):
        assert field_name in prompt


def test_47_genuinely_recurring_operating_lines_are_still_describable() -> None:
    """The rule is narrow on purpose. It forbids calling a capital-depressed
    figure recurring; it does not forbid the word, because NOI, cash base rent
    and expense recoveries carry no leasing capital and *are* recurring
    operating economics. A blanket ban would have made the report worse."""

    prose = flat(build_system_prompt())
    assert (
        "You may still describe genuinely recurring operating economics as recurring"
        in prose
    )
    assert "NOI, cash base rent, expense recoveries" in prose


# =============================================================================
# 48 / M17. A negative cash flow is not a negative distribution
# =============================================================================


def test_48_and_M17_the_prompt_forbids_the_distribution_reading() -> None:
    """**Required test 48, and mutant M17.**

    Every wrong name the review flagged is forbidden by name, and the right one
    is supplied. Naming them individually rather than gesturing at "misleading
    language" is what makes the rule checkable and the mutant killable.
    """

    prose = flat(build_system_prompt())

    assert 'Call it "cumulative levered cash flow"' in prose
    for forbidden in (
        '"negative distribution"',
        '"negative operating distribution"',
        '"capital call"',
        '"additional equity"',
        '"owner funding"',
    ):
        assert forbidden in prose, f"the rule does not forbid {forbidden}"
    assert "a negative cash flow is a negative cash flow" in prose


def test_48_the_rule_says_why_rather_than_only_what() -> None:
    """A prohibition the model cannot reason about is one it will work around.
    The rule states the fact that makes the wrong names wrong: Anchor models no
    distribution decision at all."""

    prose = flat(build_system_prompt())
    assert (
        "models no distribution decision, no preferred return, no promote, no "
        "waterfall and no capital call" in prose
    )
    assert "Anchor supplies no such field and models no such event." in prose


# =============================================================================
# The rules were added, not written over the top of existing ones
# =============================================================================


def test_the_new_rules_take_unused_numbers_and_drop_nothing() -> None:
    """The same claim G37 makes about every prompt change: rule numbering stays
    unique, so a new rule cannot silently replace an existing one."""

    prompt = build_system_prompt()
    numbers = re.findall(r"^(\d+[a-z]?)\. ", prompt, re.M)

    assert len(numbers) == len(set(numbers)), "a rule number is used twice"
    assert "35" in numbers and "36" in numbers
    for existing_block in (
        "GROUNDING RULES",
        "DETAILED-MODE NOI RULE",
        "OPERATING-MARGIN DISCIPLINE",
        "DEAL CONTEXT RULES",
        "STRUCTURE",
        "DEAL STORY",
        "LEASING-CAPITAL RULE",
        "LEASE-LEVEL RULES",
    ):
        assert existing_block in prompt


def test_the_new_rules_apply_in_every_mode() -> None:
    """Both defects were observed on a Lease-Level report, but neither is
    Lease-Level-specific: a Quick or Detailed deal with a CapEx reserve heavy
    enough to push Year 1 negative would be described exactly as wrongly. The
    block is scoped to every mode rather than to the one where it was noticed."""

    prompt = build_system_prompt()
    assert "CASH-FLOW NAMING RULES (mandatory in every mode):" in prompt


def test_the_rules_change_no_calculation_and_add_no_field() -> None:
    """The prompt is instructions, not evidence: nothing here computes, supplies
    or renames a value. Stated structurally -- the prompt module imports no
    engine or analysis calculation module at all."""

    import anchor.ai.prompts as prompts_module

    source = prompts_module.__file__
    assert source is not None
    text = open(source, encoding="utf-8").read()
    for forbidden_import in (
        "from ..engine",
        "from anchor.engine",
        "from ..analysis",
        "from anchor.analysis",
        "import math",
    ):
        assert forbidden_import not in text, (
            f"prompts.py imports {forbidden_import}; it must interpret, never compute"
        )
