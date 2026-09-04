# Workspace UX & Visual System V3 — Specification

Sprint C, Gate C1. Status: locked for C2 implementation.

Visual north star: `docs/design/Anchor Web Design.png`.

This document specifies a **UX architecture and visual system**. It changes no
financial mathematics, no engine contract, no persistence semantics, no
snapshot provenance rule, and no AI prompt or trust boundary. Every number
Anchor displays after Sprint C is produced by exactly the same deterministic
Python engine call that produced it before Sprint C.

---

## 1. Product problem

Anchor's frontend is a single vertically-stacked page. `App.tsx` renders, in
one column, for whichever operating mode is active:

```
Operating-mode toggle
  Deal Bar (name, save status, Save, Deal Library, New Deal)
  Deal Context textarea
  Deal Intake (Excel upload + OM upload/review, Excel review panel)
  Assumptions form (9 Quick fields + 5 V2 fields, or 22 Detailed fields)
  results-column:
    Owner Summary
    ResultsPanel (Key Returns, Owner Returns, Property, Capitalization,
                  Exit, Cash Flow table, Owner Return Schedule)
    Operating Statement (Detailed only)
    Sensitivity
    Break-Even
    AI Analyst
```

Consequences observed on `main` at `ca4fc16`:

- **Excessive scrolling.** Reaching the AI Analyst on an analyzed Detailed
  deal requires scrolling past intake, 22 assumption inputs, the Owner
  Summary, the full results panel, a multi-year operating statement, a
  cash-flow table, an owner return schedule, three sensitivity matrices and
  the break-even panel. Every feature Anchor has is between the user and the
  feature they want.
- **Repetition.** The Owner Summary and `ResultsPanel` legitimately restate
  the same authoritative figures (this is by design — Owner Summary is the
  owner-facing read of results). Stacked adjacently, the repetition reads as
  redundancy rather than as two audiences.
- **Weak hierarchy.** Deal identity, global navigation, mode selection, and
  section headings all compete at similar visual weight. There is no
  persistent frame telling the user where they are.
- **Unclear feature homes.** "Where does sensitivity live?" has no structural
  answer — it lives wherever it happens to fall in the scroll.
- **Poor scalability.** Each new capability lengthens the same page. The
  Sprint B additions (Owner Summary, Deal Story) made the page longer, not
  better organised.
- **Prototype feel.** A single centered column of white cards on grey reads
  as a functional prototype, not as institutional software.

The functionality is strong. The **structure** is the problem.

## 2. UX objectives

1. Replace the one-long-page mental model with a **deal workspace**: a
   persistent frame plus a switchable content region.
2. Give every existing capability **exactly one structural home**, so its
   location is a fact about the product rather than an accident of order.
3. Make the target feeling *calm, dense, analytical, institutional* — closer
   to Linear / Stripe Dashboard than to a marketing SaaS page.
4. Reduce scrolling so that **no workspace requires scrolling through another
   workspace's content**.
5. Preserve 100% of existing functionality and financial behavior.

## 3. Final information architecture

Locked. No repository constraint was found that requires deviating from the
architecture in the Sprint C brief.

```
┌──────────────┬────────────────────────────────────────────────┐
│              │  DEAL HEADER                                   │
│   GLOBAL     │  name · mode · save status · Save · Analyze · ⋯ │
│   SIDEBAR    ├────────────────────────────────────────────────┤
│              │  Overview  Underwrite  Risk  AI Analyst  Docs   │
│              ├────────────────────────────────────────────────┤
│              │                                                │
│              │  ACTIVE WORKSPACE                              │
│              │                                                │
└──────────────┴────────────────────────────────────────────────┘
```

### 3.1 Global sidebar (persistent, all views)

```
ANCHOR                    (brand mark + wordmark)

  Deal Library            (global nav — opens the library view)
  New Deal                (global nav — action)

RECENT DEALS
  <deal name>             (up to 8, most recently updated first)
  <mode> · <purchase price>
  …

  Settings                (bottom, disabled placeholder)
```

