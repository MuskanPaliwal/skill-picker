"""Evaluate live routing against a labeled JSONL dataset."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .catalog import Skill, default_actions_path, default_skills_dir, load_catalog
from .router import (
    DEFAULT_FIT_FLOOR,
    DEFAULT_GATE_FLOOR,
    DEFAULT_SHORTLIST_SIZE,
    recommend,
)
from .typesafe import (
    DEFAULT_MODEL,
    RouterUnavailable,
    call_typesafe,
    resolve_api_key,
)

EXPECTED_OUTCOMES = {"suggestions", "abstain", "skip"}


@dataclass(frozen=True)
class EvalCase:
    id: str
    request: str
    expected: str
    acceptable_skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class SuggestionScore:
    name: str
    kind: str
    invocation: str
    relative_probability: float
    fit_probability: float


@dataclass(frozen=True)
class CaseResult:
    id: str
    expected: str
    acceptable_skills: tuple[str, ...]
    status: str
    suggestions: tuple[str, ...]
    latency_ms: float
    api_calls: int
    input_tokens: int
    output_tokens: int
    gate_probability: float | None = None
    suggestion_scores: tuple[SuggestionScore, ...] = ()
    error: str | None = None


def load_cases(path: Path, known_skills: set[str]) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error

        case_id = record.get("id")
        request = record.get("request")
        expected = record.get("expected")
        acceptable = record.get("acceptable_skills", [])
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{path}:{line_number}: id must be a non-empty string")
        if case_id in seen_ids:
            raise ValueError(f"{path}:{line_number}: duplicate id {case_id!r}")
        if not isinstance(request, str) or not request.strip():
            raise ValueError(
                f"{path}:{line_number}: request must be a non-empty string"
            )
        if expected not in EXPECTED_OUTCOMES:
            raise ValueError(
                f"{path}:{line_number}: expected must be one of "
                f"{sorted(EXPECTED_OUTCOMES)}"
            )
        if not isinstance(acceptable, list) or not all(
            isinstance(name, str) for name in acceptable
        ):
            raise ValueError(
                f"{path}:{line_number}: acceptable_skills must be a string list"
            )
        unknown = sorted(set(acceptable) - known_skills)
        if unknown:
            raise ValueError(
                f"{path}:{line_number}: unknown skills: {', '.join(unknown)}"
            )
        if expected == "suggestions" and not acceptable:
            raise ValueError(
                f"{path}:{line_number}: suggestion cases need acceptable_skills"
            )
        if expected != "suggestions" and acceptable:
            raise ValueError(
                f"{path}:{line_number}: only suggestion cases accept skills"
            )

        seen_ids.add(case_id)
        cases.append(
            EvalCase(
                id=case_id,
                request=request.strip(),
                expected=expected,
                acceptable_skills=tuple(acceptable),
            )
        )

    if not cases:
        raise ValueError(f"{path}: no evaluation cases found")
    return cases


class TracedApiCall:
    def __init__(self, api_key: str, timeout: float) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        response = call_typesafe(
            payload,
            api_key=self.api_key,
            timeout=self.timeout,
        )
        usage = response.get("usage", {})
        if isinstance(usage, dict):
            self.input_tokens += int(usage.get("input_tokens", 0))
            self.output_tokens += int(usage.get("output_tokens", 0))
        return response


def evaluate_case(
    case: EvalCase,
    skills: list[Skill],
    *,
    api_key: str,
    model: str,
    gate_floor: float,
    fit_floor: float,
    shortlist_size: int,
    timeout: float,
) -> CaseResult:
    traced_call = TracedApiCall(api_key, timeout)
    started = time.perf_counter()
    try:
        result = recommend(
            case.request,
            skills,
            traced_call,
            model=model,
            gate_floor=gate_floor,
            fit_floor=fit_floor,
            shortlist_size=shortlist_size,
        )
        suggestions = tuple(
            suggestion["name"] for suggestion in result.get("suggestions", [])
        )
        suggestion_scores = tuple(
            SuggestionScore(
                name=suggestion["name"],
                kind=suggestion["kind"],
                invocation=suggestion["invocation"],
                relative_probability=float(suggestion["relative_probability"]),
                fit_probability=float(suggestion["fit_probability"]),
            )
            for suggestion in result.get("suggestions", [])
        )
        return CaseResult(
            id=case.id,
            expected=case.expected,
            acceptable_skills=case.acceptable_skills,
            status=str(result.get("status", "unknown")),
            suggestions=suggestions,
            latency_ms=(time.perf_counter() - started) * 1_000,
            api_calls=traced_call.calls,
            input_tokens=traced_call.input_tokens,
            output_tokens=traced_call.output_tokens,
            gate_probability=(
                float(result["gate_probability"])
                if "gate_probability" in result
                else None
            ),
            suggestion_scores=suggestion_scores,
        )
    except (KeyError, OSError, TypeError, ValueError, RouterUnavailable) as error:
        return CaseResult(
            id=case.id,
            expected=case.expected,
            acceptable_skills=case.acceptable_skills,
            status="unavailable",
            suggestions=(),
            latency_ms=(time.perf_counter() - started) * 1_000,
            api_calls=traced_call.calls,
            input_tokens=traced_call.input_tokens,
            output_tokens=traced_call.output_tokens,
            error=str(error),
        )


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def matches_expectation(result: CaseResult) -> bool:
    if result.error:
        return False
    if result.expected == "suggestions":
        acceptable = set(result.acceptable_skills)
        return any(name in acceptable for name in result.suggestions[:3])
    if result.expected == "abstain":
        return result.status == "ok" and not result.suggestions
    return result.status == "skipped"


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    suggestion_results = [
        result for result in results if result.expected == "suggestions"
    ]
    abstain_results = [result for result in results if result.expected == "abstain"]
    skip_results = [result for result in results if result.expected == "skip"]
    api_results = [result for result in results if result.api_calls > 0]

    top1_hits = 0
    top3_hits = 0
    reciprocal_rank = 0.0
    false_negatives = 0
    for result in suggestion_results:
        acceptable = set(result.acceptable_skills)
        if result.suggestions and result.suggestions[0] in acceptable:
            top1_hits += 1
        first_rank = next(
            (
                index
                for index, name in enumerate(result.suggestions[:3], start=1)
                if name in acceptable
            ),
            None,
        )
        if first_rank is not None:
            top3_hits += 1
            reciprocal_rank += 1.0 / first_rank
        else:
            false_negatives += 1

    false_positives = sum(bool(result.suggestions) for result in abstain_results)
    correct_skips = sum(result.status == "skipped" for result in skip_results)
    latencies = [result.latency_ms for result in api_results]

    def ratio(numerator: int | float, denominator: int) -> float:
        return float(numerator) / denominator if denominator else 0.0

    matching_cases = sum(matches_expectation(result) for result in results)
    return {
        "cases": len(results),
        "matching_cases": matching_cases,
        "case_accuracy": ratio(matching_cases, len(results)),
        "suggestion_cases": len(suggestion_results),
        "abstain_cases": len(abstain_results),
        "skip_cases": len(skip_results),
        "top1_accuracy": ratio(top1_hits, len(suggestion_results)),
        "top3_recall": ratio(top3_hits, len(suggestion_results)),
        "mean_reciprocal_rank": ratio(reciprocal_rank, len(suggestion_results)),
        "false_negative_rate": ratio(false_negatives, len(suggestion_results)),
        "false_positive_rate": ratio(false_positives, len(abstain_results)),
        "skip_accuracy": ratio(correct_skips, len(skip_results)),
        "api_failures": sum(result.error is not None for result in results),
        "api_calls": sum(result.api_calls for result in results),
        "input_tokens": sum(result.input_tokens for result in results),
        "output_tokens": sum(result.output_tokens for result in results),
        "latency_ms": {
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
    }


def print_report(summary: dict[str, Any], results: list[CaseResult]) -> None:
    def percent(value: float, cases: int) -> str:
        # A rate over zero cases is unmeasured, not a score of zero.
        return f"{value * 100:.1f}%" if cases else "n/a"

    suggestion_cases = summary["suggestion_cases"]
    latency = summary["latency_ms"]
    print("Skill routing evaluation")
    print(f"- Cases: {summary['cases']}")
    print(
        f"- Overall case accuracy: "
        f"{percent(summary['case_accuracy'], summary['cases'])}"
    )
    print(f"- Top-1 accuracy: {percent(summary['top1_accuracy'], suggestion_cases)}")
    print(f"- Top-3 recall: {percent(summary['top3_recall'], suggestion_cases)}")
    print(
        f"- Mean reciprocal rank: "
        f"{summary['mean_reciprocal_rank']:.3f}" if suggestion_cases else
        "- Mean reciprocal rank: n/a"
    )
    print(
        f"- False-positive rate: "
        f"{percent(summary['false_positive_rate'], summary['abstain_cases'])}"
    )
    print(
        f"- False-negative rate: "
        f"{percent(summary['false_negative_rate'], suggestion_cases)}"
    )
    print(
        f"- Explicit-action bypass: "
        f"{percent(summary['skip_accuracy'], summary['skip_cases'])}"
    )
    print(
        "- Latency: "
        f"mean {latency['mean']:.0f} ms, "
        f"p50 {latency['p50']:.0f} ms, "
        f"p95 {latency['p95']:.0f} ms"
    )
    print(
        f"- API: {summary['api_calls']} calls, "
        f"{summary['api_failures']} failures, "
        f"{summary['input_tokens']} input tokens, "
        f"{summary['output_tokens']} output tokens"
    )

    failures = [result for result in results if result.error]
    if failures:
        print("\nAPI failures")
        for result in failures:
            print(f"- {result.id}: {result.error}")

    mismatches = [
        result
        for result in results
        if not result.error and not matches_expectation(result)
    ]
    if mismatches:
        print("\nRouting mismatches")
        for result in mismatches:
            expected = (
                ", ".join(result.acceptable_skills)
                if result.acceptable_skills
                else result.expected
            )
            actual = ", ".join(result.suggestions) or result.status
            print(f"- {result.id}: expected {expected}; got {actual}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--skills-dir", type=Path)
    parser.add_argument("--actions", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--gate-floor", type=float, default=DEFAULT_GATE_FLOOR)
    parser.add_argument("--fit-floor", type=float, default=DEFAULT_FIT_FLOOR)
    parser.add_argument(
        "--shortlist-size", type=int, default=DEFAULT_SHORTLIST_SIZE
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    skills_dir = args.skills_dir.expanduser() if args.skills_dir else default_skills_dir()
    actions_path = args.actions.expanduser() if args.actions else default_actions_path()

    try:
        api_key = resolve_api_key()
    except RouterUnavailable as error:
        parser.error(str(error))
    if not api_key:
        parser.error("no API key available; a live evaluation cannot run without one")

    try:
        skills = load_catalog(skills_dir, actions_path)
        cases = load_cases(
            args.cases.expanduser(),
            {skill.name for skill in skills},
        )
    except (OSError, ValueError, RouterUnavailable) as error:
        parser.error(str(error))
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be at least 1")
        cases = cases[: args.limit]

    results = [
        evaluate_case(
            case,
            skills,
            api_key=api_key,
            model=args.model,
            gate_floor=args.gate_floor,
            fit_floor=args.fit_floor,
            shortlist_size=args.shortlist_size,
            timeout=args.timeout,
        )
        for case in cases
    ]
    summary = summarize(results)
    print_report(summary, results)

    if args.json_output:
        output = {
            "configuration": {
                "model": args.model,
                "gate_floor": args.gate_floor,
                "fit_floor": args.fit_floor,
                "shortlist_size": args.shortlist_size,
                "cases": str(args.cases),
                "skills_dir": str(skills_dir),
                "actions": str(actions_path) if actions_path else None,
            },
            "summary": summary,
            "results": [asdict(result) for result in results],
        }
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(output, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"- JSON report: {args.json_output}")

    return 1 if summary["api_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
