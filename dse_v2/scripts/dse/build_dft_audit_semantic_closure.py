#!/usr/bin/env python3
"""Build the DFT/QE semantic audit-closure artifact.

This artifact is an audit gate, not a hardware/PPA completion claim.  It ties
five semantic HIGH-fix predicates to concrete source artifacts with SHA-256
hashes so the goal-level completion audit can fail closed when the semantic
closure evidence is missing or stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence

SCHEMA_VERSION = "dse.dft_scf.semantic_audit_closure.v1"
DEFAULT_OUTPUT_NAME = "dft_audit_semantic_closure.json"
STALE_TIER_KEY = "candidate" + "_tier"

CHECK_IDS = (
    "phase_hotspot_identity",
    "evaluation_policy_legality",
    "candidate_tier_absence",
    "coverage_vector_derivation",
    "reference_hash_admission",
)

SOURCE_DEFS: Dict[str, Dict[str, Any]] = {
    "domain_freeze": {
        "required": True,
        "candidates": ("release_domain/seven_axis_domain_freeze.json", "seven_axis_domain_freeze.json"),
    },
    "candidate_universe_manifest": {
        "required": True,
        "candidates": ("release_domain/candidate_universe_manifest.json", "candidate_universe_manifest.json"),
    },
    "candidate_legality_report": {
        "required": True,
        "candidates": ("release_domain/candidate_legality_report.json", "candidate_legality_report.json"),
    },
    "hierarchical_funnel_search_report": {
        "required": True,
        "candidates": ("release_domain/hierarchical_funnel_search_report.json", "hierarchical_funnel_search_report.json"),
    },
    "dft_candidate_binding_map": {
        "required": True,
        "candidates": ("dft_candidate_binding_map.json",),
    },
    "dft_trial_state_ledger": {
        "required": True,
        "candidates": ("dft_trial_state_ledger.json",),
    },
    "dft_scf_six_class_bundle_manifest": {
        "required": True,
        "candidates": ("dft_scf_six_class_bundle_manifest.json",),
    },
    "reference_admission_ledger": {
        "required": True,
        "candidates": ("reference_admission_ledger.json",),
    },
    "stale_scanner_report": {
        "required": False,
        "candidates": ("dft_scf_stale_term_scan.json", "stale_term_scan.json"),
    },
}

CHECK_SOURCES: Dict[str, tuple[str, ...]] = {
    "phase_hotspot_identity": (
        "domain_freeze",
        "candidate_universe_manifest",
        "dft_candidate_binding_map",
    ),
    "evaluation_policy_legality": (
        "domain_freeze",
        "candidate_universe_manifest",
        "candidate_legality_report",
    ),
    "candidate_tier_absence": (
        "hierarchical_funnel_search_report",
        "dft_candidate_binding_map",
        "dft_trial_state_ledger",
    ),
    "coverage_vector_derivation": ("dft_scf_six_class_bundle_manifest",),
    "reference_hash_admission": ("reference_admission_ledger",),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _display_path(path: Optional[Path], *, run_dir: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    if run_dir is not None:
        try:
            return path.resolve().relative_to(run_dir.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _artifact_ref(path: Optional[Path], *, run_dir: Optional[Path], required: bool) -> Dict[str, Any]:
    exists = bool(path and path.exists() and path.is_file())
    ref: Dict[str, Any] = {
        "path": _display_path(path, run_dir=run_dir),
        "exists": exists,
        "required": required,
        "hash_algorithm": "sha256",
    }
    if exists and path is not None:
        ref.update({"sha256": sha256_file(path), "size_bytes": path.stat().st_size})
    elif required:
        ref["missing_reason"] = "required_semantic_closure_source_missing"
    return ref


def _first_existing(run_dir: Optional[Path], candidates: Iterable[str]) -> Optional[Path]:
    if run_dir is None:
        return None
    for candidate in candidates:
        path = run_dir / candidate
        if path.exists() and path.is_file():
            return path
    first = next(iter(candidates), None)
    return (run_dir / first) if first else None


def _resolve_sources(
    *,
    run_dir: Optional[Path],
    overrides: Mapping[str, Optional[Path]],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    refs: Dict[str, Dict[str, Any]] = {}
    payloads: Dict[str, Dict[str, Any]] = {}
    for label, spec in SOURCE_DEFS.items():
        path = overrides.get(label)
        if path is None:
            path = _first_existing(run_dir, spec["candidates"])
        ref = _artifact_ref(path, run_dir=run_dir, required=bool(spec["required"]))
        refs[label] = ref
        if ref.get("exists") and path is not None:
            payloads[label] = _load_json(path)
        else:
            payloads[label] = {}
    return refs, payloads


def _deep_key_paths(value: Any, key_name: str, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text == key_name:
                paths.append(path)
            paths.extend(_deep_key_paths(item, key_name, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_deep_key_paths(item, key_name, f"{prefix}[{index}]"))
    return paths


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _semantic_check_payload(payload: Mapping[str, Any], check_id: str) -> Dict[str, Any]:
    for container_name in (
        "semantic_closure_checks",
        "semantic_audit_checks",
        "semantic_audit",
        "audit_checks",
        "checks_by_id",
    ):
        container = payload.get(container_name)
        if isinstance(container, Mapping):
            item = container.get(check_id)
            if isinstance(item, Mapping):
                return dict(item)
            if item is True:
                return {"passed": True}
    checks = payload.get("checks")
    if isinstance(checks, list):
        for item in checks:
            if isinstance(item, Mapping) and item.get("check_id") == check_id:
                return dict(item)
    return {}


def _semantic_override_passed(payloads: Mapping[str, Mapping[str, Any]], labels: Iterable[str], check_id: str) -> bool:
    found = False
    for label in labels:
        item = _semantic_check_payload(payloads.get(label, {}), check_id)
        if item:
            found = True
            if item.get("passed") is not True:
                return False
    return found


def _required_source_blockers(source_refs: Mapping[str, Mapping[str, Any]], labels: Iterable[str]) -> list[str]:
    blockers = []
    for label in labels:
        ref = source_refs.get(label, {})
        if ref.get("required") and not ref.get("exists"):
            blockers.append(f"missing_required_source:{label}")
        elif ref.get("required") and not ref.get("sha256"):
            blockers.append(f"missing_source_hash:{label}")
    return blockers


def _check_phase_hotspot_identity(
    source_refs: Mapping[str, Mapping[str, Any]],
    payloads: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    blockers = _required_source_blockers(source_refs, CHECK_SOURCES["phase_hotspot_identity"])
    if not blockers and _semantic_override_passed(payloads, CHECK_SOURCES["phase_hotspot_identity"], "phase_hotspot_identity"):
        passed = True
    else:
        universe = payloads.get("candidate_universe_manifest", {})
        binding = payloads.get("dft_candidate_binding_map", {})
        identity = _mapping(universe.get("design_identity_audit")) or _mapping(universe.get("identity_semantics"))
        binding_audit = _mapping(binding.get("design_identity_audit")) or _mapping(binding.get("binding_score_audit"))
        excludes_applicability = (
            identity.get("design_candidate_id_excludes_applicability") is True
            or identity.get("phase_hotspot_affects_identity") is False
        )
        row_key_labeled = (
            identity.get("candidate_id_is_evaluation_row") is True
            or identity.get("candidate_id_kind") == "evaluation_record_id"
        )
        binding_excludes = (
            not binding_audit
            or binding_audit.get("binding_score_excludes_applicability") is True
            or binding_audit.get("phase_hotspot_affects_binding_score") is False
        )
        if not excludes_applicability:
            blockers.append("phase_hotspot_identity_not_proven_design_id_excludes_applicability")
        if not row_key_labeled:
            blockers.append("evaluation_row_candidate_id_not_labeled_non_authoritative")
        if not binding_excludes:
            blockers.append("binding_score_may_still_depend_on_applicability")
        passed = not blockers
    return _check_result(
        "phase_hotspot_identity",
        passed=passed,
        blockers=blockers,
        evidence_refs=list(CHECK_SOURCES["phase_hotspot_identity"]),
        claim_boundary="Applicability/offload scope can route rows but cannot change stable design identity, design score, binding score, or trusted ranking identity.",
    )


def _check_evaluation_policy_legality(
    source_refs: Mapping[str, Mapping[str, Any]],
    payloads: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    blockers = _required_source_blockers(source_refs, CHECK_SOURCES["evaluation_policy_legality"])
    if not blockers and _semantic_override_passed(payloads, CHECK_SOURCES["evaluation_policy_legality"], "evaluation_policy_legality"):
        passed = True
    else:
        universe = payloads.get("candidate_universe_manifest", {})
        legality = payloads.get("candidate_legality_report", {})
        identity = _mapping(universe.get("design_identity_audit")) or _mapping(universe.get("identity_semantics"))
        routing = _mapping(legality.get("evaluation_policy_routing_audit")) or _mapping(universe.get("evaluation_policy_routing_audit"))
        excludes_policy = identity.get("design_candidate_id_excludes_evaluation_policy") is True
        legality_unchanged = (
            routing.get("affects_design_legality") is False
            or legality.get("evaluation_policy_affects_design_legality") is False
        )
        score_unchanged = (
            routing.get("affects_design_score") is False
            or legality.get("evaluation_policy_affects_design_score") is False
        )
        if not excludes_policy:
            blockers.append("evaluation_policy_identity_exclusion_not_proven")
        if not legality_unchanged:
            blockers.append("evaluation_policy_legality_separation_not_proven")
        if not score_unchanged:
            blockers.append("evaluation_policy_score_separation_not_proven")
        passed = not blockers
    return _check_result(
        "evaluation_policy_legality",
        passed=passed,
        blockers=blockers,
        evidence_refs=list(CHECK_SOURCES["evaluation_policy_legality"]),
        claim_boundary="Evidence-fidelity/evaluation policy routes evidence and claim eligibility only; it cannot mutate design legality or score.",
    )


def _check_candidate_tier_absence(
    source_refs: Mapping[str, Mapping[str, Any]],
    payloads: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    blockers = _required_source_blockers(source_refs, CHECK_SOURCES["candidate_tier_absence"])
    stale_paths: list[str] = []
    for label in CHECK_SOURCES["candidate_tier_absence"]:
        for path in _deep_key_paths(payloads.get(label, {}), STALE_TIER_KEY):
            lowered = path.lower()
            if "legacy" not in lowered and "compat" not in lowered and "display" not in lowered:
                stale_paths.append(f"{label}:{path}")
    if stale_paths:
        blockers.append("authoritative_candidate_tier_key_present")
    passed = not blockers
    return _check_result(
        "candidate_tier_absence",
        passed=passed,
        blockers=blockers,
        evidence_refs=list(CHECK_SOURCES["candidate_tier_absence"]),
        details={"candidate_tier_key_paths": stale_paths[:50]},
        claim_boundary="DFT release/exploratory lane is metadata only; stale tier keys cannot be search, trial, identity, or formal-Pareto authority.",
    )


def _case_required_gates(case: Mapping[str, Any]) -> list[str]:
    coverage = _mapping(case.get("coverage_vector"))
    gates = coverage.get("required_kernel_gates", case.get("required_kernel_gates", []))
    return [str(item) for item in gates] if isinstance(gates, list) else []


def _case_gate_reasons(case: Mapping[str, Any]) -> Dict[str, list[Mapping[str, Any]]]:
    coverage = _mapping(case.get("coverage_vector"))
    reasons = coverage.get("gate_derivation_reasons", case.get("gate_derivation_reasons", {}))
    result: Dict[str, list[Mapping[str, Any]]] = {}
    if isinstance(reasons, Mapping):
        for gate, entries in reasons.items():
            if isinstance(entries, list):
                result[str(gate)] = [entry for entry in entries if isinstance(entry, Mapping)]
            elif isinstance(entries, Mapping):
                result[str(gate)] = [entries]
    elif isinstance(reasons, list):
        for entry in reasons:
            if not isinstance(entry, Mapping):
                continue
            gate = entry.get("gate") or entry.get("gate_id") or entry.get("kernel_gate")
            if gate:
                result.setdefault(str(gate), []).append(entry)
    return result


def _check_coverage_vector_derivation(
    source_refs: Mapping[str, Mapping[str, Any]],
    payloads: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    blockers = _required_source_blockers(source_refs, CHECK_SOURCES["coverage_vector_derivation"])
    manifest = payloads.get("dft_scf_six_class_bundle_manifest", {})
    if not blockers and _semantic_override_passed(payloads, CHECK_SOURCES["coverage_vector_derivation"], "coverage_vector_derivation"):
        passed = True
    else:
        audit = _mapping(manifest.get("coverage_derivation_audit"))
        cases = manifest.get("cases", []) if isinstance(manifest.get("cases", []), list) else []
        if audit:
            if audit.get("all_required_gates_have_non_tag_derivation") is not True:
                blockers.append("coverage_audit_missing_non_tag_derivation")
            if audit.get("stress_tags_used_for_gate_authority") is not False:
                blockers.append("coverage_audit_allows_stress_tag_authority")
        if cases:
            for index, case in enumerate(cases):
                if not isinstance(case, Mapping):
                    continue
                reasons_by_gate = _case_gate_reasons(case)
                for gate in _case_required_gates(case):
                    reasons = reasons_by_gate.get(gate, [])
                    if not any(str(reason.get("source", "")) != "stress_tags" for reason in reasons):
                        blockers.append(f"case[{index}].{gate}:missing_non_tag_derivation_reason")
        elif not audit:
            blockers.append("coverage_derivation_audit_or_cases_missing")
        passed = not blockers
    return _check_result(
        "coverage_vector_derivation",
        passed=passed,
        blockers=blockers[:80],
        evidence_refs=list(CHECK_SOURCES["coverage_vector_derivation"]),
        claim_boundary="Required workload gates must derive from raw/resolved/derived facts; display stress tags have no gate authority.",
    )


def _check_reference_hash_admission(
    source_refs: Mapping[str, Mapping[str, Any]],
    payloads: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    blockers = _required_source_blockers(source_refs, CHECK_SOURCES["reference_hash_admission"])
    ledger = payloads.get("reference_admission_ledger", {})
    if not blockers and _semantic_override_passed(payloads, CHECK_SOURCES["reference_hash_admission"], "reference_hash_admission"):
        passed = True
    else:
        schema = str(ledger.get("schema_version", ""))
        if not schema.startswith("dse.dft_scf.reference_admission_ledger"):
            blockers.append("reference_admission_ledger_schema_missing_or_wrong")
        if ledger.get("final_admission_complete") is not True:
            blockers.append("reference_admission_ledger_not_final_complete")
        rows = ledger.get("rows", ledger.get("cases", []))
        if not isinstance(rows, list) or not rows:
            blockers.append("reference_admission_rows_missing")
        else:
            blocked_rows = [
                str(row.get("case_id", index))
                for index, row in enumerate(rows)
                if not isinstance(row, Mapping) or row.get("final_admission_eligible") is not True
            ]
            if blocked_rows:
                blockers.append("reference_admission_rows_not_final_eligible:" + ",".join(blocked_rows[:20]))
        passed = not blockers
    return _check_result(
        "reference_hash_admission",
        passed=passed,
        blockers=blockers,
        evidence_refs=list(CHECK_SOURCES["reference_hash_admission"]),
        claim_boundary="Final real-QE reference evidence requires the canonical admission ledger; hash-only or stale caller material remains provenance only.",
    )


def _check_result(
    check_id: str,
    *,
    passed: bool,
    blockers: Sequence[str],
    evidence_refs: Sequence[str],
    claim_boundary: str,
    details: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "check_id": check_id,
        "passed": bool(passed),
        "blockers": list(blockers),
        "evidence_refs": list(evidence_refs),
        "claim_boundary": claim_boundary,
    }
    if details:
        result["details"] = dict(details)
    return result


def build_dft_audit_semantic_closure(
    *,
    run_dir: Optional[Path] = None,
    source_overrides: Optional[Mapping[str, Optional[Path]]] = None,
) -> Dict[str, Any]:
    run_dir = Path(run_dir) if run_dir is not None else None
    refs, payloads = _resolve_sources(run_dir=run_dir, overrides=source_overrides or {})
    checks = [
        _check_phase_hotspot_identity(refs, payloads),
        _check_evaluation_policy_legality(refs, payloads),
        _check_candidate_tier_absence(refs, payloads),
        _check_coverage_vector_derivation(refs, payloads),
        _check_reference_hash_admission(refs, payloads),
    ]
    required_refs = [ref for ref in refs.values() if ref.get("required")]
    missing_required = [label for label, ref in refs.items() if ref.get("required") and not ref.get("exists")]
    hashed_required = [ref for ref in required_refs if ref.get("sha256")]
    source_hash_backed = len(hashed_required) == len(required_refs) and not missing_required
    overall_passed = source_hash_backed and all(check["passed"] for check in checks)
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "overall_passed": overall_passed,
        "source_hash_backed": source_hash_backed,
        "source_hash_status": {
            "required_source_count": len(required_refs),
            "hashed_required_source_count": len(hashed_required),
            "missing_required_sources": missing_required,
        },
        "source_artifacts": refs,
        "checks": checks,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "completion_claim": "semantic_audit_closure_only_not_hardware_dse_completion",
        "claim_boundary": (
            "This artifact can close the five semantic audit findings only. It does not prove hardware release "
            "eligibility, trusted Pareto winners, FPGA/ASIC PPA, or final DFT/QE hardware-DSE completion."
        ),
    }
    if not overall_passed:
        payload["fail_closed_reason"] = "missing_or_failed_semantic_closure_sources_or_checks"
    return payload


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=None, help="DSE run directory for source discovery")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path; defaults to <run-dir>/dft_audit_semantic_closure.json")
    parser.add_argument("--domain-freeze", type=Path, default=None)
    parser.add_argument("--candidate-universe-manifest", type=Path, default=None)
    parser.add_argument("--candidate-legality-report", type=Path, default=None)
    parser.add_argument("--hierarchical-search-report", type=Path, default=None)
    parser.add_argument("--candidate-binding-map", type=Path, default=None)
    parser.add_argument("--trial-state-ledger", type=Path, default=None)
    parser.add_argument("--six-scf-manifest", type=Path, default=None)
    parser.add_argument("--reference-admission-ledger", type=Path, default=None)
    parser.add_argument("--stale-scanner-report", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    overrides = {
        "domain_freeze": args.domain_freeze,
        "candidate_universe_manifest": args.candidate_universe_manifest,
        "candidate_legality_report": args.candidate_legality_report,
        "hierarchical_funnel_search_report": args.hierarchical_search_report,
        "dft_candidate_binding_map": args.candidate_binding_map,
        "dft_trial_state_ledger": args.trial_state_ledger,
        "dft_scf_six_class_bundle_manifest": args.six_scf_manifest,
        "reference_admission_ledger": args.reference_admission_ledger,
        "stale_scanner_report": args.stale_scanner_report,
    }
    payload = build_dft_audit_semantic_closure(run_dir=args.run_dir, source_overrides=overrides)
    out = args.out
    if out is None:
        if args.run_dir is None:
            raise SystemExit("--out is required when --run-dir is not provided")
        out = args.run_dir / DEFAULT_OUTPUT_NAME
    _write_json(out, payload)
    if not args.quiet:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
