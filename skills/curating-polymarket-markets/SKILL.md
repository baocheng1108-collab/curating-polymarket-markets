---
name: curating-polymarket-markets
description: Use when a user asks to curate unresolved Polymarket markets, enforce category quotas or future-deadline horizons, produce synchronized English and Chinese JSON, or exclude events found in historical batches.
---

# Curating Polymarket Markets

## Overview

Build a current, auditable set of unresolved binary Polymarket questions. Use deterministic scripts for source fields and validation; use editorial judgment only for semantic classification, regions, summaries, translations, and rule paraphrases.

## Workflow

1. Read [references/schema.md](references/schema.md). If any existing or historical batch must be excluded, also read [references/batch-dedup.md](references/batch-dedup.md).
2. Record the requested total, category quotas, minimum remaining days, reference files, output paths, and an explicit `as-of` time. Never hardcode a previous request's values.
3. Fetch a reserve candidate pool. Repeat `--category` and `--quota` for every requested category; make each candidate quota larger than its final quota:

   ```bash
   python3 scripts/fetch_candidates.py \
     --category <key>=<polymarket-tag> \
     --quota <key>=<candidate-count> \
     --min-days <days> \
     --as-of <ISO-8601> \
     --output <candidates.json>
   ```

   For offline snapshots, add `--input-dir <directory>` containing `<key>.json`. With no `--category`, the legacy politics, economy, sports, and technology defaults remain available.
4. Curate market questions, not parent event titles. Reclassify by subject, keep one question per event, and exclude every identity already present in references. Prefer high category-relative heat, adequate liquidity, objective rules, and an identifiable primary settlement source.
5. Write English first. Translate display text only; preserve order, numbers, booleans, timestamps, URLs, and `options.value` in Chinese.
6. Audit the finished pair. Repeat `--reference` and final `--quota` values as needed:

   ```bash
   python3 scripts/audit_batches.py \
     --english <english.json> \
     --chinese <chinese.json> \
     --reference <historical.json> \
     --quota '<English Category>=<count>' \
     --min-days <days> \
     --as-of <ISO-8601> \
     --report <audit-report.json>
   ```

7. For every `replacementRequirements` entry, replace that index with a new event from the same category, update English and Chinese together, and rerun the audit until it exits `0`.
8. Immediately before delivery, refresh selected sources and replace anything no longer active, unresolved, binary, accepting orders, or beyond the deadline cutoff. Never modify reference files.

## Selection Rules

- `active=true`, `closed=false`, accepting orders, exactly `Yes`/`No`.
- `marketEndTime` must be strictly later than `as-of + min-days`.
- Stable identity is Polymarket event slug first, explicit intermediate market ID second.
- Similar normalized titles are review warnings only; never auto-delete solely on fuzzy similarity.
- A past end date does not itself prove settlement, but it cannot satisfy a positive future horizon.

## Common Mistakes

- Selecting several outcomes from one multi-market event.
- Treating tag labels as final semantic categories.
- Translating `options.value` or changing URLs between locales.
- Replacing only one language file or changing the requested category distribution.
- Adding IDs or metadata to the final schema instead of keeping them in candidate and audit artifacts.
