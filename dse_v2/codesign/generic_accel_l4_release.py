#!/usr/bin/env python3
"""Repo-owned GenericAccel L4 replay/release evidence productization helpers.

The helpers in this module intentionally keep GenericAccel L4 subsystem evidence
separate from current-goal CDSE/DFT release claims. They can package real gem5
runtime rows into Step4-consumable artifacts, but they never upgrade synthetic
slot4 rows into trusted CDSE candidate coverage without explicit crosswalks and
all non-L4 gates.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dse_v2.codesign.l4_closure import build_coverage_claim_report, build_l4_evidence_matrix
from dse_v2.codesign.release_domain import stable_json_hash

CLAIM_BOUNDARY = (
    "This GenericAccel L4 bundle is real gem5 subsystem evidence when backed by "
    "gem5 proof rows. It is not a final FPGA/ASIC recommendation, not QE "
    "full-SCF correctness, not candidate-specific PPA, and not deliverable_complete."
)
PRODUCER = "dse_v2.scripts.dse.build_generic_accel_l4_release_artifacts"
REPLAY_PRODUCER = "dse_v2.scripts.dse.run_generic_accel_l4_release_replay"
LOCAL_REBUILD_PRODUCER = "dse_v2.scripts.dse.probe_gem5_local_rebuild"

VALID_CANDIDATE_EQUIVALENCE_SCOPES = {
    "same_identity_regenerated_l4",
    "explicit_current_goal_l4_candidate",
}
VALID_WORKLOAD_EQUIVALENCE_SCOPES = {
    "same_strict_scf_workload",
    "explicit_current_goal_l4_workload",
}
GENERIC_ACCEL_FILES = ("GenericAccel.py", "SConscript", "generic_accel.cc", "generic_accel.hh")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path | None, default: Any = None) -> Any:
    if path is None or not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path | str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_ref(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    p = Path(str(path))
    return {
        "path": str(p),
        "exists": p.exists(),
        "sha256": sha256_file(p),
        "size_bytes": p.stat().st_size if p.exists() and p.is_file() else None,
    }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _source_blocker_ids(local_rebuild: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for item in local_rebuild.get("blockers", []) or []:
        if isinstance(item, Mapping):
            ids.append(str(item.get("id") or item))
        else:
            ids.append(str(item))
    return ids


def _latest_matching_file(root: Path, pattern: str) -> Path | None:
    matches = [path for path in Path(root).glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: (path.stat().st_mtime, path.name))


def _parse_sha256sum_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "sha256": None, "reported_path": None, "line": None}
    line = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    first = line[0].strip() if line else ""
    match = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", first)
    return {
        "exists": True,
        "sha256": match.group(1).lower() if match else None,
        "reported_path": match.group(2) if match else None,
        "line": first,
    }


def _extract_rebuilt_binary_from_log(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"Local rebuild binary:\s*(.+)", text)
    return matches[-1].strip() if matches else None


def _path_equivalent(left: str | Path | None, right: str | Path | None) -> bool:
    if not left or not right:
        return False
    left_path = Path(str(left))
    right_path = Path(str(right))
    if str(left_path) == str(right_path):
        return True
    try:
        return left_path.resolve() == right_path.resolve()
    except OSError:
        return False


def _resolve_rebuilt_binary_path(
    *,
    log_binary: str | None,
    sha_reported_path: str | None,
    selected_source_root: str | None,
) -> Path | None:
    if log_binary:
        return Path(log_binary)
    if not sha_reported_path:
        return None
    reported = Path(sha_reported_path)
    if reported.is_absolute():
        return reported
    if selected_source_root:
        return Path(selected_source_root) / reported
    return None


def _replay_log_mentions_binary(log_path: Path | None, binary: Path | None) -> bool:
    if log_path is None or not log_path.exists() or binary is None:
        return False
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return "Replay contract completed" in text and str(binary) in text


def build_local_rebuild_execution_status(
    local_rebuild: Mapping[str, Any],
    expanded: Mapping[str, Any],
    *,
    runroot: Path,
) -> dict[str, Any]:
    """Promote local rebuild state only when rebuild hash and replay evidence match.

    The probe report is allowed to remain fail-closed for the current worktree
    gitlink.  This derived status only claims a local rebuild when a complete
    source provider, a SWIG provider, a rebuilt gem5.opt sha256 file, and a
    replay log over the same rebuilt binary all line up with the expanded matrix.
    """
    runroot = Path(runroot)
    selected = _select_source_provider(local_rebuild)
    swig = _select_swig_provider(local_rebuild)
    selected_root = str(_as_mapping(selected).get("root") or "") if selected else None
    sha_path = runroot / "local_rebuild_gem5_binary.sha256"
    sha_record = _parse_sha256sum_file(sha_path)
    rebuild_log = _latest_matching_file(runroot / "logs", "local_rebuild_contract_*.log")
    replay_log = _latest_matching_file(runroot / "logs", "replay_contract_*.log")
    rebuilt_binary = _resolve_rebuilt_binary_path(
        log_binary=_extract_rebuilt_binary_from_log(rebuild_log),
        sha_reported_path=sha_record.get("reported_path"),
        selected_source_root=selected_root,
    )
    rebuilt_binary_hash = sha256_file(rebuilt_binary) if rebuilt_binary else None
    expanded_hash = str(expanded.get("gem5_binary_sha256") or "").lower() or None
    expanded_binary = Path(str(expanded.get("gem5_binary"))) if expanded.get("gem5_binary") else None
    sha_matches_binary = bool(
        sha_record.get("sha256")
        and (rebuilt_binary_hash is None or rebuilt_binary_hash == sha_record.get("sha256"))
    )
    sha_matches_expanded = bool(sha_record.get("sha256") and expanded_hash == sha_record.get("sha256"))
    binary_matches_expanded = _path_equivalent(rebuilt_binary, expanded_binary)
    replay_verified = _replay_log_mentions_binary(replay_log, rebuilt_binary) and bool(expanded.get("passed_runtime_rows"))
    verified = bool(
        selected is not None
        and swig
        and sha_record.get("sha256")
        and sha_matches_binary
        and sha_matches_expanded
        and replay_verified
    )
    execution = {
        "status": "verified" if verified else "not_verified",
        "rebuild_sha256_artifact": artifact_ref(sha_path),
        "local_rebuild_log": artifact_ref(rebuild_log),
        "replay_log": artifact_ref(replay_log),
        "rebuilt_gem5_binary": artifact_ref(rebuilt_binary),
        "reported_sha256": sha_record.get("sha256"),
        "reported_sha256_path": sha_record.get("reported_path"),
        "expanded_gem5_binary": str(expanded_binary) if expanded_binary else None,
        "expanded_gem5_binary_sha256": expanded_hash,
        "selected_source_provider_root": selected_root,
        "swig_provider": swig,
        "sha_matches_binary": sha_matches_binary,
        "sha_matches_expanded_replay_matrix": sha_matches_expanded,
        "binary_path_matches_expanded_replay_matrix": binary_matches_expanded,
        "replay_verified_with_rebuilt_binary": replay_verified,
        "passed_runtime_rows": expanded.get("passed_runtime_rows"),
        "expected_negative_rows": expanded.get("expected_negative_rows"),
        "verification_policy": (
            "local_rebuild_claim_supported requires a complete source provider, a SWIG provider, "
            "local_rebuild_gem5_binary.sha256, and a replay_contract log whose rebuilt binary hash "
            "matches generic_accel_l4_expanded_proof_matrix.json."
        ),
    }
    status = dict(local_rebuild)
    status["probe_status"] = local_rebuild.get("status")
    status["probe_blockers"] = local_rebuild.get("blockers", [])
    status["verified_execution"] = execution
    if verified:
        status["status"] = "local_rebuild_and_replay_verified"
        status["local_rebuild_claim_supported"] = True
        status["rebuild_executed"] = True
        status["replay_verified_with_rebuilt_binary"] = True
        status["blockers"] = []
        status["claim_boundary"] = (
            "Local rebuild is verified only for the recorded GenericAccel gem5 source provider "
            "and replayed binary hash. This still does not imply CDSE true-candidate coverage, "
            "QE correctness, PPA closure, speedup, or deliverable_complete."
        )
    else:
        status.setdefault("rebuild_executed", False)
        status.setdefault("replay_verified_with_rebuilt_binary", False)
    return status


def _path_from_runroot(runroot: Path, raw: Any) -> Path:
    p = Path(str(raw))
    return p if p.is_absolute() else runroot / p


def proof_checks_passed(proof: Mapping[str, Any]) -> dict[str, bool]:
    checks = proof.get("checks") if isinstance(proof.get("checks"), Mapping) else {}
    names = [
        "descriptor_read_verified",
        "request_decode_verified",
        "microarchitecture_execute_verified",
        "completion_writeback_verified",
        "driver_status_verified",
        "driver_completion_descriptor_verified",
        "result_status_passed",
        "non_smoke_l4_activity",
        "stats_txt_present",
        "stats_semantics_present",
        "config_present",
        "nonzero_accelerator_activity",
    ]
    return {name: bool(proof.get(name, checks.get(name))) for name in names}


def build_step4_rows(
    expanded: Mapping[str, Any],
    local_rebuild: Mapping[str, Any],
    *,
    runroot: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    negative_rows: list[dict[str, Any]] = []
    runroot = Path(runroot)
    for expanded_row in expanded.get("rows", []) or []:
        if not isinstance(expanded_row, Mapping):
            continue
        run_dir = _path_from_runroot(runroot, expanded_row.get("run_dir", ""))
        proof_path = run_dir / "gem5_l4_proof.json"
        metrics_path = run_dir / "l4_interface_metrics.json"
        raw_path = run_dir / "raw_l4_interface_observations.json"
        request_path = run_dir / "simulation_request.json"
        result_path = run_dir / "simulation_result.raw.json"
        proof = _as_mapping(load_json(proof_path, {}) or {})
        metrics = _as_mapping(load_json(metrics_path, {}) or {})
        if expanded_row.get("proof_passed") is not True:
            negative_rows.append({
                "row_id": expanded_row.get("row_id"),
                "candidate_id": expanded_row.get("candidate_id"),
                "workload_case_id": expanded_row.get("workload_case_id"),
                "status": expanded_row.get("proof_status"),
                "descriptor_error_observed": expanded_row.get("descriptor_error_observed") is True,
                "proof_artifact": artifact_ref(proof_path),
                "claim_boundary": "Expected negative descriptor validation row; not performance or release evidence.",
            })
            continue
        candidate_id = str(expanded_row.get("candidate_id"))
        workload_case_id = str(expanded_row.get("workload_case_id"))
        row = {
            "schema_version": "dse.codesign.complete_dse_full_l4_evidence_row.v1",
            "row_id": f"{candidate_id}:{workload_case_id}",
            "source_row_id": expanded_row.get("row_id"),
            "candidate_id": candidate_id,
            "workload_case_id": workload_case_id,
            "backend": "gem5_systemc",
            "evidence_tier": "L4",
            "status": "passed_l4_runtime_only_mvp_partial",
            "claim_label": "mvp_partial_l4_runtime_only",
            "trusted_speedup_eligible": False,
            "transport_harness": "gem5_generic_accel_microarchitecture_v1",
            "gem5_l4_proof": proof,
            "l4_evidence": {
                "backend": "gem5_systemc",
                "evidence_tier": "L4",
                "transport_harness": "gem5_generic_accel_microarchitecture_v1",
                "gem5_binary": expanded.get("gem5_binary"),
                "gem5_binary_sha256": expanded.get("gem5_binary_sha256"),
                "local_rebuild_claim_supported": bool(local_rebuild.get("local_rebuild_claim_supported")),
                "local_rebuild_status": local_rebuild.get("status"),
                "proof_artifact": str(proof_path),
                "metrics_artifact": str(metrics_path) if metrics_path.exists() else None,
                "raw_observations_artifact": str(raw_path) if raw_path.exists() else None,
                "simulation_request_artifact": str(request_path) if request_path.exists() else None,
                "simulation_result_artifact": str(result_path) if result_path.exists() else None,
                "row_run_dir": str(run_dir),
            },
            "l4_interface_metrics": metrics,
            "raw_l4_interface_observations_artifact": str(raw_path) if raw_path.exists() else None,
            "proof_checks": proof_checks_passed(proof),
            "runtime_observations": {
                "driver_repeat": expanded_row.get("driver_repeat"),
                "gem5_returncode": expanded_row.get("gem5_returncode"),
                "elapsed_s": expanded_row.get("elapsed_s"),
                "log_markers": expanded_row.get("log_markers"),
                "metrics_status": expanded_row.get("metrics_status"),
            },
            "correctness": {
                "trusted_claim_eligible": False,
                "timing_only": True,
                "kernel_gate": {
                    "status": "blocked",
                    "reason": "GenericAccel L4 subsystem probe is not paired with trusted QE kernel correctness.",
                },
                "scf_physical_gate": {
                    "status": "blocked",
                    "reason": "GenericAccel L4 subsystem probe is not a QE full-SCF physical comparison.",
                },
            },
            "baseline_comparison": {
                "status": "blocked",
                "pure_software_qe_baseline": False,
                "baseline_status": "missing_for_generic_accel_l4_probe",
            },
            "calibration_consistency": {
                "status": "blocked",
                "trace_counter_consistent": False,
            },
            "blockers": [
                "synthetic_slot4_candidate_not_cdse_run2_candidate",
                "missing_candidate_crosswalk_to_run2_worklist",
                "missing_trusted_qe_kernel_correctness_for_speedup_claim",
                "missing_pure_software_qe_baseline_for_speedup_claim",
                "missing_l4_trace_counter_calibration_for_speedup_claim",
            ],
            "claim_boundary": (
                "Real gem5 GenericAccel software-visible proof row when proof_passed is true. It can feed "
                "Step4 L4 interface metrics, but it cannot claim l4_trusted_speedup or final release eligibility "
                "without explicit CDSE identity binding, QE correctness, baseline comparison, and calibration."
            ),
        }
        row["row_hash"] = stable_json_hash({k: v for k, v in row.items() if k != "row_hash"})
        rows.append(row)

        row_l4_dir = runroot / "rows" / candidate_id / workload_case_id / "l4_gem5"
        row_l4_dir.mkdir(parents=True, exist_ok=True)
        for source, target_name in [
            (proof_path, "gem5_l4_proof.json"),
            (metrics_path, "l4_interface_metrics.json"),
            (raw_path, "raw_l4_interface_observations.json"),
        ]:
            if source.exists():
                shutil.copy2(source, row_l4_dir / target_name)
    payload = {
        "schema_version": "dse.codesign.complete_dse_full_l4_evidence_rows.v1",
        "generated_at": now_iso(),
        "producer": PRODUCER,
        "source_expanded_matrix": str(runroot / "generic_accel_l4_expanded_proof_matrix.json"),
        "expected_runtime_pass_rows": expanded.get("passed_runtime_rows"),
        "row_count": len(rows),
        "rows": rows,
        "negative_validation_rows": negative_rows,
        "anti_downgrade_policy": {
            "synthetic_slot4_rows_are_not_cdse_candidate_rows": True,
            "l4_runtime_only_cannot_claim_trusted_speedup": True,
            "deliverable_complete": False,
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["rows_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "rows_hash"})
    return payload, rows


def build_preflight(
    expanded: Mapping[str, Any],
    local_rebuild: Mapping[str, Any],
    *,
    repo_root: Path,
    runroot: Path,
) -> dict[str, Any]:
    repo_root = Path(repo_root)
    runroot = Path(runroot)
    gem5_bin = Path(str(expanded.get("gem5_binary", "")))
    driver = repo_root / "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver"
    config = repo_root / "gem5_integration/configs/generic_accel_l4_test.py"
    generic_sim = repo_root / "model/generic_sim_backend/build/generic_sim"
    source_blockers = _source_blocker_ids(local_rebuild)
    local_verified = bool(local_rebuild.get("local_rebuild_claim_supported"))
    return {
        "schema_version": "dse.codesign.gem5_preflight.v1",
        "generated_at": now_iso(),
        "producer": PRODUCER,
        "status": "passed_runtime_and_local_rebuild_verified" if local_verified else "passed_runtime_external_binary_precise_rebuild_blocked",
        "gem5_binary_exists": gem5_bin.exists(),
        "driver_binary_exists": driver.exists(),
        "gem5_config_exists": config.exists(),
        "generic_sim_exists": generic_sim.exists(),
        "gem5_binary": artifact_ref(gem5_bin),
        "driver_binary": artifact_ref(driver),
        "gem5_config": artifact_ref(config),
        "generic_sim": artifact_ref(generic_sim),
        "runtime_preflight_blockers": [],
        "source_rebuild_blockers": source_blockers,
        "blockers": [] if local_verified else ["local_rebuild_not_proven_current_lane", *source_blockers],
        "local_rebuild_claim_supported": local_verified,
        "verified_local_rebuild_execution": local_rebuild.get("verified_execution"),
        "local_rebuild_probe_report": artifact_ref(runroot / "local_rebuild_probe_report.json"),
        "claim_boundary": (
            "Runtime replay prerequisites are tracked separately from local source rebuild blockers. "
            "Source/build reproducibility remains fail-closed unless local_rebuild_claim_supported is true."
        ),
    }


def build_reports(
    step4_payload: Mapping[str, Any],
    step4_rows: list[dict[str, Any]],
    worklist: Mapping[str, Any],
    *,
    runroot: Path,
    local_rebuild: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidates = sorted({str(row["candidate_id"]) for row in step4_rows})
    workloads = sorted({str(row["workload_case_id"]) for row in step4_rows})
    release_subset = {
        "schema_version": "dse.generic_accel.synthetic_l4_release_subset.v1",
        "release_subset_hash": stable_json_hash({"candidates": candidates, "scope": "generic_accel_l4_synthetic_only"}),
        "legal_candidate_ids": candidates,
        "claim_boundary": "Synthetic GenericAccel L4 probe candidates only; not equivalent to CDSE run2 candidate IDs.",
    }
    workload_suite = {
        "schema_version": "dse.generic_accel.synthetic_l4_workload_suite.v1",
        "manifest_hash": stable_json_hash({"workloads": workloads, "scope": "generic_accel_l4_synthetic_only"}),
        "workload_case_ids": workloads,
        "claim_boundary": "Synthetic GenericAccel L4 probe workloads only; not the six-class QE full-SCF suite.",
    }
    matrix = build_l4_evidence_matrix(release_subset, workload_suite, step4_rows)
    coverage = build_coverage_claim_report(matrix)
    matrix_rows = [row for row in matrix.get("rows", []) or [] if isinstance(row, Mapping)]
    blocker_counts = Counter()
    for row in matrix_rows:
        for blocker in row.get("blockers", []) or []:
            blocker_counts[str(blocker)] += 1
    gate_count = sum(
        1
        for row in matrix_rows
        if isinstance(row.get("gates"), Mapping) and row["gates"].get("real_l4_gem5_full_flow") is True
    )
    trusted_count = sum(1 for row in matrix_rows if row.get("trusted_speedup_eligible") is True)
    complete_report = {
        "schema_version": "dse.codesign.complete_dse_full_l4_report.v1",
        "generated_at": now_iso(),
        "producer": PRODUCER,
        "status": "blocked_or_partial",
        "release_subset_path": str(runroot / "generic_accel_l4_release_subset_manifest.json"),
        "workload_suite_path": str(runroot / "generic_accel_l4_workload_suite_manifest.json"),
        "gem5_preflight_path": str(runroot / "gem5_preflight.json"),
        "evidence_rows_path": str(runroot / "evidence_rows.json"),
        "step4_l4_evidence_rows_path": str(runroot / "step4_l4_evidence_rows.json"),
        "l4_evidence_matrix_path": str(runroot / "l4_evidence_matrix.json"),
        "coverage_claim_report_path": str(runroot / "coverage_claim_report.json"),
        "candidate_workload_l4_coverage_matrix_path": str(runroot / "candidate_workload_l4_coverage_matrix.json"),
        "expected_row_count": matrix.get("expected_row_count"),
        "row_count": len(step4_rows),
        "matrix_row_count": matrix.get("row_count"),
        "blocked_row_count": coverage.get("blocked_row_count"),
        "claims": {
            "foundation_artifacts_emitted": True,
            "mvp_partial": bool(step4_rows),
            "deliverable_complete": False,
            "l4_trusted_speedup": False,
        },
        "claim_boundaries": {
            "foundation": "Expanded gem5 L4 runtime proofs, Step4 rows, matrices, hashes, and replay contract exist.",
            "mvp_partial": "L4 runtime rows exist but remain untrusted for speedup/release because CDSE identity, QE correctness, baseline, calibration, PPA, and full-SCF gates are absent.",
            "deliverable_complete": "False until every current-goal CDSE candidate/workload row has trusted L4, QE, PPA, and release-gate evidence.",
        },
        "evidence_summary": {
            "expanded_runtime_pass_rows": len(step4_rows),
            "expanded_negative_validation_rows": len(step4_payload.get("negative_validation_rows", []) or []),
            "real_l4_gem5_full_flow_rows": gate_count,
            "trusted_speedup_eligible_rows": trusted_count,
            "actual_cdse_candidate_kernel_target_axis_count": worklist.get("candidate_kernel_target_axis_count"),
            "actual_cdse_gate_row_count": worklist.get("gate_row_count"),
            "actual_cdse_trusted_pass_count": worklist.get("trusted_pass_count"),
            "actual_cdse_mapped_l4_rows": 0,
            "local_rebuild_claim_supported": bool(_as_mapping(local_rebuild).get("local_rebuild_claim_supported")),
        },
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "coverage": {
            "all_rows_present_as_matrix_records": coverage.get("all_rows_present"),
            "blocked_row_count": coverage.get("blocked_row_count"),
            "claim_labels": coverage.get("claim_labels"),
            "claims": coverage.get("claims"),
        },
        "prompt_to_artifact_checklist": [
            {
                "requirement": "local source rebuild route probed",
                "artifact": str(runroot / "local_rebuild_probe_report.json"),
                "passed": bool(local_rebuild),
                "status": _as_mapping(local_rebuild).get("probe_status", _as_mapping(local_rebuild).get("status")),
            },
            {
                "requirement": "local source rebuild and replay verified",
                "artifact": str(runroot / "local_rebuild_contract.json"),
                "passed": bool(_as_mapping(local_rebuild).get("local_rebuild_claim_supported")),
                "status": _as_mapping(local_rebuild).get("status", "missing_local_rebuild_status"),
            },
            {"requirement": "external binary provenance recorded", "artifact": str(runroot / "gem5_binary_provenance.json"), "passed": bool(step4_rows)},
            {"requirement": "expanded multi-request L4 proof rows", "artifact": str(runroot / "generic_accel_l4_expanded_proof_matrix.json"), "passed": bool(step4_rows)},
            {"requirement": "Step4 canonical L4 evidence rows emitted", "artifact": str(runroot / "step4_l4_evidence_rows.json"), "passed": bool(step4_rows)},
            {"requirement": "actual CDSE run2 candidate mapping", "artifact": str(runroot / "candidate_workload_l4_coverage_matrix.json"), "passed": False},
            {"requirement": "release gate binding remains fail-closed", "artifact": str(runroot / "release_gate_l4_binding_status.json"), "passed": True},
            {"requirement": "global deliverable_complete", "artifact": str(runroot / "complete_dse_full_l4_evidence_report.json"), "passed": False},
        ],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    complete_report["report_hash"] = stable_json_hash({k: v for k, v in complete_report.items() if k != "report_hash"})
    return release_subset, workload_suite, matrix, coverage | {"_complete_report": complete_report}


def _load_crosswalk(path: Path | None) -> Mapping[str, Any]:
    payload = load_json(path, {}) if path else {}
    return payload if isinstance(payload, Mapping) else {}


def _confidence_one(entry: Mapping[str, Any]) -> bool:
    try:
        return float(entry.get("confidence", 0.0)) >= 1.0
    except (TypeError, ValueError):
        return False


def _normalize_candidate_crosswalk(path: Path | None) -> dict[str, Any]:
    payload = _load_crosswalk(path)
    raw = payload.get("candidate_crosswalk", payload.get("mappings", payload))
    raw_pairs = raw if isinstance(raw, Mapping) else {}
    pairs: dict[str, str] = {}
    valid_pairs: dict[str, str] = {}
    invalid_entries: list[dict[str, Any]] = []
    for source_id, entry in raw_pairs.items():
        source = str(source_id)
        if isinstance(entry, str):
            pairs[source] = entry
            invalid_entries.append({"source_id": source, "reason": "candidate_crosswalk_entry_must_be_structured"})
            continue
        if not isinstance(entry, Mapping):
            invalid_entries.append({"source_id": source, "reason": "candidate_crosswalk_entry_not_object"})
            continue
        target = str(entry.get("l4_candidate_id") or entry.get("target_candidate_id") or "").strip()
        scope = str(entry.get("equivalence_scope") or entry.get("identity_equivalence") or "").strip()
        if target:
            pairs[source] = target
        if not target:
            invalid_entries.append({"source_id": source, "reason": "missing_l4_candidate_id"})
        elif scope not in VALID_CANDIDATE_EQUIVALENCE_SCOPES:
            invalid_entries.append({"source_id": source, "target_id": target, "reason": "unsupported_candidate_equivalence_scope", "equivalence_scope": scope or None})
        elif not _confidence_one(entry):
            invalid_entries.append({"source_id": source, "target_id": target, "reason": "candidate_crosswalk_confidence_below_one", "confidence": entry.get("confidence")})
        else:
            valid_pairs[source] = target
    return {"path": str(path) if path else None, "pairs": pairs, "valid_structured_pairs": valid_pairs, "invalid_entries": invalid_entries}


def _normalize_workload_crosswalk(path: Path | None) -> dict[str, Any]:
    payload = _load_crosswalk(path)
    raw = payload.get("workload_crosswalk", payload.get("mappings", payload))
    raw_pairs = raw if isinstance(raw, Mapping) else {}
    pairs: dict[str, list[str]] = {}
    valid_pairs: dict[str, list[str]] = {}
    invalid_entries: list[dict[str, Any]] = []
    for source_id, entry in raw_pairs.items():
        source = str(source_id)
        targets: list[str] = []
        if isinstance(entry, str):
            targets = [entry]
            invalid_entries.append({"source_id": source, "reason": "workload_crosswalk_entry_must_be_structured"})
        elif isinstance(entry, Sequence) and not isinstance(entry, (str, bytes, bytearray, Mapping)):
            targets = [str(item) for item in entry if item]
            invalid_entries.append({"source_id": source, "reason": "workload_crosswalk_entry_must_be_structured"})
        elif isinstance(entry, Mapping):
            raw_targets = entry.get("l4_workload_case_ids") or entry.get("target_workload_case_ids") or entry.get("l4_workload_case_id") or entry.get("target_workload_case_id")
            if isinstance(raw_targets, list):
                targets = [str(item) for item in raw_targets if item]
            elif raw_targets:
                targets = [str(raw_targets)]
            scope = str(entry.get("equivalence_scope") or entry.get("identity_equivalence") or "").strip()
            if not targets:
                invalid_entries.append({"source_id": source, "reason": "missing_l4_workload_case_ids"})
            elif scope not in VALID_WORKLOAD_EQUIVALENCE_SCOPES:
                invalid_entries.append({"source_id": source, "target_ids": targets, "reason": "unsupported_workload_equivalence_scope", "equivalence_scope": scope or None})
            elif not _confidence_one(entry):
                invalid_entries.append({"source_id": source, "target_ids": targets, "reason": "workload_crosswalk_confidence_below_one", "confidence": entry.get("confidence")})
            else:
                valid_pairs[source] = targets
        else:
            invalid_entries.append({"source_id": source, "reason": "workload_crosswalk_entry_not_object"})
        if targets:
            pairs[source] = targets
    return {"path": str(path) if path else None, "pairs": pairs, "valid_structured_pairs": valid_pairs, "invalid_entries": invalid_entries}


def _work_item_workload_keys(item: Mapping[str, Any]) -> list[str]:
    keys = []
    for key in ("workload_case_id", "kernel_id", "kernel", "case_id"):
        value = item.get(key)
        if value:
            keys.append(str(value))
    return keys


def _trusted_row(row: Mapping[str, Any]) -> bool:
    return row.get("trusted_speedup_eligible") is True or row.get("claim_label") == "l4_trusted_speedup"


def _mapped_cdse_rows(
    work_items: Sequence[Mapping[str, Any]],
    step4_rows: Sequence[Mapping[str, Any]],
    candidate_crosswalk: Mapping[str, Any],
    workload_crosswalk: Mapping[str, Any],
) -> list[dict[str, Any]]:
    cand_pairs = _as_mapping(candidate_crosswalk.get("valid_structured_pairs"))
    workload_pairs = _as_mapping(workload_crosswalk.get("valid_structured_pairs"))
    evidence = {(str(row.get("candidate_id")), str(row.get("workload_case_id"))): row for row in step4_rows}
    mapped: list[dict[str, Any]] = []
    for item in work_items:
        cdse_candidate = str(item.get("candidate_id") or "")
        l4_candidate = cand_pairs.get(cdse_candidate)
        if not l4_candidate:
            continue
        target_workloads: list[str] = []
        matched_key = None
        for key in _work_item_workload_keys(item):
            if key in workload_pairs:
                target_workloads.extend(str(target) for target in workload_pairs[key])
                matched_key = key
        for l4_workload in sorted(dict.fromkeys(target_workloads)):
            row = evidence.get((str(l4_candidate), str(l4_workload)))
            if row is None:
                continue
            mapped.append({
                "cdse_candidate_id": cdse_candidate,
                "cdse_kernel_id": item.get("kernel_id"),
                "cdse_target_platform_kind": item.get("target_platform_kind"),
                "l4_candidate_id": str(l4_candidate),
                "l4_workload_case_id": str(l4_workload),
                "workload_crosswalk_key": matched_key,
                "source_l4_row_id": row.get("row_id"),
                "l4_claim_label": row.get("claim_label"),
                "trusted_l4_speedup_eligible": _trusted_row(row),
                "cdse_claimable": item.get("claimable"),
                "cdse_dominant_status": item.get("dominant_status"),
                "cdse_blocker_ids": item.get("blocker_ids", []),
            })
    return mapped


def build_candidate_workload_coverage(
    expanded: Mapping[str, Any],
    matrix: Mapping[str, Any],
    worklist: Mapping[str, Any],
    step4_rows: Sequence[Mapping[str, Any]],
    *,
    runroot: Path,
    slot2_worklist: Path | None = None,
    candidate_crosswalk: Path | None = None,
    workload_crosswalk: Path | None = None,
) -> dict[str, Any]:
    work_items = [item for item in worklist.get("work_items", []) or [] if isinstance(item, Mapping)]
    sample = [
        {
            "candidate_id": item.get("candidate_id"),
            "kernel_id": item.get("kernel_id"),
            "target_platform_kind": item.get("target_platform_kind"),
            "dominant_status": item.get("dominant_status"),
            "claimable": item.get("claimable"),
            "gate_row_count": item.get("gate_row_count"),
            "blocker_ids": item.get("blocker_ids", []),
        }
        for item in work_items[:12]
    ]
    passed_rows = [row for row in expanded.get("rows", []) or [] if isinstance(row, Mapping) and row.get("proof_passed") is True]
    negative_rows = [row for row in expanded.get("rows", []) or [] if isinstance(row, Mapping) and row.get("descriptor_error_observed") is True]
    cand_x = _normalize_candidate_crosswalk(candidate_crosswalk)
    work_x = _normalize_workload_crosswalk(workload_crosswalk)
    mapped_rows = _mapped_cdse_rows(work_items, step4_rows, cand_x, work_x)
    mapped_trusted = [row for row in mapped_rows if row.get("trusted_l4_speedup_eligible") is True]
    if not cand_x["valid_structured_pairs"] or not work_x["valid_structured_pairs"]:
        status = "blocked_no_explicit_mapping_from_slot4_synthetic_rows_to_cdse_worklist"
    elif not mapped_rows:
        status = "blocked_crosswalk_present_no_matching_l4_evidence_rows"
    elif not mapped_trusted:
        status = "blocked_mapped_l4_rows_not_trusted_for_release"
    else:
        status = "blocked_mapped_l4_rows_require_non_l4_release_gates"

    blockers = []
    if not cand_x["valid_structured_pairs"] or not work_x["valid_structured_pairs"]:
        blockers.append("missing_candidate_workload_crosswalk")
    if mapped_rows and not mapped_trusted:
        blockers.append("mapped_l4_rows_not_trusted_for_speedup_claim")
    if cand_x["invalid_entries"]:
        blockers.append("candidate_crosswalk_invalid_or_weak")
    if work_x["invalid_entries"]:
        blockers.append("workload_crosswalk_invalid_or_weak")
    blockers.extend([
        "slot4_synthetic_l4_rows_not_mapped_to_run2_cdse_candidates" if not mapped_rows else "slot4_l4_rows_mapped_but_still_runtime_only",
        "actual_run2_worklist_trusted_pass_count_zero" if int(worklist.get("trusted_pass_count") or 0) == 0 else "actual_run2_worklist_trusted_pass_count_not_sufficient_for_release",
        "missing_qe_full_scf_correctness_and_baseline_for_l4_speedup",
        "missing_candidate_specific_ppa_gate_evidence",
    ])
    blockers = sorted(dict.fromkeys(blockers))
    payload = {
        "schema_version": "dse.generic_accel.candidate_workload_l4_coverage_matrix.v1",
        "generated_at": now_iso(),
        "producer": PRODUCER,
        "status": status,
        "deliverable_complete": False,
        "expanded_slot4_l4_scope": {
            "status": "runtime_l4_proof_available_for_synthetic_scope",
            "passed_runtime_row_count": len(passed_rows),
            "expected_negative_row_count": len(negative_rows),
            "candidate_ids": sorted({str(row.get("candidate_id")) for row in passed_rows}),
            "workload_case_ids": sorted({str(row.get("workload_case_id")) for row in passed_rows}),
            "cartesian_expected_row_count": matrix.get("expected_row_count"),
            "matrix_row_count": matrix.get("row_count"),
            "matrix_blocked_row_count": matrix.get("blocked_row_count"),
            "matrix_ref": str(runroot / "l4_evidence_matrix.json"),
            "proof_rows": [
                {
                    "source_row_id": row.get("row_id"),
                    "candidate_id": row.get("candidate_id"),
                    "workload_case_id": row.get("workload_case_id"),
                    "proof_passed": row.get("proof_passed"),
                    "proof_artifact": str(_path_from_runroot(runroot, row.get("run_dir")) / "gem5_l4_proof.json"),
                    "metrics_artifact": str(_path_from_runroot(runroot, row.get("run_dir")) / "l4_interface_metrics.json"),
                }
                for row in passed_rows
            ],
            "negative_validation_rows": [
                {
                    "source_row_id": row.get("row_id"),
                    "candidate_id": row.get("candidate_id"),
                    "workload_case_id": row.get("workload_case_id"),
                    "descriptor_error_observed": row.get("descriptor_error_observed"),
                    "proof_artifact": str(_path_from_runroot(runroot, row.get("run_dir")) / "gem5_l4_proof.json"),
                }
                for row in negative_rows
            ],
        },
        "actual_run2_cdse_scope": {
            "status": status,
            "worklist_artifact": artifact_ref(slot2_worklist),
            "worklist_schema_version": worklist.get("schema_version"),
            "worklist_status": worklist.get("status"),
            "worklist_hash": worklist.get("worklist_hash"),
            "candidate_kernel_target_axis_count": worklist.get("candidate_kernel_target_axis_count"),
            "gate_row_count": worklist.get("gate_row_count"),
            "trusted_pass_count": worklist.get("trusted_pass_count"),
            "mapped_l4_evidence_row_count": len(mapped_rows),
            "mapped_trusted_l4_evidence_row_count": len(mapped_trusted),
            "mapped_rows": mapped_rows[:100],
            "sample_blocked_work_items": sample,
        },
        "crosswalk_validation": {
            "candidate_crosswalk": cand_x,
            "workload_crosswalk": work_x,
        },
        "binding_policy": {
            "synthetic_slot4_candidate_equivalence_to_cdse_disallowed_without_crosswalk": True,
            "structured_crosswalk_required_for_mapping_count": True,
            "mapped_runtime_only_rows_do_not_create_trusted_speedup": True,
            "required_next_artifact": "explicit candidate/workload crosswalk plus per-CDSE L4 request generation with trusted QE/PPA gates",
        },
        "blockers": blockers,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["coverage_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "coverage_hash"})
    return payload


def build_release_binding(
    local_rebuild: Mapping[str, Any],
    expanded: Mapping[str, Any],
    coverage_matrix: Mapping[str, Any],
    *,
    runroot: Path,
    local_rebuild_contract: Mapping[str, Any] | None = None,
    cdse_intake_queue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    actual = _as_mapping(coverage_matrix.get("actual_run2_cdse_scope"))
    local_contract = _as_mapping(local_rebuild_contract)
    intake = _as_mapping(cdse_intake_queue)
    local_verified = bool(local_rebuild.get("local_rebuild_claim_supported"))
    local_blockers = [] if local_verified else ["local_rebuild_not_proven_current_lane", *_source_blocker_ids(local_rebuild)]
    blockers = sorted(dict.fromkeys([
        *local_blockers,
        *[str(item) for item in coverage_matrix.get("blockers", []) or []],
        "run2_candidate_specific_ppa_evidence_missing",
        "run3_trusted_full_scf_evidence_missing",
        "run1_release_gate_inputs_missing",
        "target_specific_fpga_asic_recommendation_gates_missing",
    ]))
    payload = {
        "schema_version": "dse.generic_accel.release_gate_l4_binding_status.v1",
        "generated_at": now_iso(),
        "producer": PRODUCER,
        "status": "blocked_release_gate_inputs_partial_l4_bundle_available",
        "deliverable_complete": False,
        "l4_bundle_available_as_step4_input": True,
        "local_rebuild_status": {
            "status": local_rebuild.get("status"),
            "local_rebuild_claim_supported": local_verified,
            "rebuild_executed": bool(local_rebuild.get("rebuild_executed")),
            "replay_verified_with_rebuilt_binary": bool(local_rebuild.get("replay_verified_with_rebuilt_binary")),
            "verified_execution": local_rebuild.get("verified_execution"),
            "blockers": local_rebuild.get("blockers", []),
            "report": str(runroot / "local_rebuild_probe_report.json"),
        },
        "runtime_l4_proof_status": {
            "status": (
                "passed_expanded_local_rebuilt_binary_runtime_route"
                if local_verified and expanded.get("passed_runtime_rows")
                else "passed_expanded_external_binary_runtime_route"
                if expanded.get("passed_runtime_rows")
                else "blocked_no_runtime_rows"
            ),
            "gem5_binary": expanded.get("gem5_binary"),
            "gem5_binary_sha256": expanded.get("gem5_binary_sha256"),
            "passed_runtime_rows": expanded.get("passed_runtime_rows"),
            "expected_negative_rows": expanded.get("expected_negative_rows"),
            "matrix": str(runroot / "generic_accel_l4_expanded_proof_matrix.json"),
        },
        "release_consumable_integration_status": {
            "status": "blocked_actual_cdse_mapping_and_non_l4_gates_missing",
            "step4_evidence_rows": str(runroot / "step4_l4_evidence_rows.json"),
            "candidate_workload_l4_coverage_matrix": str(runroot / "candidate_workload_l4_coverage_matrix.json"),
            "cdse_l4_binding_intake_queue": str(runroot / "cdse_l4_binding_intake_queue.json"),
            "local_rebuild_contract": str(runroot / "local_rebuild_contract.json"),
            "l4_evidence_matrix": str(runroot / "l4_evidence_matrix.json"),
            "coverage_claim_report": str(runroot / "coverage_claim_report.json"),
            "complete_l4_report": str(runroot / "complete_dse_full_l4_evidence_report.json"),
            "actual_cdse_mapped_l4_rows": actual.get("mapped_l4_evidence_row_count"),
            "actual_cdse_mapped_trusted_l4_rows": actual.get("mapped_trusted_l4_evidence_row_count"),
            "cdse_binding_intake_status": intake.get("status"),
            "cdse_binding_intake_work_item_count": intake.get("work_item_count"),
            "local_rebuild_contract_status": local_contract.get("status"),
            "local_rebuild_selected_source_provider": (
                _as_mapping(local_contract.get("selected_source_provider")).get("root")
                if local_contract.get("selected_source_provider")
                else None
            ),
        },
        "final_recommendation_chain_support": {
            "supports": [
                "GenericAccel descriptor/read/decode/uarch/completion software-visible L4 subsystem evidence",
                "Step4 canonical L4 interface metrics for synthetic proof rows",
                "descriptor validation negative-path evidence when present",
                *(
                    ["local gem5 rebuild plus replay over matching rebuilt binary hash"]
                    if local_verified
                    else []
                ),
            ],
            "does_not_support": [
                *([] if local_verified else ["local gem5 source rebuild closure"]),
                "run2 CDSE candidate-specific trusted L4 coverage",
                "QE full-SCF correctness or six-class closure",
                "FPGA/ASIC PPA hard gates",
                "global release-gate deliverable_complete",
            ],
        },
        "blockers": blockers,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["binding_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "binding_hash"})
    return payload


def _source_candidate_ready(candidate: Mapping[str, Any]) -> bool:
    if not candidate.get("exists") or not candidate.get("sconstruct_exists") or not candidate.get("generic_accel_dir_exists"):
        return False
    active_vs_source = _as_mapping(candidate.get("active_vs_source"))
    if not active_vs_source:
        files = _as_mapping(candidate.get("generic_accel_files"))
        return all(_as_mapping(files.get(name)).get("exists") for name in GENERIC_ACCEL_FILES)
    for name in GENERIC_ACCEL_FILES:
        info = _as_mapping(active_vs_source.get(name))
        if not info.get("source_exists"):
            return False
    return True


def _select_source_provider(local_rebuild: Mapping[str, Any]) -> Mapping[str, Any] | None:
    candidates = [item for item in local_rebuild.get("source_candidates", []) or [] if isinstance(item, Mapping)]
    for candidate in candidates:
        if _source_candidate_ready(candidate):
            return candidate
    return None


def _select_swig_provider(local_rebuild: Mapping[str, Any]) -> str | None:
    search = _as_mapping(local_rebuild.get("swig_provider_search"))
    usable = search.get("usable", []) if isinstance(search.get("usable"), Sequence) else []
    for item in usable:
        if item:
            return str(item)
    for check in local_rebuild.get("swig_checks", []) or []:
        if not isinstance(check, Mapping) or check.get("returncode") != 0:
            continue
        cmd = check.get("cmd", [])
        if isinstance(cmd, Sequence) and cmd:
            return str(cmd[0])
    return None


def build_local_rebuild_contract(local_rebuild: Mapping[str, Any], *, repo_root: Path, runroot: Path) -> dict[str, Any]:
    """Build a fail-closed local gem5 rebuild contract without executing rebuilds."""
    repo_root = Path(repo_root)
    runroot = Path(runroot)
    selected = _select_source_provider(local_rebuild)
    swig = _select_swig_provider(local_rebuild)
    execution = _as_mapping(local_rebuild.get("verified_execution"))
    rebuild_verified = bool(local_rebuild.get("local_rebuild_claim_supported"))
    if rebuild_verified:
        status = "local_rebuild_and_replay_verified"
    elif selected is None:
        status = "blocked_missing_complete_gem5_source_provider"
    elif not swig:
        status = "blocked_missing_swig_provider"
    else:
        status = "ready_for_explicit_local_rebuild_attempt"
    source_root = str(_as_mapping(selected).get("root") or repo_root / "gem5_integration/gem5")
    rebuild_commands = [
        f'cd "{source_root}"',
        f'export SWIG_BIN="{swig or "<provide-swig-provider>"}"',
        'scons build/X86/gem5.opt -j"${JOBS:-2}"',
        "sha256sum build/X86/gem5.opt",
        f'GEM5_BIN="{source_root}/build/X86/gem5.opt" RUNROOT="{runroot}" bash "{runroot / "replay_contract.sh"}"',
    ]
    blockers = [] if rebuild_verified else sorted(dict.fromkeys(
        _source_blocker_ids(local_rebuild)
        + ([] if selected is not None else ["missing_complete_gem5_source_provider"])
        + ([] if swig else ["swig_provider_missing"])
    ))
    payload = {
        "schema_version": "dse.generic_accel.local_rebuild_contract.v1",
        "generated_at": now_iso(),
        "producer": PRODUCER,
        "status": status,
        "local_rebuild_claim_supported": rebuild_verified,
        "rebuild_executed": bool(local_rebuild.get("rebuild_executed")),
        "replay_verified_with_rebuilt_binary": bool(local_rebuild.get("replay_verified_with_rebuilt_binary")),
        "verified_execution": dict(execution) if execution else None,
        "current_worktree_source_root": str(repo_root / "gem5_integration/gem5"),
        "selected_source_provider": dict(selected) if selected is not None else None,
        "swig_provider": swig,
        "source_provider_status": "available_complete_source_provider" if selected is not None else "missing_complete_source_provider",
        "swig_provider_status": "available" if swig else "missing",
        "rebuild_commands": rebuild_commands,
        "expected_outputs": {
            "gem5_binary": f"{source_root}/build/X86/gem5.opt",
            "gem5_binary_sha256": str(runroot / "local_rebuild_gem5_binary.sha256"),
            "replay_log_dir": str(runroot / "logs"),
        },
        "non_destructive_policy": {
            "contract_generation_does_not_run_scons": True,
            "no_sudo_or_system_package_mutation": True,
            "external_source_provider_is_read_only_until_operator_runs_contract": True,
        },
        "upstream_probe_report": str(runroot / "local_rebuild_probe_report.json"),
        "blockers": blockers,
        "claim_boundary": "A rebuild contract is replay infrastructure. It is not a local rebuild proof until the script runs, records a rebuilt gem5.opt hash, and the replay contract passes with that rebuilt binary.",
    }
    payload["contract_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "contract_hash"})
    return payload


def write_local_rebuild_contract_script(contract: Mapping[str, Any], *, runroot: Path) -> None:
    runroot = Path(runroot)
    selected = _as_mapping(contract.get("selected_source_provider"))
    source_default = selected.get("root") or ""
    swig_default = contract.get("swig_provider") or ""
    text = f'''#!/usr/bin/env bash
set -euo pipefail

RUNROOT="${{RUNROOT:-{runroot}}}"
SOURCE_ROOT="${{SOURCE_ROOT:-{source_default}}}"
SWIG_BIN="${{SWIG_BIN:-{swig_default}}}"
JOBS="${{JOBS:-2}}"
LOG_DIR="$RUNROOT/logs"
LOG="$LOG_DIR/local_rebuild_contract_$(date -u +%Y%m%dT%H%M%SZ).log"
mkdir -p "$LOG_DIR"

run_step() {{
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) :: $* =====" | tee -a "$LOG"
  "$@" 2>&1 | tee -a "$LOG"
}}

if [[ -z "$SOURCE_ROOT" || ! -f "$SOURCE_ROOT/SConstruct" ]]; then
  echo "SOURCE_ROOT missing SConstruct: $SOURCE_ROOT" | tee -a "$LOG"
  exit 3
fi
if [[ -z "$SWIG_BIN" || ! -x "$SWIG_BIN" ]]; then
  echo "SWIG_BIN missing or not executable: $SWIG_BIN" | tee -a "$LOG"
  echo "Set SWIG_BIN to a lane-local provider; this script intentionally avoids privileged package installation." | tee -a "$LOG"
  exit 4
fi

run_step "$SWIG_BIN" -version
cd "$SOURCE_ROOT"
run_step scons build/X86/gem5.opt -j"$JOBS"
run_step test -x build/X86/gem5.opt
sha256sum build/X86/gem5.opt | tee "$RUNROOT/local_rebuild_gem5_binary.sha256" | tee -a "$LOG"

echo "Local rebuild binary: $SOURCE_ROOT/build/X86/gem5.opt" | tee -a "$LOG"
echo "Next: GEM5_BIN=$SOURCE_ROOT/build/X86/gem5.opt RUNROOT=$RUNROOT bash $RUNROOT/replay_contract.sh" | tee -a "$LOG"
'''
    path = runroot / "local_rebuild_contract.sh"
    write_text(path, text)
    path.chmod(0o755)


def _safe_fragment(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "unknown")).strip("_")
    return text or "unknown"


def build_cdse_l4_binding_intake_queue(worklist: Mapping[str, Any], coverage_matrix: Mapping[str, Any], *, runroot: Path) -> dict[str, Any]:
    work_items = [item for item in worklist.get("work_items", []) or [] if isinstance(item, Mapping)]
    actual = _as_mapping(coverage_matrix.get("actual_run2_cdse_scope"))
    mapped_count = int(actual.get("mapped_l4_evidence_row_count") or 0)
    mapped_trusted_count = int(actual.get("mapped_trusted_l4_evidence_row_count") or 0)
    if not work_items:
        status = "blocked_missing_cdse_worklist"
    elif mapped_count == 0:
        status = "awaiting_cdse_l4_binding_inputs"
    elif mapped_trusted_count == 0:
        status = "mapped_runtime_only_requires_trust_gates"
    else:
        status = "awaiting_non_l4_release_gates"
    queue_items = []
    required_artifacts = [
        "explicit_candidate_workload_crosswalk",
        "cdse_bound_simulation_request",
        "gem5_l4_proof_passed",
        "l4_interface_metrics",
        "trusted_qe_kernel_correctness",
        "pure_software_qe_baseline",
        "trace_counter_calibration",
        "target_specific_ppa_gate_evidence",
    ]
    for item in work_items:
        candidate = str(item.get("candidate_id") or "")
        kernel = str(item.get("kernel_id") or item.get("workload_case_id") or item.get("kernel") or "")
        target = str(item.get("target_platform_kind") or item.get("target") or "")
        base = Path("cdse_l4_requests") / _safe_fragment(candidate) / _safe_fragment(kernel) / _safe_fragment(target)
        queue_items.append({
            "intake_id": f"{_safe_fragment(candidate)}:{_safe_fragment(kernel)}:{_safe_fragment(target)}",
            "candidate_id": candidate,
            "kernel_id": kernel,
            "target_platform_kind": target,
            "claimable": item.get("claimable"),
            "dominant_status": item.get("dominant_status"),
            "gate_row_count": item.get("gate_row_count"),
            "source_blocker_ids": item.get("blocker_ids", []),
            "current_l4_binding_status": "awaiting_cdse_bound_l4_request",
            "expected_l4_request_artifact": str(base / "simulation_request.json"),
            "expected_l4_proof_artifact": str(base / "gem5_l4_proof.json"),
            "expected_l4_metrics_artifact": str(base / "l4_interface_metrics.json"),
            "required_artifacts": required_artifacts,
            "trusted_speedup_eligible_after_intake": False,
        })
    payload = {
        "schema_version": "dse.generic_accel.cdse_l4_binding_intake_queue.v1",
        "generated_at": now_iso(),
        "producer": PRODUCER,
        "status": status,
        "deliverable_complete": False,
        "worklist_schema_version": worklist.get("schema_version"),
        "worklist_status": worklist.get("status"),
        "worklist_hash": worklist.get("worklist_hash"),
        "work_item_count": len(work_items),
        "actual_cdse_mapped_l4_rows": mapped_count,
        "actual_cdse_mapped_trusted_l4_rows": mapped_trusted_count,
        "queue_items": queue_items,
        "queue_truncated": False,
        "intake_policy": {
            "explicit_crosswalk_required": True,
            "cdse_bound_requests_required": True,
            "runtime_l4_rows_alone_do_not_create_speedup_claims": True,
            "non_l4_qe_baseline_calibration_and_ppa_gates_required": True,
        },
        "claim_boundary": "This queue is the contract for future run2 true-candidate L4 intake. It does not map synthetic slot4 rows to CDSE candidates and does not make any row trusted until all listed artifacts are present and adjudicated.",
    }
    payload["queue_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "queue_hash"})
    return payload


def build_repair_queue(local_rebuild: Mapping[str, Any], coverage_matrix: Mapping[str, Any]) -> dict[str, Any]:
    local_verified = bool(local_rebuild.get("local_rebuild_claim_supported"))
    items = [
        {
            "id": "restore_lane_gem5_source_tree",
            "priority": "P0",
            "status": "source_provider_rebuild_verified_current_worktree_still_gitlink" if local_verified else "blocked_ready_to_execute",
            "owner_lane": "slot4",
            "blocker": (
                "current worktree gem5_integration/gem5 remains a gitlink/empty dir, but a recorded complete source provider rebuilt and replayed"
                if local_verified
                else "current worktree gem5_integration/gem5 is a gitlink/empty dir without SConstruct"
            ),
            "next_commands": [
                "verify .gitmodules/submodule mapping or create a lane-owned complete gem5 source checkout",
                "copy/graft GenericAccel source files into lane-owned gem5 src/dev/generic_accel only after source provenance is recorded",
            ],
            "done_when": "gem5_integration/gem5/SConstruct and src/dev/generic_accel/* exist in the lane worktree with hashes recorded",
        },
        {
            "id": "provide_swig_for_gem5_build",
            "priority": "P0",
            "status": "completed_lane_local_provider_recorded" if local_verified else "blocked_missing_dependency_provider",
            "owner_lane": "slot4",
            "blocker": "lane-local SWIG provider was used for the recorded rebuild" if local_verified else "swig not found in PATH and bounded local provider search found no usable provider",
            "next_commands": [
                "locate a non-system swig provider in conda/module/local tool cache or add a documented lane-local provider",
                "rerun: command -v swig && swig -version",
            ],
            "done_when": "swig -version succeeds without sudo/apt/yum and provider path is recorded",
        },
        {
            "id": "local_gem5_rebuild_preflight",
            "priority": "P0",
            "status": "completed_rebuild_and_replay_verified" if local_verified else "pending_after_source_and_swig",
            "owner_lane": "slot4",
            "blocker": "resolved for GenericAccel L4 subsystem replay bundle" if local_verified else "local source rebuild not proven",
            "next_commands": [
                "cd gem5_integration/gem5 && scons build/X86/gem5.opt -j2",
                "hash build/X86/gem5.opt and rerun replay_contract.sh with GEM5_BIN pointing to the rebuilt binary",
            ],
            "done_when": "local rebuilt gem5.opt hash plus expanded matrix replay are recorded in the same runroot",
        },
        {
            "id": "cdse_candidate_l4_crosswalk_and_requests",
            "priority": "P0",
            "status": "blocked_missing_mapping" if coverage_matrix.get("actual_run2_cdse_scope", {}).get("mapped_l4_evidence_row_count", 0) == 0 else "mapped_rows_present_but_not_trusted",
            "owner_lane": "slot4+slot2",
            "blocker": "slot4 synthetic rows are not trusted run2 CDSE candidate/workload rows",
            "next_commands": [
                "derive candidate/workload crosswalk from run2 worklist and Step2 candidate records",
                "generate per-CDSE GenericAccel simulation_request.json rows for required kernels/workloads",
                "rerun expanded gem5 matrix over mapped rows and regenerate Step4 evidence rows",
            ],
            "done_when": "candidate_workload_l4_coverage_matrix actual_run2_cdse_scope mapped_trusted_l4_evidence_row_count > 0 with explicit crosswalk artifacts",
        },
        {
            "id": "run2_candidate_specific_ppa_execution",
            "priority": "P0",
            "status": "blocked_missing_input_evidence",
            "owner_lane": "slot2",
            "blocker": "candidate-specific golden/sim/synth/Vivado/DC rows remain trusted_pass_count=0",
            "next_commands": [
                "execute dft_hardware_tie_breaker_execution_queue rows on IC/EDA route",
                "parse and adjudicate target-specific PPA evidence without cross-target substitution",
            ],
            "done_when": "run2 worklist trusted_pass_count increases with target-specific PPA gate artifacts",
        },
        {
            "id": "run3_trusted_full_scf_upgrade",
            "priority": "P0",
            "status": "blocked_qe_physical_evidence",
            "owner_lane": "slot3",
            "blocker": "trusted full-SCF pair count remains unavailable for final L4 speedup/release claims",
            "next_commands": [
                "repair QE baseline/accelerated full-SCF physical comparison path",
                "replace proxy-recovered rows with trusted QE-consumed kernel numeric evidence",
            ],
            "done_when": "trusted_full_scf_pair_count > 0 with required physical error metrics present",
        },
    ]
    payload = {
        "schema_version": "dse.generic_accel.l4_repair_queue.v1",
        "generated_at": now_iso(),
        "producer": PRODUCER,
        "status": "open_blockers_present",
        "item_count": len(items),
        "items": items,
        "source_blockers": {
            "local_rebuild": local_rebuild.get("blockers", []),
            "coverage": coverage_matrix.get("blockers", []),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    payload["queue_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "queue_hash"})
    return payload


def build_hash_manifest(runroot: Path, *, slot_root: Path | None = None) -> dict[str, Any]:
    runroot = Path(runroot)
    files = []
    for path in sorted(runroot.rglob("*")):
        if not path.is_file() or path.name == "hash_manifest.json":
            continue
        try:
            rel = path.relative_to(runroot)
        except ValueError:
            rel = path
        files.append({
            "path": str(rel),
            "absolute_path": str(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        })
    external_slot_artifacts = []
    if slot_root:
        for name in ("status.md", "final.md"):
            p = Path(slot_root) / name
            external_slot_artifacts.append(artifact_ref(p))
    payload = {
        "schema_version": "dse.generic_accel.hash_manifest.v1",
        "generated_at": now_iso(),
        "runroot": str(runroot),
        "file_count": len(files),
        "files": files,
        "external_slot_artifacts": [item for item in external_slot_artifacts if item is not None],
        "claim_boundary": "Hashes cover the runroot proof/replay bundle; external binary hash is recorded in gem5_binary_provenance.json when present.",
    }
    payload["manifest_hash"] = stable_json_hash({k: v for k, v in payload.items() if k != "manifest_hash"})
    return payload


def build_markdown_report(report: Mapping[str, Any], binding: Mapping[str, Any], coverage_matrix: Mapping[str, Any], *, runroot: Path) -> str:
    actual = _as_mapping(coverage_matrix.get("actual_run2_cdse_scope"))
    return f"""# GenericAccel gem5 L4 release-consumable evidence report

