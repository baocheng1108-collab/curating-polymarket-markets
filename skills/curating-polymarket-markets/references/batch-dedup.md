# Batch Deduplication and Replacement

Use this reference whenever a new English/Chinese batch must not repeat events from historical JSON files.

## Identity contract

The audit uses this precedence:

1. Polymarket `eventSlug`, either from an intermediate `eventSlug` field or a `polymarket.com/event/<slug>` / `polymarket.com/zh/event/<slug>` URL in `rules`.
2. Explicit intermediate `sourceMarketId` or `marketId`.
3. Missing stable identity, which blocks final delivery.

Final objects cannot contain source-ID metadata, so every final `rules` value must preserve a Polymarket event link. Two different market questions under one event slug count as one event for batch diversity.

A market-ID fallback is comparable only when both records use the same intermediate identity namespace. A market-ID-only historical record cannot prove disjointness from final event slugs, so the audit reports `reference_incomparable_identity` until an event slug or an explicit crosswalk is supplied.

Normalized-title similarity is diagnostic only. A `similar_title` warning asks for human review but never authorizes automatic deletion when stable identities differ.

## Audit command

```bash
python3 scripts/audit_batches.py \
  --english <english.json> \
  --chinese <chinese.json> \
  --reference <historical-a.json> \
  --reference <historical-b.json> \
  --quota '<English Category>=<count>' \
  --category-label '<Custom English Category>=<中文分类>' \
  --min-days <days> \
  --as-of <ISO-8601> \
  --report <audit-report.json>
```

`--reference`, `--quota`, and `--category-label` are repeatable. The eight standard category labels need no `--category-label`. The command reads all target and reference inputs without modifying them, writes only `--report`, and exits `1` when blocking errors exist.

## Report semantics

- `summary`: target/reference counts, observed category counts, and finding totals.
- `identities`: stable identity selected for each target index.
- `errors`: blocking schema, quota, horizon, bilingual, identity, or overlap findings.
- `warnings`: non-blocking review findings such as highly similar titles with different identities.
- `replacementRequirements`: target indexes that must be rebuilt, their English category, and reason codes.

Batch-level quota errors can lack an index. Correct them by adding or removing entries only through the requested curation workflow, then regenerate both locales.

## Replacement loop

1. Build a forbidden set from all target and historical stable identities.
2. For each reported index, keep its existing English category and array position.
3. Choose a reserve candidate with a stable identity outside the forbidden set.
4. Confirm `active=true`, `closed=false`, accepting orders, exact `Yes`/`No`, and `marketEndTime > as-of + min-days`.
5. Rebuild the English object from the source, then rebuild the Chinese object at the same index while preserving all invariant values and URLs.
6. Add the new identity to the forbidden set and remove the replaced target identity only when no other target uses it.
7. Rerun the complete audit. Repeat until it exits `0` and only reviewed warnings remain.

Never edit, reorder, translate, or overwrite a historical reference file.
