#!/usr/bin/env python3
"""Audit a DFT-first QE end-to-end DSE run against completion requirements.

The audit is intentionally stricter than a green unit-test signal.  It maps the
DFT-first objective to concrete run artifacts and verifies the evidence boundary:
Step1 remains facts-only, Step2 L1/L2 output remains candidate-generation only,
Step3 ranking uses measured generic_sim timing, and Step4 is trusted only when a
real gem5 GenericAccel run preserved stats/config/command/completion evidence
with non-zero accelerator activity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.evidence.full_flow import build_gem5_l4_proof
from dse_v2.reference_workloads.dft_profile_schema import (
    DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA,
    DFT_DOMAIN_VALIDATION_SCHEMA,
    DFT_PROFILE_CONTRACT_VERSION,
    DFT_PROFILE_METADATA_SCHEMA,
    profile_contract_from_package,
)


AUDIT_SCHEMA = "dse.dft_end_to_end_completion_audit.v1"
RUN_SUMMARY_SCHEMA = "dse.dft_end_to_end_summary.v1"
WORKLOAD_PACKAGE_SCHEMA = "dse.step1.workload_package.v1"
WORKLOAD_CHARACTERIZATION_SCHEMA = "dse.workload_characterization.v1"
DOMAIN_POLICY_HINTS_SCHEMA = "dse.step2.domain_policy_hints.v1"
GSIM_REQUEST_SCHEMA = "gsim.request.v1"
GSIM_RESULT_SCHEMA = "gsim.result.v1"
NUMERICAL_VALIDATION_SCHEMA = "dse.numerical_validation.v1"
VERDICT_SCHEMA = "dse.verdict.v1"
GEM5_PROOF_SCHEMA = "dse.gem5_l4_proof.v1"
GEM5_ACTIVITY_SCHEMA = "dse.gem5_activity_summary.v1"

REQUIRED_STEP1_ARTIFACTS = [
    "workload_package.json",
    "workload_graph.json",
    "workload_characterization.json",
]

REQUIRED_STEP2_ARTIFACTS = [
    "l1_evaluation_result.json",
    "l2_evaluation_result.json",
    "low_fidelity_screening_summary.json",
    "mapping_seed_set.json",
    "architecture_candidate_set.json",
    "step3_simulation_queue.json",
    "domain_policy_hints.json",
]

REQUIRED_STEP3_ARTIFACT_KEYS = [
    "simulation_result",
]

REQUIRED_STEP3_DIR_ARTIFACTS = [
    "manifest.json",
    "simulation_request.json",
    "simulation_result.raw.json",
    "step3_status.json",
]

REQUIRED_STEP4_ADJUDICATION_KEYS = [
    "kernel_numerical_validation",
    "domain_physics_validation",
    "verdict",
    "claim_validation",
    "evidence_requirements",
    "provenance",
    "artifact_manifest",
]

REQUIRED_STEP4_ARTIFACTS = [
    "artifact_manifest.json",
    "gem5.log",
    "stats.txt",
    "manifest.json",
    "gem5_completion_descriptor.json",
    "gem5_l4_proof.json",
    "gem5_activity_summary.json",
]

REQUIRED_GEM5_CHECKS = [
    "descriptor_read_verified",
    "request_decode_verified",
    "microarchitecture_execute_verified",
    "completion_writeback_verified",
    "driver_status_verified",
    "driver_completion_descriptor_verified",
    "result_status_passed",
    "stats_txt_present",
    "config_present",
    "nonzero_accelerator_activity",
]

REQUIRED_GEM5_LOG_MARKERS = [
    "descriptor_read verified=true",
    "uarch_request_decode verified=true",
    "microarchitecture_execute verified=true",
    "completion_writeback verified=true",
]

REQUIRED_GEM5_SOURCE_ARTIFACTS = [
    "gem5_log",
    "gem5_stdout",
    "gem5_stats",
    "gem5_command_descriptor",
    "gem5_completion_descriptor",
    "gem5_activity_summary",
    "simulation_request",
    "simulation_result",
]

GEM5_SOURCE_ARTIFACT_PATH_KEYS = set(REQUIRED_GEM5_SOURCE_ARTIFACTS) | {
    "gem5_config_ini",
    "gem5_config_json",
    "gem5_stderr",
}

STEP1_FORBIDDEN_DECISION_KEYS = {
    "architecture_candidate_set",
    "descriptor_protocol",
    "gem5_l4_proof",
    "mapping",
    "mapping_selected_record",
    "runtime_schedule",
    "simulator_verdict",
    "step3_simulation_queue",
    "verdict",
}

SMOKE_TOKEN_PATTERN = re.compile(r"(?<!non[-_])(?<!non)smoke", re.IGNORECASE)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _path_from(value: Any, *, base: Path) -> Optional[Path]:
    if value in (None, ""):
        return None
    path = Path(str(value))
    return path if path.is_absolute() else base / path


def _is_under(path: Optional[Path], root: Path) -> bool:
    if path is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _rebase_outside_run(path: Optional[Path], *, run_dir: Path, fallback: Path) -> Optional[Path]:
    if path is not None and (not path.is_absolute() or _is_under(path, run_dir)):
        return path
    return fallback if fallback.exists() else path


def _artifact_path(value: Any, *, base: Path, run_dir: Path, fallback_name: str) -> Optional[Path]:
    path = _path_from(value, base=base)
    return _rebase_outside_run(path, run_dir=run_dir, fallback=base / fallback_name)


def _exists(value: Any, *, base: Path) -> bool:
    path = _path_from(value, base=base)
    return bool(path and path.exists())


def _load_mapping_artifact(value: Any, *, base: Path) -> tuple[Optional[Path], Dict[str, Any]]:
    path = _path_from(value, base=base)
    if path is None or not path.exists():
        return path, {}
    payload = _load_json(path)
    return path, payload if _is_mapping(payload) else {}


def _load_mapping_artifact_scoped(
    value: Any,
    *,
    base: Path,
    run_dir: Path,
    fallback_name: str,
) -> tuple[Optional[Path], Dict[str, Any]]:
    path = _artifact_path(value, base=base, run_dir=run_dir, fallback_name=fallback_name)
    if path is None or not path.exists():
        return path, {}
    payload = _load_json(path)
    return path, payload if _is_mapping(payload) else {}


def _json_contains_key(value: Any, forbidden: set[str]) -> Optional[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in forbidden:
                return str(key)
            found = _json_contains_key(item, forbidden)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _json_contains_key(item, forbidden)
            if found:
                return found
    return None


def _positive_float(value: Any) -> bool:
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return False
    return value_f > 0.0 and value_f not in {float("inf"), float("-inf")} and value_f == value_f


def _parse_gem5_stats(path: Path) -> Dict[str, float]:
    """Parse scalar numeric fields from a gem5 m5out stats.txt artifact.

    gem5 stats lines use a whitespace-separated `name value # comment` shape;
    non-scalar banners and vector subfields are ignored.  The audit only trusts
    metrics that parse to finite floats so an empty placeholder stats file cannot
    satisfy Step4 evidence.
    """
    if not path.exists():
        return {}
    metrics: Dict[str, float] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("----------"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue
        if value == value and value not in {float("inf"), float("-inf")}:
            metrics[parts[0]] = value
    return metrics


def _float_equal(left: Any, right: Any, *, tolerance: float = 1e-9) -> bool:
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def _command_from_manifest(manifest: Mapping[str, Any]) -> List[str]:
    replay = manifest.get("replay_metadata", {}) if _is_mapping(manifest.get("replay_metadata")) else {}
    for key in ("simulator_replay_command", "simulator_cmd", "simulator_command", "cmd"):
        value = replay.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    for key in ("cmd", "simulator_cmd", "simulator_command"):
        value = manifest.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    return []


def _forbidden_no_smoke_tokens(tokens: Sequence[str]) -> List[str]:
    """Return replay-command tokens that indicate a smoke/demo/skip path.

    The prompt explicitly disallows smoke/demo evidence.  The audit must not
    flag the legitimate phrase "non-smoke", so smoke detection rejects only
    smoke not immediately qualified by non-, non_, or non.
    """

    hits: List[str] = []
    for token in tokens:
        text = str(token).lower()
        if text == "--skip-gem5-l4" or "demo" in text or SMOKE_TOKEN_PATTERN.search(text):
            hits.append(str(token))
    return hits


def _normalise_source_artifacts(
    source_artifacts: Mapping[str, Any],
    *,
    base: Path,
    run_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    normalised: Dict[str, Any] = {}
    for key, value in source_artifacts.items():
        if key in GEM5_SOURCE_ARTIFACT_PATH_KEYS and isinstance(value, str) and value:
            path = _path_from(value, base=base)
            if run_dir is not None and path is not None and path.is_absolute() and not _is_under(path, run_dir):
                path = base / Path(str(value)).name
            normalised[key] = str(path) if path is not None else value
        else:
            normalised[key] = value
    return normalised


def _same_number(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return left == right


def _artifact_manifest_entries(directory: Path) -> Dict[str, Mapping[str, Any]]:
    path = directory / "artifact_manifest.json"
    if not path.exists():
        return {}
    payload = _load_json(path)
    if not _is_mapping(payload):
        return {}
    entries: Dict[str, Mapping[str, Any]] = {}
    for item in payload.get("artifacts", []) or []:
        if _is_mapping(item) and item.get("path"):
            entries[str(item.get("path"))] = item
    return entries


def _manifest_hash_mismatches(directory: Path, required_paths: Sequence[str]) -> List[Dict[str, Any]]:
    entries = _artifact_manifest_entries(directory)
    mismatches: List[Dict[str, Any]] = []
    for rel in required_paths:
        entry = entries.get(rel)
        path = directory / rel
        if not entry:
            mismatches.append({"path": rel, "reason": "missing_manifest_entry"})
            continue
        if entry.get("exists") is not True:
            mismatches.append({"path": rel, "reason": "manifest_entry_not_exists", "entry_exists": entry.get("exists")})
            continue
        if not path.exists():
            mismatches.append({"path": rel, "reason": "missing_file"})
            continue
        expected_sha = entry.get("sha256")
        if not expected_sha:
            mismatches.append({"path": rel, "reason": "missing_manifest_sha256"})
            continue
        actual_sha = _sha256(path)
        if actual_sha != expected_sha:
            mismatches.append({
                "path": rel,
                "reason": "sha256_mismatch",
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
            })
        expected_size = entry.get("size_bytes")
        if expected_size is not None and path.stat().st_size != int(expected_size):
            mismatches.append({
                "path": rel,
                "reason": "size_mismatch",
                "expected_size_bytes": expected_size,
                "actual_size_bytes": path.stat().st_size,
            })
    return mismatches


class AuditBuilder:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.checks: List[Dict[str, Any]] = []

    def check(self, check_id: str, requirement: str, passed: bool, evidence: Any = None, detail: str = "") -> None:
        payload: Dict[str, Any] = {
            "check_id": check_id,
            "requirement": requirement,
            "passed": bool(passed),
        }
        if evidence is not None:
            payload["evidence"] = evidence
        if detail:
            payload["detail"] = detail
        self.checks.append(payload)

    def result(self) -> Dict[str, Any]:
        failed = [check for check in self.checks if not check["passed"]]
        return {
            "schema_version": AUDIT_SCHEMA,
            "run_dir": str(self.run_dir),
            "status": "passed" if not failed else "failed",
            "passed": not failed,
            "check_count": len(self.checks),
            "failed_count": len(failed),
            "failed_checks": failed,
            "checks": self.checks,
        }


def _audit_step1(builder: AuditBuilder, summary: Mapping[str, Any]) -> None:
    run_dir = builder.run_dir
    step1 = summary.get("step1", {}) if _is_mapping(summary.get("step1")) else {}
    step1_dir = _rebase_outside_run(
        _path_from(step1.get("run_dir"), base=run_dir),
        run_dir=run_dir,
        fallback=run_dir / "step1",
    ) or run_dir / "step1"
    builder.check(
        "step1_status_complete",
        "Step1 QE source parsing/workload characterization completed",
        step1.get("status") == "complete",
        {"step1_dir": str(step1_dir), "status": step1.get("status")},
    )
    builder.check(
        "step1_facts_only",
        "Step1 is facts/summaries/hints only, not mapping/schedule/runtime/gem5 verdict",
        step1.get("facts_only") is True,
        {"facts_only": step1.get("facts_only")},
    )
    missing = [name for name in REQUIRED_STEP1_ARTIFACTS if not (step1_dir / name).exists()]
    builder.check(
        "step1_required_artifacts_present",
        "Step1 required workload artifacts are present",
        not missing,
        {"step1_dir": str(step1_dir), "missing": missing},
    )
    characterization_path = step1_dir / "workload_characterization.json"
    package_path = step1_dir / "workload_package.json"
    if package_path.exists():
        package = _load_json(package_path)
        profile = package.get("profile", {}) if _is_mapping(package.get("profile")) else {}
        profile_domain_validation = (
            profile.get("domain_validation", {}) if _is_mapping(profile.get("domain_validation")) else {}
        )
        dft_metadata = (
            package.get("domain_metadata", {}).get("dft", {})
            if _is_mapping(package.get("domain_metadata"))
            else {}
        )
        profile_contract = profile_contract_from_package(package) if _is_mapping(package) else {}
        profile_metadata = (
            profile_contract.get("profile_metadata", {})
            if _is_mapping(profile_contract.get("profile_metadata"))
            else {}
        )
        source_facts = [
            fact for fact in dft_metadata.get("source_facts", []) or []
            if _is_mapping(fact)
        ] if _is_mapping(dft_metadata) else []
        source_types = sorted({str(fact.get("source_type")) for fact in source_facts if fact.get("source_type")})
        fields = {str(fact.get("field")) for fact in source_facts if fact.get("field")}
        builder.check(
            "step1_package_schema",
            "Step1 workload package uses the expected source-fact schema version",
            _is_mapping(package) and package.get("schema_version") == WORKLOAD_PACKAGE_SCHEMA,
            {"artifact": str(package_path), "schema_version": package.get("schema_version") if _is_mapping(package) else None},
        )
        builder.check(
            "step1_dft_profile_schema_contract",
            "Step1 cites the frozen DFT profile/schema contract under profile-owned metadata, not generic core fields",
            _is_mapping(profile_metadata)
            and profile_metadata.get("schema_version") == DFT_PROFILE_METADATA_SCHEMA
            and profile_metadata.get("contract_version") == DFT_PROFILE_CONTRACT_VERSION
            and profile_metadata.get("owner") == "dse_v2.reference_workloads"
            and profile_metadata.get("core_must_import") is False
            and profile_metadata.get("core_required_fields") == []
            and profile_metadata.get("domain_validation_schema") == DFT_DOMAIN_VALIDATION_SCHEMA
            and profile_metadata.get("domain_physics_validation_schema") == DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA
            and profile_domain_validation.get("contract_version") == DFT_PROFILE_CONTRACT_VERSION
            and profile_domain_validation.get("schema_version") == DFT_DOMAIN_VALIDATION_SCHEMA
            and profile_domain_validation.get("domain_physics_validation_schema") == DFT_DOMAIN_PHYSICS_VALIDATION_SCHEMA,
            {
                "artifact": str(package_path),
                "profile_contract": profile_contract,
                "profile_domain_validation_schema": profile_domain_validation.get("schema_version"),
                "profile_domain_contract_version": profile_domain_validation.get("contract_version"),
            },
        )
        builder.check(
            "step1_qe_source_facts_preserved",
            "Step1 preserves QE source facts with provenance before any mapping or simulator decision",
            bool(source_facts)
            and "input" in source_types
            and bool({"log", "profile"} & set(source_types))
            and "input.calculation" in fields
            and any(field.startswith("phase_timing.") for field in fields)
            and all(fact.get("schema_version") == "dse.dft.source_fact.v1" for fact in source_facts)
            and any(fact.get("source_path") for fact in source_facts),
            {
                "artifact": str(package_path),
                "source_fact_count": len(source_facts),
                "source_types": source_types,
                "has_input_calculation": "input.calculation" in fields,
                "has_phase_timing": any(field.startswith("phase_timing.") for field in fields),
            },
        )
    if characterization_path.exists():
        characterization = _load_json(characterization_path)
        builder.check(
            "step1_characterization_schema",
            "Step1 characterization uses the expected architecture-independent schema version",
            _is_mapping(characterization) and characterization.get("schema_version") == WORKLOAD_CHARACTERIZATION_SCHEMA,
            {"artifact": str(characterization_path), "schema_version": characterization.get("schema_version") if _is_mapping(characterization) else None},
        )
        found = _json_contains_key(characterization, STEP1_FORBIDDEN_DECISION_KEYS)
        builder.check(
            "step1_no_decision_fields",
            "Step1 characterization contains no Step2/Step3/Step4 decision fields",
            found is None,
            {"artifact": str(characterization_path), "forbidden_key": found},
        )
        builder.check(
            "step1_domain_summaries_present",
            "Step1 carries DFT/QE domain summaries without polluting the generic core",
            all(key in characterization for key in ("domain_phase_summary", "domain_workflow_summary", "domain_claim_summary")),
            {
                "artifact": str(characterization_path),
                "present": sorted(key for key in ("domain_phase_summary", "domain_workflow_summary", "domain_claim_summary") if key in characterization),
            },
        )


def _records(summary: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [record for record in summary.get("step2_step3_records", []) or [] if _is_mapping(record)]


def _audit_step2_step3(builder: AuditBuilder, summary: Mapping[str, Any]) -> None:
    records = _records(summary)
    builder.check(
        "step2_candidate_records_present",
        "Step2 generated architecture/mapping candidates for the tested scope",
        bool(records),
        {"record_count": len(records)},
    )
    verified_latencies: Dict[str, float] = {}
    for index, record in enumerate(records):
        arch = str(record.get("architecture_id", f"record_{index}"))
        step2_dir = _rebase_outside_run(
            _path_from(record.get("step2_dir"), base=builder.run_dir),
            run_dir=builder.run_dir,
            fallback=builder.run_dir / "architectures" / arch / "step2",
        )
        step3_dir = _rebase_outside_run(
            _path_from(record.get("step3_dir"), base=builder.run_dir),
            run_dir=builder.run_dir,
            fallback=builder.run_dir / "architectures" / arch / "step3_systemc",
        )
        missing_step2 = [
            name for name in REQUIRED_STEP2_ARTIFACTS
            if step2_dir is None or not (step2_dir / name).exists()
        ]
        builder.check(
            f"step2_artifacts_present:{arch}",
            "Step2 persisted replayable candidate-generation artifacts",
            not missing_step2,
            {"architecture_id": arch, "step2_dir": str(step2_dir), "missing": missing_step2},
        )
        estimated = record.get("step2_estimated_screening", {}) if _is_mapping(record.get("step2_estimated_screening")) else {}
        builder.check(
            f"step2_estimate_boundary:{arch}",
            "Step2 L1/L2 estimates are candidate-generation only",
            estimated.get("trusted_final_claim") is False,
            {"architecture_id": arch, "trusted_final_claim": estimated.get("trusted_final_claim")},
        )
        hints_path = step2_dir / "domain_policy_hints.json" if step2_dir is not None else None
        hints = _load_json(hints_path) if hints_path is not None and hints_path.exists() else {}
        hints_text = json.dumps(hints, sort_keys=True).lower() if hints else ""
        domain_keys = set(str(item) for item in hints.get("domain_keys", []) or []) if _is_mapping(hints) else set()
        if _is_mapping(hints) and hints.get("domain_key"):
            domain_keys.add(str(hints.get("domain_key")))
        builder.check(
            f"step2_dft_fpga_policy_hints:{arch}",
            "Step2 DFT policy emits candidate-only FPGA-oriented architecture/mapping hints outside the generic core",
            _is_mapping(hints)
            and hints.get("schema_version") == DOMAIN_POLICY_HINTS_SCHEMA
            and (hints.get("policy_id") == "dft-fpga-reference-v1" or "dft-fpga-reference-v1" in hints.get("policy_ids", []))
            and ("dft" in domain_keys)
            and hints.get("trusted_final_claim") is False
            and "fpga" in hints_text,
            {
                "architecture_id": arch,
                "artifact": str(hints_path) if hints_path is not None else None,
                "schema_version": hints.get("schema_version") if _is_mapping(hints) else None,
                "policy_id": hints.get("policy_id") if _is_mapping(hints) else None,
                "domain_keys": sorted(domain_keys),
                "has_fpga_hint": "fpga" in hints_text,
                "trusted_final_claim": hints.get("trusted_final_claim") if _is_mapping(hints) else None,
            },
        )
        timing = record.get("step3_measured_timing", {}) if _is_mapping(record.get("step3_measured_timing")) else {}
        latency = timing.get("latency_ms")
        if record.get("timing_verified") is True and _positive_float(latency):
            verified_latencies[arch] = float(latency)
        missing_step3 = [
            key for key in REQUIRED_STEP3_ARTIFACT_KEYS
            if not _exists(timing.get(key), base=step3_dir or builder.run_dir)
        ]
        missing_step3_dir_artifacts = [
            name for name in REQUIRED_STEP3_DIR_ARTIFACTS
            if step3_dir is None or not (step3_dir / name).exists()
        ]
        builder.check(
            f"step3_timing_verified:{arch}",
            "Step3 generic_sim timing pre-screen is measured with execution-owned artifacts present",
            record.get("timing_verified") is True
            and _positive_float(latency)
            and not missing_step3
            and not missing_step3_dir_artifacts,
            {
                "architecture_id": arch,
                "timing_verified": record.get("timing_verified"),
                "latency_ms": latency,
                "missing": missing_step3 + missing_step3_dir_artifacts,
            },
        )
        step4_adjudication = record.get("step4_adjudication", {}) if _is_mapping(record.get("step4_adjudication")) else {}
        missing_step4_adjudication = [
            key for key in REQUIRED_STEP4_ADJUDICATION_KEYS
            if not _exists(step4_adjudication.get(key), base=builder.run_dir)
        ]
        kernel_path, kernel_validation = _load_mapping_artifact(step4_adjudication.get("kernel_numerical_validation"), base=builder.run_dir)
        domain_path, domain_validation = _load_mapping_artifact(step4_adjudication.get("domain_physics_validation"), base=builder.run_dir)
        claim_path, claim_validation = _load_mapping_artifact(step4_adjudication.get("claim_validation"), base=builder.run_dir)
        builder.check(
            f"step4_adjudication_artifacts_present:{arch}",
            "DFT Step4 owns kernel/domain validation and claim-validation wrappers over Step3 timing artifacts",
            not missing_step4_adjudication
            and kernel_validation.get("schema_version") == "dse.kernel_numerical_validation.v1"
            and kernel_validation.get("owner") == "evidence_adjudication"
            and domain_validation.get("schema_version") == "dse.dft.domain_physics_validation.v1"
            and domain_validation.get("owner") == "domain_profile_adjudication"
            and domain_validation.get("status") == "not_claimed"
            and claim_validation.get("schema_version") == "dse.claim_validation.v1"
            and claim_validation.get("owner") == "claim_validation"
            and claim_validation.get("claim_levels", {}).get("domain_physics_evidence") is False,
            {
                "architecture_id": arch,
                "step4_adjudication": step4_adjudication,
                "missing": missing_step4_adjudication,
                "kernel_numerical_validation": str(kernel_path),
                "domain_physics_validation": str(domain_path),
                "claim_validation": str(claim_path),
                "domain_status": domain_validation.get("status"),
            },
        )
        if not missing_step3 and not missing_step3_dir_artifacts and step3_dir is not None:
            sim_path, sim_result = _load_mapping_artifact_scoped(
                timing.get("simulation_result"),
                base=step3_dir,
                run_dir=builder.run_dir,
                fallback_name="simulation_result.json",
            )
            raw_sim_path, raw_sim_result = _load_mapping_artifact(step3_dir / "simulation_result.raw.json", base=step3_dir)
            numerical_path, numerical = _load_mapping_artifact_scoped(
                timing.get("numerical_validation"),
                base=step3_dir,
                run_dir=builder.run_dir,
                fallback_name="numerical_validation.json",
            )
            verdict_path, verdict = _load_mapping_artifact_scoped(
                timing.get("verdict"),
                base=step3_dir,
                run_dir=builder.run_dir,
                fallback_name="verdict.json",
            )
            request_path, request = _load_mapping_artifact(step3_dir / "simulation_request.json", base=step3_dir)
            manifest = _load_json(step3_dir / "manifest.json")
            manifest = manifest if _is_mapping(manifest) else {}
            replay_cmd = _command_from_manifest(manifest)
            replay_lower = [token.lower() for token in replay_cmd]
            replay_result = manifest.get("replay_metadata", {}).get("simulation_result") if _is_mapping(manifest.get("replay_metadata")) else None
            replay_request = manifest.get("replay_metadata", {}).get("simulation_request") if _is_mapping(manifest.get("replay_metadata")) else None
            replay_result_path = _artifact_path(
                replay_result,
                base=step3_dir,
                run_dir=builder.run_dir,
                fallback_name="simulation_result.json",
            )
            replay_request_path = _artifact_path(
                replay_request,
                base=step3_dir,
                run_dir=builder.run_dir,
                fallback_name="simulation_request.json",
            )
            result_arg_path = None
            if "--result" in replay_cmd:
                result_index = replay_cmd.index("--result")
                if result_index + 1 < len(replay_cmd):
                    result_arg_path = _artifact_path(
                        replay_cmd[result_index + 1],
                        base=step3_dir,
                        run_dir=builder.run_dir,
                        fallback_name="simulation_result.raw.json",
                    )
            request_arg_path = None
            if "--request" in replay_cmd:
                request_index = replay_cmd.index("--request")
                if request_index + 1 < len(replay_cmd):
                    request_arg_path = _artifact_path(
                        replay_cmd[request_index + 1],
                        base=step3_dir,
                        run_dir=builder.run_dir,
                        fallback_name="simulation_request.json",
                    )
            has_generic_sim = any(Path(token).name == "generic_sim" for token in replay_cmd)
            has_request_flag = "--request" in replay_cmd
            has_result_flag = "--result" in replay_cmd
            sim_metrics = sim_result.get("metrics", {}) if _is_mapping(sim_result.get("metrics")) else {}
            raw_metrics = raw_sim_result.get("metrics", {}) if _is_mapping(raw_sim_result.get("metrics")) else {}
            manifest_checked_paths = [
                "simulation_request.json",
                "simulation_result.raw.json",
                "simulation_result.json",
                "verdict.json",
            ]
            if (step3_dir / "simulator_consistency_check.json").exists():
                manifest_checked_paths.append("simulator_consistency_check.json")
            hash_mismatches = _manifest_hash_mismatches(step3_dir, manifest_checked_paths)
            builder.check(
                f"step3_raw_timing_artifacts_consistent:{arch}",
                "Step3 raw/public generic_sim result is consistent with Step4-adjudicated compatibility validation artifacts",
                request.get("schema_version") == GSIM_REQUEST_SCHEMA
                and
                sim_result.get("schema_version") == GSIM_RESULT_SCHEMA
                and raw_sim_result.get("schema_version") == GSIM_RESULT_SCHEMA
                and sim_result.get("status") == "passed"
                and raw_sim_result.get("status") == "passed"
                and _float_equal(sim_metrics.get("latency_ms"), latency)
                and _float_equal(raw_metrics.get("latency_ms"), latency)
                and _float_equal(raw_metrics.get("latency_ms"), sim_metrics.get("latency_ms"))
                and (
                    (numerical.get("schema_version") == NUMERICAL_VALIDATION_SCHEMA and numerical.get("passed") is True)
                    or (kernel_validation.get("schema_version") == "dse.kernel_numerical_validation.v1" and kernel_validation.get("passed") is True)
                )
                and verdict.get("schema_version") == VERDICT_SCHEMA
                and verdict.get("simulation_passed") is True
                and verdict.get("numerical_validation_passed") is True
                and verdict.get("trusted_for_final_ranking") is False,
                {
                    "architecture_id": arch,
                    "simulation_request": str(request_path),
                    "request_schema_version": request.get("schema_version"),
                    "simulation_result": str(sim_path),
                    "simulation_status": sim_result.get("status"),
                    "simulation_schema_version": sim_result.get("schema_version"),
                    "raw_simulation_result": str(raw_sim_path),
                    "raw_simulation_status": raw_sim_result.get("status"),
                    "raw_simulation_schema_version": raw_sim_result.get("schema_version"),
                    "summary_latency_ms": latency,
                    "raw_latency_ms": sim_metrics.get("latency_ms"),
                    "true_raw_latency_ms": raw_metrics.get("latency_ms"),
                    "numerical_validation": str(numerical_path),
                    "numerical_schema_version": numerical.get("schema_version"),
                    "numerical_passed": numerical.get("passed"),
                    "step4_kernel_numerical_schema_version": kernel_validation.get("schema_version"),
                    "step4_kernel_numerical_passed": kernel_validation.get("passed"),
                    "verdict": str(verdict_path),
                    "verdict_schema_version": verdict.get("schema_version"),
                    "verdict_simulation_passed": verdict.get("simulation_passed"),
                    "verdict_numerical_validation_passed": verdict.get("numerical_validation_passed"),
                    "verdict_trusted_for_final_ranking": verdict.get("trusted_for_final_ranking"),
                },
            )
            builder.check(
                f"step3_artifact_manifest_hashes:{arch}",
                "Compatibility artifact manifest hashes match audited request/result/validation/verdict artifacts",
                not hash_mismatches,
                {
                    "architecture_id": arch,
                    "artifact_manifest": str(step3_dir / "artifact_manifest.json"),
                    "checked_paths": manifest_checked_paths,
                    "mismatches": hash_mismatches,
                },
            )
            builder.check(
                f"step3_replay_manifest_consistent:{arch}",
                "Step3 manifest contains a replayable generic_sim command and points to the audited request/result artifacts",
                bool(replay_cmd)
                and has_generic_sim
                and has_request_flag
                and has_result_flag
                and not any("skip" in token or "smoke" in token or "demo" in token for token in replay_lower)
                and replay_request_path is not None
                and replay_request_path.resolve() == request_path.resolve()
                and replay_result_path is not None
                and replay_result_path.resolve() == sim_path.resolve(),
                {
                    "architecture_id": arch,
                    "manifest": str(step3_dir / "manifest.json"),
                    "replay_command": replay_cmd,
                    "has_generic_sim": has_generic_sim,
                    "has_request_flag": has_request_flag,
                    "has_result_flag": has_result_flag,
                    "manifest_request": str(replay_request_path) if replay_request_path else None,
                    "audited_request": str(request_path),
                    "manifest_result": str(replay_result_path) if replay_result_path else None,
                    "audited_result": str(sim_path),
                    "request_arg": str(request_arg_path) if request_arg_path else None,
                    "result_arg": str(result_arg_path) if result_arg_path else None,
                    "audited_raw_result": str(raw_sim_path),
                    "forbidden_skip_tokens": [token for token in replay_lower if "skip" in token or "smoke" in token or "demo" in token],
                },
            )
            builder.check(
                f"step3_raw_result_replay_bound:{arch}",
                "Step3 manifest generic_sim --result argument points to the audited raw result artifact",
                request_arg_path is not None
                and request_arg_path.resolve() == request_path.resolve()
                and result_arg_path is not None
                and result_arg_path.resolve() == raw_sim_path.resolve(),
                {
                    "architecture_id": arch,
                    "manifest": str(step3_dir / "manifest.json"),
                    "request_arg": str(request_arg_path) if request_arg_path else None,
                    "audited_request": str(request_path),
                    "result_arg": str(result_arg_path) if result_arg_path else None,
                    "audited_raw_result": str(raw_sim_path),
                },
            )
    best = summary.get("best_architecture", {}) if _is_mapping(summary.get("best_architecture")) else {}
    if verified_latencies:
        step4 = summary.get("step4_gem5", {}) if _is_mapping(summary.get("step4_gem5")) else {}
        attempts = [attempt for attempt in step4.get("attempts", []) or [] if _is_mapping(attempt)]
        passing_attempts = [
            attempt for attempt in attempts
            if attempt.get("trusted_step4_timing") is True and _positive_float(attempt.get("step3_latency_ms"))
        ]
        if step4.get("trusted_step4_timing") is True and passing_attempts:
            selected = min(
                passing_attempts,
                key=lambda attempt: (float(attempt.get("step3_latency_ms", float("inf"))), str(attempt.get("architecture_id", ""))),
            )
            expected_best = (str(selected.get("architecture_id")), float(selected.get("step3_latency_ms")))
            requirement = "Best architecture is the minimum measured Step3 latency among candidates that passed Step4 real gem5 proof"
        else:
            expected_best = min(verified_latencies.items(), key=lambda item: item[1])
            requirement = "Best architecture is selected by minimum measured Step3 latency within tested architecture IDs"
        builder.check(
            "best_architecture_from_measured_step3",
            requirement,
            best.get("architecture_id") == expected_best[0] and float(best.get("latency_ms", -1.0)) == expected_best[1],
            {"expected": {"architecture_id": expected_best[0], "latency_ms": expected_best[1]}, "actual": best},
        )
    else:
        builder.check(
            "best_architecture_from_measured_step3",
            "Best architecture is selected by minimum measured Step3 latency within tested architecture IDs",
            False,
            {"reason": "no verified Step3 latency records"},
        )


def _audit_step4(builder: AuditBuilder, summary: Mapping[str, Any]) -> None:
    step4 = summary.get("step4_gem5", {}) if _is_mapping(summary.get("step4_gem5")) else {}
    best = summary.get("best_architecture", {}) if _is_mapping(summary.get("best_architecture")) else {}
    step4_arch = str(step4.get("architecture_id") or best.get("architecture_id") or "")
    step4_dir = _rebase_outside_run(
        _path_from(step4.get("run_dir"), base=builder.run_dir),
        run_dir=builder.run_dir,
        fallback=builder.run_dir / "step4_gem5" / step4_arch if step4_arch else builder.run_dir / "step4_gem5",
    )
    attempts = [attempt for attempt in step4.get("attempts", []) or [] if _is_mapping(attempt)]
    selected_attempts = [
        attempt for attempt in attempts
        if attempt.get("trusted_step4_timing") is True
        and str(attempt.get("architecture_id")) == str(step4.get("architecture_id"))
    ]
    selected_attempt = selected_attempts[0] if selected_attempts else {}
    builder.check(
        "step4_attempted_real_gem5",
        "Step4 attempted real gem5 GenericAccel validation",
        step4.get("attempted") is True and step4.get("status") == "passed" and step4.get("trusted_step4_timing") is True,
        {
            "attempted": step4.get("attempted"),
            "status": step4.get("status"),
            "trusted_step4_timing": step4.get("trusted_step4_timing"),
            "run_dir": str(step4_dir),
        },
    )
    if step4_dir is None:
        builder.check("step4_run_dir_present", "Step4 run directory is present", False, {"run_dir": None})
        return
    selected_attempt_dir = _rebase_outside_run(
        _path_from(selected_attempt.get("run_dir"), base=builder.run_dir),
        run_dir=builder.run_dir,
        fallback=step4_dir if step4_dir is not None else builder.run_dir / "step4_gem5" / step4_arch,
    ) if selected_attempt else None
    builder.check(
        "step4_selected_attempt_bound_to_best_architecture",
        "Step4 selected passing attempt, inspected run directory, and public best architecture refer to the same candidate",
        step4.get("trusted_step4_timing") is True
        and bool(step4.get("architecture_id"))
        and step4.get("architecture_id") == best.get("architecture_id")
        and _float_equal(step4.get("step3_latency_ms"), best.get("latency_ms"))
        and bool(selected_attempt)
        and selected_attempt_dir is not None
        and selected_attempt_dir.resolve() == step4_dir.resolve()
        and selected_attempt.get("status") == "passed",
        {
            "best_architecture": best.get("architecture_id"),
            "best_latency_ms": best.get("latency_ms"),
            "step4_architecture": step4.get("architecture_id"),
            "step4_latency_ms": step4.get("step3_latency_ms"),
            "step4_run_dir": str(step4_dir),
            "selected_attempt_run_dir": str(selected_attempt_dir) if selected_attempt_dir else None,
            "selected_attempt_status": selected_attempt.get("status") if selected_attempt else None,
            "attempt_count": len(attempts),
        },
    )
    config_present = (step4_dir / "config.ini").exists() or (step4_dir / "config.json").exists()
    missing = [name for name in REQUIRED_STEP4_ARTIFACTS if not (step4_dir / name).exists()]
    if not config_present:
        missing.append("config.ini|config.json")
    builder.check(
        "step4_non_smoke_artifacts_present",
        "Step4 non-smoke evidence includes gem5 log, stats, config, command, completion, proof, and activity artifacts",
        not missing,
        {"step4_dir": str(step4_dir), "missing": missing},
    )
    log_path = step4_dir / "gem5.log"
    stats_path = step4_dir / "stats.txt"
    config_paths = [path for path in [step4_dir / "config.ini", step4_dir / "config.json"] if path.exists()]
    manifest_path = step4_dir / "manifest.json"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    missing_markers = [marker for marker in REQUIRED_GEM5_LOG_MARKERS if marker not in log_text]
    manifest = _load_json(manifest_path) if manifest_path.exists() else {}
    replay_cmd = _command_from_manifest(manifest) if isinstance(manifest, Mapping) else []
    replay_cmd_lower = [token.lower() for token in replay_cmd]
    has_gem5_binary = any(Path(token).name.startswith("gem5.") or Path(token).name == "gem5.opt" for token in replay_cmd)
    has_generic_accel_config = any(token.endswith(".py") and "generic_accel" in token for token in replay_cmd_lower)
    has_required_runtime_args = all(flag in replay_cmd for flag in ("--binary", "--request", "--simulator"))
    no_skip_flag = "--skip-gem5-l4" not in replay_cmd
    builder.check(
        "step4_raw_gem5_evidence_consistent",
        "Raw gem5 evidence contains expected log markers plus non-empty stats/config and a replay command manifest",
        not missing_markers
        and stats_path.exists()
        and stats_path.stat().st_size > 0
        and bool(config_paths)
        and all(path.stat().st_size > 0 for path in config_paths)
        and isinstance(manifest, Mapping)
        and bool(replay_cmd),
        {
            "gem5_log": str(log_path),
            "missing_log_markers": missing_markers,
            "stats_size": stats_path.stat().st_size if stats_path.exists() else 0,
            "config_artifacts": [str(path) for path in config_paths],
            "manifest": str(manifest_path),
            "manifest_has_command": bool(replay_cmd),
        },
    )
    step4_manifest_paths = [
        "manifest.json",
        "gem5.log",
        "systemc_stdout.log",
        "systemc_stderr.log",
        "stats.txt",
        "gem5_command_descriptor.json",
        "gem5_completion_descriptor.json",
        "gem5_l4_proof.json",
        "gem5_activity_summary.json",
        "simulation_request.json",
        "simulation_result.raw.json",
    ] + [path.name for path in config_paths]
    step4_hash_mismatches = _manifest_hash_mismatches(step4_dir, step4_manifest_paths)
    builder.check(
        "step4_artifact_manifest_hashes",
        "Step4 artifact_manifest hashes bind raw gem5/config/proof/activity/request/result artifacts to audited files",
        not step4_hash_mismatches,
        {
            "artifact_manifest": str(step4_dir / "artifact_manifest.json"),
            "required_paths": step4_manifest_paths,
            "mismatches": step4_hash_mismatches,
        },
    )
    required_stats = ["simTicks", "finalTick", "simInsts", "simOps", "system.cpu.numCycles"]
    parsed_stats = _parse_gem5_stats(stats_path)
    missing_stats = [name for name in required_stats if name not in parsed_stats]
    nonpositive_stats = [name for name in required_stats if name in parsed_stats and not _positive_float(parsed_stats[name])]
    builder.check(
        "step4_gem5_stats_semantics_present",
        "gem5 stats.txt contains positive simulator tick, instruction/op, and CPU-cycle counters from a real run",
        stats_path.exists() and not missing_stats and not nonpositive_stats,
        {
            "stats": str(stats_path),
            "required_fields": required_stats,
            "parsed_required_fields": {name: parsed_stats.get(name) for name in required_stats if name in parsed_stats},
            "missing_fields": missing_stats,
            "nonpositive_fields": nonpositive_stats,
        },
    )
    builder.check(
        "step4_manifest_replays_real_gem5",
        "Step4 manifest contains a replayable real gem5 GenericAccel command, not a skip/smoke path",
        bool(replay_cmd)
        and has_gem5_binary
        and has_generic_accel_config
        and has_required_runtime_args
        and no_skip_flag,
        {
            "manifest": str(manifest_path),
            "replay_command": replay_cmd,
            "has_gem5_binary": has_gem5_binary,
            "has_generic_accel_config": has_generic_accel_config,
            "has_required_runtime_args": has_required_runtime_args,
            "no_skip_flag": no_skip_flag,
        },
    )
    proof_path = step4_dir / "gem5_l4_proof.json"
    proof: Mapping[str, Any] = {}
    if proof_path.exists():
        loaded_proof = _load_json(proof_path)
        proof = loaded_proof if _is_mapping(loaded_proof) else {}
        checks = proof.get("checks", {}) if _is_mapping(proof.get("checks")) else {}
        failed = [key for key in REQUIRED_GEM5_CHECKS if checks.get(key) is not True]
        builder.check(
            "step4_gem5_proof_checks_pass",
            "gem5 proof shows descriptor read, request decode, microarchitecture execute, completion writeback, stats/config, and non-zero activity",
            proof.get("schema_version") == GEM5_PROOF_SCHEMA
            and proof.get("passed") is True
            and proof.get("fallback_from_gem5") is False
            and not failed
            and proof.get("transport_harness") == "gem5_generic_accel_microarchitecture_v1",
            {
                "proof": str(proof_path),
                "schema_version": proof.get("schema_version"),
                "fallback_from_gem5": proof.get("fallback_from_gem5"),
                "transport_harness": proof.get("transport_harness"),
                "failed_checks": failed,
                "missing_evidence": proof.get("missing_evidence", []),
            },
        )
        source_artifacts = proof.get("source_artifacts", {}) if _is_mapping(proof.get("source_artifacts")) else {}
        normalised_sources = _normalise_source_artifacts(
            source_artifacts,
            base=step4_dir,
            run_dir=builder.run_dir,
        ) if _is_mapping(source_artifacts) else {}
        missing_sources = []
        empty_sources = []
        for key in REQUIRED_GEM5_SOURCE_ARTIFACTS:
            path = _path_from(normalised_sources.get(key), base=step4_dir)
            if path is None or not path.exists():
                missing_sources.append(key)
            elif path.stat().st_size <= 0:
                empty_sources.append(key)
        config_source_present = any(
            (path := _path_from(normalised_sources.get(key), base=step4_dir)) is not None and path.exists()
            for key in ("gem5_config_ini", "gem5_config_json")
        )
        builder.check(
            "step4_proof_source_artifacts_exist",
            "gem5 proof source_artifacts point to the raw evidence files used to make the non-smoke claim",
            _is_mapping(source_artifacts)
            and source_artifacts.get("require_gem5_stats_config") is True
            and not missing_sources
            and not empty_sources
            and config_source_present,
            {
                "proof": str(proof_path),
                "require_gem5_stats_config": source_artifacts.get("require_gem5_stats_config") if _is_mapping(source_artifacts) else None,
                "missing_sources": missing_sources,
                "empty_sources": empty_sources,
                "config_source_present": config_source_present,
            },
        )
        raw_log_path = _path_from(normalised_sources.get("gem5_log"), base=step4_dir)
        raw_stdout_path = _path_from(normalised_sources.get("gem5_stdout"), base=step4_dir)
        raw_result_path = _path_from(normalised_sources.get("simulation_result"), base=step4_dir)
        raw_log_text = raw_log_path.read_text(encoding="utf-8", errors="replace") if raw_log_path and raw_log_path.exists() else ""
        raw_stdout_text = raw_stdout_path.read_text(encoding="utf-8", errors="replace") if raw_stdout_path and raw_stdout_path.exists() else ""
        raw_result = _load_json(raw_result_path) if raw_result_path and raw_result_path.exists() else {}
        raw_result = raw_result if _is_mapping(raw_result) else {}
        recomputed = build_gem5_l4_proof(raw_log_text, raw_stdout_text, raw_result, normalised_sources)
        recomputed_checks = recomputed.get("checks", {}) if _is_mapping(recomputed.get("checks")) else {}
        differing_checks = sorted(
            key for key in REQUIRED_GEM5_CHECKS
            if checks.get(key) is not recomputed_checks.get(key)
        )
        builder.check(
            "step4_proof_recomputed_from_raw_artifacts",
            "gem5 proof booleans recompute from raw log/stdout/result/source artifacts",
            recomputed.get("passed") is True
            and proof.get("passed") is True
            and proof.get("fallback_from_gem5") is False
            and recomputed.get("fallback_from_gem5") is False
            and not differing_checks,
            {
                "proof": str(proof_path),
                "raw_log": str(raw_log_path) if raw_log_path else None,
                "raw_stdout": str(raw_stdout_path) if raw_stdout_path else None,
                "raw_result": str(raw_result_path) if raw_result_path else None,
                "recomputed_passed": recomputed.get("passed"),
                "stored_passed": proof.get("passed"),
                "differing_checks": differing_checks,
                "recomputed_missing_evidence": recomputed.get("missing_evidence", []),
            },
        )
    else:
        raw_result = {}
    source_artifacts_guard = proof.get("source_artifacts", {}) if _is_mapping(proof.get("source_artifacts")) else {}
    fallback_hits = []
    if step4.get("fallback_from_gem5") is True:
        fallback_hits.append("summary.step4_gem5.fallback_from_gem5")
    if proof.get("fallback_from_gem5") is True:
        fallback_hits.append("gem5_l4_proof.fallback_from_gem5")
    if _is_mapping(source_artifacts_guard) and source_artifacts_guard.get("fallback_from_gem5") is True:
        fallback_hits.append("gem5_l4_proof.source_artifacts.fallback_from_gem5")
    forbidden_step4_tokens = _forbidden_no_smoke_tokens(replay_cmd)
    builder.check(
        "step4_no_smoke_demo_or_fallback_tokens",
        "Step4 selected evidence does not route through skip, smoke, demo, or fallback markers",
        not forbidden_step4_tokens and not fallback_hits,
        {
            "manifest": str(manifest_path),
            "forbidden_replay_tokens": forbidden_step4_tokens,
            "fallback_hits": fallback_hits,
            "proof": str(proof_path),
        },
    )
    activity_path = step4_dir / "gem5_activity_summary.json"
    if activity_path.exists():
        activity = _load_json(activity_path)
        raw_result_for_activity = raw_result if _is_mapping(raw_result) else {}
        raw_summary = raw_result_for_activity.get("microarchitecture_summary", {}) if _is_mapping(raw_result_for_activity.get("microarchitecture_summary")) else {}
        raw_events = [event for event in raw_result_for_activity.get("events", []) or [] if _is_mapping(event)]
        raw_accelerator_events = [
            event for event in raw_events
            if str(event.get("device", "host")) not in {"", "host", "cpu", "host-0"}
        ]
        raw_devices = sorted({str(event.get("device")) for event in raw_accelerator_events if event.get("device")})
        builder.check(
            "step4_nonzero_accelerator_activity",
            "gem5 activity summary records non-zero accelerator work",
            activity.get("schema_version") == GEM5_ACTIVITY_SCHEMA
            and activity.get("execution_engine") == "gem5_generic_accel_microarchitecture_v1"
            and raw_result_for_activity.get("execution_engine") == "gem5_generic_accel_microarchitecture_v1"
            and bool(activity.get("nonzero_accelerator_activity"))
            and int(activity.get("accelerator_event_count", 0) or 0) > 0
            and _positive_float(activity.get("total_cycles"))
            and _positive_float(activity.get("total_flops")),
            {
                "activity": str(activity_path),
                "schema_version": activity.get("schema_version"),
                "execution_engine": activity.get("execution_engine"),
                "accelerator_devices": activity.get("accelerator_devices"),
                "accelerator_event_count": activity.get("accelerator_event_count"),
                "total_cycles": activity.get("total_cycles"),
                "total_flops": activity.get("total_flops"),
            },
        )
        builder.check(
            "step4_activity_matches_raw_result",
            "gem5 activity summary is derived from the raw gem5 microarchitecture result",
            activity.get("event_count") == len(raw_events)
            and activity.get("accelerator_event_count") == len(raw_accelerator_events)
            and sorted(str(device) for device in activity.get("accelerator_devices", []) or []) == raw_devices
            and _same_number(activity.get("micro_op_count"), raw_summary.get("micro_op_count"))
            and _same_number(activity.get("total_cycles"), raw_summary.get("total_cycles"))
            and _same_number(activity.get("total_flops"), raw_summary.get("total_flops")),
            {
                "activity": str(activity_path),
                "raw_event_count": len(raw_events),
                "activity_event_count": activity.get("event_count"),
                "raw_accelerator_event_count": len(raw_accelerator_events),
                "activity_accelerator_event_count": activity.get("accelerator_event_count"),
                "raw_devices": raw_devices,
                "activity_devices": activity.get("accelerator_devices"),
                "raw_micro_op_count": raw_summary.get("micro_op_count"),
                "activity_micro_op_count": activity.get("micro_op_count"),
                "raw_total_cycles": raw_summary.get("total_cycles"),
                "activity_total_cycles": activity.get("total_cycles"),
                "raw_total_flops": raw_summary.get("total_flops"),
                "activity_total_flops": activity.get("total_flops"),
            },
        )


def audit_run(run_dir: Path) -> Dict[str, Any]:
    run_dir = run_dir.resolve()
    builder = AuditBuilder(run_dir)
    summary_path = run_dir / "dft_end_to_end_summary.json"
    builder.check(
        "summary_artifact_present",
        "Top-level DFT end-to-end summary exists",
        summary_path.exists(),
        {"summary": str(summary_path)},
    )
    if not summary_path.exists():
        return builder.result()
    summary = _load_json(summary_path)
    builder.check(
        "summary_status_complete",
        "End-to-end run status is complete",
        summary.get("status") == "complete",
        {"status": summary.get("status")},
    )
    builder.check(
        "summary_schema_version",
        "End-to-end run summary uses the expected DFT-first schema version",
        summary.get("schema_version") == RUN_SUMMARY_SCHEMA,
        {"schema_version": summary.get("schema_version")},
    )
    scope = summary.get("scope", {}) if _is_mapping(summary.get("scope")) else {}
    completion = summary.get("completion", {}) if _is_mapping(summary.get("completion")) else {}
    builder.check(
        "scope_qe_and_domain_neutral",
        "Scope is QE-focused and keeps DFT logic out of the domain-neutral core",
        "QE" in str(scope.get("workload_focus", "")) and scope.get("domain_neutral_core") is True and str(scope.get("dft_logic_location", "")).startswith("dse_v2/reference_workloads"),
        {"scope": scope},
    )
    builder.check(
        "no_dft_correctness_claim",
        "Flow does not claim DFT numerical/scientific correctness",
        scope.get("trusted_final_dft_correctness_claimed") is False and completion.get("trusted_final_dft_correctness_claimed") is False,
        {"scope": scope.get("trusted_final_dft_correctness_claimed"), "completion": completion.get("trusted_final_dft_correctness_claimed")},
    )
    _audit_step1(builder, summary)
    _audit_step2_step3(builder, summary)
    _audit_step4(builder, summary)
    return builder.result()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="DFT-first run directory containing dft_end_to_end_summary.json")
    parser.add_argument("--out", type=Path, default=None, help="Optional audit JSON output path; defaults to <run_dir>/dft_end_to_end_audit.json")
    parser.add_argument("--quiet", action="store_true", help="Do not print the audit JSON to stdout")
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    audit = audit_run(args.run_dir)
    out = args.out or (args.run_dir / "dft_end_to_end_audit.json")
    _write_json(out, audit)
    if not args.quiet:
        print(json.dumps(audit, indent=2, sort_keys=True))
    return 0 if audit.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
