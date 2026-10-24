import datetime as dt
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "fetch_candidates.py"
SPEC = importlib.util.spec_from_file_location("fetch_candidates", SCRIPT_PATH)
fetch_candidates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch_candidates)


def make_market(market_id, question, end_date, volume=100):
    return {
        "id": market_id,
        "slug": f"market-{market_id}",
        "question": question,
        "description": f"Description for {question}",
        "endDate": end_date,
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.6", "0.4"]),
        "volume24hr": volume,
        "liquidity": 50,
    }


def make_event(slug, markets):
    return {
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "markets": markets,
        "tags": [],
    }


class FetchCandidatesTests(unittest.TestCase):
    def write_snapshot(self, directory, category, events):
        (directory / f"{category}.json").write_text(
            json.dumps(events), encoding="utf-8"
        )

    def test_custom_categories_and_quotas(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            self.write_snapshot(
                directory,
                "crypto",
                [
                    make_event(
                        "crypto-event",
                        [
                            make_market("1", "Will token A launch?", "2027-02-01T00:00:00Z", 200),
                            make_market("2", "Will token B launch?", "2027-03-01T00:00:00Z", 100),
                        ],
                    )
                ],
            )
            output = directory / "candidates.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input-dir",
                    str(directory),
                    "--category",
                    "crypto=crypto",
                    "--quota",
                    "crypto=2",
                    "--min-days",
                    "50",
                    "--as-of",
                    "2026-10-24T00:00:00Z",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(list(payload["categories"]), ["crypto"])
            self.assertEqual(len(payload["categories"]["crypto"]), 2)
            self.assertEqual(payload["minDays"], 50)
            self.assertEqual(payload["asOf"], "2026-10-24T00:00:00Z")

    def test_min_days_is_strict(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            self.write_snapshot(
                directory,
                "crypto",
                [
                    make_event("before", [make_market("1", "Before?", "2026-12-12T00:00:00Z")]),
                    make_event("equal", [make_market("2", "Equal?", "2026-12-13T00:00:00Z")]),
                    make_event("after", [make_market("3", "After?", "2026-12-14T00:00:00Z")]),
                ],
            )

            payload = fetch_candidates.build_payload(
                directory,
                {"crypto": "crypto"},
                {"crypto": 1},
                100,
                50,
                dt.datetime(2026, 10, 24, tzinfo=dt.timezone.utc),
            )

            self.assertEqual(
                [item["sourceMarketId"] for item in payload["categories"]["crypto"]],
                ["3"],
            )

    def test_as_of_makes_filter_deterministic(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            self.write_snapshot(
                directory,
                "crypto",
                [make_event("dated", [make_market("1", "Dated?", "2027-01-01T00:00:00Z")])],
            )

            payload = fetch_candidates.build_payload(
                directory,
                {"crypto": "crypto"},
                {"crypto": 1},
                100,
                30,
                dt.datetime(2026, 10, 24, tzinfo=dt.timezone.utc),
            )
            self.assertEqual(len(payload["categories"]["crypto"]), 1)

            with self.assertRaisesRegex(RuntimeError, "Only 0 valid crypto candidates"):
                fetch_candidates.build_payload(
                    directory,
                    {"crypto": "crypto"},
                    {"crypto": 1},
                    100,
                    30,
                    dt.datetime(2026, 12, 15, tzinfo=dt.timezone.utc),
                )

    def test_legacy_defaults_remain_available(self):
        self.assertEqual(
            fetch_candidates.parse_category_specs([]),
            {
                "politics": "politics",
                "economy": "economy",
                "sports": "sports",
                "technology": "tech",
            },
        )

    def test_omitting_min_days_keeps_past_active_candidates(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            self.write_snapshot(
                directory,
                "crypto",
                [make_event("past", [make_market("1", "Past but active?", "2025-01-01T00:00:00Z")])],
            )
            output = directory / "candidates.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input-dir",
                    str(directory),
                    "--category",
                    "crypto=crypto",
                    "--quota",
                    "crypto=1",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["categories"]["crypto"][0]["sourceMarketId"], "1")

    def test_malformed_specs_fail_cleanly(self):
        with self.assertRaisesRegex(ValueError, "NAME=TAG"):
            fetch_candidates.parse_category_specs(["crypto"])
        with self.assertRaisesRegex(ValueError, "category name"):
            fetch_candidates.parse_category_specs(["culture entertainment=pop-culture"])
        with self.assertRaisesRegex(ValueError, "unknown category"):
            fetch_candidates.parse_quota_specs(
                ["weather=2"], {"crypto": "crypto"}, 20
            )
        with self.assertRaisesRegex(ValueError, "positive"):
            fetch_candidates.parse_quota_specs(
                ["crypto=0"], {"crypto": "crypto"}, 20
            )


if __name__ == "__main__":
    unittest.main()
