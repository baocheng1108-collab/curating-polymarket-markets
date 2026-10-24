import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "audit_batches.py"
KEYS = [
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
CATEGORY_LABELS = {"Crypto": "加密货币", "Politics": "政治"}


def load_audit():
    if not SCRIPT_PATH.exists():
        raise AssertionError("audit_batches.py is missing")
    spec = importlib.util.spec_from_file_location("audit_batches", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def market(title, category, slug, end_ms=1800000000000, language="en"):
    is_chinese = language == "zh"
    category_value = CATEGORY_LABELS.get(category, category) if is_chinese else category
    values = {
        "title": f"中文：{title}" if is_chinese else title,
        "category": category_value,
        "region": "全球" if is_chinese else "Global",
        "heatScore": 80,
        "sentiment": 55,
        "isMarketAptable": True,
        "marketSuggestion": f"中文：{title}" if is_chinese else title,
        "description": "中文说明。" if is_chinese else "A neutral description.",
        "options": [
            {"value": "Yes", "label": "是" if is_chinese else "Yes"},
            {"value": "No", "label": "否" if is_chinese else "No"},
        ],
        "marketEndTime": end_ms,
        "resolutionTime": end_ms + 86_400_000,
        "rules": (
            f"规则 [Polymarket](https://polymarket.com/event/{slug})。"
            if is_chinese
            else f"Rules [Polymarket](https://polymarket.com/event/{slug})."
        ),
    }
    return {key: values[key] for key in KEYS}


def codes(report, collection="errors"):
    return [item["code"] for item in report[collection]]


class AuditBatchesTests(unittest.TestCase):
    def test_extracts_event_slug_from_english_and_zh_urls(self):
        audit = load_audit()
        self.assertEqual(
            audit.extract_identity({"rules": "https://polymarket.com/event/alpha-event"}),
            ("eventSlug", "alpha-event"),
        )
        self.assertEqual(
            audit.extract_identity({"rules": "https://polymarket.com/zh/event/beta-event?x=1"}),
            ("eventSlug", "beta-event"),
        )

    def test_event_slug_precedes_market_id(self):
        audit = load_audit()
        self.assertEqual(
            audit.extract_identity(
                {"eventSlug": "event-one", "sourceMarketId": "market-99"}
            ),
            ("eventSlug", "event-one"),
        )

    def test_internal_event_duplicate_is_error(self):
        audit = load_audit()
        english = [
            market("Will A happen?", "Crypto", "same-event"),
            market("Will B happen?", "Crypto", "same-event"),
        ]
        chinese = [
            market("Will A happen?", "Crypto", "same-event", language="zh"),
            market("Will B happen?", "Crypto", "same-event", language="zh"),
        ]
        report = audit.audit_batches(
            english, chinese, [], {"Crypto": 2}, None, CATEGORY_LABELS
        )
        self.assertIn("internal_duplicate", codes(report))
        duplicate = next(e for e in report["errors"] if e["code"] == "internal_duplicate")
        self.assertEqual(duplicate["index"], 1)
        self.assertEqual(duplicate["category"], "Crypto")

    def test_historical_event_overlap_is_error(self):
        audit = load_audit()
        english = [market("Will A happen?", "Crypto", "old-event")]
        chinese = [market("Will A happen?", "Crypto", "old-event", language="zh")]
        references = [[market("A historical question?", "Crypto", "old-event")]]
        report = audit.audit_batches(
            english, chinese, references, {"Crypto": 1}, None, CATEGORY_LABELS
        )
        self.assertIn("historical_overlap", codes(report))
        overlap = next(e for e in report["errors"] if e["code"] == "historical_overlap")
        self.assertEqual((overlap["index"], overlap["category"]), (0, "Crypto"))
        self.assertEqual(
            report["replacementRequirements"],
            [{"index": 0, "category": "Crypto", "reasons": ["historical_overlap"]}],
        )

    def test_missing_stable_identity_is_error(self):
        audit = load_audit()
        english = [market("Will A happen?", "Crypto", "missing")]
        chinese = [market("Will A happen?", "Crypto", "missing", language="zh")]
        english[0]["rules"] = "Rules with no Polymarket link."
        chinese[0]["rules"] = "没有 Polymarket 链接。"
        report = audit.audit_batches(
            english, chinese, [], {"Crypto": 1}, None, CATEGORY_LABELS
        )
        self.assertIn("missing_identity", codes(report))

    def test_reference_missing_identity_is_error(self):
        audit = load_audit()
        english = [market("Will A happen?", "Crypto", "event-a")]
        chinese = [market("Will A happen?", "Crypto", "event-a", language="zh")]
        reference = market("Historical item?", "Crypto", "missing")
        reference["rules"] = "Historical rules without a Polymarket event link."

        report = audit.audit_batches(
            english, chinese, [[reference]], {"Crypto": 1}, None, CATEGORY_LABELS
        )

        self.assertIn("reference_missing_identity", codes(report))

    def test_market_id_reference_is_incomparable_with_event_slug_target(self):
        audit = load_audit()
        english = [market("Will A happen?", "Crypto", "event-a")]
        chinese = [market("Will A happen?", "Crypto", "event-a", language="zh")]
        reference = market("Historical item?", "Crypto", "missing")
        reference["rules"] = "Historical rules without an event link."
        reference["sourceMarketId"] = "source-42"

        report = audit.audit_batches(
            english, chinese, [[reference]], {"Crypto": 1}, None, CATEGORY_LABELS
        )

        self.assertIn("reference_incomparable_identity", codes(report))

    def test_clean_pair_passes_all_invariants(self):
        audit = load_audit()
        english = [
            market("Will A happen?", "Crypto", "event-a"),
            market("Will B happen?", "Politics", "event-b"),
        ]
        chinese = [
            market("Will A happen?", "Crypto", "event-a", language="zh"),
            market("Will B happen?", "Politics", "event-b", language="zh"),
        ]
        report = audit.audit_batches(
            english,
            chinese,
            [],
            {"Crypto": 1, "Politics": 1},
            1790000000000,
            CATEGORY_LABELS,
        )
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["summary"]["targetCount"], 2)
        self.assertEqual(report["summary"]["quotaCounts"], {"Crypto": 1, "Politics": 1})

    def test_quota_and_strict_horizon_failures_are_reported(self):
        audit = load_audit()
        cutoff = 1800000000000
        english = [market("Will A happen?", "Crypto", "event-a", cutoff)]
        chinese = [market("Will A happen?", "Crypto", "event-a", cutoff, "zh")]
        report = audit.audit_batches(
            english, chinese, [], {"Crypto": 2}, cutoff, CATEGORY_LABELS
        )
        self.assertIn("quota_mismatch", codes(report))
        self.assertIn("deadline_too_soon", codes(report))

    def test_bilingual_index_mismatch_is_error(self):
        audit = load_audit()
        english = [market("Will A happen?", "Crypto", "event-a")]
        chinese = [market("Will A happen?", "Crypto", "event-a", language="zh")]
        chinese[0]["sentiment"] = 54
        report = audit.audit_batches(
            english, chinese, [], {"Crypto": 1}, None, CATEGORY_LABELS
        )
        self.assertIn("bilingual_invariant", codes(report))
        mismatch = next(e for e in report["errors"] if e["code"] == "bilingual_invariant")
        self.assertEqual(mismatch["field"], "sentiment")

    def test_chinese_schema_and_nested_options_are_validated(self):
        audit = load_audit()
        cases = []

        chinese_title = market("Will A happen?", "Crypto", "event-a", language="zh")
        chinese_title["title"] = None
        cases.append((market("Will A happen?", "Crypto", "event-a"), chinese_title))

        chinese_bool = market("Will A happen?", "Crypto", "event-a", language="zh")
        chinese_bool["isMarketAptable"] = 1
        cases.append((market("Will A happen?", "Crypto", "event-a"), chinese_bool))

        chinese_score = market("Will A happen?", "Crypto", "event-a", language="zh")
        chinese_score["heatScore"] = 80.0
        cases.append((market("Will A happen?", "Crypto", "event-a"), chinese_score))

        chinese_options = market("Will A happen?", "Crypto", "event-a", language="zh")
        chinese_options["options"] = [
            {"value": "Yes", "label": "是"},
            {"value": "No", "label": "否"},
            None,
        ]
        cases.append((market("Will A happen?", "Crypto", "event-a"), chinese_options))

        english_label = market("Will A happen?", "Crypto", "event-a")
        english_label["options"][0].pop("label")
        cases.append((english_label, market("Will A happen?", "Crypto", "event-a", language="zh")))

        for english, chinese in cases:
            with self.subTest(chinese=chinese, english=english):
                report = audit.audit_batches(
                    [english], [chinese], [], {"Crypto": 1}, None, CATEGORY_LABELS
                )
                self.assertTrue(
                    {"schema_type", "schema_options"}.intersection(codes(report)),
                    report,
                )

    def test_malformed_records_return_structured_errors(self):
        audit = load_audit()
        report = audit.audit_batches(
            [None], [None], [], {"Crypto": 1}, None, CATEGORY_LABELS
        )
        self.assertIn("schema_type", codes(report))
        self.assertEqual(report["replacementRequirements"][0]["index"], 0)

    def test_null_options_cli_writes_error_report(self):
        load_audit()
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            english = market("Will A happen?", "Crypto", "event-a")
            chinese = market("Will A happen?", "Crypto", "event-a", language="zh")
            english["options"] = None
            en_path = directory / "en.json"
            zh_path = directory / "zh.json"
            report_path = directory / "report.json"
            en_path.write_text(json.dumps([english]), encoding="utf-8")
            zh_path.write_text(json.dumps([chinese]), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--english",
                    str(en_path),
                    "--chinese",
                    str(zh_path),
                    "--quota",
                    "Crypto=1",
                    "--report",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("schema_options", codes(json.loads(report_path.read_text())))

    def test_similar_titles_with_distinct_slugs_are_warning_only(self):
        audit = load_audit()
        english = [
            market("Will Bitcoin reach $100,000 by 2027?", "Crypto", "bitcoin-100000"),
            market("Will Bitcoin reach $100,001 by 2027?", "Crypto", "bitcoin-100001"),
        ]
        chinese = [
            market("Will Bitcoin reach $100,000 by 2027?", "Crypto", "bitcoin-100000", language="zh"),
            market("Will Bitcoin reach $100,001 by 2027?", "Crypto", "bitcoin-100001", language="zh"),
        ]
        report = audit.audit_batches(
            english, chinese, [], {"Crypto": 2}, None, CATEGORY_LABELS
        )
        self.assertEqual(report["errors"], [])
        self.assertIn("similar_title", codes(report, "warnings"))

    def test_cli_does_not_modify_inputs(self):
        load_audit()
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            paths = {
                "english": directory / "en.json",
                "chinese": directory / "zh.json",
                "reference": directory / "old.json",
            }
            paths["english"].write_text(
                json.dumps([market("Will A happen?", "Crypto", "event-a")], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            paths["chinese"].write_text(
                json.dumps([market("Will A happen?", "Crypto", "event-a", language="zh")], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            paths["reference"].write_text(
                json.dumps([market("Will Old happen?", "Crypto", "old-event")], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            before = {name: path.read_bytes() for name, path in paths.items()}
            report_path = directory / "report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--english",
                    str(paths["english"]),
                    "--chinese",
                    str(paths["chinese"]),
                    "--reference",
                    str(paths["reference"]),
                    "--quota",
                    "Crypto=1",
                    "--min-days",
                    "50",
                    "--as-of",
                    "2026-10-24T00:00:00Z",
                    "--report",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(report_path.exists())
            self.assertEqual(
                {name: path.read_bytes() for name, path in paths.items()}, before
            )

    def test_cli_rejects_report_aliasing_any_input(self):
        load_audit()
        for alias_kind in ("direct", "symlink", "hardlink"):
            with self.subTest(alias_kind=alias_kind), tempfile.TemporaryDirectory() as raw_dir:
                directory = Path(raw_dir)
                en_path = directory / "en.json"
                zh_path = directory / "zh.json"
                ref_path = directory / "old.json"
                en_path.write_text(json.dumps([market("A?", "Crypto", "event-a")]), encoding="utf-8")
                zh_path.write_text(json.dumps([market("A?", "Crypto", "event-a", language="zh")]), encoding="utf-8")
                ref_path.write_text(json.dumps([market("Old?", "Crypto", "old-event")]), encoding="utf-8")
                before = {path: path.read_bytes() for path in (en_path, zh_path, ref_path)}

                if alias_kind == "direct":
                    report_path = en_path
                elif alias_kind == "symlink":
                    report_path = directory / "report-link.json"
                    report_path.symlink_to(zh_path)
                else:
                    report_path = directory / "report-hardlink.json"
                    os.link(ref_path, report_path)

                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT_PATH),
                        "--english",
                        str(en_path),
                        "--chinese",
                        str(zh_path),
                        "--reference",
                        str(ref_path),
                        "--quota",
                        "Crypto=1",
                        "--report",
                        str(report_path),
                    ],
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    {path: path.read_bytes() for path in (en_path, zh_path, ref_path)}, before
                )


if __name__ == "__main__":
    unittest.main()