Generated: {report.get('generated_at')}
Status: **{report.get('status')}**
deliverable_complete: **false**
Producer: `{PRODUCER}`

## Three-layer status

1. Local rebuild: `{binding.get('local_rebuild_status', {}).get('status')}`; local rebuild claim supported = `{binding.get('local_rebuild_status', {}).get('local_rebuild_claim_supported')}`.
2. Runtime L4 proof: `{binding.get('runtime_l4_proof_status', {}).get('status')}` with `{binding.get('runtime_l4_proof_status', {}).get('passed_runtime_rows')}` passed rows and `{binding.get('runtime_l4_proof_status', {}).get('expected_negative_rows')}` expected negative row.
3. Release-consumable integration: `{binding.get('release_consumable_integration_status', {}).get('status')}`; actual CDSE mapped L4 rows = `{binding.get('release_consumable_integration_status', {}).get('actual_cdse_mapped_l4_rows')}`.

## Key artifacts

- Expanded matrix: `{runroot / 'generic_accel_l4_expanded_proof_matrix.json'}`
- Step4 rows: `{runroot / 'step4_l4_evidence_rows.json'}`
- Candidate/workload coverage: `{runroot / 'candidate_workload_l4_coverage_matrix.json'}`
- Release binding: `{runroot / 'release_gate_l4_binding_status.json'}`
- Repair queue: `{runroot / 'l4_repair_queue.json'}`
- Replay contract: `{runroot / 'replay_contract.sh'}`

