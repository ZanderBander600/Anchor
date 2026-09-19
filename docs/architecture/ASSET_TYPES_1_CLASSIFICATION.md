# Asset Types 1: Controlled Classification and Analyst-Authored Subtypes

Status: **implemented on `feature/asset-types-1-classification`, pending human
acceptance.** Not accepted. Baseline: `main` at `2e6ca8e` (PR #42), schema v13.
Risk tier: Tier 2 (schema, API contract, fingerprint boundary, persistence),
with Tier 3 product UI.

This document is the authority for Asset Types 1. It adds **classification
only**. It adds no type-specific calculation, assumption, KPI, benchmark,
underwriting template or AI behavior, and it changes no financial result.

## 1. Three separate concepts

| Concept | What it is | Where it lives |
| --- | --- | --- |
| **Asset Type** | A controlled classification: one of ten fixed values | `asset_type` on a Deal and a Managed Asset |
| **Asset Subtype** | The analyst's own description, free text | `asset_subtype` beside it |
| **Business Plan / Strategy** | Existing D6 and P7.4 concepts | Unchanged, and never read or written by classification |

A Deal Context (Gate A4) is also unrelated. It is narrative for the AI Analyst.
Classification is never shown to the AI Analyst.

## 2. The vocabulary and the subtype

### 2.1 Controlled Asset Types

| Wire value | Product label |
| --- | --- |
| `multifamily` | Multifamily |
| `office` | Office |
| `industrial` | Industrial |
| `retail` | Retail |
| `hospitality` | Hospitality |
| `self_storage` | Self-Storage |
| `manufactured_housing` | Manufactured Housing |
| `mixed_use` | Mixed-Use |
| `land_development` | Land/Development |
| `other` | Other |

The wire value is the only representation. The database, the API and the
frontend all use it. `anchor.asset_types.AssetType` is the backend authority.
`web/src/assetTypes.ts` declares the same pairs, and
`tests/test_asset_types_1_architecture.py` holds the two files equal.

Only these ten values are accepted. Matching is exact: no case-folding,
trimming or near-match. `"Multifamily"`, `" multifamily"` and `"condo"` are
refused (`invalid_asset_type`). They are never guessed.

### 2.2 Asset Subtype

- Optional for every type except `other`.
- Required for `other`. The product labels the field **Describe the Asset
  Type** and says that it is required (`asset_subtype_required`).
- For every other type the label is **Asset Subtype (optional)**, with the
  examples *Garden apartments*, *Medical office* and *Last-mile warehouse*.
- Free text. It is never matched against a list or mapped to a predefined
  value.
- Leading and trailing whitespace is trimmed. Blank or whitespace-only means
  absent (`null`).
- Otherwise it is stored exactly as the analyst typed it, including
  capitalization and wording.
- Maximum length is **80 characters**, counted as Unicode characters after
  trimming (`asset_subtype_too_long`). That fits a phrase like "Class A
  suburban medical office with ambulatory surgery" and keeps a library row to
  one line.
- One line of text. Control characters, including newlines and tabs, are
  refused (`invalid_asset_subtype`).
- A subtype with no type is refused (`asset_subtype_without_type`). It would be
  a classification nobody chose.

`AssetClassificationError` carries every issue at once, so one request reports
problems with both fields. It deliberately does not subclass `ValueError`, so a
broad `except ValueError` cannot silently swallow it (the D5.5C lesson).

## 3. Deals: Quick, Detailed and Lease-Level

- Every mode carries `asset_type` and `asset_subtype` on the `Deal` contract
  and wire.
- Classification is metadata that applies to every mode, like the Business
  Plan. It is stored once per deal in `deal_asset_classifications`, keyed by
  deal id. It is never stored in a mode's own table.
- **New Deal.** The product requires an Asset Type before a new Deal's first
  Save. A Save without one stops, and then:
  - the header shows the reason;
  - the Underwrite strip opens;
  - the select is marked `aria-invalid`;
  - an alert announces the message;
  - focus moves to the select.
- **Legacy Deal.** A Deal with no classification reads as "Not specified". It
  opens, analyzes and saves normally. Nothing is inferred for it. It gains a
  type only when the analyst chooses one, and the strip starts open to invite
  that choice.
- **Editing.** The Underwrite strip sits above Deal Context on every tab in all
  three modes. It edits the classification. A change marks the Deal dirty, and
  the next Save or Update persists it.
- **Overview.** Overview shows the type and subtype (or "Not specified") above
  the Owner Summary in every mode.
- **Deal Library.**
  - Each row shows the classification on its existing meta line, so rows keep
    their height.
  - The Asset Type filter offers All, every type, and Not specified. It only
    hides rows and writes nothing.
  - A polite status line announces the count.
- **Duplicate** copies the classification exactly. **Delete** removes the
  classification row.

### 3.1 API

`POST /deals` and `PUT /deals/{id}` accept `asset_type` and `asset_subtype` in
every mode. Classification has two explicit compatibility rules:

- **A body with neither key** comes from a client that predates classification:
  - on create it stores "Not specified";
  - on update it **keeps** the stored classification (`KEEP_CLASSIFICATION`).

  So an older client or saved fixture can never erase a classification by
  leaving the keys out.
- **A body that names either key** states the whole classification. The missing
  key reads as `null`, and both are validated together. An explicit
  `asset_type: null` records "Not specified".

A refusal is a structured 422. Each issue carries `code`, `field_id`
(`asset_type` or `asset_subtype`), `category: "classification"` and `message`.
A refused write changes nothing.

For Lease-Level, `_DEAL_WRITE_FIELDS` names the classification keys only for
the `/deals` write routes. `/deals/fingerprint` keeps `_DEAL_FIELDS`, so a
Lease-Level fingerprint body that carries `asset_type` is refused as an unknown
key rather than silently ignored.

## 4. Investments

An Investment may hold several Deals (Units). It has **no classification of its
own**, and none is manufactured.

- **Units panel.** An Asset Type column shows each Unit's own Deal
  classification.
- **Investment Library.** An **Asset Types** column lists the distinct types of
  the Investment's Units:
  - in vocabulary order;
  - with "Not specified" last for an unclassified Unit, or a Unit missing from
    the loaded Deal list;
  - one chip per type, with a "Mixed:" prefix for screen readers when there is
    more than one type.
- **Filter.** The Investment Library filter keeps an Investment when **any** of
  its Units matches. It never chooses one type to stand for the whole
  Investment.
- **Unchanged.** Consolidation, Investment economics, fingerprints and the
  `VisibleInvestment` wire are unchanged. `/investments/{id}/details` carries no
  classification key.

## 5. Managed Assets: a snapshot, and one classification source

- **Snapshot.** When `create_managed_asset` creates a Managed Asset, it copies
  the source Deal's saved `asset_type` and `asset_subtype` into
  `managed_asset_classifications`, in the same transaction.
- **Frozen.** The only SQL that writes this table is that create path's INSERT
  and the owned DELETE. No statement updates it (held by the architecture
  guard). A later Deal edit therefore reclassifies the Deal and leaves the
  asset unchanged, exactly as the frozen acquisition fingerprint is left.
- **Unclassified source.** An unclassified source Deal gives an unclassified
  asset ("Not specified"). Classifying the Deal afterwards does not reach the
  asset.
- **One source.** The hand-typed **Property Type** input is removed from Create
  Managed Asset. The panel instead shows, read-only, the classification that
  will be copied. It also says when the Deal on screen has an unsaved
  classification change that the copy will not include.
- **Retired property type.** On `POST /managed-assets`:
  - `property_type` is retired;
  - a body that still carries it with a value is refused
    (`property_type_retired`, 422), rather than silently dropped or stored as a
    competing classification;
  - `null` is accepted from an older client;
  - a body that tries to state `asset_type` itself is refused as carrying an
    unknown field.
- **Legacy property type.** `managed_assets.property_type` is preserved and
  returned verbatim. It is **legacy text**: typed by hand before Asset Types 1,
  never written now, never a classification, and never mapped onto a type.
  Where an asset has no type, the product shows "Not specified" and, beneath
  it, *Recorded as "…"*. In the asset detail view it appears as "Recorded
  Property Type (legacy)".
- **Where classification appears.** Managed Assets and Monthly Reporting each
  show one **Asset Type** column (Property Type is replaced, not duplicated).
  Each has its own Asset Type filter, including Not specified. The sidebar and
  the asset workspace's meta line and Overview also show it.
- **No financial effect.** Classification changes no monthly result. The AM1
  performance engine takes reports only, and it names no classification.

## 6. Classification is non-economic

- It is in **no fingerprint**: not the Quick, Detailed or Lease-Level financial
  fingerprint, the AI context fingerprint, any Scenario, Strategy, Investment,
  structured or Partnership variant fingerprint, or the Managed Asset's frozen
  acquisition fingerprint. The row converters never pass it to a
  `fingerprint_*` call.
- It is in **no engine input** and **no AI grounding**. No engine, analysis,
  leasing, Business Plan or AI module names it.
- Changing only the classification therefore:
  - leaves `/analyze` output byte-identical;
  - leaves every fingerprint identical;
  - keeps a saved analysis snapshot, AI snapshot and sensitivity snapshots;
  - creates or removes no Scenario, Strategy, Capital Structure or Partnership;
  - invokes no AI;
  - rewrites no other field.

  `tests/test_asset_types_1_deals.py` proves each point in all three modes.

## 7. Persistence, migration and compatibility

- **Schema v14** adds two tables. There is no ALTER, and the DDL of `deals`,
  `detailed_deals`, `lease_level_deals` and `managed_assets` is unchanged byte
  for byte:
  - `deal_asset_classifications (deal_id TEXT PRIMARY KEY, asset_type TEXT NOT NULL, asset_subtype TEXT)`
  - `managed_asset_classifications (managed_asset_id TEXT PRIMARY KEY REFERENCES managed_assets(id), asset_type TEXT NOT NULL, asset_subtype TEXT)`
- **No row means "Not specified".** There is exactly one spelling of
  unclassified, and the migration writes no row. `asset_type` is `NOT NULL`
  because a row exists only for a chosen type. Both columns are typed TEXT, with
  no JSON.
- **Unreadable stored data.** A stored token the vocabulary no longer
  recognises, or a pair the rules refuse, raises `PersistedDealDataError`. It
  is never softened to "Not specified", which would silently erase a choice.
- **Compatibility oracle.** `tests/test_asset_types_1_compatibility_oracle.py`
  builds a real v13 database with `main` at `2e6ca8e` itself (`git archive`,
  objects only). It proves that:
  - the migration adds exactly the two empty tables, alters nothing, rewrites
    no row, and is idempotent;
  - every recorded v13 response replays identically, apart from the two added
    keys, which must read `null`;
  - replaying writes nothing;
  - the legacy `property_type` "Multifamily" is preserved and never mapped;
  - a legacy Deal classified afterwards keeps its analysis snapshot, and its
    existing Managed Asset keeps its own snapshot.
- **Earlier oracles.** Two kinds of earlier guard were updated, and neither was
  loosened:
  - Every guard that asserts an exact added-table set or schema version now
    names the two tables and pins 14: the P7.2, P7.4, P7.6, P7.9 Stage 2 and
    AM1 oracles, the D5.4 and D6.5 migration tests, the D5.8A pre-gate
    database test and the fresh-store checks.
  - Every response oracle (P7.2, P7.4, P7.6, P7.7, P7.8, P7.9 Stage 2, AM1
    and the D6.9 closeout) sets aside **only** `null` classification keys
    absent from the recorded response (`without_unstated_classification`, and
    `_LATER_NULL_KEYS` in D6.9). A legacy record returned classified still
    fails, and the D6.9 self-test proves it.
- **Re-pinned guards.** AM1, P7.9 Stage 2 and D6.5 guards that measured their
  own claims against the working tree are re-pinned to their committed ranges.

## 8. Guards, mutation proofs and exclusions

`tests/test_asset_types_1_architecture.py` holds:

- the production ledger;
- the unchanged financial and AI modules;
- the fingerprint boundary;
- the frozen snapshot;
- vocabulary parity;
- that the two classification modules compute nothing.

The ledger is measured against the working tree while the gate is open. The
next gate re-pins it to the merged range. G37 names the two new frontend
modules (`_ASSET_TYPES_1_WEB`).

`tests/test_asset_types_1_mutation_proofs.py` proves that four weakened
invariants are caught:

- an omission read as "clear";
- a Managed Asset reading the Deal's live classification;
- an unknown stored token softened to "Not specified";
- the fingerprint route owning a classification key.

**Explicit exclusions: later asset-type phases, not this one.**

- Type-specific assumptions, underwriting templates, default inputs or
  validation ranges.
- Type-specific KPIs, benchmarks or market comparables.
- Using classification in any calculation, fingerprint, sensitivity, Decision
  Matrix or consolidation.
- AI Analyst awareness of classification, or AI-suggested classification.
- A subtype vocabulary, subtype suggestions or mapping free text onto types.
- An Investment-level classification.
- Reclassifying an existing Managed Asset.
- Inferring a type for legacy records or legacy `property_type` text.
- Showing the type in the Recent Deals sidebar. The contract permits it but
  does not require it, so it is left out to keep the collapsed rail unchanged.
