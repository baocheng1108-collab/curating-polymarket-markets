#!/usr/bin/env python3
"""Audit bilingual Polymarket batches without modifying source files."""

import argparse
import datetime as dt
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


EXACT_KEYS = [
    "title",
    "category",
    "region",
    "heatScore",
    "sentiment",
    "isMarketAptable",
    "marketSuggestion",
    "description",
    "options",
    "marketEndTime",
    "resolutionTime",
    "rules",
]
DEFAULT_CATEGORY_LABELS = {
    "Crypto": "加密货币",
    "Politics": "政治",
    "Economy": "经济",
    "Sports": "体育",
    "Technology": "科技",
    "Weather": "天气",
    "Culture & Entertainment": "文化与娱乐",
    "Other": "其他",
}
EVENT_URL_RE = re.compile(
    r"https?://(?:www\.)?polymarket\.com/(?:zh/)?event/([a-z0-9-]+)",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s)\]]+")


def extract_identity(item):
    event_slug = item.get("eventSlug")
    if isinstance(event_slug, str) and event_slug.strip():
        return ("eventSlug", event_slug.strip().lower())
    rules = item.get("rules")
    if isinstance(rules, str):
        match = EVENT_URL_RE.search(rules)
        if match:
            return ("eventSlug", match.group(1).lower())
    for field in ("sourceMarketId", "marketId"):
        value = item.get(field)
        if value is not None and str(value).strip():
            return ("marketId", str(value).strip())
    return None


def normalize_title(value):
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in normalized if character.isalnum())


def extract_urls(item):
    rules = item.get("rules")
    return URL_RE.findall(rules) if isinstance(rules, str) else []


def is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def option_values(item):
    if not isinstance(item, dict) or not isinstance(item.get("options"), list):
        return None
    values = []
    for option in item["options"]:
        if not isinstance(option, dict):
            return None
        values.append(option.get("value"))
    return values


