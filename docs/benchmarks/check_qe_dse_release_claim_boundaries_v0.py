#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE_DOCS = (
    ROOT / "pro_work/full_system_dse_closure_review_20260429.md",
    ROOT / "docs/benchmarks/qe_complete_architecture_family_dse_framework_v0.md",
)

EXACT_EVIDENCE_TIERS = (
    "survey-catalog",
    "projection-screened",
    "systemc-cycle-accounted",
    "final-best-eligible",
)
LOW_EVIDENCE_TIERS = {"survey-catalog", "projection-screened"}
HIGH_EVIDENCE_TIERS = {"systemc-cycle-accounted", "final-best-eligible"}

TIER_FIELD_NAMES = {
    "dse_evidence_tier",
    "evidence_tier",
    "evidence_tiers",
    "claim_tier",
    "claim_tiers",
    "claim_boundary_tier",
    "claim_boundary_tiers",
}

NEGATION_OR_BOUNDARY_TERMS = (
    " not ",
    " no ",
    " non-claim",
    " non_claim",
    " cannot ",
    " must not ",
    " do not ",
    " does not ",
    " without ",
    " unless ",
    " only when ",
    " requires ",
    " required ",
    " forbid",
    " forbidden",
    " refuse",
    " blocked",
    " blocker",
    " missing ",
    " absent ",
    " remains below",
    " evidence-gated",
)

