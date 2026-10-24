# Curating Polymarket Markets

A Codex skill for curating unresolved Polymarket markets, generating English and Chinese JSON batches, enforcing category quotas and minimum time-to-close, and replacing events that duplicate a historical batch.

用于筛选 Polymarket 未结算市场的 Codex Skill，支持中英文 JSON、分类配额、最短剩余时间，以及与历史批次的跨批去重与替换。

## Included

- Candidate collection from Polymarket
- Exact category-quota checks
- Minimum-days-to-close validation
- English/Chinese batch consistency checks
- Within-batch and historical-batch deduplication
- Replacement auditing and unit tests

## Install in Codex

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo baocheng1108-collab/curating-polymarket-markets \
  --path skills/curating-polymarket-markets
```

Restart Codex after installation so the new skill is discovered.

安装完成后重启 Codex，使新 Skill 生效。

## Verify

```bash
python3 -m unittest discover \
  -s ~/.codex/skills/curating-polymarket-markets/tests \
  -v
```

## Repository layout

```text
skills/curating-polymarket-markets/
├── SKILL.md
├── agents/openai.yaml
├── references/
├── scripts/
└── tests/
```

## Typical request

> Use curating-polymarket-markets to produce 50 unresolved markets closing more than 50 days from now, using the requested category quotas. Deduplicate them against my historical batch and replace every duplicate with a new event.

> 使用 curating-polymarket-markets 生成 50 条距离截止时间超过 50 天的未结算市场，按指定分类配额输出；与历史批次去重，并用新事件替换所有重复项。