**Naming decision.** The concept image labels the first nav row "Deals". The
production label stays **"Deal Library"** — it is the established product name
for that surface, it is what the view it opens is titled, and it carries more
information than "Deals" in an app where "deal" is also the singular working
object. The design language, not the word, is what delivers the redesign.

**Settings.** Anchor has no settings implementation. The row renders as a
visually disabled, non-interactive placeholder marked `aria-disabled`. No
settings system is built. It exists so the sidebar's bottom anchor matches the
locked IA and so a future gate has an obvious home.

### 3.2 Deal header (workspace view only)

Rendered whenever a deal workspace is active; not rendered in the library
view, which is a global surface with no single active deal.

| Element | Source | Notes |
| --- | --- | --- |
| Deal name | `dealName` / `detailedDealName` | Editable input, `Deal Name` label (visually hidden) |
| Operating mode | `operatingMode` | Segmented control, `role="tablist"`, tabs `Quick Underwrite` / `Detailed Underwrite` |
| Save status | `saveStatus` / `detailedSaveStatus` | Pill: `Unsaved deal` / `Unsaved changes` / `Saved · <timestamp>` |
| Save | `handleSaveDeal` / `handleSaveDetailedDeal` | Label `Save Deal` when never saved, `Update Deal` when saved |
| Analyze | `runQuickAnalyze` / `runDetailedAnalyze` | Primary action |
| Overflow `⋯` | existing duplicate/delete handlers | Duplicate deal, Delete deal — enabled only for a saved deal |

**No fictional metadata.** The concept image shows a property photo, city,
asset type and building size. Anchor's `Deal` contract has `name`,
`operating_mode`, `deal_context`, `inputs`/`terms`, snapshots and timestamps —
and nothing else. The header shows only those. No photo, address, asset type,
or square footage is added.

**Save label decision.** The concept image shows a single "Save". Production
keeps the existing dynamic `Save Deal` / `Update Deal` label: it distinguishes
"this will create a deal" from "this will update the deal you opened", which
is real information the status pill alone does not convey at the moment of
clicking.

### 3.3 Deal workspace navigation

Five workspaces: **Overview · Underwrite · Risk · AI Analyst · Documents**.

ARIA tabs pattern: `role="tablist"` on the nav, `role="tab"` per item with
`aria-selected` and `aria-controls`, `role="tabpanel"` per workspace with
`aria-labelledby`. Inactive panels carry the `hidden` attribute.

## 4. Workspace ownership

### Overview — the owner-facing read of the deal

Owns `OwnerSummaryPanel`, which already contains Deal Identity, The Play,
Key Returns, Investment Snapshot / Debt-Risk, Operating Story / Owner Returns,
Break-Even Highlights, and the AI Deal Story when one exists.

Overview **does not** stack `ResultsPanel`, the operating statement, the
cash-flow table, the owner return schedule, sensitivity, break-even controls,
or the full AI Analyst beneath it. That stacking is precisely the problem
Sprint C exists to solve.

Empty state when no valid analysis exists: one clean panel pointing the user
to Underwrite → Analyze. Not a grid of N/A cards.

### Underwrite — all numerical underwriting assumptions

Owns the operating-mode-appropriate assumptions form (`AssumptionsForm` for
Quick, `DetailedAssumptionsForm` for Detailed) and the Deal Context field.

**Deal Context placement.** Deal Context is analyst-authored narrative that
feeds the AI Analyst and the Owner Summary's "The Play". It is part of what
the analyst asserts about the deal, it participates in dirty tracking exactly
like an assumption, and editing it invalidates AI output. It therefore belongs
with the assumptions, in Underwrite. It is not a document, not a risk output,
and not an AI output.

Underwrite additionally hosts the **temporary Detailed Results region** — see
§4.6.

C3 will restructure this workspace into Acquisition / Operations / Debt / Exit
sub-sections. C2 does not.

### Risk — sensitivity and break-even