def audit_batches(english, chinese, references, quotas, min_end_ms, category_labels):
    errors = []
    warnings = []
    identities = []

    def add_error(code, message, index=None, category=None, **extra):
        finding = {"code": code, "message": message}
        if index is not None:
            finding["index"] = index
        if category is not None:
            finding["category"] = category
        finding.update(extra)
        errors.append(finding)

    def add_warning(code, message, **extra):
        finding = {"code": code, "message": message}
        finding.update(extra)
        warnings.append(finding)

    def validate_market(item, index, locale):
        category = (
            item.get("category")
            if isinstance(item, dict) and isinstance(item.get("category"), str)
            else None
        )
        if not isinstance(item, dict):
            add_error(
                "schema_type",
                f"{locale} market item must be an object",
                index=index,
                category=category,
                locale=locale,
            )
            return False
        if list(item.keys()) != EXACT_KEYS:
            add_error(
                "schema_keys",
                f"{locale} market object keys or key order do not match the contract",
                index=index,
                category=category,
                locale=locale,
                expected=EXACT_KEYS,
                actual=list(item.keys()),
            )
        for field in ("title", "category", "region", "marketSuggestion", "description", "rules"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                add_error(
                    "schema_type",
                    f"{locale} {field} must be a non-empty string",
                    index=index,
                    category=category,
                    locale=locale,
                    field=field,
                )
        for field in ("heatScore", "sentiment"):
            value = item.get(field)
            if not is_integer(value) or not 0 <= value <= 100:
                add_error(
                    "schema_type",
                    f"{locale} {field} must be an integer from 0 through 100",
                    index=index,
                    category=category,
                    locale=locale,
                    field=field,
                )
        if not isinstance(item.get("isMarketAptable"), bool):
            add_error(
                "schema_type",
                f"{locale} isMarketAptable must be boolean",
                index=index,
                category=category,
                locale=locale,
                field="isMarketAptable",
            )
        options = item.get("options")
        expected_labels = ["Yes", "No"] if locale == "English" else ["是", "否"]
        options_valid = (
            isinstance(options, list)
            and len(options) == 2
            and all(
                isinstance(option, dict)
                and list(option.keys()) == ["value", "label"]
                for option in options
            )
        )
        if options_valid:
            values = [option["value"] for option in options]
            labels = [option["label"] for option in options]
            options_valid = values == ["Yes", "No"] and labels == expected_labels
        if not options_valid:
            add_error(
                "schema_options",
                f"{locale} options must contain exactly labeled Yes and No objects",
                index=index,
                category=category,
                locale=locale,
                field="options",
            )
        end_time = item.get("marketEndTime")
        resolution_time = item.get("resolutionTime")
        if not is_integer(end_time) or len(str(end_time)) != 13:
            add_error(
                "schema_timestamp",
                f"{locale} marketEndTime must be a 13-digit integer",
                index=index,
                category=category,
                locale=locale,
                field="marketEndTime",
            )
        if not is_integer(resolution_time) or len(str(resolution_time)) != 13:
            add_error(
                "schema_timestamp",
                f"{locale} resolutionTime must be a 13-digit integer",
                index=index,
                category=category,
                locale=locale,
                field="resolutionTime",
            )
        if is_integer(end_time) and is_integer(resolution_time):
            if resolution_time - end_time != 86_400_000:
                add_error(
                    "resolution_offset",
                    f"{locale} resolutionTime must equal marketEndTime plus 86,400,000",
                    index=index,
                    category=category,
                    locale=locale,
                )
            if min_end_ms is not None and end_time <= min_end_ms:
                add_error(
                    "deadline_too_soon",
                    f"{locale} marketEndTime must be strictly later than the configured cutoff",
                    index=index,
                    category=category,
                    locale=locale,
                    marketEndTime=end_time,
                    cutoff=min_end_ms,
                )
        return True

    if not isinstance(english, list):
        raise TypeError("English batch must be a JSON array")
    if not isinstance(chinese, list):
        raise TypeError("Chinese batch must be a JSON array")
    if len(english) != len(chinese):
        add_error(
            "bilingual_length",
            "English and Chinese arrays must have identical lengths",
            englishCount=len(english),
            chineseCount=len(chinese),
        )

    category_counts = Counter()
    reference_identities = set()
    for reference_index, reference in enumerate(references):
        if not isinstance(reference, list):
            raise TypeError(f"Reference batch {reference_index} must be a JSON array")
        for item_index, item in enumerate(reference):
            identity = extract_identity(item) if isinstance(item, dict) else None
            if identity is None:
                add_error(
                    "reference_missing_identity",
                    "A historical item has no stable Polymarket identity",
                    reference=reference_index,
                    referenceItemIndex=item_index,
                )
            else:
                reference_identities.add(identity)
                if identity[0] == "marketId":
                    add_error(
                        "reference_incomparable_identity",
                        "A market-ID-only historical item cannot be compared with final event slugs",
                        reference=reference_index,
                        referenceItemIndex=item_index,
                        identity={"type": identity[0], "value": identity[1]},
                    )

    seen_identities = {}
    for index, item in enumerate(english):
        if not validate_market(item, index, "English"):
            continue
        category = item.get("category") if isinstance(item.get("category"), str) else None
        if category is not None:
            category_counts[category] += 1

        identity = extract_identity(item)
        if identity is None:
            add_error(
                "missing_identity",
                "Market has no event slug or explicit source market ID",
                index=index,
                category=category,
            )
        else:
            identities.append({"index": index, "type": identity[0], "value": identity[1]})
            if identity in seen_identities:
                add_error(
                    "internal_duplicate",
                    "Stable Polymarket identity repeats inside the target batch",
                    index=index,
                    category=category,
                    identity={"type": identity[0], "value": identity[1]},
                    firstIndex=seen_identities[identity],
                )
            else:
                seen_identities[identity] = index
            if identity in reference_identities:
                add_error(
                    "historical_overlap",
                    "Stable Polymarket identity already exists in a historical batch",
                    index=index,
                    category=category,
                    identity={"type": identity[0], "value": identity[1]},
                )

    for category, expected_count in quotas.items():
        actual_count = category_counts.get(category, 0)
        if actual_count != expected_count:
            add_error(
                "quota_mismatch",
                f"Category {category} has {actual_count} items; expected {expected_count}",
                category=category,
                expected=expected_count,
                actual=actual_count,
            )
    unrequested = sorted(set(category_counts) - set(quotas)) if quotas else []
    for category in unrequested:
        add_error(
            "unexpected_category",
            f"Category {category} is not present in the requested quotas",
            category=category,
            actual=category_counts[category],
        )

    invariant_fields = [
        "heatScore",
        "sentiment",
        "isMarketAptable",
        "marketEndTime",
        "resolutionTime",
    ]
    for index, item in enumerate(chinese):
        validate_market(item, index, "Chinese")

    for index in range(min(len(english), len(chinese))):
        en_item = english[index]
        zh_item = chinese[index]
        if not isinstance(en_item, dict) or not isinstance(zh_item, dict):
            add_error("bilingual_invariant", "Paired items must be objects", index=index)
            continue
        category = en_item.get("category") if isinstance(en_item.get("category"), str) else None
        expected_label = category_labels.get(category) if category is not None else None
        if category is not None and expected_label is None:
            add_error(
                "category_label_missing",
                f"No Chinese label mapping is configured for {category}",
                index=index,
                category=category,
            )
        elif expected_label is not None and zh_item.get("category") != expected_label:
            add_error(
                "bilingual_invariant",
                "Chinese category does not match the configured label",
                index=index,
                category=category,
                field="category",
            )
        for field in invariant_fields:
            if en_item.get(field) != zh_item.get(field):
                add_error(
                    "bilingual_invariant",
                    f"English and Chinese {field} values differ",
                    index=index,
                    category=category,
                    field=field,
                )
        en_values = option_values(en_item)
        zh_values = option_values(zh_item)
        if en_values != zh_values:
            add_error(
                "bilingual_invariant",
                "English and Chinese options.value differ",
                index=index,
                category=category,
                field="options.value",
            )
        if extract_urls(en_item) != extract_urls(zh_item):
            add_error(
                "bilingual_invariant",
                "English and Chinese rules URLs differ",
                index=index,
                category=category,
                field="rules.urls",
            )
        if extract_identity(en_item) != extract_identity(zh_item):
            add_error(
                "bilingual_invariant",
                "English and Chinese stable identities differ",
                index=index,
                category=category,
                field="identity",
            )

    for left in range(len(english)):
        if not isinstance(english[left], dict):
            continue
        left_identity = extract_identity(english[left])
        left_raw_title = english[left].get("title")
        if not isinstance(left_raw_title, str):
            continue
        left_title = normalize_title(left_raw_title)
        if not left_title:
            continue
        for right in range(left + 1, len(english)):
            if not isinstance(english[right], dict):
                continue
            right_identity = extract_identity(english[right])
            right_raw_title = english[right].get("title")
            if not isinstance(right_raw_title, str):
                continue
            right_title = normalize_title(right_raw_title)
            if not right_title or left_identity == right_identity:
                continue
            similarity = difflib.SequenceMatcher(None, left_title, right_title).ratio()
            if similarity >= 0.92:
                add_warning(
                    "similar_title",
                    "Titles are highly similar but stable identities differ",
                    indexes=[left, right],
                    similarity=round(similarity, 3),
                )

    replacement_reasons = defaultdict(list)
    replacement_categories = {}
    for error in errors:
        index = error.get("index")
        if isinstance(index, int) and 0 <= index < len(english):
            item = english[index]
            fallback_category = item.get("category") if isinstance(item, dict) else None
            replacement_categories[index] = error.get("category") or fallback_category
            if error["code"] not in replacement_reasons[index]:
                replacement_reasons[index].append(error["code"])
    replacements = [
        {
            "index": index,
            "category": replacement_categories[index],
            "reasons": replacement_reasons[index],
        }
        for index in sorted(replacement_reasons)
    ]

    return {
        "summary": {
            "targetCount": len(english),
            "referenceCount": sum(len(reference) for reference in references),
            "quotaCounts": dict(category_counts),
            "errorCount": len(errors),
            "warningCount": len(warnings),
        },
        "identities": identities,
        "errors": errors,
        "warnings": warnings,
        "replacementRequirements": replacements,
    }


def parse_iso(value):
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def parse_mapping(values, value_parser, option_name):
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option_name} must use NAME=VALUE, got {value!r}")
        name, raw_value = value.rsplit("=", 1)
        if not name.strip() or not raw_value.strip():
            raise ValueError(f"{option_name} must use non-empty NAME=VALUE")
        result[name.strip()] = value_parser(raw_value.strip())
    return result


