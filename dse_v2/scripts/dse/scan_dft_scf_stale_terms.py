#!/usr/bin/env python3
"""Scan DFT/QE full-SCF hardware DSE docs/code for stale downgrade terms."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


SCAN_SCHEMA = "dse.dft_scf.stale_term_scan.v1"
DEFAULT_SCAN_ROOTS = ("AGENTS.md", "README.md", "CLAUDE.md", "docs", "dse_v2")
SKIP_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "runs",
    "tmp",
}
SKIP_SUFFIXES = {".pyc", ".o", ".a", ".so", ".png", ".jpg", ".jpeg", ".pdf"}
SCANNER_FIXTURE_FILES = {
    "scan_dft_scf_stale_terms.py",
    "test_dft_scf_stale_term_scan.py",
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]
    status: str
    canonical_replacement: str
    rationale: str


RULES: tuple[Rule, ...] = (
    Rule(
        "old_date_horizon",
        re.compile(r"2026-05-15\s+00:00(?::00)?(?:\s+CST)?"),
        "must_fix",
        "2026-06-01 12:00:00 CST",
        "The active goal date gate is 2026-06-01 12:00 local, not the older DFT-first horizon.",
    ),
    Rule(
        "old_midnight_completion_decision",
        re.compile(r"do_not_mark_complete_before_midnight_horizon"),
        "must_fix",
        "do_not_mark_complete_before_date_horizon",
        "Goal completion must be keyed to the active date horizon, not a stale midnight label.",
    ),
    Rule(
        "dft_removed_mainline_conflict",
        re.compile(
            r"(no longer the mainline|removed from the active working tree|DFT removed from mainline|not a QE/VASP-specific DFT codebase)",
            re.IGNORECASE,
        ),
        "must_fix",
        "generic core + active DFT/QE full-SCF reference proof path",
        "Front-door wording must not imply the active DFT/QE proof path is forbidden.",
    ),
    Rule(
        "ambiguous_step3_searchable_alias",
        re.compile(r"\bstep3_searchable\b"),
        "legacy_allowed",
        "step2_screenable / step3_evaluable / simulation_eligible / simulation_blockers",
        "Legacy alias remains in compatibility payloads but should not be introduced as new terminology.",
    ),
    Rule(
        "hpsi_only_completion_boundary",
        re.compile(r"\bh_?psi-only\b", re.IGNORECASE),
        "claim_boundary_allowed",
        "full-SCF evaluated hybrid / all-major-kernel evidence",
        "The term is allowed when it rejects h_psi-only completion, but it cannot define the active target.",
    ),
    Rule(
        "authoritative_candidate_tier",
        re.compile(r"\bcandidate_tier\b"),
        "authoritative_stale",
        "release_policy.lane / release_policy.formal_pareto_allowed",
        "DFT release/exploratory routing must not use candidate_tier as a search, Trial, identity, binding, or formal-Pareto authority.",
    ),
    Rule(
        "stress_tags_gate_authority",
        re.compile(r"(stress_tags.*required_kernel_gates|required_kernel_gates.*stress_tags)", re.IGNORECASE),
        "authoritative_stale",
        "feature-derived coverage_vector.gate_derivation_reasons",
        "Manual stress_tags are display-only and cannot authorize required kernel gates.",
    ),
    Rule(
        "phase_hotspot_design_identity",
        re.compile(r"(DFT_DESIGN_AXIS_IDS.*dft_phase_hotspot_selection|dft_phase_hotspot_selection.*DFT_DESIGN_AXIS_IDS)"),
        "authoritative_stale",
        "DFT_APPLICABILITY_AXIS_IDS",
        "DFT phase/hotspot selection is applicability scope, not stable design identity.",
    ),
    Rule(
        "evaluation_policy_design_legality",
        re.compile(r"(DFT_LEGALITY_CONSTRAINTS.*evidence_fidelity_promotion_policy|evidence_fidelity_promotion_policy.*DFT_LEGALITY_CONSTRAINTS)"),
        "authoritative_stale",
        "DFT_EVALUATION_POLICY_AXIS_IDS / evaluation_policy_routing",
        "Evaluation policy can route evidence but cannot affect design legality.",
    ),
)


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    if not root.exists():
        return
    for path in root.rglob("*"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield path


def _line_context(lines: Sequence[str], index: int) -> str:
    start = max(0, index - 1)
    end = min(len(lines), index + 2)
    return "\n".join(lines[start:end]).strip()


def _hit_status(path: Path, rule: Rule, line: str, context: str) -> str:
    if path.name in SCANNER_FIXTURE_FILES and rule.status == "must_fix":
        return "scanner_fixture_allowed"
    if rule.status != "authoritative_stale":
        return rule.status
    normalized = str(path).replace("\\", "/")
    lowered = f"{line}\n{context}".lower()
    if "/tests/" in normalized or path.name in SCANNER_FIXTURE_FILES:
        return "authoritative_stale_test_guard_allowed"
    if path.suffix.lower() in {".md", ".rst", ".txt"}:
        return "authoritative_stale_documentation_allowed"
    if rule.rule_id == "authoritative_candidate_tier":
        allowed_markers = (
            "legacy_candidate_tier",
            "candidate_tier_authoritative",
            "deprecated display wrapper",
            "not authoritative",
            "legacy display/provenance",
            "params.pop(\"candidate_tier\")",
            "pop(\"candidate_tier\"",
            "formal_pareto_tier_field",
        )
        if any(marker in lowered for marker in allowed_markers):
            return "authoritative_stale_compatibility_allowed"
    if rule.rule_id == "stress_tags_gate_authority" and "display" in lowered and "not_authoritative" in lowered:
        return "authoritative_stale_compatibility_allowed"
    return rule.status


def scan_paths(paths: Iterable[Path]) -> Dict[str, Any]:
    hits: List[Dict[str, Any]] = []
    for root in paths:
        for path in _iter_files(Path(root)):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = text.splitlines()
            for lineno, line in enumerate(lines, 1):
                for rule in RULES:
                    if not rule.pattern.search(line):
                        continue
                    context = _line_context(lines, lineno - 1)
                    status = _hit_status(path, rule, line, context)
                    hits.append({
                        "rule_id": rule.rule_id,
                        "status": status,
                        "path": str(path),
                        "line": lineno,
                        "text": line.strip(),
                        "context": context,
                        "canonical_replacement": rule.canonical_replacement,
                        "rationale": rule.rationale,
                    })
    status_counts: Dict[str, int] = {}
    for hit in hits:
        status_counts[hit["status"]] = status_counts.get(hit["status"], 0) + 1
    must_fix_count = status_counts.get("must_fix", 0)
    authoritative_stale_count = status_counts.get("authoritative_stale", 0)
    return {
        "schema_version": SCAN_SCHEMA,
        "status": "passed" if must_fix_count == 0 and authoritative_stale_count == 0 else "blocked",
        "must_fix_count": must_fix_count,
        "authoritative_stale_count": authoritative_stale_count,
        "status_counts": status_counts,
        "hit_count": len(hits),
        "hits": hits,
        "claim_boundary": (
            "must_fix hits block completion; legacy_allowed and "
            "claim_boundary_allowed hits are migration reminders only."
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path(item) for item in DEFAULT_SCAN_ROOTS])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--allow-must-fix", action="store_true")
    parser.add_argument("--fail-on-authoritative-stale-terms", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = scan_paths(args.paths)
    if args.out:
        _write_json(args.out, report)
    if not args.quiet:
        print(json.dumps(report, indent=2, sort_keys=True))
    if report["must_fix_count"] and not args.allow_must_fix:
        return 2
    if args.fail_on_authoritative_stale_terms and report["authoritative_stale_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