## Coverage boundary

Expanded runtime rows are real gem5 GenericAccel subsystem evidence when backed by proof artifacts. Actual run2 CDSE coverage is `{actual.get('mapped_l4_evidence_row_count')}` mapped rows, `{actual.get('mapped_trusted_l4_evidence_row_count')}` trusted rows, out of `{actual.get('candidate_kernel_target_axis_count')}` candidate/kernel/target axes.

## Blockers

""" + "\n".join(f"- {item}" for item in binding.get("blockers", [])) + "\n"


def write_replay_contract(
    *,
    runroot: Path,
    repo_root: Path,
    gem5_bin: Path | None = None,
    slot2_worklist: Path | None = None,
    candidate_crosswalk: Path | None = None,
    workload_crosswalk: Path | None = None,
) -> None:
    runroot = Path(runroot)
    repo_root = Path(repo_root)
    gem5_default = gem5_bin or Path(os.environ.get("GEM5_BIN", "/mnt/f/phd/year_2/project/dft_accelerate/gem5_integration/gem5/build/X86/gem5.opt"))
    slot2_default = slot2_worklist or Path(os.environ.get("SLOT2_WORKLIST", ""))
    line_continue = "\\"
    candidate_arg = f' {line_continue}\n  --candidate-crosswalk "$CANDIDATE_CROSSWALK"' if candidate_crosswalk else ""
    workload_arg = f' {line_continue}\n  --workload-crosswalk "$WORKLOAD_CROSSWALK"' if workload_crosswalk else ""
    text = f'''#!/usr/bin/env bash
set -euo pipefail

RUNROOT="${{RUNROOT:-{runroot}}}"
REPO_ROOT="${{REPO_ROOT:-{repo_root}}}"
GEM5_BIN="${{GEM5_BIN:-{gem5_default}}}"
SLOT2_WORKLIST="${{SLOT2_WORKLIST:-{slot2_default}}}"
CANDIDATE_CROSSWALK="${{CANDIDATE_CROSSWALK:-{candidate_crosswalk or ''}}}"
WORKLOAD_CROSSWALK="${{WORKLOAD_CROSSWALK:-{workload_crosswalk or ''}}}"
LOG_DIR="$RUNROOT/logs"
LOG="$LOG_DIR/replay_contract_$(date -u +%Y%m%dT%H%M%SZ).log"
mkdir -p "$LOG_DIR"

run_step() {{
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) :: $* =====" | tee -a "$LOG"
  "$@" 2>&1 | tee -a "$LOG"
}}

if [[ ! -d "$REPO_ROOT/dse_v2" ]]; then
  echo "REPO_ROOT does not look like this repo: $REPO_ROOT" | tee -a "$LOG"
  exit 2
fi
if [[ ! -x "$GEM5_BIN" ]]; then
  echo "GEM5_BIN missing or not executable: $GEM5_BIN" | tee -a "$LOG"
  exit 3
fi
if [[ -z "$SLOT2_WORKLIST" || ! -f "$SLOT2_WORKLIST" ]]; then
  echo "SLOT2_WORKLIST missing: $SLOT2_WORKLIST" | tee -a "$LOG"
  exit 4
fi

cd "$REPO_ROOT"

run_step python3 -m py_compile gem5_integration/configs/generic_accel_l4_test.py

if [[ ! -x gem5_integration/test_programs/generic_accel/generic_accel_l4_driver ]]; then
  run_step gcc -std=c99 -O2 -Wall -Wextra -static -I "$REPO_ROOT" \
    gem5_integration/test_programs/generic_accel/generic_accel_l4_driver.c \
    -o gem5_integration/test_programs/generic_accel/generic_accel_l4_driver
fi

if [[ ! -x model/generic_sim_backend/build/generic_sim ]]; then
  run_step cmake -S model/generic_sim_backend -B model/generic_sim_backend/build
  run_step cmake --build model/generic_sim_backend/build -j2
fi

run_step python3 dse_v2/scripts/dse/run_generic_accel_l4_release_replay.py {line_continue}
  --repo-root "$REPO_ROOT" {line_continue}
  --runroot "$RUNROOT" {line_continue}
  --gem5-bin "$GEM5_BIN" {line_continue}
  --external-binary-ok

run_step python3 dse_v2/scripts/dse/build_generic_accel_l4_release_artifacts.py {line_continue}
  --repo-root "$REPO_ROOT" {line_continue}
  --runroot "$RUNROOT" {line_continue}
  --slot2-worklist "$SLOT2_WORKLIST"{candidate_arg}{workload_arg}

run_step python3 -m pytest -q gem5_integration/tests dse_v2/tests/test_l4_evidence_matrix_claims.py dse_v2/tests/test_generic_accel_l4_release_productization.py
run_step ctest --test-dir model/generic_sim_backend/build --output-on-failure

run_step python3 - <<'PY_REPLAY_AUDIT' "$RUNROOT"
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
checks=[]
expanded=json.loads((root/'generic_accel_l4_expanded_proof_matrix.json').read_text())
binding=json.loads((root/'release_gate_l4_binding_status.json').read_text())
coverage=json.loads((root/'candidate_workload_l4_coverage_matrix.json').read_text())
checks.append(('expanded_passed_runtime_rows>=3', expanded.get('passed_runtime_rows',0) >= 3))
checks.append(('expanded_expected_negative_rows>=1', expanded.get('expected_negative_rows',0) >= 1))
checks.append(('binding_deliverable_complete_false', binding.get('deliverable_complete') is False))
checks.append(('trusted_cdse_l4_rows_zero_until_real_binding', coverage['actual_run2_cdse_scope']['mapped_trusted_l4_evidence_row_count'] == 0))
failed=[name for name, ok in checks if not ok]
print(json.dumps({{'checks': checks, 'failed': failed}}, indent=2))
raise SystemExit(1 if failed else 0)
PY_REPLAY_AUDIT

echo "Replay contract completed. Log: $LOG" | tee -a "$LOG"

run_step python3 dse_v2/scripts/dse/build_generic_accel_l4_release_artifacts.py {line_continue}
  --repo-root "$REPO_ROOT" {line_continue}
  --runroot "$RUNROOT" {line_continue}
  --slot2-worklist "$SLOT2_WORKLIST"{candidate_arg}{workload_arg}

echo "Replay contract artifacts refreshed after completion marker. Log: $LOG" | tee -a "$LOG"
'''
    path = runroot / "replay_contract.sh"
    write_text(path, text)
    path.chmod(0o755)
    write_text(
        runroot / "replay_contract.md",
        f"""# GenericAccel L4 replay contract

