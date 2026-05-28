#!/usr/bin/env python3
"""Build DFT numerical correctness evidence for the Step5 ledger.

This artifact intentionally separates three gates:

1. real QE reference-output final admission for the strict six-SCF suite;
2. per-candidate/per-major-kernel golden correctness reports;
3. end-to-end full-SCF host+accelerator numerical comparison.

The first two gates may pass while the artifact remains blocked_temporary when
full-SCF end-to-end comparison is absent.  That is deliberate: kernel-level
golden correctness and reference-output hashes are progress evidence, not final
DFT numerical correctness or deliverable completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS  # noqa: E402


EXPECTED_STRICT_SCF_CLASS_IDS = (
    "small_multi_k_scf",
    "metal_smearing_scf",
    "insulator_scf",
    "slab_vacuum_large_fft_scf",
    "gamma_only_supercell_scf",
    "projector_orthogonalization_heavy_scf",
)


FULL_SCF_REQUIRED_BEFORE_CORRECTNESS_CLAIM = (
    "golden reference outputs for each strict workload case",
    "per-kernel golden correctness",
    "end-to-end SCF numerical comparison for host+accelerator schedule",
)


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


def _load_legal_candidates(release_artifact_dir: Path) -> list[dict[str, Any]]:
    manifest_path = release_artifact_dir / "candidate_universe_manifest.json"
    manifest = _load_json(manifest_path)
    candidates = {
        str(candidate.get("candidate_id")): dict(candidate)
        for candidate in manifest.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal") is True and candidate.get("candidate_id")
    }
    legal_ids = [str(item) for item in manifest.get("legal_candidate_ids", []) or []]
    if not legal_ids:
        legal_ids = sorted(candidates)
    missing = [candidate_id for candidate_id in legal_ids if candidate_id not in candidates]
    if missing:
        raise ValueError(f"legal candidate ids missing from manifest candidates: {missing[:5]}")
    return [candidates[candidate_id] for candidate_id in legal_ids]


def _reference_output_admission(reference_manifest_path: Path) -> dict[str, Any]:
    if not reference_manifest_path.exists():
        return {
            "schema_version": "dse.dft.numerical.reference_output_admission.v1",
            "status": "blocked_temporary",
            "passed": False,
            "artifact_ref": _artifact_ref(reference_manifest_path),
            "blockers": ["reference_manifest_missing"],
            "claim_boundary": "Missing strict-suite QE reference outputs cannot satisfy numerical correctness.",
        }

    manifest = _load_json(reference_manifest_path)
    base_dir = reference_manifest_path.parent
    entries = [entry for entry in manifest.get("entries", []) or [] if isinstance(entry, Mapping)]
    entry_by_class = {str(entry.get("class_id")): entry for entry in entries if entry.get("class_id")}
    missing_class_ids = [case_id for case_id in EXPECTED_STRICT_SCF_CLASS_IDS if case_id not in entry_by_class]
    extra_class_ids = sorted(set(entry_by_class) - set(EXPECTED_STRICT_SCF_CLASS_IDS))
    entry_records: list[dict[str, Any]] = []
    blockers: list[str] = []
    if manifest.get("complete") is not True:
        blockers.append("reference_manifest_complete_false")
    if manifest.get("final_admission_complete") is not True:
        blockers.append("reference_manifest_final_admission_complete_false")
    if missing_class_ids:
        blockers.append("reference_manifest_missing_strict_suite_classes")

    for case_id in EXPECTED_STRICT_SCF_CLASS_IDS:
        entry = entry_by_class.get(case_id, {})
        rel_path = entry.get("path")
        output_path = base_dir / str(rel_path) if rel_path else base_dir / "<missing>"
        exists = output_path.exists()
        observed_hash = _sha256_file(output_path) if exists else None
        expected_hash = str(entry.get("sha256") or entry.get("hash") or "")
        hash_matches = bool(exists and expected_hash and observed_hash == expected_hash)
        entry_passed = bool(
            exists
            and hash_matches
            and entry.get("final_admission_eligible") is True
            and entry.get("hash_final") is True
            and entry.get("provenance_hash_only") is not True
            and entry.get("returncode", 0) == 0
            and entry.get("job_done") is True
            and entry.get("scf_converged") is True
        )
        if not entry_passed:
            blockers.append(f"reference_entry_not_final_admitted::{case_id}")
        entry_records.append(
            {
                "class_id": case_id,
                "path": str(output_path),
                "exists": exists,
                "expected_sha256": expected_hash,
                "observed_sha256": observed_hash,
                "hash_matches": hash_matches,
                "final_admission_eligible": bool(entry.get("final_admission_eligible", False)),
                "hash_final": bool(entry.get("hash_final", False)),
                "provenance_hash_only": bool(entry.get("provenance_hash_only", False)),
                "job_done": bool(entry.get("job_done", False)),
                "scf_converged": bool(entry.get("scf_converged", False)),
                "status": "passed" if entry_passed else "blocked_temporary",
            }
        )

    passed = bool(
        not blockers
        and not missing_class_ids
        and manifest.get("complete") is True
        and manifest.get("final_admission_complete") is True
    )
    return {
        "schema_version": "dse.dft.numerical.reference_output_admission.v1",
        "status": "passed" if passed else "blocked_temporary",
        "passed": passed,
        "artifact_ref": _artifact_ref(reference_manifest_path),
        "suite_id": manifest.get("suite_id"),
        "entry_count": len(entries),
        "expected_strict_class_ids": list(EXPECTED_STRICT_SCF_CLASS_IDS),
        "missing_class_ids": missing_class_ids,
        "extra_class_ids": extra_class_ids,
        "entry_records": entry_records,
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": (
            "Passed reference admission means six strict-suite QE outputs exist, hash-match, and are final-admission eligible. "
            "It is reference-input evidence only; full-SCF accelerator numerical correctness still needs end-to-end comparison."
        ),
    }


def _golden_correctness_summary(
    candidate_specific_evidence_dir: Path,
    legal_candidates: list[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_records: list[dict[str, Any]] = []
    unit_records: list[dict[str, Any]] = []
    missing_units: list[str] = []
    failed_units: list[str] = []

    for candidate in legal_candidates:
        candidate_id = str(candidate["candidate_id"])
        candidate_passed_kernel_ids: list[str] = []
        candidate_blockers: list[str] = []
        for kernel_id in MAJOR_SCF_KERNEL_IDS:
            report_path = candidate_specific_evidence_dir / candidate_id / kernel_id / "golden_correctness_report.json"
            unit_id = f"{candidate_id}::{kernel_id}"
            if not report_path.exists():
                missing_units.append(unit_id)
                candidate_blockers.append(f"missing_golden_correctness_report::{kernel_id}")
                unit_records.append(
                    {
                        "candidate_id": candidate_id,
                        "kernel_id": kernel_id,
                        "unit_id": unit_id,
                        "status": "blocked_temporary",
                        "artifact_ref": _artifact_ref(report_path),
                        "blockers": ["golden_correctness_report_missing"],
                    }
                )
                continue
            try:
                payload = _load_json(report_path)
                payload_candidate_id = str(payload.get("candidate_id") or "")
                payload_kernel_id = str(payload.get("kernel_id") or "")
                passed = bool(
                    payload.get("status") == "passed"
                    and payload.get("verdict", "passed") == "passed"
                    and payload.get("passed") is True
                    and payload_candidate_id == candidate_id
                    and payload_kernel_id == kernel_id
                )
                blockers = [] if passed else ["golden_correctness_payload_not_passed_or_identity_mismatch"]
                if passed:
                    candidate_passed_kernel_ids.append(kernel_id)
                else:
                    failed_units.append(unit_id)
                    candidate_blockers.append(f"golden_correctness_not_passed::{kernel_id}")
                unit_records.append(
                    {
                        "candidate_id": candidate_id,
                        "kernel_id": kernel_id,
                        "unit_id": unit_id,
                        "status": "passed" if passed else "blocked_temporary",
                        "artifact_ref": _artifact_ref(report_path),
                        "max_abs_error": payload.get("max_abs_error"),
                        "payload_status": payload.get("status"),
                        "payload_verdict": payload.get("verdict"),
                        "payload_passed": payload.get("passed"),
                        "blockers": blockers,
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive artifact preservation
                failed_units.append(unit_id)
                candidate_blockers.append(f"golden_correctness_unreadable::{kernel_id}")
                unit_records.append(
                    {
                        "candidate_id": candidate_id,
                        "kernel_id": kernel_id,
                        "unit_id": unit_id,
                        "status": "blocked_temporary",
                        "artifact_ref": _artifact_ref(report_path),
                        "blockers": [f"golden_correctness_report_unreadable:{type(exc).__name__}: {exc}"],
                    }
                )
        candidate_kernel_set = set(candidate_passed_kernel_ids)
        complete = set(MAJOR_SCF_KERNEL_IDS) <= candidate_kernel_set and not candidate_blockers
        candidate_records.append(
            {
                "candidate_id": candidate_id,
                "status": "passed" if complete else "blocked_temporary",
                "expected_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
                "passed_kernel_ids": candidate_passed_kernel_ids,
                "missing_kernel_ids": sorted(set(MAJOR_SCF_KERNEL_IDS) - candidate_kernel_set),
                "blockers": candidate_blockers,
            }
        )

    passed_candidate_ids = [row["candidate_id"] for row in candidate_records if row["status"] == "passed"]
    passed = len(passed_candidate_ids) == len(legal_candidates) and not missing_units and not failed_units
    return {
        "schema_version": "dse.dft.numerical.kernel_golden_correctness_summary.v1",
        "status": "passed" if passed else "blocked_temporary",
        "passed": passed,
        "candidate_specific_evidence_dir": str(candidate_specific_evidence_dir),
        "candidate_count": len(legal_candidates),
        "expected_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
        "expected_unit_count": len(legal_candidates) * len(MAJOR_SCF_KERNEL_IDS),
        "unit_count": len(unit_records),
        "passed_unit_count": sum(1 for row in unit_records if row["status"] == "passed"),
        "passed_candidate_count": len(passed_candidate_ids),
        "missing_units": missing_units,
        "failed_units": failed_units,
        "candidate_records": candidate_records,
        "unit_records": unit_records,
        "claim_boundary": (
            "Passed kernel golden correctness means every legal candidate has a passed golden_correctness_report.json "
            "for every major SCF kernel. It does not prove full-SCF host+accelerator numerical equivalence."
        ),
    }


def _full_scf_comparison_evidence_summary(
    full_scf_comparison_evidence_path: Path | None,
    legal_candidate_ids: list[str],
) -> dict[str, Any]:
    if full_scf_comparison_evidence_path is None:
        return {
            "schema_version": "dse.dft.numerical.full_scf_comparison_evidence_summary.v1",
            "status": "not_recorded",
            "passed": False,
            "present": False,
            "candidate_records": [],
            "candidate_status_by_id": {},
            "blockers": ["full_scf_comparison_evidence_not_attached"],
            "claim_boundary": (
                "No independent full-SCF host+accelerator end-to-end numerical comparison "
                "artifact was attached."
            ),
        }
    evidence_path = Path(full_scf_comparison_evidence_path)
    if not evidence_path.exists():
        return {
            "schema_version": "dse.dft.numerical.full_scf_comparison_evidence_summary.v1",
            "status": "blocked_temporary",
            "passed": False,
            "present": False,
            "artifact_ref": _artifact_ref(evidence_path),
            "candidate_records": [],
            "candidate_status_by_id": {},
            "blockers": ["full_scf_comparison_evidence_missing"],
            "claim_boundary": "Missing full-SCF comparison evidence cannot satisfy numerical correctness.",
        }

    payload = _load_json(evidence_path)
    top_level_blockers: list[str] = []
    strict_class_ids = [
        str(item)
        for item in (
            payload.get("strict_scf_class_ids")
            or payload.get("workload_class_ids")
            or payload.get("workload_case_ids")
            or []
        )
    ]
    missing_class_ids = [
        class_id for class_id in EXPECTED_STRICT_SCF_CLASS_IDS if class_id not in strict_class_ids
    ]
    extra_class_ids = sorted(set(strict_class_ids) - set(EXPECTED_STRICT_SCF_CLASS_IDS))
    covered_kernel_ids = [
        str(item)
        for item in (
            payload.get("covered_accelerated_kernel_ids")
            or payload.get("accelerated_kernel_ids")
            or payload.get("major_kernel_ids")
            or payload.get("required_kernel_ids")
            or []
        )
    ]
    missing_kernel_ids = [
        kernel_id for kernel_id in MAJOR_SCF_KERNEL_IDS if kernel_id not in covered_kernel_ids
    ]
    if payload.get("status") != "passed" or payload.get("passed") is not True:
        top_level_blockers.append("full_scf_comparison_payload_not_passed")
    if payload.get("comparison_scope") != "full_scf_host_accelerator_end_to_end":
        top_level_blockers.append("comparison_scope_not_full_scf_host_accelerator_end_to_end")
    if payload.get("trusted_accelerated_numeric_source") is not True:
        top_level_blockers.append("trusted_accelerated_numeric_source_not_true")
    if payload.get("host_accelerator_end_to_end") is not True:
        top_level_blockers.append("host_accelerator_end_to_end_not_true")
    if payload.get("full_scf_schedule_consumed") is not True:
        top_level_blockers.append("full_scf_schedule_not_consumed")
    if payload.get("host_bound_costs_included") is not True:
        top_level_blockers.append("host_bound_costs_not_included")
    if payload.get("fixture") is True:
        top_level_blockers.append("fixture_full_scf_comparison_forbidden")
    if payload.get("baseline_copy") is True:
        top_level_blockers.append("baseline_copy_forbidden")
    if payload.get("timing_only") is True:
        top_level_blockers.append("timing_only_comparison_forbidden")
    if missing_class_ids:
        top_level_blockers.append("strict_six_scf_classes_not_all_covered")
    if missing_kernel_ids:
        top_level_blockers.append("major_accelerated_kernels_not_all_covered")

    raw_records = [
        record
        for record in payload.get("candidate_records", []) or []
        if isinstance(record, Mapping) and record.get("candidate_id")
    ]
    records_by_id = {str(record.get("candidate_id")): dict(record) for record in raw_records}
    candidate_status_by_id: dict[str, str] = {}
    candidate_records: list[dict[str, Any]] = []
    missing_candidate_ids = [candidate_id for candidate_id in legal_candidate_ids if candidate_id not in records_by_id]
    if missing_candidate_ids:
        top_level_blockers.append("legal_candidate_full_scf_comparison_records_missing")

    for candidate_id in legal_candidate_ids:
        record = records_by_id.get(candidate_id, {})
        record_blockers = list(top_level_blockers)
        record_class_ids = [
            str(item)
            for item in (
                record.get("strict_scf_class_ids")
                or record.get("workload_class_ids")
                or strict_class_ids
            )
        ]
        record_kernel_ids = [
            str(item)
            for item in (
                record.get("covered_accelerated_kernel_ids")
                or record.get("accelerated_kernel_ids")
                or covered_kernel_ids
            )
        ]
        record_missing_classes = [
            class_id for class_id in EXPECTED_STRICT_SCF_CLASS_IDS if class_id not in record_class_ids
        ]
        record_missing_kernels = [
            kernel_id for kernel_id in MAJOR_SCF_KERNEL_IDS if kernel_id not in record_kernel_ids
        ]
        if not record:
            record_blockers.append("full_scf_comparison_record_missing")
        if record and (record.get("status") != "passed" or record.get("passed") is not True):
            record_blockers.append("candidate_full_scf_comparison_not_passed")
        if record and record.get("comparison_scope", payload.get("comparison_scope")) != "full_scf_host_accelerator_end_to_end":
            record_blockers.append("candidate_comparison_scope_not_full_scf_host_accelerator_end_to_end")
        if record and record.get("trusted_accelerated_numeric_source", payload.get("trusted_accelerated_numeric_source")) is not True:
            record_blockers.append("candidate_trusted_accelerated_numeric_source_not_true")
        if record and record.get("host_accelerator_end_to_end", payload.get("host_accelerator_end_to_end")) is not True:
            record_blockers.append("candidate_host_accelerator_end_to_end_not_true")
        if record and record.get("fixture", False) is True:
            record_blockers.append("candidate_fixture_full_scf_comparison_forbidden")
        if record and record.get("baseline_copy", False) is True:
            record_blockers.append("candidate_baseline_copy_forbidden")
        if record and record.get("timing_only", False) is True:
            record_blockers.append("candidate_timing_only_comparison_forbidden")
        if record_missing_classes:
            record_blockers.append("candidate_strict_six_scf_classes_not_all_covered")
        if record_missing_kernels:
            record_blockers.append("candidate_major_accelerated_kernels_not_all_covered")
        if record and record.get("blockers"):
            record_blockers.append("candidate_record_has_blockers")
        record_status = "passed" if not record_blockers else "blocked_temporary"
        candidate_status_by_id[candidate_id] = record_status
        candidate_records.append(
            {
                "candidate_id": candidate_id,
                "status": record_status,
                "passed": record_status == "passed",
                "strict_scf_class_ids": record_class_ids,
                "missing_strict_scf_class_ids": record_missing_classes,
                "covered_accelerated_kernel_ids": record_kernel_ids,
                "missing_accelerated_kernel_ids": record_missing_kernels,
                "blockers": sorted(dict.fromkeys(record_blockers)),
                "source_record_status": record.get("status"),
                "source_record_passed": record.get("passed"),
                "max_total_energy_error_ry": record.get("max_total_energy_error_ry"),
                "max_density_residual": record.get("max_density_residual"),
                "max_force_error_ry_bohr": record.get("max_force_error_ry_bohr"),
            }
        )

    passed = bool(
        not top_level_blockers
        and not missing_candidate_ids
        and all(status == "passed" for status in candidate_status_by_id.values())
    )
    return {
        "schema_version": "dse.dft.numerical.full_scf_comparison_evidence_summary.v1",
        "status": "passed" if passed else "blocked_temporary",
        "passed": passed,
        "present": True,
        "artifact_ref": _artifact_ref(evidence_path),
        "comparison_scope": payload.get("comparison_scope"),
        "trusted_accelerated_numeric_source": bool(payload.get("trusted_accelerated_numeric_source", False)),
        "host_accelerator_end_to_end": bool(payload.get("host_accelerator_end_to_end", False)),
        "full_scf_schedule_consumed": bool(payload.get("full_scf_schedule_consumed", False)),
        "host_bound_costs_included": bool(payload.get("host_bound_costs_included", False)),
        "strict_scf_class_ids": strict_class_ids,
        "expected_strict_scf_class_ids": list(EXPECTED_STRICT_SCF_CLASS_IDS),
        "missing_strict_scf_class_ids": missing_class_ids,
        "extra_strict_scf_class_ids": extra_class_ids,
        "covered_accelerated_kernel_ids": covered_kernel_ids,
        "expected_accelerated_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
        "missing_accelerated_kernel_ids": missing_kernel_ids,
        "legal_candidate_ids": legal_candidate_ids,
        "missing_candidate_ids": missing_candidate_ids,
        "candidate_records": candidate_records,
        "candidate_status_by_id": candidate_status_by_id,
        "blockers": sorted(dict.fromkeys(top_level_blockers)),
        "claim_boundary": (
            "This gate accepts only a trusted full-SCF host+accelerator end-to-end numerical "
            "comparison that covers the strict six SCF classes, all legal candidates, all major "
            "claimed accelerated kernels, and explicitly includes host-bound/overhead costs. "
            "Timing-only, fixture, baseline-copy, or partial-kernel artifacts remain blocked."
        ),
    }


def _full_scf_end_to_end_summary(
    full_scf_hybrid_artifact_dir: Path | None,
    *,
    full_scf_comparison_evidence_path: Path | None,
    legal_candidate_ids: list[str],
) -> dict[str, Any]:
    comparison_summary = _full_scf_comparison_evidence_summary(
        full_scf_comparison_evidence_path,
        legal_candidate_ids,
    )
    comparison_passed = comparison_summary.get("passed") is True
    if full_scf_hybrid_artifact_dir is None:
        if comparison_passed:
            return {
                "schema_version": "dse.dft.numerical.full_scf_end_to_end_summary.v1",
                "status": "passed",
                "passed": True,
                "present": True,
                "artifact_ref": comparison_summary.get("artifact_ref", {}),
                "comparison_evidence": comparison_summary,
                "candidate_status_by_id": comparison_summary.get("candidate_status_by_id", {}),
                "required_before_correctness_claim": list(FULL_SCF_REQUIRED_BEFORE_CORRECTNESS_CLAIM),
                "blockers": [],
                "claim_boundary": comparison_summary["claim_boundary"],
            }
        return {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_summary.v1",
            "status": "not_recorded",
            "passed": False,
            "present": False,
            "comparison_evidence": comparison_summary,
            "candidate_status_by_id": {},
            "required_before_correctness_claim": list(FULL_SCF_REQUIRED_BEFORE_CORRECTNESS_CLAIM),
            "blockers": ["full_scf_end_to_end_comparison_artifact_not_attached"],
            "claim_boundary": "No full-SCF host+accelerator numerical comparison artifact was attached.",
        }
    report_path = Path(full_scf_hybrid_artifact_dir) / "full_scf_correctness_report.json"
    if not report_path.exists():
        if not comparison_passed:
            return {
                "schema_version": "dse.dft.numerical.full_scf_end_to_end_summary.v1",
                "status": "blocked_temporary",
                "passed": False,
                "present": False,
                "artifact_ref": _artifact_ref(report_path),
                "comparison_evidence": comparison_summary,
                "candidate_status_by_id": comparison_summary.get("candidate_status_by_id", {}),
                "required_before_correctness_claim": list(FULL_SCF_REQUIRED_BEFORE_CORRECTNESS_CLAIM),
                "blockers": ["full_scf_end_to_end_numerical_comparison_not_passed"],
                "claim_boundary": "Missing full_scf_correctness_report.json cannot satisfy full-SCF numerical correctness unless the attached strict comparison already passes.",
            }
        return {
            "schema_version": "dse.dft.numerical.full_scf_end_to_end_summary.v1",
            "status": "passed",
            "passed": True,
            "present": False,
            "artifact_ref": _artifact_ref(report_path),
            "comparison_evidence": comparison_summary,
            "candidate_status_by_id": comparison_summary.get("candidate_status_by_id", {}),
            "required_before_correctness_claim": list(FULL_SCF_REQUIRED_BEFORE_CORRECTNESS_CLAIM),
            "blockers": [],
            "claim_boundary": comparison_summary["claim_boundary"],
        }
    payload = _load_json(report_path)
    report_passed = bool(
        payload.get("status") == "passed"
        and payload.get("numerical_correctness_claim_eligible") is True
        and payload.get("completion_claim") is True
    )
    passed = bool(comparison_passed)
    blockers = [] if passed else ["full_scf_end_to_end_numerical_comparison_not_passed"]
    return {
        "schema_version": "dse.dft.numerical.full_scf_end_to_end_summary.v1",
        "status": "passed" if passed else "blocked_temporary",
        "passed": passed,
        "present": True,
        "artifact_ref": _artifact_ref(report_path),
        "comparison_evidence": comparison_summary,
        "candidate_status_by_id": comparison_summary.get("candidate_status_by_id", {}),
        "report_status": payload.get("status"),
        "report_completion_gate_passed": report_passed,
        "numerical_correctness_claim_eligible": bool(payload.get("numerical_correctness_claim_eligible", False)),
        "completion_claim": bool(payload.get("completion_claim", False)),
        "required_before_correctness_claim": payload.get(
            "required_before_correctness_claim",
            list(FULL_SCF_REQUIRED_BEFORE_CORRECTNESS_CLAIM),
        ),
        "blockers": blockers,
        "claim_boundary": (
            "Only an attached full-SCF host+accelerator numerical comparison with numerical_correctness_claim_eligible=true "
            "can pass this gate. Descriptor validation, full_scf_correctness_report.json, or kernel-level checks alone are insufficient."
        ),
    }


def build_numerical_correctness_evidence(
    out_dir: Path,
    *,
    release_artifact_dir: Path,
    reference_output_hash_manifest: Path,
    candidate_specific_evidence_dir: Path,
    full_scf_hybrid_artifact_dir: Path | None = None,
    full_scf_comparison_evidence_path: Path | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    legal_candidates = _load_legal_candidates(release_artifact_dir)
    legal_candidate_ids = [str(candidate["candidate_id"]) for candidate in legal_candidates]

    reference_admission = _reference_output_admission(reference_output_hash_manifest)
    kernel_golden = _golden_correctness_summary(candidate_specific_evidence_dir, legal_candidates)
    full_scf = _full_scf_end_to_end_summary(
        full_scf_hybrid_artifact_dir,
        full_scf_comparison_evidence_path=full_scf_comparison_evidence_path,
        legal_candidate_ids=legal_candidate_ids,
    )
    full_scf_status_by_candidate = {
        str(candidate_id): str(status)
        for candidate_id, status in (full_scf.get("candidate_status_by_id", {}) or {}).items()
    }

    candidate_records = []
    kernel_records_by_id = {
        str(row["candidate_id"]): row
        for row in kernel_golden.get("candidate_records", [])
        if isinstance(row, Mapping) and row.get("candidate_id")
    }
    for candidate_id in legal_candidate_ids:
        kernel_record = kernel_records_by_id.get(candidate_id, {})
        candidate_full_scf_status = full_scf_status_by_candidate.get(candidate_id, full_scf.get("status"))
        full_passed = bool(
            full_scf.get("passed") is True
            and candidate_full_scf_status in {"passed", True}
        )
        comparison_artifacts: list[dict[str, Any]] = []
        if isinstance(full_scf.get("artifact_ref"), Mapping):
            comparison_artifacts.append(dict(full_scf["artifact_ref"]))
        comparison_evidence = full_scf.get("comparison_evidence", {})
        if isinstance(comparison_evidence, Mapping) and isinstance(comparison_evidence.get("artifact_ref"), Mapping):
            comparison_ref = dict(comparison_evidence["artifact_ref"])
            if comparison_ref not in comparison_artifacts:
                comparison_artifacts.append(comparison_ref)
        reference_passed = reference_admission.get("passed") is True
        kernel_passed = kernel_record.get("status") == "passed"
        status = "passed" if reference_passed and kernel_passed and full_passed else "blocked_temporary"
        blockers: list[str] = []
        if not reference_passed:
            blockers.append("strict_qe_reference_output_admission_not_passed")
        if not kernel_passed:
            blockers.append("per_major_kernel_golden_correctness_not_passed")
        if not full_passed:
            blockers.append("full_scf_end_to_end_numerical_comparison_not_passed")
        candidate_records.append(
            {
                "candidate_id": candidate_id,
                "numerical_job_id": f"numerical::{candidate_id}",
                "status": status,
                "reference_output_admission_status": reference_admission.get("status"),
                "kernel_golden_status": kernel_record.get("status", "blocked_temporary"),
                "full_scf_end_to_end_status": candidate_full_scf_status,
                "passed_kernel_ids": kernel_record.get("passed_kernel_ids", []),
                "missing_kernel_ids": kernel_record.get("missing_kernel_ids", list(MAJOR_SCF_KERNEL_IDS)),
                "comparison_status": {
                    "status": status,
                    "reference_outputs": [reference_admission.get("artifact_ref", {})],
                    "comparison_artifacts": comparison_artifacts,
                    "reason": (
                        "strict QE references and per-kernel golden correctness are attached, but full-SCF end-to-end comparison is still blocked"
                        if reference_passed and kernel_passed and not full_passed
                        else "numerical correctness requires reference admission, kernel golden correctness, and full-SCF end-to-end comparison"
                    ),
                },
                "completion_eligible": status == "passed",
                "blockers": blockers,
                "claim_boundary": (
                    "Candidate numerical row remains blocked until full-SCF host+accelerator end-to-end comparison passes; "
                    "kernel golden correctness and QE reference hashes alone are not full numerical correctness."
                ),
            }
        )

    passed_candidate_count = sum(1 for row in candidate_records if row["status"] == "passed")
    status = "passed" if passed_candidate_count == len(legal_candidate_ids) else "blocked_temporary"
    candidate_blocker_histogram: Counter[str] = Counter()
    for row in candidate_records:
        candidate_blocker_histogram.update(str(blocker) for blocker in row.get("blockers", []) or [])
    top_level_blockers: list[str] = []
    if reference_admission.get("passed") is not True:
        top_level_blockers.append("strict_qe_reference_output_admission_not_passed")
    if kernel_golden.get("passed") is not True:
        top_level_blockers.append("per_major_kernel_golden_correctness_not_passed")
    if full_scf.get("passed") is not True:
        top_level_blockers.append("full_scf_end_to_end_numerical_comparison_not_passed")
    payload = {
        "schema_version": "dse.dft.numerical_correctness_execution_evidence.v1",
        "status": status,
        "release_artifact_dir": str(release_artifact_dir),
        "legal_candidate_ids": legal_candidate_ids,
        "candidate_count": len(legal_candidate_ids),
        "passed_candidate_count": passed_candidate_count,
        "blocked_candidate_count": len(legal_candidate_ids) - passed_candidate_count,
        "reference_output_admission": reference_admission,
        "kernel_golden_correctness": kernel_golden,
        "full_scf_end_to_end_comparison": full_scf,
        "full_scf_comparison_status": full_scf.get("status"),
        "full_scf_comparison_blockers": full_scf.get("blockers", []),
        "reference_output_admission_passed": reference_admission.get("passed") is True,
        "kernel_level_golden_correctness_passed": kernel_golden.get("passed") is True,
        "full_scf_end_to_end_numerical_passed": full_scf.get("passed") is True,
        "candidate_records": candidate_records,
        "blockers": sorted(dict.fromkeys(top_level_blockers)),
        "blocker_count": len(set(top_level_blockers)),
        "candidate_blocker_histogram": dict(sorted(candidate_blocker_histogram.items())),
        "evidence_gap_summary": {
            "status": status,
            "reference_output_admission_passed": reference_admission.get("passed") is True,
            "kernel_level_golden_correctness_passed": kernel_golden.get("passed") is True,
            "full_scf_end_to_end_numerical_passed": full_scf.get("passed") is True,
            "candidate_count": len(legal_candidate_ids),
            "passed_candidate_count": passed_candidate_count,
            "blocked_candidate_count": len(legal_candidate_ids) - passed_candidate_count,
            "top_candidate_blockers": [
                {"blocker": blocker, "count": count}
                for blocker, count in candidate_blocker_histogram.most_common(12)
            ],
            "required_next_evidence": (
                "trusted full-SCF host+accelerator end-to-end numerical comparison"
                if full_scf.get("passed") is not True
                else "none"
            ),
        },
        "source_artifacts": [
            _artifact_ref(release_artifact_dir / "candidate_universe_manifest.json"),
            reference_admission.get("artifact_ref", {}),
            *(
                [full_scf.get("artifact_ref", {})]
                if isinstance(full_scf.get("artifact_ref"), Mapping)
                else []
            ),
            *(
                [full_scf.get("comparison_evidence", {}).get("artifact_ref", {})]
                if isinstance(full_scf.get("comparison_evidence"), Mapping)
                and isinstance(full_scf.get("comparison_evidence", {}).get("artifact_ref"), Mapping)
                else []
            ),
        ],
        "required_before_correctness_claim": list(FULL_SCF_REQUIRED_BEFORE_CORRECTNESS_CLAIM),
        "claim_boundary": (
            "This artifact can document passed strict QE reference admission and passed per-major-kernel golden correctness. "
            "It satisfies numerical_status only if the full-SCF host+accelerator end-to-end numerical comparison gate also passes; otherwise it is progress evidence only."
        ),
    }
    evidence_path = out_dir / "numerical_correctness_execution_evidence.json"
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output evidence directory")
    parser.add_argument("--release-artifact-dir", type=Path, required=True, help="Directory containing candidate_universe_manifest.json")
    parser.add_argument("--reference-output-hash-manifest", type=Path, required=True, help="reference_output_hash_manifest.json for strict QE outputs")
    parser.add_argument("--candidate-specific-evidence-dir", type=Path, required=True, help="Directory containing candidate/kernel golden_correctness_report.json artifacts")
    parser.add_argument("--full-scf-hybrid-artifact-dir", type=Path, default=None, help="Optional full_scf_hybrid_bundle directory")
    parser.add_argument(
        "--full-scf-comparison-evidence",
        type=Path,
        default=None,
        help=(
            "Optional trusted full-SCF host+accelerator end-to-end numerical comparison artifact. "
            "It must cover all strict six SCF classes, all legal candidates, and all major claimed accelerated kernels."
        ),
    )
    args = parser.parse_args(argv)

    payload = build_numerical_correctness_evidence(
        args.out,
        release_artifact_dir=args.release_artifact_dir,
        reference_output_hash_manifest=args.reference_output_hash_manifest,
        candidate_specific_evidence_dir=args.candidate_specific_evidence_dir,
        full_scf_hybrid_artifact_dir=args.full_scf_hybrid_artifact_dir,
        full_scf_comparison_evidence_path=args.full_scf_comparison_evidence,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "artifact": str(args.out / "numerical_correctness_execution_evidence.json"),
                "reference_output_admission_passed": payload["reference_output_admission_passed"],
                "kernel_level_golden_correctness_passed": payload["kernel_level_golden_correctness_passed"],
                "full_scf_end_to_end_numerical_passed": payload["full_scf_end_to_end_numerical_passed"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
