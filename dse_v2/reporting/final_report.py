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

CLAIM_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "best_architecture": {
        "description": "A final architecture winner/recommendation.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": [
            "verdict.json",
            "simulation_result.json",
            "architecture.json",
            "mapping.json",
            "phase_breakdown.csv",
        ],
        "notes": [
            "Must be backed by SystemC or gem5+SystemC evidence.",
            "Predicted-only, blocked, prototype-only, or analytical/TLM claims cannot be winners.",
            "A single pilot may prove feasibility but should not overclaim a cross-candidate best architecture.",
        ],
    },
    "mapping_comparison": {
        "description": "A comparison between mappings or architecture/mapping pairs.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["simulation_result.json", "mapping.json", "phase_breakdown.csv"],
        "notes": ["Every compared entry must resolve to trusted evidence."],
    },
    "bottleneck": {
        "description": "A timing/resource bottleneck diagnosis.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["simulation_result.json", "phase_breakdown.csv", "resource_summary.csv"],
        "notes": ["Phase/resource tables must be cited for trusted bottleneck claims."],
    },
    "feasibility": {
        "description": "A feasibility statement for a specific design point/run.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "simulation_result.json"],
        "notes": ["Feasibility is scoped to the cited design/run, not a global DSE winner."],
    },
    "pareto_frontier": {
        "description": "A trusted Pareto-frontier claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "simulation_result.json", "claim_validation.json"],
        "notes": ["Every Pareto member must be SystemC/gem5+SystemC-backed."],
    },
    "convergence": {
        "description": "A search convergence/budget claim.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json", "simulation_result.json"],
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
        "required_evidence": ["verdict.json"],
        "notes": ["Timing-level shell evidence is insufficient unless explicit numerical checks are cited."],
    },
    "unsupported_stub_limitation": {
        "description": "A limitation/blocker/prototype boundary statement.",
        "trusted_backends": sorted(TRUSTED_BACKENDS),
        "required_evidence": ["verdict.json"],
        "notes": ["Blocked/prototype claims are reportable limitations, never trusted winners."],
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


def build_evidence_index(run_dir: Path, artifact_paths: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Return an evidence index keyed by relative artifact path."""
    run_dir = Path(run_dir)
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
                "workload_graph.json",
                "simulation_request.json",
                "simulation_result.json",
                "phase_breakdown.csv",
                "resource_summary.csv",
                "data_movement_summary.csv",
                "systemc_stdout.log",
                "systemc_stderr.log",
                "gem5_systemc_blockers.json",
            ]
    else:
        paths = [str(path) for path in artifact_paths]

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
        if evidence_id not in evidence_ids or not evidence_index.get(evidence_id, {}).get("exists", False)
    ]

    reasons: List[str] = []
    status = str(claim.get("status", claim.get("lifecycle_state", ""))).lower()
    if status in {"blocked", "unsupported", "stub", "prototype-unverified"}:
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

    trusted = not reasons and claim_type != "unsupported_stub_limitation"
    validation_status = "trusted" if trusted else "untrusted"
    if bool(claim.get("predicted_only", False)) or fidelity in PREDICTED_FIDELITIES:
        validation_status = "predicted_only"
    elif status in {"blocked", "unsupported", "stub", "prototype-unverified"} or claim_type == "unsupported_stub_limitation":
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
    return {
        "schema_version": "dse.claim_validation.v1",
        "generated_at": _now_iso(),
        "trusted_claim_ids": trusted_claim_ids,
        "blocked_or_predicted_claim_ids": blocked_or_predicted,
        "validations": validations,
        "passed": all(
            item["trusted"] or item["validation_status"] in {"blocked_or_limitation", "predicted_only"}
            for item in validations
        ),
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
) -> List[Dict[str, Any]]:
    backend = str(verdict.get("backend", simulation_result.get("backend", "systemc")))
    fidelity = "L4" if backend == "gem5_systemc" else "L3"
    trusted = bool(verdict.get("trusted_for_final_ranking", False))
    run_id = str(verdict.get("run_id", simulation_result.get("run_id", "unknown")))

    claims: List[Dict[str, Any]] = [
        {
            "claim_id": "feasibility_current_design",
            "claim_type": "feasibility",
            "statement": "The cited design point completed the timing-level QE SCF shell run." if trusted else "The cited design point is not trusted for final ranking.",
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if trusted else "blocked",
            "design_point_id": run_id,
            "evidence_ids": ["verdict.json", "simulation_result.json", "phase_breakdown.csv"],
        }
    ]

    if simulation_result.get("phase_results"):
        claims.append({
            "claim_id": "phase_timing_breakdown",
            "claim_type": "bottleneck",
            "statement": "Phase timing/resource bottleneck analysis is available for the cited run.",
            "backend": backend,
            "source_fidelity": fidelity,
            "predicted_only": False,
            "status": "simulated" if trusted else "blocked",
            "design_point_id": run_id,
            "evidence_ids": ["simulation_result.json", "phase_breakdown.csv", "resource_summary.csv"],
        })

    if verdict.get("gem5_systemc_blockers"):
        claims.append({
            "claim_id": "gem5_systemc_l4_blocked",
            "claim_type": "unsupported_stub_limitation",
            "statement": "gem5+SystemC full QE SCF shell binding is blocked/prototype for this run.",
            "backend": "gem5_systemc",
            "source_fidelity": "L4",
            "predicted_only": False,
            "status": "blocked",
            "design_point_id": run_id,
            "evidence_ids": ["verdict.json", "gem5_systemc_blockers.json"],
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
    return {
        "design_point_id": str(design_point.get("design_point_id", simulation_result.get("run_id", "unknown"))),
        "architecture_id": architecture.get("architecture_id", design_point.get("system_architecture", {}).get("system_id")),
        "mapping_id": mapping.get("mapping_id"),
        "backend": simulation_result.get("backend"),
        "status": simulation_result.get("status"),
        "metrics": {
            "latency_ms": metrics.get("latency_ms"),
            "throughput_gops": metrics.get("throughput_gops"),
            "power_w": metrics.get("power_w"),
            "energy_j": metrics.get("energy_j"),
            "total_data_movement_mb": metrics.get("total_data_movement_mb"),
            "dma_time_ms": metrics.get("dma_time_ms"),
        },
        "validation": validation,
        "evidence_ids": ["verdict.json", "simulation_result.json", "architecture.json", "mapping.json", "phase_breakdown.csv"],
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
    workload_graph = _load_json(run_dir / "workload_graph.json")
    simulation_result = _load_json(run_dir / "simulation_result.json")
    blockers = _load_json(run_dir / "gem5_systemc_blockers.json")
    evidence_index = build_evidence_index(run_dir, artifact_paths=artifact_paths)

    claim_list = list(claims) if claims is not None else _default_claims(verdict=verdict, simulation_result=simulation_result)
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

    trusted_ranking = [candidate] if trusted_validation.get("trusted") else []
    predicted_only_candidates = [
        {"claim": dict(claim), "validation": validation_by_id.get(str(claim.get("claim_id", claim.get("claim_type", "unknown"))), {})}
        for claim in claim_list
        if bool(claim.get("predicted_only", False)) or _claim_fidelity(claim) in PREDICTED_FIDELITIES
    ]
    blocked_or_prototype = [
        {"claim": dict(claim), "validation": validation_by_id.get(str(claim.get("claim_id", claim.get("claim_type", "unknown"))), {})}
        for claim in claim_list
        if str(claim.get("status", claim.get("lifecycle_state", ""))).lower() in {"blocked", "unsupported", "stub", "prototype-unverified"}
        or str(claim.get("claim_type")) == "unsupported_stub_limitation"
    ]

    selected_recommendation: Dict[str, Any]
    if trusted_ranking:
        selected_recommendation = {
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
            "selection_status": "no_trusted_recommendation",
            "trusted_winner": False,
            "rationale": "No candidate passed trusted claim validation; predicted-only or blocked entries are excluded from trusted winners.",
            "evidence_ids": ["verdict.json", "claim_validation.json"],
        }

    limitations = list(verdict.get("evidence_gaps", []) or [])
    if blockers.get("blockers"):
        limitations.append("gem5+SystemC L4 binding remains blocked/prototype for this run.")
    if not trusted_ranking:
        limitations.append("No trusted final ranking is available from the cited evidence.")
    limitations.append("Timing-level QE SCF shell evidence does not by itself prove numerical QE correctness or board/ASIC results.")

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
            "workload_id": manifest.get("workload", workload_graph.get("graph_id")),
            "graph_id": workload_graph.get("graph_id"),
            "required_qe_scf_phases": simulation_result.get("required_qe_scf_phases", []),
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
        "trusted_ranking": trusted_ranking,
        "predicted_only_candidates": predicted_only_candidates,
        "blocked_or_prototype": blocked_or_prototype,
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
    lines = [
        "# Generic DSE Final Report",
        "",
        "## Executive Summary",
        f"- Run id: `{run.get('run_id')}`",
        f"- Backend: `{run.get('backend')}`",
        f"- Trusted for final ranking: `{run.get('trusted_for_final_ranking')}`",
        f"- Recommendation status: `{selected.get('selection_status')}`",
        f"- Trusted winner: `{selected.get('trusted_winner')}`",
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

    lines.extend(["", "## Predicted-only / Blocked", ""])
    blocked = report.get("blocked_or_prototype", []) or []
    predicted = report.get("predicted_only_candidates", []) or []
    if not blocked and not predicted:
        lines.append("- None recorded.")
    for item in predicted:
        claim = item.get("claim", {})
        lines.append(f"- Predicted-only: `{claim.get('claim_id', claim.get('claim_type'))}`")
    for item in blocked:
        claim = item.get("claim", {})
        lines.append(f"- Blocked/prototype: `{claim.get('claim_id', claim.get('claim_type'))}` — {claim.get('statement', '')}")

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
    """Generate final_report.json/md plus evidence requirement and claim validation artifacts."""
    run_dir = Path(run_dir)
    report, claim_validation, requirements = generate_final_report(
        run_dir,
        claims=claims,
        artifact_paths=artifact_paths,
    )
    _write_json(run_dir / "evidence_requirements.json", requirements)
    _write_json(run_dir / "claim_validation.json", claim_validation)
    _write_json(run_dir / "final_report.json", report)
    _write_text(run_dir / "final_report.md", render_markdown_report(report))
    return {
        "evidence_requirements": "evidence_requirements.json",
        "claim_validation": "claim_validation.json",
        "final_report_json": "final_report.json",
        "final_report_markdown": "final_report.md",
    }
