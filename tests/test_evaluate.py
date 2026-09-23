from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skill_picker.evaluate import CaseResult, load_cases, percentile, summarize


class LoadCasesTests(unittest.TestCase):
    def test_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"id":"same","request":"one","expected":"abstain"}',
                        '{"id":"same","request":"two","expected":"abstain"}',
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate id"):
                load_cases(path, set())

    def test_rejects_cases_naming_unknown_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(
                '{"id":"one","request":"fix it","expected":"suggestions",'
                '"acceptable_skills":["not-a-skill"]}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unknown skills"):
                load_cases(path, {"diagnose"})


class SummaryTests(unittest.TestCase):
    def test_scores_suggestions_abstention_and_skip_separately(self) -> None:
        results = [
            CaseResult(
                id="top-one",
                expected="suggestions",
                acceptable_skills=("diagnose",),
                status="ok",
                suggestions=("diagnose", "review"),
                latency_ms=100.0,
                api_calls=2,
                input_tokens=10,
                output_tokens=2,
            ),
            CaseResult(
                id="top-two",
                expected="suggestions",
                acceptable_skills=("verify-fix",),
                status="ok",
                suggestions=("diagnose", "verify-fix"),
                latency_ms=200.0,
                api_calls=2,
                input_tokens=20,
                output_tokens=4,
            ),
            CaseResult(
                id="false-negative",
                expected="suggestions",
                acceptable_skills=("review",),
                status="ok",
                suggestions=(),
                latency_ms=300.0,
                api_calls=1,
                input_tokens=30,
                output_tokens=6,
            ),
            CaseResult(
                id="correct-abstain",
                expected="abstain",
                acceptable_skills=(),
                status="ok",
                suggestions=(),
                latency_ms=400.0,
                api_calls=1,
                input_tokens=40,
                output_tokens=8,
            ),
            CaseResult(
                id="false-positive",
                expected="abstain",
                acceptable_skills=(),
                status="ok",
                suggestions=("diagnose",),
                latency_ms=500.0,
                api_calls=2,
                input_tokens=50,
                output_tokens=10,
            ),
            CaseResult(
                id="explicit",
                expected="skip",
                acceptable_skills=(),
                status="skipped",
                suggestions=(),
                latency_ms=1.0,
                api_calls=0,
                input_tokens=0,
                output_tokens=0,
            ),
        ]

        summary = summarize(results)

        self.assertEqual(summary["matching_cases"], 4)
        self.assertAlmostEqual(summary["case_accuracy"], 2 / 3)
        self.assertAlmostEqual(summary["top1_accuracy"], 1 / 3)
        self.assertAlmostEqual(summary["top3_recall"], 2 / 3)
        self.assertAlmostEqual(summary["mean_reciprocal_rank"], 0.5)
        self.assertAlmostEqual(summary["false_negative_rate"], 1 / 3)
        self.assertAlmostEqual(summary["false_positive_rate"], 0.5)
        self.assertEqual(summary["skip_accuracy"], 1.0)
        self.assertEqual(summary["api_calls"], 8)
        self.assertEqual(summary["input_tokens"], 150)
        self.assertEqual(summary["output_tokens"], 30)
        self.assertEqual(summary["latency_ms"]["p50"], 300.0)

    def test_percentile_interpolates_small_samples(self) -> None:
        self.assertEqual(percentile([], 0.95), 0.0)
        self.assertEqual(percentile([10.0], 0.95), 10.0)
        self.assertEqual(percentile([0.0, 100.0], 0.95), 95.0)


if __name__ == "__main__":
    unittest.main()
