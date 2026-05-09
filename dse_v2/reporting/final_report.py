#!/usr/bin/env python3
"""Final report generation and claim validation for generic DSE evidence runs.

The report layer is intentionally conservative: it can summarize a trusted
SystemC/gem5+SystemC evidence run, but it does not convert a single pilot into
an architecture winner or Pareto conclusion. Comparative claims must be created
by a higher-level search run that has comparable evidence for every trusted
candidate.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPORT_SCHEMA_VERSION = "dse.final_report.v1"
CLAIM_VALIDATION_SCHEMA_VERSION = "dse.claim_validation.v1"

TRUSTED_BACKENDS = {"systemc", "gem5_systemc"}
UNTRUSTED_FIDELITIES = {"l1", "l2", "analytical", "tlm", "surrogate", "predicted"}
WINNER_CLAIM_TYPES = {"best_architecture", "selected_recommendation", "pareto_frontier"}

REPORT_ARTIFACTS = [
    "final_report.json",
    "final_report.md",
    "claim_validation.json",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path, default: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    return loaded if isinstance(loaded, dict) else dict(default or {})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read_phase_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value == "" or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _phase_bottleneck(phase_rows: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    available: List[Tuple[float, Mapping[str, Any]]] = []
    for row in phase_rows:
        if row.get("status") != "available":
            continue
        latency = _float_or_none(row.get("latency_ms"))
        if latency is not None:
            available.append((latency, row))
    if not available:
        return None
    latency, row = max(available, key=lambda item: item[0])
    return {
        "phase": row.get("phase"),
        "device": row.get("device"),
        "latency_ms": latency,
        "evidence_ids": ["phase_breakdown.csv", "simulation_result.json"],
    }


def _artifact_index(run_dir: Path, required_files: Iterable[str]) -> List[Dict[str, Any]]:
    manifest = _load_json(run_dir / "artifact_manifest.json")
    indexed: Dict[str, Dict[str, Any]] = {}
    for entry in manifest.get("artifacts", []) or []:
        if isinstance(entry, dict) and entry.get("path"):
            indexed[str(entry["path"])] = dict(entry)

    paths = sorted(set(required_files) | set(indexed))
    entries: List[Dict[str, Any]] = []
    for rel in paths:
        entry = dict(indexed.get(rel, {}))
        path = run_dir / rel
        entry.setdefault("path", rel)
        entry.setdefault("required", rel in set(required_files))
        entry["exists"] = path.exists()
        if not path.exists():
            entry.setdefault("unavailable_reason", "not generated for this run")
        else:
            entry.pop("unavailable_reason", None)
            if path.is_file():
                entry.setdefault("size_bytes", path.stat().st_size)
        entries.append(entry)
    return entries


def _trusted_candidate_from_run(
    *,
    run_id: str,
    backend: str,
    verdict: Mapping[str, Any],
    architecture: Mapping[str, Any],
    mapping: Mapping[str, Any],
    simulation_result: Mapping[str, Any],
    bottleneck: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not verdict.get("trusted_for_final_ranking", False):
        return None
    metrics = simulation_result.get("metrics", {}) if isinstance(simulation_result.get("metrics"), dict) else {}
    return {
        "rank": 1,
        "run_id": run_id,
        "backend": backend,
        "architecture_id": architecture.get("architecture_id"),
        "architecture_family": architecture.get("architecture_family"),
        "mapping_id": mapping.get("mapping_id"),
        "trusted_scope": "single-run feasibility evidence; not a comparative architecture-winner claim",
        "metrics": {
            "latency_ms": metrics.get("latency_ms"),
            "throughput_gops": metrics.get("throughput_gops"),
            "power_w": metrics.get("power_w"),
            "energy_j": metrics.get("energy_j"),
        },
        "bottleneck_phase": bottleneck,
        "evidence_ids": ["verdict.json", "simulation_result.json", "phase_breakdown.csv"],
    }


def _build_claims(
    *,
    run_id: str,
    backend: str,
    verdict: Mapping[str, Any],
    bottleneck: Optional[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    trusted = bool(verdict.get("trusted_for_final_ranking", False))
    if trusted:
        claims.append({
            "claim_id": f"{run_id}:feasibility",
            "claim_type": "feasibility",
            "text": "This design point has standalone SystemC timing-level evidence for the required QE SCF shell phases.",
            "backend": backend,
            "source_fidelity": "L3" if backend == "systemc" else "L4",
            "trusted": True,
            "predicted_only": False,
            "blocked": False,
            "evidence_ids": ["verdict.json", "simulation_result.json", "phase_breakdown.csv", "resource_summary.csv"],
            "limitations": [
                "Feasibility applies to this design point only; it is not a final best-architecture claim.",
            ],
        })
        if bottleneck:
            claims.append({
                "claim_id": f"{run_id}:dominant_phase",
                "claim_type": "bottleneck_diagnosis",
                "text": f"The longest emitted phase in this run is {bottleneck.get('phase')}.",
                "backend": backend,
                "source_fidelity": "L3" if backend == "systemc" else "L4",
                "trusted": True,
                "predicted_only": False,
                "blocked": False,
                "evidence_ids": list(bottleneck.get("evidence_ids", [])),
                "limitations": [
                    "This is a per-run timing observation, not a cross-architecture bottleneck conclusion.",
                ],
            })

    for blocker in verdict.get("gem5_systemc_blockers", []) or []:
        if not isinstance(blocker, dict):
            continue
        claims.append({
            "claim_id": f"{run_id}:{blocker.get('id', 'gem5_systemc_blocked')}",
            "claim_type": "unsupported_stub_limitation",
            "text": blocker.get("detail", "gem5+SystemC path is blocked for this run."),
            "backend": "gem5_systemc",
            "source_fidelity": "L4",
            "trusted": False,
            "predicted_only": False,
            "blocked": True,
            "evidence_ids": ["verdict.json", "gem5_systemc_blockers.json"],
            "limitations": ["Blocked claims are documented for audit and cannot enter trusted ranking."],
        })
    return claims


def _claim_backend(claim: Mapping[str, Any]) -> str:
    return str(claim.get("backend", claim.get("source_backend", ""))).lower()


def _claim_fidelity(claim: Mapping[str, Any]) -> str:
    return str(claim.get("source_fidelity", claim.get("fidelity", ""))).lower()


def validate_report_claims(report: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
    """Validate claim/evidence consistency for a final report payload."""
    errors: List[str] = []
    warnings: List[str] = []
    claims = report.get("claims", []) or []
    if not isinstance(claims, list):
        errors.append("claims must be a list")
        claims = []

    trusted_claim_count = 0
    for idx, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claim[{idx}] is not an object")
            continue
        claim_id = str(claim.get("claim_id", f"claim[{idx}]"))
        trusted = bool(claim.get("trusted", False))
        predicted_only = bool(claim.get("predicted_only", False))
        blocked = bool(claim.get("blocked", False))
        claim_type = str(claim.get("claim_type", ""))
        evidence_ids = claim.get("evidence_ids", []) or []

        if trusted:
            trusted_claim_count += 1
            if predicted_only:
                errors.append(f"{claim_id}: trusted claim cannot be predicted_only")
            if blocked:
                errors.append(f"{claim_id}: trusted claim cannot be blocked")
            if _claim_backend(claim) not in TRUSTED_BACKENDS:
                errors.append(f"{claim_id}: trusted claim backend must be SystemC or gem5+SystemC")
            if _claim_fidelity(claim) in UNTRUSTED_FIDELITIES:
                errors.append(f"{claim_id}: trusted claim cannot use low-fidelity source")
            if not evidence_ids:
                errors.append(f"{claim_id}: trusted claim must list evidence_ids")

        if predicted_only and claim_type in WINNER_CLAIM_TYPES:
            errors.append(f"{claim_id}: predicted-only candidate cannot be a winner/Pareto claim")

        if not isinstance(evidence_ids, list):
            errors.append(f"{claim_id}: evidence_ids must be a list")
            continue
        for evidence_id in evidence_ids:
            rel = Path(str(evidence_id))
            if rel.is_absolute() or ".." in rel.parts:
                errors.append(f"{claim_id}: evidence id must be a run-local relative path: {evidence_id}")
                continue
            if not (run_dir / rel).exists():
                errors.append(f"{claim_id}: evidence id does not resolve to a file: {evidence_id}")

    selected = report.get("selected_recommendation", {}) or {}
    if isinstance(selected, dict) and selected.get("status") == "selected":
        evidence_ids = selected.get("evidence_ids", []) or []
        if selected.get("predicted_only"):
            errors.append("selected_recommendation: predicted-only candidate cannot be selected")
        if selected.get("backend") not in TRUSTED_BACKENDS:
            errors.append("selected_recommendation: backend must be SystemC or gem5+SystemC")
        if not evidence_ids:
            errors.append("selected_recommendation: selected design requires evidence_ids")
        for evidence_id in evidence_ids:
            if not (run_dir / str(evidence_id)).exists():
                errors.append(f"selected_recommendation: evidence id does not resolve: {evidence_id}")
    else:
        warnings.append("No comparative selected recommendation emitted; report is single-run evidence only.")

    return {
        "schema_version": CLAIM_VALIDATION_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "passed": not errors,
        "trusted_claim_count": trusted_claim_count,
        "errors": errors,
        "warnings": warnings,
    }


def build_final_report(run_dir: Path) -> Dict[str, Any]:
    """Build a final report payload from an existing evidence run directory."""
    run_dir = Path(run_dir)
    manifest = _load_json(run_dir / "manifest.json")
    verdict = _load_json(run_dir / "verdict.json")
    design_point = _load_json(run_dir / "design_point.json")
    architecture = _load_json(run_dir / "architecture.json")
    mapping = _load_json(run_dir / "mapping.json")
    workload_graph = _load_json(run_dir / "workload_graph.json")
    simulation_result = _load_json(run_dir / "simulation_result.json")
    phase_rows = _read_phase_rows(run_dir / "phase_breakdown.csv")

    run_id = str(verdict.get("run_id") or manifest.get("run_id") or design_point.get("design_point_id") or run_dir.name)
    backend = str(verdict.get("backend") or manifest.get("backend") or simulation_result.get("backend") or "unknown")
    bottleneck = _phase_bottleneck(phase_rows)
    trusted_candidate = _trusted_candidate_from_run(
        run_id=run_id,
        backend=backend,
        verdict=verdict,
        architecture=architecture,
        mapping=mapping,
        simulation_result=simulation_result,
        bottleneck=bottleneck,
    )

    required_files = manifest.get("required_evidence_files") or [
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
    ]
    required_files = list(dict.fromkeys([str(path) for path in required_files] + REPORT_ARTIFACTS))

    report: Dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "run_metadata": {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "backend": backend,
            "evidence_mode": verdict.get("evidence_mode") or manifest.get("evidence_mode"),
            "trusted_for_final_ranking": bool(verdict.get("trusted_for_final_ranking", False)),
            "cli_command": manifest.get("cli_command", []),
            "simulator_command": manifest.get("simulator_command", []),
        },
        "workload": {
            "workload_id": manifest.get("workload", "unknown"),
            "graph_id": workload_graph.get("graph_id"),
            "node_count": len(workload_graph.get("nodes", {}) or {}),
            "edge_count": len(workload_graph.get("edges", []) or []),
            "required_qe_scf_phases": verdict.get("required_qe_scf_phases", []),
            "missing_required_phases": verdict.get("missing_required_phases", []),
        },
        "architecture_catalog_scope": {
            "architecture_id": architecture.get("architecture_id"),
            "architecture_family": architecture.get("architecture_family"),
            "architecture_status": architecture.get("status"),
            "trusted_final_eligible": architecture.get("trusted_final_eligible", False),
            "scope_note": architecture.get("architecture_scope"),
        },
        "search_configuration": {
            "mapping_id": mapping.get("mapping_id"),
            "mapping_policy": mapping.get("mapping_policy"),
            "search_status": mapping.get("search_status"),
            "convergence_status": "not_applicable_single_seeded_candidate",
            "budget_status": "not_applicable_single_seeded_candidate",
        },
        "trusted_ranking": [trusted_candidate] if trusted_candidate else [],
        "predicted_only_candidates": [
            {
                "candidate_id": f"{run_id}:mapping_search_placeholder",
                "status": "predicted_only_not_selected",
                "reason": "Architecture catalog expansion and mapping feedback search are not completed by this single evidence run.",
                "evidence_ids": [],
            }
        ],
        "selected_recommendation": {
            "status": "not_selected",
            "reason": "This report summarizes one evidence run; it does not compare multiple trusted candidates, so no best architecture or Pareto winner is claimed.",
            "predicted_only": False,
            "evidence_ids": [],
        },
        "pareto_alternatives": [],
        "claims": _build_claims(run_id=run_id, backend=backend, verdict=verdict, bottleneck=bottleneck),
        "evidence_index": _artifact_index(run_dir, required_files),
        "limitations": list(verdict.get("evidence_gaps", []) or []) + [
            "Single-run reports cannot establish architecture-family superiority, Pareto optimality, or final DSE winner status.",
            "Numerical QE correctness and board/ASIC implementation claims are outside this timing-level evidence report.",
        ],
        "replay_instructions": {
            "python_replay_command": manifest.get("replay_metadata", {}).get("python_replay_command", manifest.get("cli_command", [])),
            "simulator_replay_command": manifest.get("replay_metadata", {}).get("simulator_replay_command", manifest.get("simulator_command", [])),
            "simulation_request": "simulation_request.json",
            "simulation_result": "simulation_result.json",
        },
    }
    report["validation"] = validate_report_claims(report, run_dir)
    return report


def render_markdown_report(report: Mapping[str, Any]) -> str:
    metadata = report.get("run_metadata", {}) or {}
    workload = report.get("workload", {}) or {}
    architecture = report.get("architecture_catalog_scope", {}) or {}
    search = report.get("search_configuration", {}) or {}
    selected = report.get("selected_recommendation", {}) or {}
    validation = report.get("validation", {}) or {}

    lines = [
        f"# Generic DSE Final Report — {metadata.get('run_id', 'unknown')}",
        "",
        "## Executive Summary",
        f"- Backend: `{metadata.get('backend', 'unknown')}`",
        f"- Trusted for final ranking: `{metadata.get('trusted_for_final_ranking', False)}`",
        f"- Workload graph: `{workload.get('graph_id', 'unknown')}` with {workload.get('node_count', 0)} nodes and {workload.get('edge_count', 0)} edges",
        f"- Missing required QE SCF phases: {workload.get('missing_required_phases', [])}",
        f"- Validation passed: `{validation.get('passed', False)}`",
        "",
        "## Architecture and Mapping Scope",
        f"- Architecture: `{architecture.get('architecture_id', 'unknown')}` ({architecture.get('architecture_family', 'unknown')})",
        f"- Architecture status: `{architecture.get('architecture_status', 'unknown')}`",
        f"- Mapping: `{search.get('mapping_id', 'unknown')}` via `{search.get('mapping_policy', 'unknown')}`",
        f"- Search/convergence: `{search.get('convergence_status', 'unknown')}`",
        "",
        "## Trusted Ranking",
    ]
    ranking = report.get("trusted_ranking", []) or []
    if ranking:
        for item in ranking:
            metrics = item.get("metrics", {}) or {}
            lines.extend([
                f"- Rank {item.get('rank')}: `{item.get('architecture_id')}` / `{item.get('mapping_id')}`",
                f"  - Scope: {item.get('trusted_scope')}",
                f"  - Latency ms: `{metrics.get('latency_ms')}`; power W: `{metrics.get('power_w')}`; energy J: `{metrics.get('energy_j')}`",
                f"  - Evidence: {', '.join(item.get('evidence_ids', []))}",
            ])
    else:
        lines.append("- No trusted ranking entries were emitted.")

    lines.extend([
        "",
        "## Selected Recommendation",
        f"- Status: `{selected.get('status', 'unknown')}`",
        f"- Reason: {selected.get('reason', '')}",
        "",
        "## Claims",
    ])
    for claim in report.get("claims", []) or []:
        lines.extend([
            f"- `{claim.get('claim_id')}` ({claim.get('claim_type')})",
            f"  - Trusted: `{claim.get('trusted', False)}`; blocked: `{claim.get('blocked', False)}`; predicted-only: `{claim.get('predicted_only', False)}`",
            f"  - Evidence: {', '.join(claim.get('evidence_ids', []))}",
            f"  - Text: {claim.get('text', '')}",
        ])

    lines.extend([
        "",
        "## Limitations",
    ])
    for limitation in report.get("limitations", []) or []:
        lines.append(f"- {limitation}")

    lines.extend([
        "",
        "## Replay Instructions",
        "```json",
        json.dumps(report.get("replay_instructions", {}), indent=2, sort_keys=True),
        "```",
        "",
    ])
    return "\n".join(lines)


def generate_final_report_artifacts(run_dir: Path) -> Dict[str, Any]:
    """Write final_report.json, final_report.md, and claim_validation.json."""
    run_dir = Path(run_dir)
    report = build_final_report(run_dir)
    validation = report["validation"]
    _write_json(run_dir / "final_report.json", report)
    _write_json(run_dir / "claim_validation.json", validation)
    _write_text(run_dir / "final_report.md", render_markdown_report(report))
    return {
        "report_path": str(run_dir / "final_report.json"),
        "markdown_path": str(run_dir / "final_report.md"),
        "validation_path": str(run_dir / "claim_validation.json"),
        "validation_passed": validation.get("passed", False),
        "trusted_claim_count": validation.get("trusted_claim_count", 0),
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a final report for a generic DSE evidence run directory.")
    parser.add_argument("run_dir", type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    result = generate_final_report_artifacts(args.run_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
