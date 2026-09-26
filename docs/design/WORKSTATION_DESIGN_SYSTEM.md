# Anchor Workstation Design System

Status: introduced by the UI/UX workstation refinement (feature branch
`claude/compassionate-keller-hi5y87`, 2026-09-26). **Not yet human accepted.**
Presentation and interaction only: nothing here calculates, re-derives, hides
or reorders a figure.

The shared conventions live in `web/src/workstation.css`, loaded after
`web/src/index.css`. `index.css` keeps each gate's own layout and the rules its
architecture guards pin; `workstation.css` holds what every surface shares.
Earlier design intent is in `docs/workspace_ux_visual_system_v3_spec.md`; this
document supersedes it only where the two differ on shared presentation.

## Principles

- **Navy is the brand and the primary action. Blue is state** — the active
  tab, focus, links, the Base column. Headings are slate, not blue.
- **Semantic colour carries meaning, always with words or a glyph.** Capital
  Structure, Refinance and Partnership results never colour an outcome as
  good or bad (their guards enforce it); Asset Management colours
  Unfavourable red because the engine assessed it so.
- **Organized density.** Related figures form one strip, not a card each.
  Registers are one bordered list with row rules, not stacked boxes.
- **A long table scrolls inside its card, never the page.** An edge shadow
  says there is more.

## Tokens (`:root`)

| Group | Tokens |
| --- | --- |
| Brand | `--ws-navy`, `--ws-navy-hover`, `--ws-navy-soft` |
| Type scale | `--ws-fs-eyebrow` 11 · `--ws-fs-label` 12 · `--ws-fs-table` 13 · `--ws-fs-body` 13.5 · `--ws-fs-section` 15 · `--ws-fs-page` 20 · `--ws-fs-metric` 26 |
| Titles | `--ws-title` (slate section titles) |
| Controls | `--ws-control-h` 34 / `-sm` 30 / `-xs` 26, `--ws-control-border`, `--ws-control-border-hover` |
| Surfaces | `--ws-card-pad`, `--ws-inset`, `--ws-rule`, `--ws-rule-strong` |
| Tables | `--ws-th-bg`, `--ws-th-text`, `--ws-row-rule`, `--ws-total-rule`, `--ws-row-hover` |
| Semantic | `--ws-positive`, `--ws-negative`, `--ws-caution`, `--ws-info` (+ `-soft`) |

The legacy `--color-*` tokens in `index.css` now resolve to the same palette;
`--text-muted` is `#667085` (4.9:1 on white).

## Actions

| Class | Use |
| --- | --- |
| `btn btn-primary` | The one action a surface exists for (Analyze, Save …). |
| `btn btn-secondary` | Clearly interactive, subordinate (Update Deal, Run Analysis). |
| `btn btn-ghost` | Tertiary: Cancel, Close, Edit, Done. Dark text — never reads as disabled. |
| `btn btn-add` | Adds a row or record here (Add Senior Debt, Add Third-Party Cost). Dashed accent outline with a plus drawn by CSS, so the accessible name is unchanged. |
| `btn btn-remove` | Removes or deletes the row it sits in. Quiet; danger on hover. |
| `btn btn-danger-outline` | Starts a page-level destructive act whose confirmation follows (Delete Investment). |
| `btn btn-danger` | The confirming step of a destructive act only. |

Sizes: `btn-sm`, `btn-xs`. Every button shows a 2px accent focus outline.

## Titles and surfaces

- Page title: 20–22px / 700 (`.deal-header-name-input`, `.memo-header-name`,
  library and AM page titles).
- Card title: 11.5px uppercase slate — `.card-title`, `.scenario-panel-title`,
  `.assumption-section-title`, `.live-case-title` and peers share one rule.
- Sub-section title inside a card: 14–15px / 680 sentence case.
- Workspace head (`WorkspacePanel`): title and purpose on one line; page-level
  actions go in its `actions` slot, right-aligned on that line.
- `.ws-tag` / `.ws-tag-linked`: a short classification beside a name.
- `.empty-state` with `.empty-state-title` + `.empty-state-body`: say what
  belongs here and what to do next.

## Navigation levels

1. **Workspace tabs** (`.workspace-nav`): underline tabs in the header band,
   aligned to the content column.
2. **Section bar** (`.sub-nav-segmented`): a contained bar; the active item is
   a raised white tab with a navy label. Wraps rather than scrolling on narrow
   screens.
3. **Inline tabs** (`.sub-nav-inline`): small underline text.
4. **View toggles** (Project / Position / Partner, Monthly / YTD): compact,
   navy-filled when on — they change the view, not the place.

## Tables

- Shared header treatment: 11px uppercase, `--ws-th-bg`, one rule.
- Text left, figures right, and the header over its column: mark a column
  with `col-num` or `col-text` on both the `th` and its cells. The gate-level
  shared header rules stay unchanged.
- Totals are ruled above (`--ws-total-rule`) and weighted, not shaded.
- Long headers wrap (`white-space: normal`) instead of clipping the last
  column; figures keep one line.

## Metrics

A group of related figures is one strip: a bordered band whose cells are
divided by hairlines (the 1px flex gap over a rule-coloured background), so a
strip that wraps still divides cleanly. Headline figures 26px navy; supporting
figures 15–18px.

## Editors

Capital positions, refinances, partners and tiers are cards whose header band
holds the name (the fieldset legend, floated into the band), what it is, where
it ranks, and its own Remove. Editor Save / Cancel stay reachable at the foot
of the viewport (`.scenario-editor-actions`, sticky).

## Responsive

- Breakpoints in `workstation.css` use range syntax (`width <= 1023px`) so
  they never collide with the `@media (max-width: …)` blocks guards locate.
- Grid tracks use `minmax(min(Xrem, 100%), 1fr)` so no track outgrows a phone.
- Rows whose layout depends on their card, not the window, use container
  queries (the refinance cost rows).
- The deal header keeps the name legible: where name, mode switch and
  actions cannot share a line, the actions take a second, right-aligned row.
- Library rows stack on a phone: name and facts first, actions beneath.
- Verified at 1920, 1440, 1280, 1024, 390 and 200% zoom with no page-level or
  clipped horizontal overflow.
