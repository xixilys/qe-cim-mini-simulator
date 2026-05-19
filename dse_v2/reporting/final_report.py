#!/usr/bin/env python3
"""Final report and claim-validation utilities for generic DSE evidence runs.

The reporting layer is intentionally conservative: SystemC/gem5+SystemC
simulation evidence may enter trusted sections, while predicted-only,
analytical/TLM, unavailable, or blocked claims remain visible but cannot become
trusted winners.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

TRUSTED_BACKENDS = {"systemc", "gem5_systemc"}
PREDICTED_FIDELITIES = {"l1", "l2", "analytical", "tlm", "surrogate", "predicted"}
LOW_FIDELITY_ARTIFACT_KEYS = {
    "l1_evaluation_result": "l1_evaluation_result.json",
    "l1_promotion_decision": "l1_promotion_decision.json",
    "l2_evaluation_result": "l2_evaluation_result.json",
    "l2_promotion_decision": "l2_promotion_decision.json",
    "low_fidelity_summary": "low_fidelity_screening_summary.json",
}
LOW_FIDELITY_ARTIFACT_PATHS = list(LOW_FIDELITY_ARTIFACT_KEYS.values())
EVIDENCE_ALIASES = {
    "simulator_consistency_check.json": ["numerical_validation.json"],
}

CLAIM_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "best_architecture": {
        "description": "A final architecture winner/recommendation.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": [
            "verdict.json",
            "workload_package.json",
            "graph_lowering_report.json",
            "simulation_result.json",
            "architecture.json",
            "mapping.json",
            "phase_breakdown.csv",
        ],
        "notes": [
            "Must be backed by SystemC or gem5+SystemC evidence.",
            "Predicted-only, blocked, untrusted, or analytical/TLM claims cannot be winners.",
            "A single pilot may prove feasibility but should not overclaim a cross-candidate best architecture.",
        ],
    },
    "mapping_comparison": {
        "description": "A comparison between mappings or architecture/mapping pairs.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["workload_package.json", "graph_lowering_report.json", "simulation_result.json", "mapping.json", "phase_breakdown.csv", "mapping_simulation_samples.json"],
        "notes": ["Every compared entry must resolve to trusted evidence."],
    },
    "bottleneck": {
        "description": "A timing/resource bottleneck diagnosis.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["workload_package.json", "graph_lowering_report.json", "simulation_result.json", "phase_breakdown.csv", "resource_summary.csv"],
        "notes": ["Phase/resource tables must be cited for trusted bottleneck claims."],
    },
    "feasibility": {
        "description": "A feasibility statement for a specific design point/run.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json"],
        "notes": ["Feasibility is scoped to the cited design/run, not a global DSE winner."],
    },
    "pareto_frontier": {
        "description": "A trusted Pareto-frontier claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", "claim_validation.json", "mapping_simulation_samples.json", "mapping_feedback_state.json"],
        "notes": ["Every Pareto member must be SystemC/gem5+SystemC-backed."],
    },
    "convergence": {
        "description": "A search convergence/budget claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", "mapping_simulation_samples.json", "mapping_feedback_state.json", "convergence_status.json"],
        "notes": ["Budget exhaustion must be explicit when convergence is not proven."],
    },
    "debug_replay": {
        "description": "Replay/debug reproducibility claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["manifest.json", "artifact_manifest.json"],
        "notes": ["Replay commands and artifact locations must resolve."],
    },
    "numerical_correctness": {
        "description": "Numerical equivalence/correctness claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulator_consistency_check.json"],
        "notes": [
            "Timing-level shell evidence is insufficient unless explicit numerical checks are cited.",
            "The generic SystemC timing numeric reference does not prove profile-domain correctness.",
        ],
    },
    "microarchitecture_timing_consistency": {
        "description": "Internal consistency of a gem5 GenericAccel microarchitecture timing result.",
        "trusted_backends": ["gem5_systemc"],
        "required_evidence": [
            "verdict.json",
            "workload_package.json",
            "graph_lowering_report.json",
            "simulation_result.json",
            "simulator_consistency_check.json",
            "gem5_l4_proof.json",
        ],
        "notes": [
            "This is not a profile-domain numerical correctness claim.",
            "It requires the L4 descriptor/decode/microarchitecture/completion proof to pass.",
        ],
    },
        "software_visible_codesign": {
        "description": "A gem5+SystemC software-visible co-design claim for one candidate.",
        "trusted_backends": ["gem5_systemc"],
        "required_evidence": [
            "verdict.json",
            "codesign_candidate.json",
            "codesign_verdict.json",
            "l4_execution_trace.json",
            "completion_proof.json",
            "gem5_l4_proof.json",
        ],
        "notes": [
            "Requires guest descriptor submission, GenericAccel request consumption, in-gem5 microarchitecture execution, and guest-visible completion.",
            "Blocked L4 evidence is reportable as a limitation only.",
        ],
    },
    "low_fidelity_screening": {
        "description": "A Step2 L1/L2 candidate-screening signal.",
        "trusted_backends": [],
        "required_evidence": LOW_FIDELITY_ARTIFACT_PATHS,
        "notes": [
            "L1 analytical and L2 TLM screening are candidate-generation and promotion-gate signals only.",
            "They are visible in final reports but excluded from trusted ranking and winner selection.",
        ],
    },
    "unsupported_stub_limitation": {
        "description": "A limitation/blocker/untrusted-path boundary statement.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json"],
        "notes": ["Blocked or untrusted path claims are reportable limitations, never trusted winners."],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_evidence_index(
    run_dir: Path,
    artifact_paths: Optional[Iterable[str]] = None,
    *,
    generated_in_current_pass: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return an evidence index keyed by relative artifact path."""
    run_dir = Path(run_dir)
    generated_paths = {str(path) for path in (generated_in_current_pass or [])}
    if artifact_paths is None:
        paths: List[str] = []
        artifact_manifest = _load_json(run_dir / "artifact_manifest.json")
        for entry in artifact_manifest.get("artifacts", []) or []:
            rel = entry.get("path")
            if rel:
                paths.append(str(rel))
        if not paths:
            paths = [
                "manifest.json",
                "artifact_manifest.json",
                "verdict.json",
                "design_point.json",
                "architecture.json",
                "mapping.json",
                "workload_package.json",
                "workload_graph.json",
                "graph_lowering_report.json",
                "simulation_request.json",
                "simulation_result.json",
                "simulator_consistency_check.json",
                "numerical_validation.json",
                "phase_breakdown.csv",
                "resource_summary.csv",
                "data_movement_summary.csv",
                "systemc_stdout.log",
                "systemc_stderr.log",
                "gem5_systemc_blockers.json",
            ]
    else:
        paths = [str(path) for path in artifact_paths]
    paths.extend(LOW_FIDELITY_ARTIFACT_PATHS)

    index: Dict[str, Dict[str, Any]] = {}
    for rel in sorted(set(paths)):
        path = run_dir / rel
        entry: Dict[str, Any] = {
            "path": rel,
            "exists": path.exists(),
        }
        if path.exists() and path.is_file():
            entry.update({
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
        elif rel in generated_paths:
            entry.update({
                "exists": True,
                "generated_in_current_report_pass": True,
                "hash_unavailable_reason": "artifact is generated as part of the current report/evidence pass",
            })
        else:
            entry["unavailable_reason"] = "artifact not present in run directory"
        index[rel] = entry
    return index


def evidence_requirement_table() -> List[Dict[str, Any]]:
    """Machine-readable claim classes and evidence requirements."""
    rows: List[Dict[str, Any]] = []
    for claim_type, requirement in CLAIM_REQUIREMENTS.items():
        rows.append({
            "claim_type": claim_type,
            "description": requirement["description"],
            "trusted_backends": requirement["trusted_backends"],
            "required_evidence": requirement["required_evidence"],
            "notes": requirement["notes"],
        })
    return rows


def _claim_backend(claim: Mapping[str, Any]) -> str:
    return str(claim.get("backend", claim.get("source_backend", ""))).lower()


def _claim_fidelity(claim: Mapping[str, Any]) -> str:
    return str(claim.get("fidelity", claim.get("source_fidelity", ""))).lower()


def _claim_evidence_ids(claim: Mapping[str, Any]) -> List[str]:
    evidence_ids = claim.get("evidence_ids", [])
    if isinstance(evidence_ids, str):
        return [evidence_ids]
    if isinstance(evidence_ids, Sequence):
        return [str(item) for item in evidence_ids]
    return []


def _with_gem5_l4_proof_evidence(
    evidence_ids: Iterable[str],
    *,
    backend: str,
    trusted: bool,
    proof_passed: bool,
) -> List[str]:
    ids = list(dict.fromkeys(str(item) for item in evidence_ids))
    if backend == "gem5_systemc" and trusted and proof_passed and "gem5_l4_proof.json" not in ids:
        ids.append("gem5_l4_proof.json")
    return ids


def _evidence_requirement_present(
    required_id: str,
    evidence_ids: Sequence[str],
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> bool:
    candidates = [required_id] + list(EVIDENCE_ALIASES.get(required_id, []))
    return any(candidate in evidence_ids and evidence_index.get(candidate, {}).get("exists", False) for candidate in candidates)


def _verdict_allows_trust(verdict: Mapping[str, Any]) -> bool:
    return bool(verdict.get("trusted_for_final_ranking", False))


def validate_claim(
    claim: Mapping[str, Any],
    *,
    verdict: Mapping[str, Any],
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate a single final-report claim against evidence and status rules."""
    claim_type = str(claim.get("claim_type", "unknown"))
    backend = _claim_backend(claim)
    fidelity = _claim_fidelity(claim)
    evidence_ids = _claim_evidence_ids(claim)
    requirement = CLAIM_REQUIREMENTS.get(claim_type, {})
    required_evidence = [str(x) for x in requirement.get("required_evidence", [])]

    missing_evidence = [
        evidence_id
        for evidence_id in evidence_ids
        if not evidence_index.get(evidence_id, {}).get("exists", False)
    ]
    missing_required = [
        evidence_id
        for evidence_id in required_evidence
        if not _evidence_requirement_present(evidence_id, evidence_ids, evidence_index)
    ]

    reasons: List[str] = []
    status = str(claim.get("status", claim.get("lifecycle_state", ""))).lower()
    if status in {"blocked", "unsupported", "stub", "untrusted"}:
        reasons.append(f"claim status is {status}")
    if bool(claim.get("predicted_only", False)):
        reasons.append("claim is predicted_only")
    if fidelity in PREDICTED_FIDELITIES:
        reasons.append(f"source fidelity {fidelity} is not final-ranking evidence")
    if backend not in TRUSTED_BACKENDS:
        reasons.append(f"backend {backend or '<missing>'} is not trusted for final ranking")
    if not evidence_ids:
        reasons.append("claim has no evidence_ids")
    if missing_evidence:
        reasons.append(f"unresolved evidence ids: {', '.join(missing_evidence)}")
    if missing_required:
        reasons.append(f"required evidence ids absent or unresolved: {', '.join(missing_required)}")
    if not _verdict_allows_trust(verdict) and claim_type != "unsupported_stub_limitation":
        reasons.append("run verdict is not trusted_for_final_ranking")
    if claim_type == "convergence" and not bool(claim.get("converged", False)):
        reasons.append("convergence criterion is not satisfied; budget exhaustion or incomplete search is a limitation")
    if claim_type in {"mapping_comparison", "pareto_frontier"}:
        trusted_sample_count = int(claim.get("trusted_sample_count", 0) or 0)
        if trusted_sample_count < 2:
            reasons.append("comparative claim requires at least two trusted high-fidelity samples")
    if backend == "gem5_systemc" and claim_type != "unsupported_stub_limitation" and status not in {"blocked", "unsupported", "stub", "untrusted"}:
        if not bool(verdict.get("gem5_l4_proof_passed", False)):
            reasons.append("gem5_systemc trusted claim requires passing gem5_l4_proof.json")
        if "gem5_l4_proof.json" not in evidence_ids or not evidence_index.get("gem5_l4_proof.json", {}).get("exists", False):
            reasons.append("gem5_systemc trusted claim must directly cite gem5_l4_proof.json")

    trusted = not reasons and claim_type != "unsupported_stub_limitation"
    validation_status = "trusted" if trusted else "untrusted"
    if bool(claim.get("predicted_only", False)) or fidelity in PREDICTED_FIDELITIES:
        validation_status = "predicted_only"
    elif status in {"blocked", "unsupported", "stub", "untrusted"} or claim_type == "unsupported_stub_limitation":
        validation_status = "blocked_or_limitation"

    return {
        "claim_id": str(claim.get("claim_id", claim_type)),
        "claim_type": claim_type,
        "backend": backend,
        "source_fidelity": fidelity,
        "trusted": trusted,
        "validation_status": validation_status,
        "evidence_ids": evidence_ids,
        "missing_evidence": missing_evidence,
        "reasons": reasons,
    }


def validate_claims(
    claims: Iterable[Mapping[str, Any]],
    *,
    verdict: Mapping[str, Any],
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    validations = [validate_claim(claim, verdict=verdict, evidence_index=evidence_index) for claim in claims]
    trusted_claim_ids = [item["claim_id"] for item in validations if item["trusted"]]
    blocked_or_predicted = [
        item["claim_id"]
        for item in validations
        if item["validation_status"] in {"blocked_or_limitation", "predicted_only"}
    ]
    errors = [
        f"{item['claim_id']}: {'; '.join(item['reasons'])}"
        for item in validations
        if not item["trusted"] and item["validation_status"] not in {"blocked_or_limitation", "predicted_only"}
    ]
    return {
        "schema_version": "dse.claim_validation.v1",
        "generated_at": _now_iso(),
        "trusted_claim_ids": trusted_claim_ids,
        "blocked_or_predicted_claim_ids": blocked_or_predicted,
        "validations": validations,
        "errors": errors,
        "warnings": [],
        "passed": not errors,
    }


def _read_csv_rows(path: Path, limit: int = 1000) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, str]] = []
        for idx, row in enumerate(reader):
            if idx >= limit:
                break
            rows.append(dict(row))
        return rows


def _default_claims(
    *,
    verdict: Mapping[str, Any],
    simulation_result: Mapping[str, Any],
    convergence_status: Optional[Mapping[str, Any]] = None,
    simulation_samples: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    backend = str(verdict.get("backend", simulation_result.get("backend", "systemc")))
    fidelity = "L4" if backend == "gem5_systemc" else "L3"
    trusted = bool(verdict.get("trusted_for_final_ranking", False))
    gem5_l4_proof_passed = bool(verdict.get("gem5_l4_proof_passed", False))
    run_id = str(verdict.get("run_id", simulation_result.get("run_id", "unknown")))

    claims: List[Dict[str, Any]] = [
        {
            "claim_id": "feasibility_current_design",
            "claim_type": "feasibility",
            "statement": "The cited design point completed the selected full workload timing-level run." if trusted else "The cited design point is not trusted for final ranking.",
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if trusted else "blocked",
            "design_point_id": run_id,
            "evidence_ids": _with_gem5_l4_proof_evidence(
                ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", "phase_breakdown.csv"],
                backend=backend,
                trusted=trusted,
                proof_passed=gem5_l4_proof_passed,
            ),
        }
    ]

    if trusted or simulation_result.get("phase_results"):
        claims.append({
            "claim_id": "phase_timing_breakdown",
            "claim_type": "bottleneck",
            "statement": "Phase timing/resource bottleneck analysis is available for the cited run.",
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if trusted else "blocked",
            "design_point_id": run_id,
            "evidence_ids": _with_gem5_l4_proof_evidence(
                ["workload_package.json", "graph_lowering_report.json", "simulation_result.json", "phase_breakdown.csv", "resource_summary.csv"],
                backend=backend,
                trusted=trusted,
                proof_passed=gem5_l4_proof_passed,
            ),
        })

    numerical_validation = (
        simulation_result.get("simulator_consistency_check", {})
        if simulation_result.get("simulator_consistency_check") and isinstance(simulation_result.get("simulator_consistency_check", {}), Mapping)
        else simulation_result.get("numerical_validation", {})
        if isinstance(simulation_result.get("numerical_validation", {}), Mapping)
        else {}
    )
    if numerical_validation.get("passed") is True:
        consistency_artifact = str(numerical_validation.get("artifact") or "simulator_consistency_check.json")
        validation_scope = str(numerical_validation.get("scope", ""))
        if validation_scope == "gem5_microarchitecture_timing_internal_consistency":
            claim_id = "gem5_microarchitecture_timing_consistency"
            claim_type = "microarchitecture_timing_consistency"
            statement = (
                "gem5 GenericAccel microarchitecture timing/resource outputs passed internal "
                "coverage, ordering, and conservation checks; profile-domain correctness is outside this claim."
            )
        else:
            claim_id = "generic_systemc_numeric_reference"
            claim_type = "numerical_correctness"
            statement = (
                "Generic SystemC timing numeric outputs match the independent Python reference model "
                "within declared tolerances; profile-domain correctness is outside this claim."
            )
        claims.append({
            "claim_id": claim_id,
            "claim_type": claim_type,
            "statement": statement,
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if trusted else "blocked",
            "design_point_id": run_id,
            "evidence_ids": _with_gem5_l4_proof_evidence(
                ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", consistency_artifact],
                backend=backend,
                trusted=trusted,
                proof_passed=gem5_l4_proof_passed,
            ),
        })

    if verdict.get("gem5_systemc_blockers"):
        claims.append({
            "claim_id": "gem5_systemc_l4_blocked",
            "claim_type": "unsupported_stub_limitation",
            "statement": "gem5+SystemC full-workload binding is untrusted for this run.",
            "backend": "gem5_systemc",
            "source_fidelity": "L4",
            "predicted_only": False,
            "status": "blocked",
            "design_point_id": run_id,
            "evidence_ids": ["verdict.json", "gem5_systemc_blockers.json"],
        })

    convergence_status = convergence_status or {}
    sample_records = list((simulation_samples or {}).get("samples", []) or [])
    trusted_sample_count = sum(1 for sample in sample_records if sample.get("trusted_final_eligible"))
    if convergence_status:
        claims.append({
            "claim_id": "feedback_convergence_status",
            "claim_type": "convergence",
            "statement": (
                "The feedback loop met its configured convergence criteria."
                if convergence_status.get("converged")
                else "The feedback loop did not prove convergence; stop reason and budget status are reported as limitations."
            ),
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if convergence_status.get("converged") else "blocked",
            "design_point_id": run_id,
            "converged": bool(convergence_status.get("converged", False)),
            "trusted_sample_count": trusted_sample_count,
            "evidence_ids": _with_gem5_l4_proof_evidence([
                "verdict.json",
                "workload_package.json",
                "graph_lowering_report.json",
                "simulation_result.json",
                "mapping_simulation_samples.json",
                "mapping_feedback_state.json",
                "convergence_status.json",
            ], backend=backend, trusted=bool(convergence_status.get("converged", False)), proof_passed=gem5_l4_proof_passed),
        })

    if trusted_sample_count >= 2:
        claims.append({
            "claim_id": "trusted_mapping_sample_comparison",
            "claim_type": "mapping_comparison",
            "statement": "At least two trusted high-fidelity mapping samples are available for bounded comparative ranking.",
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated",
            "design_point_id": run_id,
            "trusted_sample_count": trusted_sample_count,
            "evidence_ids": _with_gem5_l4_proof_evidence([
                "verdict.json",
                "workload_package.json",
                "graph_lowering_report.json",
                "simulation_result.json",
                "mapping.json",
                "phase_breakdown.csv",
                "mapping_simulation_samples.json",
            ], backend=backend, trusted=True, proof_passed=gem5_l4_proof_passed),
        })

    return claims


def _candidate_from_run(
    *,
    design_point: Mapping[str, Any],
    architecture: Mapping[str, Any],
    mapping: Mapping[str, Any],
    simulation_result: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> Dict[str, Any]:
    metrics = simulation_result.get("metrics", {}) if isinstance(simulation_result.get("metrics", {}), Mapping) else {}
    backend = str(simulation_result.get("backend", ""))
    proof = simulation_result.get("gem5_l4_proof", {}) if backend == "gem5_systemc" else {}
    proof_passed = bool(proof.get("passed", False)) if isinstance(proof, Mapping) else False
    evidence_ids = _with_gem5_l4_proof_evidence(
        ["verdict.json", "workload_package.json", "graph_lowering_report.json", "simulation_result.json", "architecture.json", "mapping.json", "phase_breakdown.csv"],
        backend=backend,
        trusted=bool(validation.get("trusted", False)),
        proof_passed=proof_passed,
    )
    return {
        "design_point_id": str(design_point.get("design_point_id", simulation_result.get("run_id", "unknown"))),
        "architecture_id": architecture.get("architecture_id", design_point.get("system_architecture", {}).get("system_id")),
        "mapping_id": mapping.get("mapping_id"),
        "backend": backend,
        "status": simulation_result.get("status"),
        "trusted_scope": "single-run feasibility evidence; not a comparative architecture-winner claim",
        "metrics": {
            "latency_ms": metrics.get("latency_ms"),
            "throughput_gops": metrics.get("throughput_gops"),
            "power_w": metrics.get("power_w"),
            "energy_j": metrics.get("energy_j"),
            "total_data_movement_mb": metrics.get("total_data_movement_mb"),
            "dma_time_ms": metrics.get("dma_time_ms"),
        },
        "validation": validation,
        "evidence_ids": evidence_ids,
    }


def _phase_summary(run_dir: Path) -> Dict[str, Any]:
    rows = _read_csv_rows(run_dir / "phase_breakdown.csv")
    available = [row for row in rows if row.get("status") == "available"]
    slowest = sorted(
        available,
        key=lambda row: float(row.get("latency_ms") or 0.0),
        reverse=True,
    )[:5]
    return {
        "available_phase_count": len(available),
        "missing_phase_count": len(rows) - len(available),
        "slowest_phases": [
            {
                "phase": row.get("phase"),
                "device": row.get("device"),
                "latency_ms": float(row.get("latency_ms") or 0.0),
                "evidence_id": "phase_breakdown.csv",
            }
            for row in slowest
        ],
    }


def _artifact_exists(run_dir: Path, evidence_index: Mapping[str, Mapping[str, Any]], rel_path: str) -> bool:
    entry = evidence_index.get(rel_path)
    if entry is not None:
        return bool(entry.get("exists", False))
    return (run_dir / rel_path).exists()


def _decision_summary(payload: Mapping[str, Any], *, artifact: str, exists: bool) -> Dict[str, Any]:
    return {
        "artifact": artifact,
        "exists": exists,
        "decision": payload.get("decision"),
        "promote": bool(payload.get("promote", False)),
        "from_layer": payload.get("from_layer", payload.get("source_layer")),
        "to_layer": payload.get("to_layer", payload.get("target_layer")),
        "reason": payload.get("reason"),
        "promotion_score": payload.get("promotion_score", payload.get("score")),
        "confidence": payload.get("confidence"),
        "threshold": payload.get("threshold"),
        "low_fidelity_role": payload.get("low_fidelity_role"),
        "trusted_final_claim": bool(payload.get("trusted_final_claim", False)),
    }


def _layer_screening_summary(
    result: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    result_artifact: str,
    decision_artifact: str,
    result_exists: bool,
    decision_exists: bool,
) -> Dict[str, Any]:
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics", {}), Mapping) else {}
    uncertainty = result.get("uncertainty", {}) if isinstance(result.get("uncertainty", {}), Mapping) else {}
    return {
        "artifact": result_artifact,
        "exists": result_exists,
        "fidelity_level_achieved": result.get("fidelity_level_achieved"),
        "status": result.get("status", "missing" if not result_exists else None),
        "design_point_id": result.get("design_point_id"),
        "family": result.get("family"),
        "candidate_id": result.get("candidate_id"),
        "feasible": result.get("feasible"),
        "confidence": result.get("confidence"),
        "promotion_score": result.get("promotion_score"),
        "mape_percent": result.get("mape_percent"),
        "metrics": dict(metrics),
        "uncertainty": dict(uncertainty),
        "provenance": result.get("provenance", {}),
        "candidate_generation_only": bool(result.get("candidate_generation_only", result_exists)),
        "low_fidelity_role": result.get("low_fidelity_role"),
        "trusted_final_claim": bool(result.get("trusted_final_claim", False)),
        "promotion_decision": _decision_summary(decision, artifact=decision_artifact, exists=decision_exists),
    }


def _low_fidelity_screening_section(
    run_dir: Path,
    *,
    evidence_index: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    loaded = {
        key: _load_json(run_dir / filename)
        for key, filename in LOW_FIDELITY_ARTIFACT_KEYS.items()
    }
    exists = {
        key: _artifact_exists(run_dir, evidence_index, filename)
        for key, filename in LOW_FIDELITY_ARTIFACT_KEYS.items()
    }
    present = any(exists.values())
    missing_artifacts = [
        filename
        for key, filename in LOW_FIDELITY_ARTIFACT_KEYS.items()
        if not exists[key]
    ]
    summary = loaded["low_fidelity_summary"]
    status = str(summary.get("status") or ("incomplete" if present and missing_artifacts else "available" if present else "unavailable"))
    l1 = _layer_screening_summary(
        loaded["l1_evaluation_result"],
        loaded["l1_promotion_decision"],
        result_artifact=LOW_FIDELITY_ARTIFACT_KEYS["l1_evaluation_result"],
        decision_artifact=LOW_FIDELITY_ARTIFACT_KEYS["l1_promotion_decision"],
        result_exists=exists["l1_evaluation_result"],
        decision_exists=exists["l1_promotion_decision"],
    )
    l2 = _layer_screening_summary(
        loaded["l2_evaluation_result"],
        loaded["l2_promotion_decision"],
        result_artifact=LOW_FIDELITY_ARTIFACT_KEYS["l2_evaluation_result"],
        decision_artifact=LOW_FIDELITY_ARTIFACT_KEYS["l2_promotion_decision"],
        result_exists=exists["l2_evaluation_result"],
        decision_exists=exists["l2_promotion_decision"],
    )
    return {
        "schema_version": "dse.final_report.low_fidelity_screening.v1",
        "present": present,
        "status": status,
        "summary_artifact": LOW_FIDELITY_ARTIFACT_KEYS["low_fidelity_summary"],
        "summary_exists": exists["low_fidelity_summary"],
        "passed": bool(summary.get("passed", False)),
        "required_for_step3": bool(summary.get("required_for_step3", present)),
        "artifact_refs": (
            dict(summary.get("artifact_refs", LOW_FIDELITY_ARTIFACT_KEYS))
            if isinstance(summary.get("artifact_refs", {}), Mapping)
            else dict(LOW_FIDELITY_ARTIFACT_KEYS)
        ),
        "required_artifacts": (
            list(summary.get("required_artifacts", LOW_FIDELITY_ARTIFACT_PATHS))
            if isinstance(summary.get("required_artifacts", []), list)
            else list(LOW_FIDELITY_ARTIFACT_PATHS)
        ),
        "missing_artifacts": missing_artifacts,
        "loaded_artifacts": [filename for key, filename in LOW_FIDELITY_ARTIFACT_KEYS.items() if exists[key]],
        "candidate_id": summary.get("candidate_id") or l1.get("candidate_id") or l2.get("candidate_id"),
        "mapping_id": summary.get("mapping_id"),
        "policy": summary.get("policy", {}),
        "promotion_scores": summary.get("promotion_scores", {}),
        "thresholds": summary.get("thresholds", {}),
        "confidence": summary.get("confidence", {}),
        "blockers": list(summary.get("blockers", []) or []),
        "l1": l1,
        "l2": l2,
        "candidate_generation_only": True,
        "low_fidelity_role": "candidate_generator_only",
        "trusted_final_claim": False,
        "trusted_final_eligible": False,
        "excluded_from_trusted_ranking": True,
        "notes": [
            "L1/L2 screening is reported for Step2 transparency and Step3 gate traceability only.",
            "Trusted ranking and selected winners require SystemC or gem5+SystemC evidence.",
        ],
    }


def _low_fidelity_claims(low_fidelity: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if not low_fidelity.get("present"):
        return []
    summary_artifact = str(low_fidelity.get("summary_artifact", LOW_FIDELITY_ARTIFACT_KEYS["low_fidelity_summary"]))
    claims: List[Dict[str, Any]] = []
    for layer_key, backend, source_fidelity, statement in [
        (
            "l1",
            "analytical",
            "L1",
            "L1 analytical screening is available as a Step2 candidate-generation signal only.",
        ),
        (
            "l2",
            "tlm",
            "L2",
            "L2 TLM screening is available as a Step2 candidate-generation signal only.",
        ),
    ]:
        layer = low_fidelity.get(layer_key, {}) if isinstance(low_fidelity.get(layer_key, {}), Mapping) else {}
        if not layer.get("exists"):
            continue
        evidence_ids = list(LOW_FIDELITY_ARTIFACT_PATHS)
        if not low_fidelity.get("summary_exists") and summary_artifact in evidence_ids:
            evidence_ids.remove(summary_artifact)
        claims.append({
            "claim_id": f"{layer_key}_screening_candidate_signal",
            "claim_type": "low_fidelity_screening",
            "statement": statement,
            "backend": backend,
            "source_fidelity": source_fidelity,
            "predicted_only": True,
            "status": layer.get("status", "available"),
            "design_point_id": layer.get("design_point_id"),
            "candidate_id": layer.get("candidate_id", low_fidelity.get("candidate_id")),
            "low_fidelity_role": "candidate_generator_only",
            "trusted_final_claim": False,
            "evidence_ids": evidence_ids,
        })
    return claims


def generate_final_report(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build final report, claim validation, and evidence requirements payloads."""
    run_dir = Path(run_dir)
    manifest = _load_json(run_dir / "manifest.json")
    verdict = _load_json(run_dir / "verdict.json")
    design_point = _load_json(run_dir / "design_point.json")
    architecture = _load_json(run_dir / "architecture.json")
    mapping = _load_json(run_dir / "mapping.json")
    workload_package = _load_json(run_dir / "workload_package.json")
    workload_graph = _load_json(run_dir / "workload_graph.json")
    graph_lowering = _load_json(run_dir / "graph_lowering_report.json")
    simulation_result = _load_json(run_dir / "simulation_result.json")
    simulator_consistency_check = _load_json(run_dir / "simulator_consistency_check.json")
    numerical_validation = simulator_consistency_check or _load_json(run_dir / "numerical_validation.json")
    blockers = _load_json(run_dir / "gem5_systemc_blockers.json")
    codesign_candidate = _load_json(run_dir / "codesign_candidate.json")
    codesign_verdict = _load_json(run_dir / "codesign_verdict.json")
    simulation_samples = _load_json(run_dir / "mapping_simulation_samples.json")
    feedback_state = _load_json(run_dir / "mapping_feedback_state.json")
    convergence_status = _load_json(run_dir / "convergence_status.json")
    workflow_payload = simulation_result.get("workflow", workload_package.get("workflow", graph_lowering.get("workflow", {})))
    if not isinstance(workflow_payload, Mapping):
        workflow_payload = {}
    profile_domain_validation = simulation_result.get("domain_validation")
    if not isinstance(profile_domain_validation, Mapping):
        profile_domain_validation = simulation_result.get("profile_domain_validation", verdict.get("domain_validation", {}))
    if not isinstance(profile_domain_validation, Mapping):
        profile_domain_validation = {}
    unavailable_metrics = simulation_result.get("unavailable_metrics", [])
    if not isinstance(unavailable_metrics, list):
        unavailable_metrics = []
    generated_report_paths = {
        "artifact_manifest.json",
        "evidence_requirements.json",
        "claim_validation.json",
        "final_report.json",
        "final_report.md",
    }
    evidence_index = build_evidence_index(
        run_dir,
        artifact_paths=artifact_paths,
        generated_in_current_pass=generated_report_paths,
    )
    low_fidelity_screening = _low_fidelity_screening_section(
        run_dir,
        evidence_index=evidence_index,
    )

    claim_list = list(claims) if claims is not None else _default_claims(
        verdict=verdict,
        simulation_result=simulation_result,
        convergence_status=convergence_status,
        simulation_samples=simulation_samples,
    )
    if claims is None:
        claim_list.extend(_low_fidelity_claims(low_fidelity_screening))
    if claims is None and codesign_verdict:
        codesign_trusted = bool(codesign_verdict.get("trusted_for_codesign_ranking", False))
        claim_list.append({
            "claim_id": "software_visible_codesign_current_candidate",
            "claim_type": "software_visible_codesign",
            "statement": (
                "The cited co-design candidate closed the software-visible descriptor/request/microarchitecture/completion path."
                if codesign_trusted
                else "The cited co-design candidate did not close the L4 software-visible proof path."
            ),
            "backend": "gem5_systemc",
            "source_fidelity": "L4",
            "predicted_only": False,
            "status": "simulated" if codesign_trusted else "blocked",
            "design_point_id": codesign_candidate.get("design_point_id", verdict.get("run_id")),
            "codesign_candidate_id": codesign_candidate.get("codesign_candidate_id"),
            "evidence_ids": [
                "verdict.json",
                "codesign_candidate.json",
                "codesign_verdict.json",
                "l4_execution_trace.json",
                "completion_proof.json",
                "gem5_l4_proof.json",
            ],
        })
    claim_validation = validate_claims(claim_list, verdict=verdict, evidence_index=evidence_index)
    validation_by_id = {item["claim_id"]: item for item in claim_validation["validations"]}

    trusted_validation = validation_by_id.get("feasibility_current_design", {})
    candidate = _candidate_from_run(
        design_point=design_point,
        architecture=architecture,
        mapping=mapping,
        simulation_result=simulation_result,
        validation=trusted_validation,
    )

    sample_records = list(simulation_samples.get("samples", []) or [])
    trusted_sample_records = [sample for sample in sample_records if sample.get("trusted_final_eligible")]
    if len(trusted_sample_records) > 1:
        trusted_ranking = [
            {
                "design_point_id": str(sample.get("candidate_id")),
                "architecture_id": architecture.get("architecture_id", design_point.get("system_architecture", {}).get("system_id")),
                "mapping_id": mapping.get("mapping_id"),
                "backend": sample.get("backend"),
                "status": sample.get("status"),
                "trusted_scope": "bounded multi-candidate high-fidelity ranking; not global convergence unless convergence_status proves it",
                "metrics": sample.get("metrics", {}),
                "validation": {"trusted": True, "validation_status": "trusted"},
                "evidence_ids": list(sample.get("evidence_ids", []) or []),
            }
            for sample in sorted(
                trusted_sample_records,
                key=lambda item: float((item.get("metrics", {}) or {}).get("latency_ms") or float("inf")),
            )
        ]
    else:
        trusted_ranking = [candidate] if trusted_validation.get("trusted") else []
    predicted_only_candidates = [
        {"claim": dict(claim), "validation": validation_by_id.get(str(claim.get("claim_id", claim.get("claim_type", "unknown"))), {})}
        for claim in claim_list
        if bool(claim.get("predicted_only", False)) or _claim_fidelity(claim) in PREDICTED_FIDELITIES
    ]
    blocked_or_untrusted = [
        {"claim": dict(claim), "validation": validation_by_id.get(str(claim.get("claim_id", claim.get("claim_type", "unknown"))), {})}
        for claim in claim_list
        if str(claim.get("status", claim.get("lifecycle_state", ""))).lower() in {"blocked", "unsupported", "stub", "untrusted"}
        or str(claim.get("claim_type")) == "unsupported_stub_limitation"
    ]

    selected_recommendation: Dict[str, Any]
    if len(trusted_sample_records) > 1:
        selected_recommendation = {
            "status": "not_selected",
            "selection_status": "trusted_comparative_ranking_available_but_not_converged"
            if not convergence_status.get("converged")
            else "trusted_converged_recommendation_available",
            "trusted_winner": bool(convergence_status.get("converged", False)),
            "design_point_id": trusted_ranking[0]["design_point_id"],
            "rationale": (
                "Multiple trusted high-fidelity samples are ranked by latency. "
                "The recommendation remains non-global unless convergence_status.json proves configured convergence."
            ),
            "evidence_ids": _with_gem5_l4_proof_evidence(
                _claim_evidence_ids(trusted_ranking[0]) + ["mapping_simulation_samples.json", "convergence_status.json"],
                backend=str(trusted_ranking[0].get("backend", "")),
                trusted=True,
                proof_passed=bool(verdict.get("gem5_l4_proof_passed", False)),
            ),
        }
    elif trusted_ranking:
        selected_recommendation = {
            "status": "not_selected",
            "selection_status": "trusted_feasibility_candidate_not_cross_candidate_winner",
            "trusted_winner": False,
            "design_point_id": candidate["design_point_id"],
            "rationale": (
                "This run is SystemC/gem5+SystemC-backed and feasible for the cited design point. "
                "It is not promoted to a global best-architecture winner without comparable trusted candidates."
            ),
            "evidence_ids": candidate["evidence_ids"],
        }
    else:
        selected_recommendation = {
            "status": "not_selected",
            "selection_status": "no_trusted_recommendation",
            "trusted_winner": False,
            "rationale": "No candidate passed trusted claim validation; predicted-only or blocked entries are excluded from trusted winners.",
            "evidence_ids": ["verdict.json", "claim_validation.json"],
        }

    limitations = list(verdict.get("evidence_gaps", []) or [])
    if blockers.get("blockers"):
        limitations.append("gem5+SystemC L4 binding is untrusted for this run.")
    if codesign_verdict and not codesign_verdict.get("trusted_for_codesign_ranking", False):
        limitations.append("Software-visible co-design claim is blocked until codesign_verdict.json and gem5_l4_proof.json pass.")
    if not trusted_ranking:
        limitations.append("No trusted final ranking is available from the cited evidence.")
    if convergence_status:
        limitations.extend(str(item) for item in convergence_status.get("limitations", []) or [])
        if convergence_status.get("stop_reason") == "budget_exhausted" and not convergence_status.get("converged"):
            limitations.append("Feedback loop stopped by budget exhaustion; this is not proof of global convergence.")
    importer_payload = workload_package.get("importer", {}) if isinstance(workload_package.get("importer", {}), Mapping) else {}
    if workload_package and importer_payload.get("claim_boundary") not in {"full_workload", "full", "end_to_end"}:
        limitations.append("WorkloadPackage claim boundary is reduced/diagnostic; trusted final claims are not allowed for this run.")
    if graph_lowering and not graph_lowering.get("full_workload_eligible", False):
        limitations.append("Graph lowering report is not full-workload eligible; final trusted claims are blocked for this run.")
    if low_fidelity_screening.get("present"):
        limitations.append("Step2 L1/L2 screening is low-fidelity candidate-generation evidence only; it is excluded from trusted final ranking.")
    workload_family = manifest.get("workload_family", workload_package.get("workload_family"))
    if numerical_validation.get("passed"):
        limitations.append(
            "Timing-level numeric outputs are reference-validated for this generic SystemC run, "
            "but this does not prove profile-specific domain correctness or board/ASIC results."
        )
    else:
        limitations.append("Timing-level workload evidence does not by itself prove profile-specific domain correctness or board/ASIC results.")
    if profile_domain_validation:
        limitations.append(str(profile_domain_validation.get("boundary", "Profile/importer-domain correctness is unclaimed without profile/importer validation evidence.")))

    report = {
        "schema_version": "dse.final_report.v1",
        "generated_at": _now_iso(),
        "run_metadata": {
            "run_id": manifest.get("run_id", verdict.get("run_id", simulation_result.get("run_id"))),
            "backend": manifest.get("backend", verdict.get("backend", simulation_result.get("backend"))),
            "evidence_mode": manifest.get("evidence_mode", verdict.get("evidence_mode")),
            "trusted_for_final_ranking": bool(verdict.get("trusted_for_final_ranking", False)),
            "manifest": "manifest.json",
            "verdict": "verdict.json",
        },
        "workload": {
            "workload_id": manifest.get("workload", workload_package.get("workload_id", workload_graph.get("graph_id"))),
            "workload_family": workload_family,
            "profile_id": (workload_package.get("profile", {}) or {}).get("profile_id", verdict.get("workload_package", {}).get("profile_id")),
            "profile_version": (workload_package.get("profile", {}) or {}).get("profile_version", verdict.get("workload_package", {}).get("profile_version")),
            "importer_id": importer_payload.get("importer_id", manifest.get("workload_importer")),
            "importer_version": importer_payload.get("importer_version"),
            "claim_boundary": importer_payload.get("claim_boundary"),
            "source": workload_package.get("source", {}),
            "profile": workflow_payload,
            "workflow": workflow_payload,
            "graph_id": workload_graph.get("graph_id"),
            "graph_lowering": {
                "artifact": "graph_lowering_report.json",
                "status": graph_lowering.get("status"),
                "full_workload_eligible": graph_lowering.get("full_workload_eligible"),
                "unsupported_constructs": graph_lowering.get("unsupported_constructs", []),
            },
            "required_coverage": simulation_result.get("required_coverage", simulation_result.get("profile_required_coverage", [])),
            "profile_required_coverage": simulation_result.get("profile_required_coverage", simulation_result.get("required_coverage", [])),
            "missing_required_coverage": simulation_result.get("missing_required_coverage", []),
            "domain_validation": simulation_result.get("domain_validation", profile_domain_validation),
            "profile_domain_validation": simulation_result.get("profile_domain_validation", profile_domain_validation),
            "unavailable_metrics": unavailable_metrics,
            "phase_summary": _phase_summary(run_dir),
        },
        "architecture_catalog_scope": {
            "architecture_id": architecture.get("architecture_id"),
            "architecture_family": architecture.get("architecture_family"),
            "status": architecture.get("status"),
            "trusted_final_eligible": architecture.get("trusted_final_eligible", False),
            "scope": architecture.get("architecture_scope"),
        },
        "search_configuration": {
            "mapping_policy": mapping.get("mapping_policy"),
            "search_status": mapping.get("search_status"),
            "scheduling_policy": design_point.get("scheduling_policy"),
            "config": design_point.get("config", {}),
        },
        "feedback_loop": {
            "simulation_samples_artifact": "mapping_simulation_samples.json",
            "feedback_state_artifact": "mapping_feedback_state.json",
            "convergence_status_artifact": "convergence_status.json",
            "sample_count": len(sample_records),
            "trusted_sample_count": len(trusted_sample_records),
            "feedback_state_summary": {
                "screened_count": feedback_state.get("screened_count"),
                "promoted_count": feedback_state.get("promoted_count"),
                "simulation_budget": feedback_state.get("simulation_budget", {}),
                "ranking_update": feedback_state.get("ranking_update", {}),
            },
            "convergence": convergence_status,
        },
        "low_fidelity_screening": low_fidelity_screening,
        "codesign": {
            "candidate_artifact": "codesign_candidate.json" if codesign_candidate else None,
            "verdict_artifact": "codesign_verdict.json" if codesign_verdict else None,
            "codesign_candidate_id": codesign_candidate.get("codesign_candidate_id"),
            "l4_required": bool(
                (codesign_candidate.get("promotion_policy", {}) or {}).get("l4_required", False)
                if isinstance(codesign_candidate.get("promotion_policy", {}), Mapping)
                else False
            ),
            "trusted_for_codesign_ranking": bool(codesign_verdict.get("trusted_for_codesign_ranking", False)),
            "status": codesign_verdict.get("status", "not_run" if codesign_candidate else "unavailable"),
            "evidence_ids": codesign_verdict.get("evidence_ids", []),
        },
        "numerical_validation": {
            "artifact": "simulator_consistency_check.json" if simulator_consistency_check else "numerical_validation.json",
            "status": numerical_validation.get("status"),
            "passed": bool(numerical_validation.get("passed", False)),
            "scope": numerical_validation.get("scope"),
            "summary": numerical_validation.get("summary", {}),
            "domain_correctness_boundary": numerical_validation.get("domain_correctness_boundary"),
        },
        "trusted_ranking": trusted_ranking,
        "predicted_only_candidates": predicted_only_candidates,
        "blocked_or_untrusted": blocked_or_untrusted,
        "pareto_alternatives": [],
        "selected_recommendation": selected_recommendation,
        "claims": claim_list,
        "claim_validation": claim_validation,
        "evidence_requirements": evidence_requirement_table(),
        "evidence_index": evidence_index,
        "limitations": limitations,
        "replay_instructions": {
            "python_replay_command": manifest.get("replay_metadata", {}).get("python_replay_command", manifest.get("cli_command", [])),
            "simulator_replay_command": manifest.get("replay_metadata", {}).get("simulator_replay_command", manifest.get("simulator_command", [])),
            "run_directory": str(run_dir),
            "required_artifact_index": "artifact_manifest.json",
        },
    }

    requirements_payload = {
        "schema_version": "dse.evidence_requirements.v1",
        "generated_at": _now_iso(),
        "requirements": evidence_requirement_table(),
        "trusted_backend_policy": sorted(TRUSTED_BACKENDS),
        "predicted_fidelity_policy": sorted(PREDICTED_FIDELITIES),
    }
    return report, claim_validation, requirements_payload


def render_markdown_report(report: Mapping[str, Any]) -> str:
    """Render a concise audit-friendly Markdown report."""
    run = report.get("run_metadata", {})
    selected = report.get("selected_recommendation", {})
    workload = report.get("workload", {}) if isinstance(report.get("workload", {}), Mapping) else {}
    domain_validation = workload.get("profile_domain_validation", workload.get("domain_validation", {}))
    domain_validation = domain_validation if isinstance(domain_validation, Mapping) else {}
    lines = [
        "# Generic DSE Final Report",
        "",
        "## Executive Summary",
        f"- Run id: `{run.get('run_id')}`",
        f"- Backend: `{run.get('backend')}`",
        f"- Workload family: `{workload.get('workload_family')}`",
        f"- Profile: `{workload.get('profile_id')}` `{workload.get('profile_version')}`",
        f"- Importer: `{workload.get('importer_id')}` `{workload.get('importer_version')}`",
        f"- Trusted for final ranking: `{run.get('trusted_for_final_ranking')}`",
        f"- Recommendation status: `{selected.get('selection_status')}`",
        f"- Trusted winner: `{selected.get('trusted_winner')}`",
        f"- Profile/importer-domain validation: `{domain_validation.get('status')}`",
        "",
        "## Trusted Ranking",
    ]
    trusted = report.get("trusted_ranking", []) or []
    if trusted:
        for idx, candidate in enumerate(trusted, start=1):
            metrics = candidate.get("metrics", {})
            lines.append(
                f"{idx}. `{candidate.get('design_point_id')}` — latency `{metrics.get('latency_ms')}` ms, "
                f"energy `{metrics.get('energy_j')}` J, evidence `{', '.join(candidate.get('evidence_ids', []))}`"
            )
    else:
        lines.append("- No trusted ranking entries; predicted-only and blocked candidates are excluded from winners.")

    lines.extend(["", "## Predicted-only / Blocked / Untrusted", ""])
    blocked = report.get("blocked_or_untrusted", []) or []
    predicted = report.get("predicted_only_candidates", []) or []
    if not blocked and not predicted:
        lines.append("- None recorded.")
    for item in predicted:
        claim = item.get("claim", {})
        lines.append(f"- Predicted-only: `{claim.get('claim_id', claim.get('claim_type'))}`")
    for item in blocked:
        claim = item.get("claim", {})
        lines.append(f"- Blocked/untrusted: `{claim.get('claim_id', claim.get('claim_type'))}` — {claim.get('statement', '')}")

    low_fidelity = report.get("low_fidelity_screening", {})
    low_fidelity = low_fidelity if isinstance(low_fidelity, Mapping) else {}
    l1 = low_fidelity.get("l1", {}) if isinstance(low_fidelity.get("l1", {}), Mapping) else {}
    l2 = low_fidelity.get("l2", {}) if isinstance(low_fidelity.get("l2", {}), Mapping) else {}
    lines.extend([
        "",
        "## Low-Fidelity Screening",
        f"- Present: `{low_fidelity.get('present')}`",
        f"- Status: `{low_fidelity.get('status')}`",
        f"- Passed Step3 gate: `{low_fidelity.get('passed')}`",
        f"- Role: `{low_fidelity.get('low_fidelity_role')}`",
        f"- Excluded from trusted ranking: `{low_fidelity.get('excluded_from_trusted_ranking')}`",
    ])
    if low_fidelity.get("present"):
        lines.extend([
            f"- L1: `{l1.get('status')}` confidence `{l1.get('confidence')}` score `{l1.get('promotion_score')}`",
            f"- L2: `{l2.get('status')}` confidence `{l2.get('confidence')}` score `{l2.get('promotion_score')}`",
            f"- Missing artifacts: `{', '.join(low_fidelity.get('missing_artifacts', []) or []) or 'none'}`",
        ])
    else:
        lines.append("- No L1/L2 screening artifacts found in this run directory.")

    feedback = report.get("feedback_loop", {}) or {}
    convergence = feedback.get("convergence", {}) or {}
    lines.extend([
        "",
        "## Feedback / Convergence",
        f"- Sample count: `{feedback.get('sample_count')}`",
        f"- Trusted sample count: `{feedback.get('trusted_sample_count')}`",
        f"- Converged: `{convergence.get('converged')}`",
        f"- Stop reason: `{convergence.get('stop_reason')}`",
        f"- Budget: `{convergence.get('simulation_budget')}`",
    ])

    lines.extend(["", "## Claim Validation", ""])
    for validation in report.get("claim_validation", {}).get("validations", []) or []:
        reason = "; ".join(validation.get("reasons", [])) or "ok"
        lines.append(
            f"- `{validation.get('claim_id')}`: `{validation.get('validation_status')}`, "
            f"trusted=`{validation.get('trusted')}` ({reason})"
        )

    lines.extend(["", "## Limitations", ""])
    for limitation in report.get("limitations", []) or []:
        lines.append(f"- {limitation}")

    replay = report.get("replay_instructions", {})
    lines.extend([
        "",
        "## Replay Instructions",
        f"- Python command: `{replay.get('python_replay_command')}`",
        f"- Simulator command: `{replay.get('simulator_replay_command')}`",
        f"- Run directory: `{replay.get('run_directory')}`",
        f"- Artifact index: `{replay.get('required_artifact_index')}`",
        "",
    ])
    return "\n".join(lines)


def write_final_report_artifacts(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Compatibility wrapper for Step4 claim validation plus Step5 reports.

    New staged flows should call ``write_step4_claim_validation_artifacts`` from
    evidence adjudication and ``write_step5_report_artifacts`` from reporting.
    This wrapper remains for older full-flow callers that still expect one API.
    """
    step4_paths = write_step4_claim_validation_artifacts(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    step5_paths = write_step5_report_artifacts(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    return {**step4_paths, **step5_paths}


def write_step4_claim_validation_artifacts(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Generate Step4-owned evidence requirements and claim validation."""
    run_dir = Path(run_dir)
    _report, claim_validation, requirements = generate_final_report(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    _write_json(run_dir / "evidence_requirements.json", requirements)
    _write_json(run_dir / "claim_validation.json", claim_validation)
    return {
        "evidence_requirements": "evidence_requirements.json",
        "claim_validation": "claim_validation.json",
    }


def write_step5_report_artifacts(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Generate Step5-owned final report, ranking, and summary artifacts."""
    run_dir = Path(run_dir)
    missing_step4 = [
        artifact
        for artifact in ("verdict.json", "claim_validation.json", "evidence_requirements.json")
        if not (run_dir / artifact).exists()
    ]
    if missing_step4:
        raise ValueError(
            "Step5 report generation requires Step4 adjudication artifacts before final report writing: "
            + ", ".join(missing_step4)
        )
    source_claim_validation = _load_json(run_dir / "claim_validation.json")
    if not source_claim_validation:
        raise ValueError("Step5 report generation requires a non-empty Step4 claim_validation.json")
    report, _claim_validation, _requirements = generate_final_report(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    report.setdefault("run_metadata", {})["source_step4_claim_validation"] = "claim_validation.json"
    report.setdefault("run_metadata", {})["source_step4_claim_validation_passed"] = bool(source_claim_validation.get("passed", False))
    report.setdefault("run_metadata", {})["step5_trust_boundary"] = (
        "Step5 presents Step4 evidence and may report blocked claims; it does not upgrade unpassed Step4 claim validation."
    )
    _write_json(run_dir / "final_report.json", report)
    _write_text(run_dir / "final_report.md", render_markdown_report(report))
    campaign_summary = {
        "schema_version": "dse.step5.campaign_summary.v1",
        "generated_at": _now_iso(),
        "run_metadata": report.get("run_metadata", {}),
        "selected_recommendation": report.get("selected_recommendation", {}),
        "trusted_ranking_count": len(report.get("trusted_ranking", []) or []),
        "limitations": report.get("limitations", []),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json", "evidence_requirements.json"],
    }
    _write_json(run_dir / "campaign_summary.json", campaign_summary)
    _write_json(run_dir / "trusted_ranking.json", {
        "schema_version": "dse.step5.trusted_ranking.v1",
        "generated_at": _now_iso(),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json"],
        "trusted_ranking": report.get("trusted_ranking", []),
    })
    _write_json(run_dir / "pareto_frontier.json", {
        "schema_version": "dse.step5.pareto_frontier.v1",
        "generated_at": _now_iso(),
        "source_step4_artifacts": ["verdict.json", "claim_validation.json"],
        "pareto_alternatives": report.get("pareto_alternatives", []),
    })
    return {
        "final_report_json": "final_report.json",
        "final_report_markdown": "final_report.md",
        "campaign_summary": "campaign_summary.json",
        "trusted_ranking": "trusted_ranking.json",
        "pareto_frontier": "pareto_frontier.json",
    }


def validate_report_claims(report: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
    """Compatibility validator for report-shaped claim payloads.

    The newer report path validates explicit claim lists with ``validate_claims``.
    Some tests and downstream scripts still pass a complete report object and
    expect a compact ``errors``/``warnings`` contract.  Keep this wrapper
    conservative so predicted-only or low-fidelity winners remain rejected even
    when a caller has not built a full evidence index.
    """
    run_dir = Path(run_dir)
    errors: List[str] = []
    warnings: List[str] = []
    claims = report.get("claims", []) or []
    if not isinstance(claims, list):
        errors.append("claims must be a list")
        claims = []

    trusted_claim_count = 0
    winner_claim_types = {"best_architecture", "selected_recommendation", "pareto_frontier"}
    for idx, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            errors.append(f"claim[{idx}] is not an object")
            continue
        claim_id = str(claim.get("claim_id", f"claim[{idx}]"))
        claim_type = str(claim.get("claim_type", ""))
        predicted_only = bool(claim.get("predicted_only", False))
        blocked = bool(claim.get("blocked", False)) or str(claim.get("status", "")).lower() == "blocked"
        trusted = bool(claim.get("trusted", False))
        backend = _claim_backend(claim)
        fidelity = _claim_fidelity(claim)
        evidence_ids = _claim_evidence_ids(claim)

        if predicted_only and claim_type in winner_claim_types:
            errors.append(f"{claim_id}: predicted-only candidate cannot be a winner/Pareto claim")
        if trusted:
            trusted_claim_count += 1
            package = report.get("workload", {}) if isinstance(report.get("workload", {}), Mapping) else {}
            if package.get("claim_boundary") and package.get("claim_boundary") not in {"full_workload", "full", "end_to_end"}:
                errors.append(f"{claim_id}: trusted claim cannot use reduced/diagnostic workload boundary {package.get('claim_boundary')}")
            lowering = package.get("graph_lowering", {}) if isinstance(package.get("graph_lowering", {}), Mapping) else {}
            if lowering and lowering.get("full_workload_eligible") is False:
                errors.append(f"{claim_id}: trusted claim requires full-workload eligible graph lowering")
            if predicted_only:
                errors.append(f"{claim_id}: trusted claim cannot be predicted_only")
            if blocked:
                errors.append(f"{claim_id}: trusted claim cannot be blocked")
            if backend not in TRUSTED_BACKENDS:
                errors.append(f"{claim_id}: trusted claim backend must be SystemC or gem5+SystemC")
            if fidelity in PREDICTED_FIDELITIES:
                errors.append(f"{claim_id}: trusted claim cannot use low-fidelity source")
            if not evidence_ids:
                errors.append(f"{claim_id}: trusted claim must list evidence_ids")
        for evidence_id in evidence_ids:
            rel = Path(str(evidence_id))
            if rel.is_absolute() or ".." in rel.parts:
                errors.append(f"{claim_id}: evidence id must be a run-local relative path: {evidence_id}")
            elif not (run_dir / rel).exists():
                errors.append(f"{claim_id}: evidence id does not resolve to a file: {evidence_id}")

    selected = report.get("selected_recommendation", {}) or {}
    if isinstance(selected, Mapping) and selected.get("status") == "selected":
        evidence_ids = _claim_evidence_ids(selected)
        if selected.get("predicted_only"):
            errors.append("selected_recommendation: predicted-only candidate cannot be selected")
        if selected.get("backend") not in TRUSTED_BACKENDS:
            errors.append("selected_recommendation: backend must be SystemC or gem5+SystemC")
        if not evidence_ids:
            errors.append("selected_recommendation: selected design requires evidence_ids")
        for evidence_id in evidence_ids:
            rel = Path(str(evidence_id))
            if rel.is_absolute() or ".." in rel.parts:
                errors.append(f"selected_recommendation: evidence id must be a run-local relative path: {evidence_id}")
            elif not (run_dir / rel).exists():
                errors.append(f"selected_recommendation: evidence id does not resolve: {evidence_id}")
    else:
        warnings.append("No comparative selected recommendation emitted; report is single-run evidence only.")

    return {
        "schema_version": "dse.claim_validation.compat.v1",
        "generated_at": _now_iso(),
        "passed": not errors,
        "trusted_claim_count": trusted_claim_count,
        "errors": errors,
        "warnings": warnings,
    }


def generate_final_report_artifacts(
    run_dir: Path,
    *,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    artifact_paths: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Compatibility wrapper that writes report artifacts and returns summary keys."""
    paths = write_final_report_artifacts(run_dir, claims=claims, artifact_paths=artifact_paths)
    validation = _load_json(Path(run_dir) / "claim_validation.json")
    return {
        **paths,
        "report_path": str(Path(run_dir) / paths["final_report_json"]),
        "markdown_path": str(Path(run_dir) / paths["final_report_markdown"]),
        "validation_path": str(Path(run_dir) / paths["claim_validation"]),
        "validation_passed": bool(validation.get("passed", False)),
        "trusted_claim_count": len(validation.get("trusted_claim_ids", []) or []),
    }
