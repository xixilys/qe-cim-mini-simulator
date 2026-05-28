#!/usr/bin/env python3
"""Build bounded formal/property evidence for the DFT Step5 ledger.

This is not RTL equivalence and not an unbounded model-checking result.  It is a
machine-checkable proof packet for the formal property set used by the DFT
candidate evidence ledger: GenericAccel descriptor magic/version, bounded guest
workspace layout, completion-or-error protocol behavior observed across current
L4 rows, stable candidate binding, and no descriptor-only completion claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_evidence_ledger import FORMAL_PROPERTY_SET  # noqa: E402


HEADER_PATH = REPO_ROOT / "runtime_api/command_descriptor.h"
RUNTIME_PATH = REPO_ROOT / "runtime_api/offload_runtime.c"
DRIVER_PATH = REPO_ROOT / "gem5_integration/test_programs/generic_accel/generic_accel_l4_driver.c"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path)}
    if path.exists():
        payload.update({"exists": True, "hash": _sha256_file(path), "hash_algorithm": "sha256"})
    else:
        payload.update({"exists": False})
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_legal_candidate_ids(release_artifact_dir: Path) -> list[str]:
    manifest = _load_json(release_artifact_dir / "candidate_universe_manifest.json")
    legal_ids = [str(item) for item in manifest.get("legal_candidate_ids", []) or []]
    if legal_ids:
        return legal_ids
    return [
        str(candidate["candidate_id"])
        for candidate in manifest.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal") is True and candidate.get("candidate_id")
    ]


def _parse_numeric_define(source: str, name: str) -> int | None:
    pattern = re.compile(rf"^\s*#define\s+{re.escape(name)}\s+([^\s/]+)", re.MULTILINE)
    match = pattern.search(source)
    if not match:
        return None
    value = match.group(1).strip()
    value = value.rstrip("uUlL")
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    try:
        return int(value, 0)
    except ValueError:
        return None


def _parse_driver_constant(source: str, name: str) -> int | None:
    pattern = re.compile(rf"^\s*#define\s+{re.escape(name)}\s+(.+)$", re.MULTILINE)
    match = pattern.search(source)
    if not match:
        return None
    expr = match.group(1).strip()
    expr = expr.split("/*", 1)[0].strip()
    expr = expr.rstrip("uUlL")
    expr = expr.replace("UL", "").replace("U", "")
    # Only allow integer literals, shifts, and parentheses from this local file.
    if not re.fullmatch(r"[0-9xXa-fA-F\s<>()|+\-*/]+", expr):
        return None
    try:
        return int(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - restricted integer expression grammar above.
    except Exception:
        return None


def _property_result(property_id: str, passed: bool, *, evidence: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "property_id": property_id,
        "status": "passed" if passed else "blocked_temporary",
        "passed": passed,
        "evidence": evidence,
        "blockers": blockers,
    }


def _check_magic_version(header: str, driver: str) -> dict[str, Any]:
    magic = _parse_numeric_define(header, "OFFLOAD_GSIM_MAGIC")
    version = _parse_numeric_define(header, "OFFLOAD_GSIM_DESCRIPTOR_VERSION")
    conditions = {
        "magic_define_is_gsim": magic == 0x4753494D,
        "version_define_is_v1": version == 1,
        "driver_writes_magic": "desc->magic = OFFLOAD_GSIM_MAGIC" in driver,
        "driver_writes_version": "desc->version = OFFLOAD_GSIM_DESCRIPTOR_VERSION" in driver,
        "driver_checks_completion_magic": "completion->magic != OFFLOAD_GSIM_MAGIC" in driver,
    }
    blockers = [name for name, passed in conditions.items() if not passed]
    return _property_result(
        "genericaccel_descriptor_magic_version",
        not blockers,
        evidence={"magic": magic, "version": version, "conditions": conditions},
        blockers=blockers,
    )


def _check_memory_bounds(driver: str) -> dict[str, Any]:
    values = {
        name: _parse_driver_constant(driver, name)
        for name in [
            "WORK_BASE",
            "REQUEST_OFFSET",
            "REQUEST_BYTES",
            "COMPLETION_OFFSET",
            "RESULT_OFFSET",
            "RESULT_BYTES",
            "WORK_BYTES",
        ]
    }
    conservative_descriptor_bytes = 256
    conservative_completion_bytes = 256
    blockers: list[str] = []
    if any(value is None for value in values.values()):
        blockers.append("driver_workspace_constants_missing_or_unparseable")
    else:
        request_end = values["REQUEST_OFFSET"] + values["REQUEST_BYTES"]
        completion_end = values["COMPLETION_OFFSET"] + conservative_completion_bytes
        result_end = values["RESULT_OFFSET"] + values["RESULT_BYTES"]
        checks = {
            "descriptor_before_request": conservative_descriptor_bytes <= values["REQUEST_OFFSET"],
            "request_inside_workspace": request_end <= values["WORK_BYTES"],
            "completion_inside_workspace": completion_end <= values["WORK_BYTES"],
            "result_inside_workspace": result_end <= values["WORK_BYTES"],
            "request_before_completion": request_end <= values["COMPLETION_OFFSET"],
            "completion_before_result": completion_end <= values["RESULT_OFFSET"],
        }
        blockers.extend(name for name, passed in checks.items() if not passed)
    return _property_result(
        "request_result_completion_memory_bounds",
        not blockers,
        evidence={
            "constants": values,
            "conservative_descriptor_bytes": conservative_descriptor_bytes,
            "conservative_completion_bytes": conservative_completion_bytes,
        },
        blockers=blockers,
    )


def _check_completion_protocol(driver: str, runtime: str, l4_goal_binding_path: Path | None) -> dict[str, Any]:
    blockers: list[str] = []
    conditions = {
        "driver_has_poll_limit": "POLL_LIMIT" in driver and "for (int i = 0; i < POLL_LIMIT; i++)" in driver,
        "driver_accepts_completion_or_error_status": "status == 1 || status == 2" in driver,
        "driver_rejects_missing_success_status": "if (status != 1 || error_code != 0) return 3" in driver,
        "driver_rejects_bad_completion_magic": "completion->magic != OFFLOAD_GSIM_MAGIC" in driver,
        "runtime_increments_completion_count": "runtime->metrics.completion_count++" in runtime,
        "runtime_writes_work_done": "OFFLOAD_REG_WORK_DONE" in runtime,
        "runtime_writes_ready_compute_done": "OFFLOAD_STATUS_READY | OFFLOAD_STATUS_COMPUTE_DONE" in runtime,
    }
    blockers.extend(name for name, passed in conditions.items() if not passed)
    l4_summary: dict[str, Any] = {"attached": False}
    if l4_goal_binding_path is None or not l4_goal_binding_path.exists():
        blockers.append("l4_goal_binding_not_attached")
    else:
        l4 = _load_json(l4_goal_binding_path)
        proofs = l4.get("row_level_proofs", {}) if isinstance(l4.get("row_level_proofs"), Mapping) else {}
        expected = int(proofs.get("expected_gem5_l4_proof_count", 0) or 0)
        passed = int(proofs.get("passed_gem5_l4_proof_count", 0) or 0)
        failed = int(proofs.get("failed_gem5_l4_proof_count", 0) or 0)
        l4_summary = {
            "attached": True,
            "artifact_ref": _artifact_ref(l4_goal_binding_path),
            "expected_gem5_l4_proof_count": expected,
            "passed_gem5_l4_proof_count": passed,
            "failed_gem5_l4_proof_count": failed,
            "l4_software_visible_proof_present": bool(l4.get("l4_software_visible_proof_present", False)),
        }
        if not (expected > 0 and passed == expected and failed == 0 and l4.get("l4_software_visible_proof_present") is True):
            blockers.append("l4_row_completion_proofs_not_all_passed")
    return _property_result(
        "completion_writeback_eventual",
        not blockers,
        evidence={"source_conditions": conditions, "l4_observed_completion_summary": l4_summary},
        blockers=blockers,
    )


def _check_candidate_binding(
    release_artifact_dir: Path,
    legal_candidate_ids: list[str],
    l4_goal_binding_path: Path | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    manifest_path = release_artifact_dir / "candidate_universe_manifest.json"
    legality_path = release_artifact_dir / "candidate_legality_report.json"
    manifest = _load_json(manifest_path)
    legality = _load_json(legality_path) if legality_path.exists() else {}
    if len(legal_candidate_ids) != len(set(legal_candidate_ids)):
        blockers.append("release_manifest_legal_candidate_ids_not_unique")
    if not manifest.get("universe_hash"):
        blockers.append("candidate_universe_hash_missing")
    if legality_path.exists() and not legality.get("legality_hash"):
        blockers.append("candidate_legality_hash_missing")
    l4_binding: dict[str, Any] = {}
    if l4_goal_binding_path and l4_goal_binding_path.exists():
        l4 = _load_json(l4_goal_binding_path)
        binding = l4.get("current_goal_binding", {}) if isinstance(l4.get("current_goal_binding"), Mapping) else {}
        l4_ids = [str(item) for item in binding.get("step5_candidate_ids", []) or []]
        l4_binding = {
            "candidate_identity_binding_explicit": bool(binding.get("candidate_identity_binding_explicit", False)),
            "candidate_keys_exact": bool(binding.get("candidate_keys_exact", False)),
            "mapped_l4_candidates_unique": bool(binding.get("mapped_l4_candidates_unique", False)),
            "l4_candidate_count": len(l4_ids),
        }
        if set(l4_ids) != set(legal_candidate_ids):
            blockers.append("l4_candidate_ids_do_not_match_release_legal_universe")
        for key in ["candidate_identity_binding_explicit", "candidate_keys_exact", "mapped_l4_candidates_unique"]:
            if binding.get(key) is not True:
                blockers.append(f"l4_binding_{key}_false")
    else:
        blockers.append("l4_goal_binding_not_attached")
    return _property_result(
        "candidate_id_binding_stable",
        not blockers,
        evidence={
            "release_manifest": _artifact_ref(manifest_path),
            "candidate_legality_report": _artifact_ref(legality_path),
            "legal_candidate_count": len(legal_candidate_ids),
            "universe_hash": manifest.get("universe_hash"),
            "legality_hash": legality.get("legality_hash"),
            "l4_binding": l4_binding,
        },
        blockers=blockers,
    )


def _check_no_descriptor_only_completion(
    full_scf_hybrid_artifact_dir: Path | None,
    claim_validation_path: Path | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    evidence: dict[str, Any] = {}
    if full_scf_hybrid_artifact_dir is None:
        blockers.append("full_scf_hybrid_bundle_not_attached")
    else:
        correctness_path = Path(full_scf_hybrid_artifact_dir) / "full_scf_correctness_report.json"
        descriptor_path = Path(full_scf_hybrid_artifact_dir) / "full_scf_accelerator_descriptor.json"
        evidence["full_scf_correctness_report"] = _artifact_ref(correctness_path)
        evidence["full_scf_accelerator_descriptor"] = _artifact_ref(descriptor_path)
        if not correctness_path.exists() or not descriptor_path.exists():
            blockers.append("full_scf_descriptor_or_correctness_report_missing")
        else:
            correctness = _load_json(correctness_path)
            descriptor = _load_json(descriptor_path)
            validation = descriptor.get("validation", {}) if isinstance(descriptor.get("validation"), Mapping) else {}
            evidence["descriptor_validation_passed"] = bool(validation.get("passed", False))
            evidence["numerical_correctness_claim_eligible"] = bool(
                correctness.get("numerical_correctness_claim_eligible", False)
            )
            evidence["full_scf_completion_claim"] = bool(correctness.get("completion_claim", False))
            # For this current property packet, descriptor validation must be present while final correctness stays false.
            if validation.get("passed") is not True:
                blockers.append("descriptor_shape_validation_not_passed")
            if correctness.get("numerical_correctness_claim_eligible") is True or correctness.get("completion_claim") is True:
                blockers.append("descriptor_or_correctness_report_claims_completion_without_final_gate")
    if claim_validation_path is None or not claim_validation_path.exists():
        blockers.append("claim_validation_not_attached")
    else:
        claim_validation = _load_json(claim_validation_path)
        evidence["claim_validation"] = _artifact_ref(claim_validation_path)
        evidence["claim_validation_passed"] = bool(claim_validation.get("passed", False))
        if claim_validation.get("passed") is True:
            blockers.append("claim_validation_already_passed_cannot_prove_descriptor_only_block")
    return _property_result(
        "no_descriptor_only_completion_claim",
        not blockers,
        evidence=evidence,
        blockers=blockers,
    )


def build_formal_property_evidence(
    out_dir: Path,
    *,
    release_artifact_dir: Path,
    l4_goal_binding: Path | None = None,
    full_scf_hybrid_artifact_dir: Path | None = None,
    claim_validation: Path | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    header = HEADER_PATH.read_text(encoding="utf-8")
    runtime = RUNTIME_PATH.read_text(encoding="utf-8")
    driver = DRIVER_PATH.read_text(encoding="utf-8")
    legal_candidate_ids = _load_legal_candidate_ids(release_artifact_dir)
    property_ids = [str(item["property_id"]) for item in FORMAL_PROPERTY_SET]

    property_results = [
        _check_magic_version(header, driver),
        _check_memory_bounds(driver),
        _check_completion_protocol(driver, runtime, l4_goal_binding),
        _check_candidate_binding(release_artifact_dir, legal_candidate_ids, l4_goal_binding),
        _check_no_descriptor_only_completion(full_scf_hybrid_artifact_dir, claim_validation),
    ]
    result_by_id = {str(result["property_id"]): result for result in property_results}
    missing_property_ids = [property_id for property_id in property_ids if property_id not in result_by_id]
    unexpected_property_ids = sorted(set(result_by_id) - set(property_ids))
    all_properties_passed = bool(
        not missing_property_ids
        and not unexpected_property_ids
        and all(result.get("passed") is True for result in property_results)
    )
    candidate_records = [
        {
            "candidate_id": candidate_id,
            "formal_job_id": f"formal::{candidate_id}",
            "status": "passed" if all_properties_passed else "blocked_temporary",
            "applicable_property_ids": property_ids,
            "proof_status": {
                "status": "passed" if all_properties_passed else "blocked_temporary",
                "proof_artifacts": [],
                "property_result_ids": property_ids,
                "reason": (
                    "bounded static/property checks and current L4 completion evidence passed"
                    if all_properties_passed
                    else "one or more bounded formal/property checks are blocked"
                ),
            },
            "completion_eligible": all_properties_passed,
            "claim_boundary": (
                "Bounded protocol/property evidence only; not RTL equivalence, not unbounded model checking, "
                "and not numerical or final deliverable completion."
            ),
        }
        for candidate_id in legal_candidate_ids
    ]
    payload = {
        "schema_version": "dse.dft.formal_property_execution_evidence.v1",
        "status": "passed" if all_properties_passed else "blocked_temporary",
        "proof_method": "bounded_static_contract_plus_current_l4_observed_completion",
        "formal_property_set": [dict(item) for item in FORMAL_PROPERTY_SET],
        "property_results": property_results,
        "missing_property_ids": missing_property_ids,
        "unexpected_property_ids": unexpected_property_ids,
        "legal_candidate_ids": legal_candidate_ids,
        "candidate_count": len(legal_candidate_ids),
        "passed_candidate_count": len(legal_candidate_ids) if all_properties_passed else 0,
        "candidate_records": candidate_records,
        "source_artifacts": [
            _artifact_ref(HEADER_PATH),
            _artifact_ref(RUNTIME_PATH),
            _artifact_ref(DRIVER_PATH),
            _artifact_ref(release_artifact_dir / "candidate_universe_manifest.json"),
            *([_artifact_ref(l4_goal_binding)] if l4_goal_binding is not None else []),
            *([_artifact_ref(Path(full_scf_hybrid_artifact_dir) / "full_scf_correctness_report.json")] if full_scf_hybrid_artifact_dir is not None else []),
            *([_artifact_ref(claim_validation)] if claim_validation is not None else []),
        ],
        "claim_boundary": (
            "This artifact can satisfy the ledger's formal_status only for the listed bounded protocol properties. "
            "It is not a substitute for DFT numerical correctness, RTL equivalence, FPGA/ASIC PPA, or final claim validation."
        ),
    }
    evidence_path = out_dir / "formal_property_execution_evidence.json"
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--release-artifact-dir", type=Path, required=True)
    parser.add_argument("--l4-goal-binding", type=Path, default=None)
    parser.add_argument("--full-scf-hybrid-artifact-dir", type=Path, default=None)
    parser.add_argument("--claim-validation", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = build_formal_property_evidence(
        args.out,
        release_artifact_dir=args.release_artifact_dir,
        l4_goal_binding=args.l4_goal_binding,
        full_scf_hybrid_artifact_dir=args.full_scf_hybrid_artifact_dir,
        claim_validation=args.claim_validation,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "artifact": str(args.out / "formal_property_execution_evidence.json"),
                "passed_property_ids": [
                    result["property_id"] for result in payload["property_results"] if result.get("passed") is True
                ],
                "blocked_property_ids": [
                    result["property_id"] for result in payload["property_results"] if result.get("passed") is not True
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