TEXT_OVERCLAIM_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "final-best claim from catalog/projection tier",
        re.compile(
            r"\b(?:survey-catalog|projection-screened)\b[^\n.]{0,180}"
            r"\b(?:final[- ]best|final architecture winner|architecture winner|winner|best architecture)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "SystemC cycle-accuracy/physical-timing overclaim",
        re.compile(
            r"\bSystemC\b[^\n.]{0,220}"
            r"\b(?:cycle[- ]accurate|RTL cycle|physical timing|hardware cycle accuracy)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "GPU superiority claim",
        re.compile(
            r"\b(?:beats|beat|outperforms|outperform|faster than|superior to)\b[^\n.]{0,120}\bGPU\b|"
            r"\bGPU\b[^\n.]{0,120}\b(?:beaten|outperformed|slower than FPGA|inferior)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "board/ASIC measured-performance overclaim",
        re.compile(
            r"\b(?:board[- ]measured|measured board|board speedup|ASIC PPA|ASIC signoff|"
            r"physical FPGA performance|board/ASIC measured)\b",
            re.IGNORECASE,
        ),
    ),
)


class ClaimBoundaryError(RuntimeError):
    pass


def _normalize_for_boundary(text: str) -> str:
    return " " + re.sub(r"\s+", " ", text.strip().lower()) + " "


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _has_boundary_language(snippet: str) -> bool:
    normalized = _normalize_for_boundary(snippet)
    return any(term in normalized for term in NEGATION_OR_BOUNDARY_TERMS)


def _collect_text_overclaim_issues(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    for rule_name, pattern in TEXT_OVERCLAIM_RULES:
        for match in pattern.finditer(text):
            # Tables often put the boundary word in the heading
            # ("What it must not claim", "Forbidden reporting") while the
            # phrase being guarded appears in a row. Use a moderately broad
            # window so guarded table cells do not look like positive claims.
            start = max(0, match.start() - 500)
            end = min(len(text), match.end() + 500)
            snippet = text[start:end]
            if _has_boundary_language(snippet):
                continue
            issues.append(
                f"{path}:{_line_number(text, match.start())}: {rule_name}: {match.group(0)!r}"
            )
    return issues


def _collect_required_doc_language_issues(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    for tier in EXACT_EVIDENCE_TIERS:
        if tier not in text:
            issues.append(f"{path}: missing exact evidence-tier label {tier!r}")
    required_phrases = (
        "Stage C",
        "strict B4",
        "Stage D",
        "SystemC cycle",
        "systemc_cycle_evidence_ref",
    )
    for phrase in required_phrases:
        if phrase not in text:
            issues.append(f"{path}: missing release-boundary phrase {phrase!r}")
    return issues


def _is_json_path(path: Path) -> bool:
    return path.suffix.lower() == ".json"


def _iter_mappings(payload: Any, pointer: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(payload, Mapping):
        yield pointer, payload
        for key, value in payload.items():
            child_pointer = f"{pointer}.{key}"
            yield from _iter_mappings(value, child_pointer)
    elif isinstance(payload, list):
        for idx, value in enumerate(payload):
            yield from _iter_mappings(value, f"{pointer}[{idx}]")


def _values_from_tier_field(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _tier_values(mapping: Mapping[str, Any]) -> list[str]:
    tiers: list[str] = []
    for key, value in mapping.items():
        if str(key) in TIER_FIELD_NAMES:
            tiers.extend(_values_from_tier_field(value))
    return tiers


def _has_non_empty_key_fragment(mapping: Mapping[str, Any], fragments: Sequence[str]) -> bool:
    lowered_fragments = tuple(fragment.lower() for fragment in fragments)
    for key, value in mapping.items():
        lowered_key = str(key).lower()
        if all(fragment in lowered_key for fragment in lowered_fragments) and value not in (None, "", [], {}):
            return True
    return False


def _has_systemc_cycle_artifact_ref(mapping: Mapping[str, Any]) -> bool:
    direct_fragments = (
        ("systemc", "cycle", "ref"),
        ("systemc", "cycle", "hash"),
        ("cycle", "evidence", "ref"),
        ("cycle", "evidence", "hash"),
        ("artifact", "ref"),
        ("artifact", "hash"),
    )
    return any(_has_non_empty_key_fragment(mapping, fragments) for fragments in direct_fragments)


def _stage_d_required_for_mapping(mapping: Mapping[str, Any]) -> bool:
    policy_id = str(mapping.get("policy_id") or "")
    if policy_id == "qe_fpga_final_best_policy_systemc_b4_minimum_v0":
        return False
    policy = mapping.get("policy")
    if isinstance(policy, Mapping):
        if policy.get("stage_d_required_for_final_best") is False:
            return False
        if str(policy.get("policy_id") or "") == "qe_fpga_final_best_policy_systemc_b4_minimum_v0":
            return False
    return True


def _has_same_candidate_final_best_refs(mapping: Mapping[str, Any]) -> bool:
    required = [
        ("stage", "c"),
        ("b4",),
        ("systemc", "cycle"),
    ]
    if _stage_d_required_for_mapping(mapping):
        required.append(("stage", "d"))
    return all(_has_non_empty_key_fragment(mapping, fragments) for fragments in required)


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() in {"true", "yes", "winner", "selected"})


def _collect_json_issues(path: Path, payload: Any) -> list[str]:
    issues: list[str] = []
    for pointer, mapping in _iter_mappings(payload):
        tiers = _tier_values(mapping)
        for tier in tiers:
            if tier not in EXACT_EVIDENCE_TIERS:
                issues.append(f"{path}:{pointer}: unknown evidence tier {tier!r}")
                continue
            if tier in LOW_EVIDENCE_TIERS:
                for winner_key in ("winner", "is_winner", "final_best", "final_best_selected"):
                    if _truthy(mapping.get(winner_key)):
                        issues.append(f"{path}:{pointer}: {tier!r} row cannot set {winner_key}=true")
            if tier in HIGH_EVIDENCE_TIERS and not _has_systemc_cycle_artifact_ref(mapping):
                issues.append(
                    f"{path}:{pointer}: {tier!r} row requires a SystemC cycle evidence artifact ref/hash"
                )
            if tier == "final-best-eligible" and not _has_same_candidate_final_best_refs(mapping):
                stage_d_clause = (
                    "Stage D, "
                    if _stage_d_required_for_mapping(mapping)
                    else ""
                )
                issues.append(
                    f"{path}:{pointer}: final-best-eligible row requires same-candidate Stage C, strict B4, {stage_d_clause}and SystemC cycle refs"
                )
    return issues


def validate_path(path: Path, require_doc_language: bool = False) -> list[str]:
    if not path.exists():
        return [f"{path}: file does not exist"]
    if _is_json_path(path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return [f"{path}: JSON parse failed: {exc}"]
        return _collect_json_issues(path, payload)
    text = path.read_text(encoding="utf-8")
    issues = _collect_text_overclaim_issues(path, text)
    if require_doc_language:
        issues.extend(_collect_required_doc_language_issues(path, text))
    return issues


def validate_paths(paths: Sequence[Path], require_doc_language: bool = False) -> None:
    issues: list[str] = []
    for path in paths:
        issues.extend(validate_path(path, require_doc_language=require_doc_language))
    if issues:
        raise ClaimBoundaryError("\n".join(issues))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate QE DSE release claim boundaries: exact evidence-tier labels, "
            "no catalog/projection final-best overclaims, no SystemC cycle-accuracy/RTL/physical timing overclaims, "
            "and SystemC cycle artifact refs for higher evidence tiers."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Markdown/text/JSON report files to validate. Defaults to the Lane-E release docs.",
    )
    parser.add_argument(
        "--no-require-doc-language",
        action="store_true",
        help="Do not require every checked Markdown file to spell out the full evidence-tier vocabulary.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = tuple(args.paths) if args.paths else DEFAULT_RELEASE_DOCS
    require_doc_language = not args.no_require_doc_language
    validate_paths(paths, require_doc_language=require_doc_language)
    print("[PASS] QE DSE release claim boundaries:")
    for path in paths:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ClaimBoundaryError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