Owns `SensitivityPanel` and `BreakEvenPanel` (both already generalized to
accept either mode's contract shape). Break-even target editing and the
return-hurdle metric selector move here with the panel; their handlers are
unchanged.

Future scenario tooling would belong here. None is invented now.

### AI Analyst — the full long-form AI report

Owns `AiAnalystPanel` and the `Generate AI Analysis` action.

The Deal Story stays on Overview, inside the Owner Summary, exactly as
Sprint B built it. The full report does not also appear on Overview.

### Documents — ingestion and analyst review

Owns `ExcelUploadPanel`, `OmReviewPanel` / `DetailedOmReviewPanel`,
`ExcelReviewPanel` / `DetailedExcelReviewPanel`, their upload/extract/approve/
reject/cancel flows, their success and error banners, and their source
evidence display.

No document library, no document list, no new extraction capability is
invented. Documents is a home for the workflows that already exist.

### 4.6 Temporary home for the full results surfaces (C2 only)

`ResultsPanel` (Key Returns, Owner Returns, Property, Capitalization, Exit,
`CashFlowTable`, `OwnerReturnSchedule`) and `OperatingStatementTable` must
remain reachable and must not be deleted, but Overview may no longer stack
them.

**C2 decision:** they render inside **Underwrite**, in a clearly separated
`Detailed Results` section below the assumptions form, shown only when a valid
analysis exists.

Rationale: these surfaces are the direct numerical output of the assumptions
immediately above them; "change an input, look at the resulting schedule" is a
coherent underwriting loop. A sixth permanent workspace is not created. C4
will decide their final home.

## 5. Current component mapping

| Current component / feature | New workspace | C2 action | Later gate |
| --- | --- | --- | --- |
| `App.tsx` single-column layout | — | Replaced by app shell; all state and handlers retained in `App.tsx` | C3–C5 |
| `app-header` (brand strip) | Sidebar | Brand moves into sidebar top; strip removed | — |
| `operating-mode-toggle` | Deal header | Moves into header as a segmented control; same `role="tab"` names | C3 |
| `DealBar` | Deal header | Retired; `DealHeader` takes name/status/Save. Deal Library and New Deal move to sidebar | — |
| `DealLibraryPanel` | Library view | Rendered unchanged in the shell's main region | C4 |
| Deal Library data (`savedDeals`) | Sidebar | Same state reused for the Recent Deals list — no second library state system | C4 |
| `DealContextField` | Underwrite | Rendered in Underwrite | C3 |
| `AssumptionsForm` (Quick) | Underwrite | Rendered unchanged | C3 restructure |
| `DetailedAssumptionsForm` | Underwrite | Rendered unchanged | C3 restructure into Acquisition/Operations/Debt/Exit |
| `ExcelUploadPanel` | Documents | Rendered unchanged | C4 |
| `ExcelReviewPanel` | Documents | Rendered unchanged; approval navigates to Underwrite | C4 |
| `DetailedExcelReviewPanel` | Documents | Rendered unchanged; approval navigates to Underwrite | C4 |
| `OmReviewPanel` | Documents | Rendered unchanged | C4 |
| `DetailedOmReviewPanel` | Documents | Rendered unchanged | C4 |
| `OwnerSummaryPanel` | Overview | Sole primary content of Overview | C4/C5 visual refinement |
| Deal Story (inside Owner Summary) | Overview | Unchanged | C5 |
| `ResultsPanel` | Underwrite (temporary) | Rendered in the `Detailed Results` section | C4 final placement |
| `CashFlowTable` (inside `ResultsPanel`) | Underwrite (temporary) | Unchanged | C4 |
| `OwnerReturnSchedule` (inside `ResultsPanel`) | Underwrite (temporary) | Unchanged | C4 |
| `OperatingStatementTable` | Underwrite (temporary) | Rendered in the `Detailed Results` section | C4 |
| `SensitivityPanel` | Risk | Rendered unchanged | C4 layout |
| `BreakEvenPanel` | Risk | Rendered unchanged, with its target controls | C4 layout |
| `AiAnalystPanel` | AI Analyst | Rendered unchanged | C4 internal navigation |
| Analyze action | Deal header + Underwrite form | Header `Analyze` and form `Analyze Deal` call one shared function | C3 |
| Save action | Deal header | Same handlers, same semantics | — |
| Duplicate / Delete | Library view + header overflow | Same handlers | C4 |
| `error-banner` / `empty-state` | Per workspace | Scoped to the owning workspace | C5 |
| Existing responsive CSS (`@media 900px`) | — | Replaced by the shell's breakpoint set | C5 |

Nothing on `main` is orphaned by this mapping.

## 6. Design principles

1. **Frame is dark, work is light.** Navigation is a deep navy chrome; the
   workspace is a warm near-white. The user always knows which is which.
2. **Restraint over decoration.** Hierarchy comes from type scale, weight and
   spacing. Not from shadows, gradients, or color.
3. **Color carries meaning.** Blue means "primary action or headline metric".
   Green/amber/red appear only where the product genuinely asserts good /
   caution / bad. Nothing is colored for decoration.
4. **Dense, not cramped.** Institutional users read tables. Compact rows with
   generous grouping whitespace beat airy rows with none.
5. **Numbers are the content.** Financial figures get tabular numerals,
   deliberate weight, and enough size to be read at a glance.
6. **No invention.** Every field displayed maps to a real production contract.

## 7. Color system

Extends the existing `:root` token block in `web/src/index.css`. Existing
tokens are kept so no legacy component regresses; new shell tokens are added
alongside.

### Navigation (dark)

| Token | Value | Use |
| --- | --- | --- |
| `--nav-bg` | `#0d1a2d` | Sidebar background |
| `--nav-bg-elevated` | `#132339` | Sidebar section separators, brand row |
| `--nav-text` | `#e6ebf2` | Sidebar primary text |
| `--nav-text-muted` | `#8a9ab0` | Sidebar section labels, deal meta lines |
| `--nav-hover` | `rgba(255, 255, 255, 0.06)` | Nav row hover |
| `--nav-active` | `#1b2f4d` | Active nav row / active deal row |
| `--nav-active-text` | `#ffffff` | Active nav row text |
| `--nav-accent` | `#4d8df0` | Active row left indicator, brand mark |
| `--nav-border` | `rgba(255, 255, 255, 0.08)` | Sidebar internal dividers |

### Workspace (light)

| Token | Value | Use |
| --- | --- | --- |
| `--app-bg` | `#f7f8fa` | Workspace background |
| `--surface` | `#ffffff` | Cards, panels, header |
| `--surface-muted` | `#f9fafb` | Table headers, inset regions |
| `--border` | `#e3e7ed` | Card and control borders |
| `--border-strong` | `#cbd2dc` | Emphasised dividers |
| `--text` | `#111826` | Primary text |
| `--text-secondary` | `#4a5568` | Secondary text, labels |
| `--text-muted` | `#77808f` | Captions, metadata |

### Accent and semantics

| Token | Value | Use |
| --- | --- | --- |
| `--accent` | `#1d5fd0` | Primary buttons, headline metric values, active workspace tab |
| `--accent-hover` | `#174ead` | Primary button hover |
| `--accent-soft` | `#eef4fd` | Metric card fill, selected soft states |
| `--accent-border` | `#c7dbf7` | Metric card border |
| `--success` | `#1f7a3f` | Saved state, approved |
| `--success-soft` | `#e6f4ec` | — |
| `--warning` | `#8a5a06` | Unsaved changes, caution |
| `--warning-soft` | `#fdf1da` | — |
| `--danger` | `#a72b2b` | Errors, destructive actions |
| `--danger-soft` | `#fbeaea` | — |
| `--focus-ring` | `0 0 0 3px rgba(29, 95, 208, 0.28)` | Keyboard focus on light surfaces |
| `--focus-ring-dark` | `0 0 0 3px rgba(120, 170, 255, 0.42)` | Keyboard focus in the sidebar |

The existing `--color-*` tokens remain defined and in use by legacy
components. New shell CSS uses the new names. C5 may converge them.

## 8. Typography

**Font decision: no new font dependency.** The existing stack
(`-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial,
sans-serif`) resolves to Segoe UI Variable on the Windows target and to
SF Pro on macOS. Both are high-quality neutral grotesques appropriate for
institutional software, both ship tabular numerals, and both are already
rendering Anchor today. Adding a webfont would cost a network dependency, a
FOUT, and licensing questions in exchange for a marginal difference. No font
binary is downloaded.

Numeric display uses `font-variant-numeric: tabular-nums` (safely supported by
all target browsers; degrades to proportional figures, never to a broken
layout).

| Role | Size | Weight | Tracking | Notes |
| --- | --- | --- | --- | --- |
| Brand wordmark | 15px | 600 | `0.14em` | Uppercase, sidebar |
| Deal title | 20px | 650 | `-0.011em` | Deal header |
| Workspace heading | 17px | 620 | `-0.008em` | Top of each workspace |
| Section heading | 13px | 600 | `0.04em` | Uppercase, muted |
| Card title | 14px | 600 | `-0.004em` | — |
| Metric value (primary) | 26px | 650 | `-0.02em` | Tabular, accent color |
| Metric value (secondary) | 18px | 600 | `-0.015em` | Tabular |
| Body | 14px | 400 | — | 1.5 line height |
| Supporting text | 13px | 400 | — | Secondary color |
| Label | 12px | 550 | `0.01em` | Secondary color |
| Table header | 11.5px | 600 | `0.05em` | Uppercase, muted |
| Table numeric cell | 13px | 450 | — | Tabular, right aligned |
| Nav item | 13.5px | 500 | — | — |

No heading exceeds 26px. Nothing readable drops below 11.5px.

## 9. Spacing

A single 4px-based scale. New shell CSS uses only these values.

| Token | Value | Typical use |
| --- | --- | --- |
| `--sp-1` | 4px | Icon/text gap |
| `--sp-2` | 8px | Tight inline gaps |
| `--sp-3` | 12px | Control padding, nav row padding |
| `--sp-4` | 16px | Card padding (compact), grid gaps |
| `--sp-5` | 20px | Card padding (default) |
| `--sp-6` | 24px | Workspace padding, section gaps |
| `--sp-8` | 32px | Major section separation |
| `--sp-10` | 40px | Workspace bottom padding |

Fixed layout dimensions:

| Token | Value |
| --- | --- |
| `--sidebar-width` | 236px |
| `--sidebar-width-narrow` | 200px |
| `--header-height` | 64px |
| `--workspace-max` | 1360px |

## 10. Radius and shadow rules

| Token | Value | Use |
| --- | --- | --- |
| `--radius-sm` | 5px | Inputs, small buttons, badges |
| `--radius-md` | 7px | Buttons, nav rows, cards |
| `--radius-lg` | 10px | Large panels |

Restrained. Nothing above 10px; no pill-shaped cards.

| Token | Value | Use |
| --- | --- | --- |
| `--shadow-sm` | `0 1px 2px rgba(16, 24, 40, 0.04)` | Default card |
| `--shadow-md` | `0 1px 3px rgba(16,24,40,.06), 0 1px 2px rgba(16,24,40,.04)` | Header, raised menu |

Hierarchy comes from borders and background, not shadow. No card uses more
than `--shadow-sm`.

## 11. Component language

Specification only — this is a consistency contract, not an instruction to
build a generic component library. Legacy components keep their existing
classes in C2 and are converged in C3–C5.

- **Button, primary** — accent fill, white text, `--radius-md`, 32px (sm) /
  36px (md) high, `--sp-4` horizontal padding, 13.5px/550. Hover darkens.
  Disabled: 55% opacity, no pointer.
- **Button, secondary** — white fill, `--border` border, `--text` label.
- **Button, ghost** — transparent, `--text-secondary`, hover `--surface-muted`.
- **Button, danger** — ghost with `--danger` text; destructive confirmation
  stays `window.confirm`, per existing product convention.
- **Icon button** — 28px square, ghost, `--radius-sm`, always carries an
  `aria-label`.
- **Workspace tab** — 38px tall, 13.5px/550, `--text-secondary`; active is
  `--text` with a 2px `--accent` bottom indicator; hover is `--text`.
- **Nav item** — 34px tall, `--radius-md`, 13.5px/500, icon + label,
  `--nav-text`; hover `--nav-hover`; active `--nav-active` +
  `--nav-active-text` + a 3px `--nav-accent` left indicator.
- **Badge** — 11.5px/600, uppercase, `0.03em`, `--radius-sm`, 2px/7px padding,
  semantic soft background + semantic text.
- **Status indicator** — badge plus a 6px dot; never color alone — the text
  label always states the status.
- **Input / select / textarea** — 32px (sm) / 36px high, `--radius-sm`,
  `--border`, 13.5px; focus is `--accent` border + `--focus-ring`. Numeric
  inputs are tabular and right-aligned.
- **Card** — `--surface`, `--border`, `--radius-md`, `--shadow-sm`,
  `--sp-5` padding.
- **Metric card** — `--accent-soft` fill, `--accent-border` border, centered
  label + primary metric value.
- **Section panel** — card with a title row (title + optional action) and a
  1px divider under it.
- **Table** — uppercase muted header on `--surface-muted`, 1px row dividers,
  tabular right-aligned numerics, horizontal scroll inside its own container.
- **Empty state** — centered, `--surface-muted` dashed-border block, one line
  of guidance plus the action that resolves it.
- **Loading state** — a text status line in the panel that owns it. No
  skeleton system in C2.
- **Error state** — `--danger-soft` block with `--danger` text, scoped to the
  panel that owns the failed operation.

## 12. Navigation behavior

### 12.1 Views

`view: 'workspace' | 'library'` (existing state, retained).

- `library` — sidebar + `DealLibraryPanel` in the main region. No deal header,
  no workspace nav (the library is global, not a deal surface).
- `workspace` — sidebar + deal header + workspace nav + active workspace.

### 12.2 Workspace state

`workspace: 'overview' | 'underwrite' | 'risk' | 'ai' | 'documents'`.

Local React state in `App.tsx`. **No router dependency is introduced.** Five
views with no deep-linking requirement do not justify a router; adding one
would be a larger architectural change than the navigation it serves.

**One workspace state, shared across modes.** Switching Quick ↔ Detailed keeps
the selected workspace. The workspaces mean the same thing in both modes, and
resetting the tab on a mode switch would be surprising.

### 12.3 Mounting

All five workspace panels stay **mounted** at all times; inactive ones carry
the `hidden` attribute (`display: none`, and removed from the accessibility
tree).

Rationale: C2.7 requires that switching workspaces preserve unsaved form
state, analysis state, AI state, and review state. Deal-level state already
lives in `App.tsx` and survives unmounting — but `OmReviewPanel` and
`DetailedOmReviewPanel` hold **per-field analyst approval state internally**.
Unmounting Documents mid-review would silently discard an in-progress analyst
review. Keeping panels mounted makes state preservation structural rather than
something each panel must remember to support, and it is the standard ARIA
tab-panel pattern. With five panels in a POC the cost is negligible. Hidden
panels occupy zero layout, so this does not affect scroll length.

Quick vs. Detailed remains **conditionally rendered** as it is today — those
are two independent deals, not two views of one deal, and their state must
stay isolated.

### 12.4 Default workspace rules

| Situation | Workspace |
| --- | --- |
| App start (blank, unanalyzed deal) | Underwrite |
| New Deal | Underwrite |
| Successful Analyze completes | Overview |
| Analyze fails validation or the API errors | stays on the current workspace |
| Open a saved deal **with** a restored analysis snapshot | Overview |
| Open a saved deal **without** a restored analysis snapshot | Underwrite |
| Delete the currently-open deal | Underwrite (deal resets to blank) |
| Approve an Excel review in Documents | Underwrite (the approved assumptions' home) |
| Switch operating mode | unchanged |
| Save | unchanged |
| Generate AI Analysis | unchanged |

Post-Analyze navigation to Overview is implemented only for a **successful**
analysis, and only from the analysis handler, so a failed Analyze never moves
the user away from the inputs they need to fix.

### 12.5 Sidebar deal list

Reuses the existing `savedDeals` / `isDealsLoading` / `dealsError` state and
`loadSavedDeals()`. Loaded once on mount and refreshed by the same events that
already refresh the library (save, duplicate, delete, opening the library).
No second deal-library state system is created; no persistence code is
rewritten.

Rows show name + `mode · purchase price`, truncate with ellipsis, and mark the
active deal with `aria-current="true"` plus the active row treatment. Clicking
a row calls the existing `handleOpenDeal`, including its unsaved-changes
guard. Duplicate and delete are **not** crammed into the row — they stay in
the library view and in the header overflow menu.

## 13. Responsive rules

Desktop first. Primary reference 1440px.

| Width | Sidebar | Header | Workspace nav | Content |
| --- | --- | --- | --- | --- |
| ≥1440 | 236px expanded | single row | single row | max 1360px, 24px padding |
| 1280–1439 | 236px expanded | single row | single row | fluid, 24px padding |
| 1024–1279 | 200px expanded | single row, name truncates | single row | fluid, 20px padding |
| 768–1023 | 64px icon-only rail | wraps to two rows | horizontally scrollable | fluid, 16px padding |
| <768 | 64px icon-only rail | wraps | horizontally scrollable | fluid, 16px padding |

At the icon-only rail, nav labels are hidden and each row keeps its
`aria-label`; the Recent Deals list is hidden (its rows are unusable at 64px
and the library view remains one click away).

Hard rule: **no horizontal page overflow at any width.** Wide content (tables,
sensitivity matrices) scrolls inside its own container, never the page.

A perfect mobile application is explicitly out of scope for C2.

## 14. Motion principles

Specification for C5. C2 implements only the trivial subset marked ✓.

- Duration 150ms for hover/color, 180ms for position/opacity. Nothing over
  200ms.
- Easing `cubic-bezier(0.2, 0, 0.15, 1)`.
- Motion is functional: it shows a relationship or a state change. Nothing
  animates for delight.
- Financial values never animate — a number that counts up is a number the
  reader cannot trust at a glance.
- All motion respects `prefers-reduced-motion: reduce`.

| Motion | Gate |
| --- | --- |
| Nav item hover/active color ✓ | C2 |
| Button hover ✓ | C2 |
| Workspace tab indicator ✓ | C2 |
| Sidebar deal row hover ✓ | C2 |
| Workspace content fade-in on switch | C5 |
| Save state transition | C5 |
| Analysis / AI loading states | C5 |
| Sidebar collapse | C5 |

No animation library is added.

## 15. Scrolling and progressive disclosure

The governing rule: **no workspace may require scrolling through another
workspace's content to reach its own.**

- The sidebar, deal header and workspace nav are fixed frame; only the
  workspace content region scrolls.
- Splitting by workspace — not by accordion — is the primary tool. Accordions
  hide content behind an interaction with no navigational meaning; workspaces
  give it an address.
- Core information is never hidden. Every workspace shows its full content;
  it simply no longer shows five other workspaces' content.
- Wide tables scroll locally, inside their own container.
- Long content that genuinely belongs together (the operating statement, the
  cash-flow schedule) still scrolls — that is correct. The goal is not zero
  scrolling; it is that scrolling stays *within a topic*.

## 16. Accessibility principles

- Every interactive control is a real `<button>`, `<a>`, or form control.
- Workspace nav follows the ARIA tabs pattern: `tablist` / `tab` /
  `tabpanel`, `aria-selected`, `aria-controls`, `aria-labelledby`; inactive
  panels are `hidden`. Tabs are reachable and operable by keyboard.
- The active deal in the sidebar carries `aria-current="true"`; the active
  global nav item carries `aria-current="page"`.
- Visible focus on every control, on both light and dark surfaces
  (`--focus-ring` / `--focus-ring-dark`). Focus is never removed without a
  replacement.
- Status is never conveyed by color alone — every status indicator carries a
  text label.
- Icon-only controls (overflow menu, collapsed rail items) carry `aria-label`.
- Decorative icons are `aria-hidden`.
- Body text ≥13px; the smallest text (table headers, 11.5px) is uppercase,
  600-weight, and non-essential-duplicated by the cell content.
- Contrast: `--nav-text` on `--nav-bg` ≈ 13:1; `--text` on `--surface` ≈
  16:1; `--text-muted` on `--surface` ≈ 4.9:1; white on `--accent` ≈ 6.4:1.

## 17. Explicit non-goals

Sprint C, Gates C1–C2 will **not**:

- change any financial formula, convention, or engine contract;
- touch `src/anchor/engine` or `src/anchor/analysis`;
- introduce any calculation into the frontend;
- add persisted financial state or change snapshot provenance;
- change AI prompts, AI contracts, or AI trust boundaries;
- change Quick/Detailed economics or their state isolation;
- add a router or any new runtime dependency;
- add property photos, addresses, asset types, square footage, tenant data, or
  market data;
- redesign the underwriting form (C3);
- build internal AI Analyst navigation or a Documents dashboard (C4);
- build a settings system;
- build a mobile-first experience;
- redesign every legacy panel's internals.

## 18. C2 implementation scope

1. `AppSidebar` — brand, global nav, recent deals, Settings placeholder.
2. `DealHeader` — name, mode segmented control, save status, Save, Analyze,
   overflow menu.
3. `WorkspaceNav` — five ARIA tabs.
4. Five workspace regions rendered from `App.tsx`, all mounted, inactive
   `hidden`.
5. `workspace` state plus the §12.4 default rules.
6. Analyze extracted to a shared function callable from both the header and
   the form's submit.
7. Shell visual system in `index.css`: tokens, sidebar, header, nav, surfaces,
   typography, button hierarchy, focus states, breakpoints.
8. Tests for the shell, navigation, state preservation, workspace ownership,
   and feature preservation.
9. Visual QA at 1440 / 1024 / 768 across seven scenarios.

Legacy panel internals stay as they are. They will look less refined than the
shell until C3–C5. That is expected and acceptable.

## 19. Deferred scope

- **C3** — Underwrite redesign: Acquisition / Operations / Debt / Exit
  sub-sections, live metrics rail, input ergonomics.
- **C4** — Analysis workspace reorganisation: final home for `ResultsPanel` /
  operating statement / schedules, Risk layout, AI Analyst internal
  navigation, Documents organisation.
- **C5** — Polish: motion system, responsive completion, legacy panel visual
  convergence, token unification.

## 20. Open questions

1. **Final home for the full results surfaces.** C2 parks `ResultsPanel`,
   `OperatingStatementTable`, `CashFlowTable` and `OwnerReturnSchedule` in
   Underwrite. Candidates for C4: a sixth "Analysis" workspace, a
   sub-navigation inside Overview, or keeping them in Underwrite. Needs a
   product decision.
2. **Sensitivity and break-even are not persisted.** Reopening a saved deal
   restores `results` and `ai_snapshot` but not sensitivity or break-even, so
   Risk is empty until the user re-runs Analyze. C2 shows an honest "Run
   Analyze to refresh Risk outputs" state rather than fabricating values.
   Whether to persist them is a financial-persistence decision, out of scope
   for Sprint C.
3. **Two Analyze affordances.** The header `Analyze` and the form's
   `Analyze Deal` submit button both exist in C2 (the form needs a submit
   button for Enter-key submission). C3 should decide whether the form's
   button survives the Underwrite redesign.
4. **Deal Context placement.** Placed in Underwrite as analyst-authored input.
   An argument exists for Overview, where its output ("The Play") is read.
   Revisit in C3/C4.
5. **Operating mode as a header control.** Mode is presented as a segmented
   control in the header. If Detailed becomes the dominant path, mode may
   belong in the Underwrite workspace instead. Revisit in C3.
6. **Sidebar collapse.** C2 collapses to an icon rail only by breakpoint.
   A user-controlled collapse toggle is deferred to C5.
