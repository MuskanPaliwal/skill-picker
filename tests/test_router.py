from __future__ import annotations

import unittest
from typing import Any

from skill_picker.catalog import Skill
from skill_picker.router import recommend


class RecommendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skills = [
            Skill("diagnose", "Diagnose hard bugs.", "Reproduce and minimize."),
            Skill("review", "Review changed code.", "Inspect the landing diff."),
            Skill(
                "verify-fix",
                "Prove a bug fix works.",
                "Compare before and after.",
            ),
        ]

    def test_skips_when_request_explicitly_invokes_a_skill(self) -> None:
        calls: list[dict[str, Any]] = []

        result = recommend(
            "Please /diagnose this crash.",
            self.skills,
            lambda payload: calls.append(payload) or {},
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(calls, [])

    def test_skips_when_request_explicitly_invokes_a_command(self) -> None:
        calls: list[dict[str, Any]] = []
        actions = [
            *self.skills,
            Skill(
                "preflight-branch",
                "Collect branch readiness evidence.",
                "Run the deterministic command.",
                kind="script",
                invocation="preflight-branch",
            ),
        ]

        result = recommend(
            "$ preflight-branch",
            actions,
            lambda payload: calls.append(payload) or {},
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(calls, [])

    def test_gate_can_abstain_without_reranking(self) -> None:
        calls = 0

        def api_call(_: dict[str, Any]) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return {
                "answers": {
                    "which": {
                        "probabilities": {
                            "diagnose": 0.6,
                            "review": 0.3,
                            "verify-fix": 0.1,
                        }
                    },
                    "gate_acts_on_data": {"noul": 0.0},
                    "gate_needs_procedure": {"noul": 0.0},
                    "gate_just_conversation": {"noul": 1.0},
                }
            }

        result = recommend("Thanks!", self.skills, api_call)

        self.assertEqual(result["suggestions"], [])
        self.assertEqual(calls, 1)

    def test_default_gate_reranks_a_borderline_relevant_request(self) -> None:
        calls = 0
        responses = iter(
            [
                {
                    "answers": {
                        "which": {
                            "probabilities": {
                                "diagnose": 0.8,
                                "verify-fix": 0.1,
                                "review": 0.1,
                            }
                        },
                        "gate_acts_on_data": {"noul": 0.21},
                        "gate_needs_procedure": {"noul": 0.21},
                        "gate_just_conversation": {"noul": 0.79},
                    }
                },
                {
                    "answers": {
                        "which": {
                            "probabilities": {
                                "diagnose": 0.8,
                                "verify-fix": 0.1,
                                "review": 0.1,
                            }
                        },
                        "fits_0": {"noul": 0.9},
                        "fits_1": {"noul": 0.1},
                        "fits_2": {"noul": 0.1},
                    }
                },
            ]
        )

        def api_call(_: dict[str, Any]) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return next(responses)

        result = recommend(
            "Find the cause of this intermittent export crash.",
            self.skills,
            api_call,
        )

        self.assertEqual(
            [suggestion["name"] for suggestion in result["suggestions"]],
            ["diagnose"],
        )
        self.assertEqual(calls, 2)

    def test_returns_only_shortlisted_skills_that_clear_fit_floor(self) -> None:
        responses = iter(
            [
                {
                    "answers": {
                        "which": {
                            "probabilities": {
                                "diagnose": 0.6,
                                "verify-fix": 0.3,
                                "review": 0.1,
                            }
                        },
                        "gate_acts_on_data": {"noul": 1.0},
                        "gate_needs_procedure": {"noul": 1.0},
                        "gate_just_conversation": {"noul": 0.0},
                    }
                },
                {
                    "answers": {
                        "which": {
                            "probabilities": {
                                "diagnose": 0.7,
                                "verify-fix": 0.2,
                                "review": 0.1,
                            }
                        },
                        "fits_0": {"noul": 0.9},
                        "fits_1": {"noul": 0.8},
                        "fits_2": {"noul": 0.1},
                    }
                },
            ]
        )

        result = recommend(
            "The app crashes intermittently; find and fix the cause.",
            self.skills,
            lambda _: next(responses),
        )

        self.assertEqual(
            [suggestion["name"] for suggestion in result["suggestions"]],
            ["diagnose", "verify-fix"],
        )
        self.assertEqual(result["suggestions"][0]["fit_probability"], 0.9)


if __name__ == "__main__":
    unittest.main()