def positive_integer(value):
    parsed = int(value)
    if parsed < 1:
        raise ValueError("quota counts must be positive")
    return parsed


def read_array(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a bare JSON array")
    return payload


def paths_alias(first, second):
    try:
        return first.samefile(second)
    except (FileNotFoundError, OSError):
        return first.resolve(strict=False) == second.resolve(strict=False)


def validate_report_path(report_path, input_paths):
    for input_path in input_paths:
        if paths_alias(report_path, input_path):
            raise ValueError(f"--report must not overwrite input file: {input_path}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Audit bilingual Polymarket batches and historical overlap."
    )
    parser.add_argument("--english", type=Path, required=True)
    parser.add_argument("--chinese", type=Path, required=True)
    parser.add_argument("--reference", type=Path, action="append", default=[])
    parser.add_argument("--quota", action="append", default=[], metavar="CATEGORY=COUNT")
    parser.add_argument(
        "--category-label", action="append", default=[], metavar="ENGLISH=CHINESE"
    )
    parser.add_argument("--min-days", type=int, default=0)
    parser.add_argument(
        "--as-of",
        default=dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.min_days < 0:
            raise ValueError("--min-days must be zero or greater")
        validate_report_path(
            args.report, [args.english, args.chinese, *args.reference]
        )
        quotas = parse_mapping(args.quota, positive_integer, "--quota")
        labels = dict(DEFAULT_CATEGORY_LABELS)
        labels.update(parse_mapping(args.category_label, str, "--category-label"))
        as_of = parse_iso(args.as_of)
        cutoff = int((as_of + dt.timedelta(days=args.min_days)).timestamp() * 1000)
        report = audit_batches(
            read_array(args.english),
            read_array(args.chinese),
            [read_array(path) for path in args.reference],
            quotas,
            cutoff,
            labels,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Audit complete: {report['summary']['errorCount']} errors, "
        f"{report['summary']['warningCount']} warnings",
        file=sys.stderr,
    )
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
