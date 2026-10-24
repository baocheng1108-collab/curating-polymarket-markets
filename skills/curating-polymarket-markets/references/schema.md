# Polymarket JSON Contract

Use this contract when the user has not supplied a newer schema. Each final file is a bare array of market objects. Do not add a wrapper, schema version, source ID, source URL field, probability field, or commentary inside the JSON.

## Exact object shape

```json
{
  "title": "Will Example happen?",
  "category": "Politics",
  "region": "United States",
  "heatScore": 95,
  "sentiment": 72,
  "isMarketAptable": true,
  "marketSuggestion": "Will Example happen?",
  "description": "A concise neutral summary.",
  "options": [
    {"value": "Yes", "label": "Yes"},
    {"value": "No", "label": "No"}
  ],
  "marketEndTime": 1798675200000,
  "resolutionTime": 1798761600000,
  "rules": "Paraphrased criteria with [Polymarket](https://polymarket.com/event/example) and a [primary source](https://example.com)."
}
```

The object has exactly these keys in this order. Preserve the user-established spelling `isMarketAptable`.

## Category values

Default English and Chinese labels are:

| English | Chinese |
|---|---|
| `Crypto` | `加密货币` |
| `Politics` | `政治` |
| `Economy` | `经济` |
| `Sports` | `体育` |
| `Technology` | `科技` |
| `Weather` | `天气` |
| `Culture & Entertainment` | `文化与娱乐` |
| `Other` | `其他` |

User-supplied categories override this list. For each custom category, pass its localized value to the audit with `--category-label 'English=中文'`.

## Field derivation

| Field | Rule |
|---|---|
| `title` | Market `question`, not the parent event title. |
| `category` | Requested semantic category; tags are candidate-discovery hints only. |
| `region` | Geographic scope of the outcome; use `Global`/`全球` when no single region dominates. |
| `heatScore` | Integer 0–100: inclusive percentile of `volume24hr` within the fetched category. |
| `sentiment` | Integer 0–100: current Yes `outcomePrice × 100`, rounded. |
| `isMarketAptable` | `true` only when active, unresolved, accepting orders, and exactly binary. |
| `marketSuggestion` | Same localized question as `title` unless the user asks for rewriting. |
| `description` | Two or three neutral sentences summarizing the prediction and material uncertainty. |
| `options.value` | Stable machine values `Yes` and `No` in every locale. |
| `options.label` | `Yes`/`No` in English; `是`/`否` in Chinese. |
| `marketEndTime` | Gamma `endDate` converted to a 13-digit Unix millisecond integer. |
| `resolutionTime` | Default: `marketEndTime + 86_400_000`; disclose that this is an operational estimate. |
| `rules` | Objective Yes/No criteria, exceptions, one Polymarket event link for identity, and named settlement sources. Use identical URLs in both locales. |

## Bilingual invariants

Translate `title`, `category`, `region`, `marketSuggestion`, `description`, `options.label`, and prose in `rules`. Keep field names, array order, `options.value`, booleans, scores, timestamps, and every URL identical to English.

## Final checks

- Exact requested total and category quotas.
- Unique stable identities inside the target and no identity in any reference batch.
- Every source remains active, unresolved, accepting orders, binary, and strictly beyond the configured cutoff.
- Scores are integers from 0 through 100.
- Timestamps are 13-digit integers and the default resolution offset is `86_400_000`.
- English and Chinese arrays preserve all bilingual invariants.
- `audit_batches.py` exits `0`; title-similarity warnings have been reviewed.
- JSON parses without comments or trailing commas.
