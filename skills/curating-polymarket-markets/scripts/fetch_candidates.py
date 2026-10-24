#!/usr/bin/env python3
"""Fetch and normalize unresolved binary Polymarket candidate markets."""

import argparse
import bisect
import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


API_URL = "https://gamma-api.polymarket.com/events"
DEFAULT_CATEGORIES = {
    "politics": "politics",
    "economy": "economy",
    "sports": "sports",
    "technology": "tech",
}
CATEGORY_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def parse_category_specs(values):
    if not values:
        return dict(DEFAULT_CATEGORIES)
    categories = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--category must use NAME=TAG, got {value!r}")
        name, tag = value.split("=", 1)
        if not CATEGORY_NAME_RE.fullmatch(name):
            raise ValueError(
                "category name must contain only lowercase letters, numbers, "
                f"hyphens, or underscores: {name!r}"
            )
        if not tag.strip():
            raise ValueError(f"category tag must not be empty for {name!r}")
        if name in categories:
            raise ValueError(f"duplicate category: {name}")
        categories[name] = tag.strip()
    return categories


def parse_quota_specs(values, categories, default_count):
    if default_count < 1:
        raise ValueError("--per-category must be positive")
    quotas = {category: default_count for category in categories}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--quota must use NAME=COUNT, got {value!r}")
        name, raw_count = value.split("=", 1)
        if name not in categories:
            raise ValueError(f"quota references unknown category: {name}")
        try:
            count = int(raw_count)
        except ValueError as exc:
            raise ValueError(f"quota for {name} must be an integer") from exc
        if count < 1:
            raise ValueError(f"quota for {name} must be positive")
        quotas[name] = count
    return quotas


def parse_as_of(value):
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"--as-of must be ISO 8601, got {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def format_utc(value):
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_json_array(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def iso_to_millis(value):
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp() * 1000)


def fetch_events(tag_slug, limit, end_date_min=None):
    params = {
        "tag_slug": tag_slug,
        "active": "true",
        "closed": "false",
        "order": "volume24hr",
        "ascending": "false",
        "limit": str(limit),
    }
    if end_date_min is not None:
        params["end_date_min"] = format_utc(end_date_min)
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"User-Agent": "Codex-Polymarket-Skill/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def read_events(input_dir, category):
    candidates = [input_dir / f"{category}.json"]
    if category == "technology":
        candidates.append(input_dir / "tech.json")
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    names = ", ".join(path.name for path in candidates)
    raise FileNotFoundError(f"No snapshot for {category}; expected one of: {names}")


def flatten_candidates(events, category, min_end_ms=None):
    candidates = []
    seen = set()
    for event in events:
        for market in event.get("markets") or []:
            outcomes = parse_json_array(market.get("outcomes"))
            prices = parse_json_array(market.get("outcomePrices"))
            end_date = market.get("endDate") or event.get("endDate")
            end_ms = iso_to_millis(end_date)
            identifier = str(market.get("id") or market.get("slug") or "")
            if not identifier or identifier in seen:
                continue
            if not market.get("active") or market.get("closed") is not False:
                continue
            if market.get("acceptingOrders") is False:
                continue
            if outcomes != ["Yes", "No"] or len(prices) != 2:
                continue
            if not market.get("question") or not market.get("description") or end_ms is None:
                continue
            if min_end_ms is not None and end_ms <= min_end_ms:
                continue
            try:
                numeric_prices = [float(price) for price in prices]
            except (TypeError, ValueError):
                continue

            seen.add(identifier)
            event_slug = event.get("slug") or ""
            candidates.append(
                {
                    "sourceMarketId": identifier,
                    "category": category,
                    "title": market["question"],
                    "eventTitle": event.get("title"),
                    "eventSlug": event_slug,
                    "marketSlug": market.get("slug"),
                    "sourceUrl": f"https://polymarket.com/zh/event/{event_slug}",
                    "active": True,
                    "closed": False,
                    "acceptingOrders": market.get("acceptingOrders") is not False,
                    "outcomes": outcomes,
                    "outcomePrices": numeric_prices,
                    "volume24hr": float(market.get("volume24hr") or 0),
                    "liquidity": float(market.get("liquidity") or 0),
                    "sentiment": max(0, min(100, round(numeric_prices[0] * 100))),
                    "isMarketAptable": True,
                    "marketEndTime": end_ms,
                    "resolutionTime": end_ms + 86_400_000,
                    "sourceDescription": market.get("description"),
                    "resolutionSource": market.get("resolutionSource")
                    or event.get("resolutionSource")
                    or "",
                    "tags": [tag.get("slug") for tag in event.get("tags") or [] if tag.get("slug")],
                }
            )
    return candidates


def add_heat_scores(candidates):
    volumes = sorted(item["volume24hr"] for item in candidates)
    total = len(volumes)
    for item in candidates:
        rank = bisect.bisect_right(volumes, item["volume24hr"])
        item["heatScore"] = round(rank / total * 100) if total else 0


def build_payload(input_dir, category_tags, quotas, fetch_limit, min_days, as_of):
    if fetch_limit < 1:
        raise ValueError("--fetch-limit must be positive")
    if min_days is not None and min_days < 0:
        raise ValueError("--min-days must be zero or greater")
    cutoff = as_of + dt.timedelta(days=min_days) if min_days is not None else None
    cutoff_ms = int(cutoff.timestamp() * 1000) if cutoff is not None else None
    payload = {
        "source": API_URL,
        "snapshotTime": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "asOf": format_utc(as_of),
        "minDays": min_days,
        "deadlineAfter": format_utc(cutoff) if cutoff is not None else None,
        "categories": {},
    }
    for category, tag_slug in category_tags.items():
        events = (
            read_events(input_dir, category)
            if input_dir is not None
            else fetch_events(tag_slug, fetch_limit, cutoff)
        )
        candidates = flatten_candidates(events, category, cutoff_ms)
        add_heat_scores(candidates)
        candidates.sort(
            key=lambda item: (
                -item["volume24hr"],
                -item["liquidity"],
                item["sourceMarketId"],
            )
        )
        requested = quotas[category]
        if len(candidates) < requested:
            raise RuntimeError(
                f"Only {len(candidates)} valid {category} candidates; "
                f"requested {requested}. Increase --fetch-limit or inspect the source."
            )
        payload["categories"][category] = candidates[:requested]
    return payload


def build_parser():
    parser = argparse.ArgumentParser(
        description="Fetch unresolved binary Polymarket candidates for editorial curation."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="Read category event snapshots instead of calling the live Gamma API.",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        metavar="NAME=TAG",
        help="Configure a category and Polymarket tag; repeat for multiple categories.",
    )
    parser.add_argument(
        "--quota",
        action="append",
        default=[],
        metavar="NAME=COUNT",
        help="Override the candidate count for a configured category.",
    )
    parser.add_argument("--per-category", type=int, default=20)
    parser.add_argument("--fetch-limit", type=int, default=100)
    parser.add_argument(
        "--min-days",
        type=int,
        default=None,
        help="Require end times strictly later than as-of plus this many days.",
    )
    parser.add_argument(
        "--as-of",
        help="ISO 8601 reference time; defaults to the current UTC time.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        categories = parse_category_specs(args.category)
        quotas = parse_quota_specs(args.quota, categories, args.per_category)
        as_of = parse_as_of(args.as_of)
        payload = build_payload(
            args.input_dir,
            categories,
            quotas,
            args.fetch_limit,
            args.min_days,
            as_of,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote candidate pool to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