This contract reruns the repo-owned replay and release-artifact tooling from `{repo_root}`.

Default command:

```bash
RUNROOT={runroot} REPO_ROOT={repo_root} GEM5_BIN={gem5_default} SLOT2_WORKLIST={slot2_default} bash {path}
```

The contract intentionally leaves `deliverable_complete=false` unless later CDSE/QE/PPA gates provide trusted evidence.
""",
    )


def generate_release_artifacts(
    *,
    runroot: Path,
    repo_root: Path,
    slot2_worklist: Path | None = None,
    candidate_crosswalk: Path | None = None,
    workload_crosswalk: Path | None = None,
    gem5_bin: Path | None = None,
    slot_root: Path | None = None,
) -> dict[str, Any]:
    runroot = Path(runroot).resolve()
    repo_root = Path(repo_root).resolve()
    slot2_worklist = Path(slot2_worklist).resolve() if slot2_worklist else None
    expanded = _as_mapping(load_json(runroot / "generic_accel_l4_expanded_proof_matrix.json", {}) or {})
    local_rebuild_probe = _as_mapping(load_json(runroot / "local_rebuild_probe_report.json", {}) or {})
    worklist = _as_mapping(load_json(slot2_worklist, {}) or {}) if slot2_worklist else {}
    if not expanded:
        raise FileNotFoundError(f"missing expanded matrix under {runroot}")
    local_rebuild = build_local_rebuild_execution_status(local_rebuild_probe, expanded, runroot=runroot)

    step4_payload, step4_rows = build_step4_rows(expanded, local_rebuild, runroot=runroot)
    write_json(runroot / "step4_l4_evidence_rows.json", step4_payload)
    write_json(runroot / "evidence_rows.json", step4_payload)

    preflight = build_preflight(expanded, local_rebuild, repo_root=repo_root, runroot=runroot)
    write_json(runroot / "gem5_preflight.json", preflight)

    release_subset, workload_suite, matrix, coverage_with_report = build_reports(
        step4_payload,
        step4_rows,
        worklist,
        runroot=runroot,
        local_rebuild=local_rebuild,
    )
    complete_report = coverage_with_report.pop("_complete_report")
    write_json(runroot / "generic_accel_l4_release_subset_manifest.json", release_subset)
    write_json(runroot / "generic_accel_l4_workload_suite_manifest.json", workload_suite)
    write_json(runroot / "slot4_l4_release_subset_manifest.json", release_subset)
    write_json(runroot / "slot4_l4_workload_suite_manifest.json", workload_suite)
    write_json(runroot / "l4_evidence_matrix.json", matrix)
    write_json(runroot / "coverage_claim_report.json", coverage_with_report)

    coverage_matrix = build_candidate_workload_coverage(
        expanded,
        matrix,
        worklist,
        step4_rows,
        runroot=runroot,
        slot2_worklist=slot2_worklist,
        candidate_crosswalk=candidate_crosswalk,
        workload_crosswalk=workload_crosswalk,
    )
    write_json(runroot / "candidate_workload_l4_coverage_matrix.json", coverage_matrix)

    local_rebuild_contract = build_local_rebuild_contract(local_rebuild, repo_root=repo_root, runroot=runroot)
    write_json(runroot / "local_rebuild_contract.json", local_rebuild_contract)
    write_local_rebuild_contract_script(local_rebuild_contract, runroot=runroot)

    cdse_intake_queue = build_cdse_l4_binding_intake_queue(worklist, coverage_matrix, runroot=runroot)
    write_json(runroot / "cdse_l4_binding_intake_queue.json", cdse_intake_queue)

    complete_report["evidence_summary"]["actual_cdse_mapped_l4_rows"] = coverage_matrix["actual_run2_cdse_scope"]["mapped_l4_evidence_row_count"]
    complete_report["evidence_summary"]["actual_cdse_mapped_trusted_l4_rows"] = coverage_matrix["actual_run2_cdse_scope"]["mapped_trusted_l4_evidence_row_count"]
    complete_report["local_rebuild_contract_path"] = str(runroot / "local_rebuild_contract.json")
    complete_report["cdse_l4_binding_intake_queue_path"] = str(runroot / "cdse_l4_binding_intake_queue.json")
    complete_report["report_hash"] = stable_json_hash({k: v for k, v in complete_report.items() if k != "report_hash"})

    binding = build_release_binding(
        local_rebuild,
        expanded,
        coverage_matrix,
        runroot=runroot,
        local_rebuild_contract=local_rebuild_contract,
        cdse_intake_queue=cdse_intake_queue,
    )
    write_json(runroot / "release_gate_l4_binding_status.json", binding)

    repair = build_repair_queue(local_rebuild, coverage_matrix)
    write_json(runroot / "l4_repair_queue.json", repair)

    write_json(runroot / "complete_dse_full_l4_evidence_report.json", complete_report)
    write_text(runroot / "complete_dse_full_l4_evidence_report.md", build_markdown_report(complete_report, binding, coverage_matrix, runroot=runroot))

    expanded_bin = Path(str(expanded.get("gem5_binary"))) if expanded.get("gem5_binary") else None
    write_replay_contract(
        runroot=runroot,
        repo_root=repo_root,
        gem5_bin=gem5_bin or expanded_bin,
        slot2_worklist=slot2_worklist,
        candidate_crosswalk=candidate_crosswalk,
        workload_crosswalk=workload_crosswalk,
    )
    write_json(runroot / "hash_manifest.json", build_hash_manifest(runroot, slot_root=slot_root))

    return {
        "schema_version": "dse.generic_accel.l4_release_artifact_status.v1",
        "status": binding["status"],
        "runroot": str(runroot),
        "producer": PRODUCER,
        "step4_rows": len(step4_rows),
        "expanded_passed_runtime_rows": expanded.get("passed_runtime_rows"),
        "actual_cdse_mapped_l4_rows": coverage_matrix["actual_run2_cdse_scope"]["mapped_l4_evidence_row_count"],
        "actual_cdse_mapped_trusted_l4_rows": coverage_matrix["actual_run2_cdse_scope"]["mapped_trusted_l4_evidence_row_count"],
        "deliverable_complete": False,
        "artifacts": [
            "step4_l4_evidence_rows.json",
            "candidate_workload_l4_coverage_matrix.json",
            "release_gate_l4_binding_status.json",
            "l4_repair_queue.json",
            "local_rebuild_contract.json",
            "local_rebuild_contract.sh",
            "cdse_l4_binding_intake_queue.json",
            "replay_contract.sh",
            "hash_manifest.json",
        ],
    }


def _run_command(cmd: Sequence[str], cwd: Path, timeout: int = 30) -> dict[str, Any]:
    start = datetime.now(timezone.utc)
    try:
        cp = subprocess.run([str(item) for item in cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        output = (cp.stdout or "") + (cp.stderr or "")
        return {
            "cmd": [str(item) for item in cmd],
            "cwd": str(cwd),
            "returncode": cp.returncode,
            "output_tail": output[-4000:],
            "elapsed_s": round((datetime.now(timezone.utc) - start).total_seconds(), 3),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "cmd": [str(item) for item in cmd],
            "cwd": str(cwd),
            "returncode": 124,
            "output_tail": (stdout + stderr)[-4000:] + f"\nTIMEOUT after {timeout}s",
            "elapsed_s": round((datetime.now(timezone.utc) - start).total_seconds(), 3),
        }


def _default_swig_lookup() -> str | None:
    return shutil.which("swig")


def _bounded_swig_provider_search(repo_root: Path) -> dict[str, Any]:
    env_candidates = []
    for var in ("CONDA_PREFIX", "VIRTUAL_ENV"):
        value = os.environ.get(var)
        if value:
            env_candidates.append(Path(value) / "bin" / "swig")
    home = Path.home()
    candidates = [
        Path(shutil.which("swig")) if shutil.which("swig") else None,
        repo_root / ".venv/bin/swig",
        repo_root / "venv/bin/swig",
        home / ".local/bin/swig",
        home / "miniconda3/bin/swig",
        home / "anaconda3/bin/swig",
        Path("/usr/local/bin/swig"),
        Path("/usr/bin/swig"),
        Path("/opt/conda/bin/swig"),
        *env_candidates,
    ]
    seen = set()
    probes = []
    usable = []
    for raw in candidates:
        if raw is None:
            continue
        path = Path(raw)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        ref = artifact_ref(path) or {"path": str(path), "exists": False}
        executable = path.exists() and os.access(path, os.X_OK)
        probe = {**ref, "executable": executable}
        if executable:
            version = _run_command([str(path), "-version"], repo_root, timeout=10)
            probe["version_probe"] = version
            if version.get("returncode") == 0:
                usable.append(str(path))
        probes.append(probe)
    return {
        "candidate_count": len(probes),
        "usable": usable,
        "probes": probes,
        "claim_boundary": "Bounded local provider search only; no sudo/apt/yum/system mutation attempted.",
    }


def _gitlink_status(repo_root: Path) -> dict[str, Any]:
    result = _run_command(["git", "ls-tree", "HEAD", "gem5_integration/gem5"], repo_root, timeout=10)
    index_result = _run_command(["git", "ls-files", "--stage", "gem5_integration/gem5"], repo_root, timeout=10)
    output = str(result.get("output_tail", ""))
    index_output = str(index_result.get("output_tail", ""))
    is_gitlink = (
        output.startswith("160000 commit")
        or ("\tgem5_integration/gem5" in output and "160000 commit" in output)
        or index_output.startswith("160000 ")
        or (" gem5_integration/gem5" in index_output and index_output.startswith("160000 "))
    )
    commit = None
    if is_gitlink:
        match = re.search(r"160000 commit ([0-9a-fA-F]+)\s+gem5_integration/gem5", output)
        if not match:
            match = re.search(r"160000\s+([0-9a-fA-F]+)\s+\d+\s+gem5_integration/gem5", index_output)
        commit = match.group(1) if match else None
    gitmodules = repo_root / ".gitmodules"
    has_mapping = False
    if gitmodules.exists():
        text = gitmodules.read_text(encoding="utf-8", errors="replace")
        has_mapping = bool(re.search(r"path\s*=\s*gem5_integration/gem5\b", text))
    return {
        "is_gitlink": bool(is_gitlink),
        "gitlink_commit": commit,
        "has_gitmodules_mapping": has_mapping,
        "git_ls_tree": result,
        "git_ls_files_stage": index_result,
        "gitmodules": artifact_ref(gitmodules),
    }


def _file_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists():
        info.update({
            "is_file": path.is_file(),
            "is_dir": path.is_dir(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": sha256_file(path) if path.is_file() else None,
            "mtime": path.stat().st_mtime,
        })
    return info


def _source_candidate(root: Path, active_generic_accel: Path) -> dict[str, Any]:
    generic = root / "src/dev/generic_accel"
    active_vs_source = {}
    files = {}
    for name in GENERIC_ACCEL_FILES:
        source = generic / name
        active = active_generic_accel / name
        files[name] = _file_info(source)
        active_sha = sha256_file(active)
        source_sha = sha256_file(source)
        active_vs_source[name] = {
            "active_exists": active.exists(),
            "active_sha256": active_sha,
            "source_exists": source.exists(),
            "source_sha256": source_sha,
            "same_sha256": bool(active_sha and source_sha and active_sha == source_sha),
        }
    try:
        top_entries = sorted(item.name for item in root.iterdir())[:32] if root.exists() and root.is_dir() else []
    except OSError:
        top_entries = []
    return {
        "root": str(root),
        "exists": root.exists(),
        "sconstruct": str(root / "SConstruct"),
        "sconstruct_exists": (root / "SConstruct").exists(),
        "generic_accel_dir_exists": generic.exists(),
        "generic_accel_files": files,
        "active_vs_source": active_vs_source,
        "top_entries": top_entries,
    }


def probe_gem5_local_rebuild(
    *,
    repo_root: Path,
    runroot: Path | None = None,
    source_roots: Sequence[Path] | None = None,
    swig_lookup: Callable[[], str | None] | None = None,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    runroot = Path(runroot).resolve() if runroot else repo_root
    gem5_root = repo_root / "gem5_integration/gem5"
    active_generic = repo_root / "gem5_integration/src/dev/generic_accel"
    caller_supplied_swig_lookup = swig_lookup is not None
    swig_lookup = swig_lookup or _default_swig_lookup
    swig_path = swig_lookup()
    swig_provider_search = (
        {
            "candidate_count": 1 if swig_path else 0,
            "usable": [swig_path] if swig_path else [],
            "probes": [artifact_ref(swig_path)] if swig_path else [],
            "claim_boundary": "Caller-supplied swig_lookup used; bounded filesystem search intentionally bypassed for testability/caller control.",
        }
        if caller_supplied_swig_lookup
        else _bounded_swig_provider_search(repo_root)
    )
    if not swig_path and swig_provider_search.get("usable"):
        swig_path = str(swig_provider_search["usable"][0])
    swig_checks = []
    if swig_path:
        swig_checks.append(_run_command([swig_path, "-version"], repo_root, timeout=10))
    else:
        swig_checks.append({"cmd": ["command", "-v", "swig"], "cwd": str(repo_root), "returncode": 1, "output_tail": "swig not found"})
    scons_check = _run_command(["bash", "-lc", "command -v scons || true; scons --version 2>/dev/null || true"], repo_root, timeout=20)
    gitlink = _gitlink_status(repo_root)
    roots = [gem5_root]
    for root in source_roots or []:
        p = Path(root)
        if p not in roots:
            roots.append(p)
    for p in [
        Path("/home/xixilys/project/dft_accelerate/gem5_integration/gem5"),
        Path("/mnt/f/phd/year_2/project/dft_accelerate/gem5_integration/gem5"),
        Path("/mnt/f/phd/year_2/project/dft_accelerate/gem5_src"),
    ]:
        if p not in roots:
            roots.append(p)
    source_candidates = [_source_candidate(root, active_generic) for root in roots]
    blockers: list[dict[str, str]] = []
    if not (gem5_root / "SConstruct").exists():
        blockers.append({
            "id": "current_worktree_gem5_source_tree_missing",
            "detail": f"{gem5_root} lacks SConstruct; current worktree cannot rebuild gem5 locally.",
        })
    if gitlink.get("is_gitlink") and not gitlink.get("has_gitmodules_mapping"):
        blockers.append({
            "id": "gitlink_without_gitmodules_mapping",
            "detail": "HEAD records gem5_integration/gem5 as a gitlink but .gitmodules has no mapping for that path.",
        })
    if not swig_path:
        blockers.append({
            "id": "swig_provider_missing",
            "detail": "swig is not in PATH and bounded local provider search found no usable binary.",
        })
    dry_run = {
        "cmd": ["scons", "build/X86/gem5.opt", "--dry-run", "-j1"],
        "cwd": str(gem5_root),
        "skipped": True,
        "returncode": None,
        "reason": "current worktree gem5 source tree lacks SConstruct" if not (gem5_root / "SConstruct").exists() else "source rebuild intentionally not executed by non-destructive probe",
    }
    payload = {
        "schema_version": "dse.generic_accel.local_rebuild_probe_report.v1",
        "created_at": now_iso(),
        "producer": LOCAL_REBUILD_PRODUCER,
        "status": "blocked_precise" if blockers else "ready_for_local_rebuild_attempt",
        "worktree": str(repo_root),
        "local_rebuild_claim_supported": False,
        "reason": "local source rebuild not performed by probe; blockers record why rebuild is not currently claimable",
        "blockers": blockers,
        "gitlink_status": gitlink,
        "scons_check": scons_check,
        "swig_checks": swig_checks,
        "swig_provider_search": swig_provider_search,
        "current_worktree_dry_run": dry_run,
        "source_candidates": source_candidates,
        "claim_boundary": "Source/build reproducibility only. Runtime L4 proof is assessed separately.",
    }
    if runroot:
        write_json(runroot / "local_rebuild_probe_report.json", payload)
    return payload


__all__ = [
    "CLAIM_BOUNDARY",
    "PRODUCER",
    "build_cdse_l4_binding_intake_queue",
    "build_candidate_workload_coverage",
    "build_hash_manifest",
    "build_local_rebuild_contract",
    "build_local_rebuild_execution_status",
    "build_preflight",
    "build_release_binding",
    "build_repair_queue",
    "build_reports",
    "build_step4_rows",
    "generate_release_artifacts",
    "probe_gem5_local_rebuild",
    "write_local_rebuild_contract_script",
    "write_replay_contract",
]
