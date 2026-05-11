#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import shlex
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_DIR = ROOT / "docs/benchmarks"
TOOLS_BENCHMARKS_DIR = Path(__file__).resolve().parent
PHASE_CONFIG_PATH = BENCHMARKS_DIR / "qe_next_stage_dse_simulator_phase_config_v0.json"
RUNNER_PATH = TOOLS_BENCHMARKS_DIR / "run_systemc_architecture_family_dse_sweep.py"
COMPONENT_REGISTRY_BUILDER_PATH = TOOLS_BENCHMARKS_DIR / "build_qe_ic_component_registry.py"
GPU_BASELINE_READINESS_PATH = TOOLS_BENCHMARKS_DIR / "assess_qe_cpu_gpu_baseline_readiness.py"
PHASE1_EVIDENCE_CLOSURE_PATH = TOOLS_BENCHMARKS_DIR / "assess_qe_phase1_evidence_closure.py"
PHASE1_EVIDENCE_CLOSURE_RENDERER_PATH = TOOLS_BENCHMARKS_DIR / "render_qe_phase1_evidence_closure_md.py"
ADJUDICATOR_RUNNER_PATH = TOOLS_BENCHMARKS_DIR / "run_qe_system_design_adjudicator.py"
BLOCKING_STATUSES = {
    "model_error",
    "candidate_missing",
    "baseline_missing",
    "baseline_normalization_error",
    "compare_error",
}


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("qe_dse_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import runner module from {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_component_registry_builder() -> Any:
    spec = importlib.util.spec_from_file_location(
        "qe_ic_component_registry_builder",
        COMPONENT_REGISTRY_BUILDER_PATH,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(
            f"cannot import component registry builder from {COMPONENT_REGISTRY_BUILDER_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_gpu_baseline_readiness_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "qe_gpu_baseline_readiness",
        GPU_BASELINE_READINESS_PATH,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(
            f"cannot import gpu baseline readiness module from {GPU_BASELINE_READINESS_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_phase1_evidence_closure_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "qe_phase1_evidence_closure",
        PHASE1_EVIDENCE_CLOSURE_PATH,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(
            f"cannot import phase1 evidence closure module from {PHASE1_EVIDENCE_CLOSURE_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_phase1_evidence_closure_renderer_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "qe_phase1_evidence_closure_renderer",
        PHASE1_EVIDENCE_CLOSURE_RENDERER_PATH,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(
            "cannot import phase1 evidence closure renderer module from "
            f"{PHASE1_EVIDENCE_CLOSURE_RENDERER_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_adjudicator_runner_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "qe_system_design_adjudicator",
        ADJUDICATOR_RUNNER_PATH,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(
            f"cannot import adjudicator runner module from {ADJUDICATOR_RUNNER_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_reference_gpu_case_id(reference_dir: Path) -> str:
    for path in sorted(reference_dir.glob("qe_*_cuda_gpu_kern_sum.csv")):
        name = path.name.removesuffix("_cuda_gpu_kern_sum.csv")
        if name:
            return name
    return "qe_reference_gpu"


def parse_reference_gpu_total_wall_s(reference_dir: Path) -> float | None:
    timing_path = reference_dir / "qe_timing.json"
    if not timing_path.exists():
        return None
    payload = json.loads(timing_path.read_text(encoding="utf-8"))
    total = payload.get("total_wall_s")
    if isinstance(total, (int, float)):
        return float(total)
    for entry in payload.get("entries", []):
        if entry.get("name") == "electrons" and isinstance(entry.get("wall_s"), (int, float)):
            return float(entry["wall_s"])
    wall_values = [
        float(entry["wall_s"])
        for entry in payload.get("entries", [])
        if isinstance(entry.get("wall_s"), (int, float))
    ]
    return max(wall_values) if wall_values else None


def parse_reference_gpu_measured_ops(reference_dir: Path) -> list[str]:
    timing_path = reference_dir / "qe_timing.json"
    if not timing_path.exists():
        return []
    payload = json.loads(timing_path.read_text(encoding="utf-8"))
    ops = [
        str(entry["name"])
        for entry in payload.get("entries", [])
        if isinstance(entry.get("gpu_s"), (int, float)) and float(entry["gpu_s"]) > 0.0
    ]
    return sorted(dict.fromkeys(ops))


def parse_reference_gpu_device_name(reference_dir: Path) -> str | None:
    app_out = reference_dir / "qe_iter2_app.out"
    if not app_out.exists():
        return None
    pattern = re.compile(r"Device name:\s*(.+)")
    for line in app_out.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.search(line)
        if match:
            return match.group(1).strip()
    return None


def parse_reference_gpu_top_kernels(reference_dir: Path, limit: int = 3) -> list[str]:
    csv_path = reference_dir / "qe_si54_profile_cuda_gpu_kern_sum.csv"
    if not csv_path.exists():
        return []
    kernels: list[str] = []
    with csv_path.open(encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = (row.get("Name") or "").strip()
            pct = (row.get("Time (%)") or "").strip()
            if not name:
                continue
            kernels.append(f"{name} ({pct}%)" if pct else name)
            if len(kernels) >= limit:
                break
    return kernels


def build_reference_gpu_annex_summary(reference_dir: Path) -> dict[str, Any]:
    case_id = parse_reference_gpu_case_id(reference_dir)
    total_wall_s = parse_reference_gpu_total_wall_s(reference_dir)
    measured_ops = parse_reference_gpu_measured_ops(reference_dir)
    device_name = parse_reference_gpu_device_name(reference_dir)
    top_kernels = parse_reference_gpu_top_kernels(reference_dir)
    row = {
        "baseline_dir": str(reference_dir),
        "case_id": case_id,
        "gpu_mode": "practical_reference",
        "status": "reference_only",
        "baseline_state": "reference_only",
        "decisive_for_case": False,
        "reason": "reference_trace_only_without_manifest",
        "time_to_convergence_s": total_wall_s,
        "gpu_measured_ops": measured_ops,
        "device_name": device_name,
        "top_kernels": top_kernels,
    }
    return {
        "schema_version": "qe_gpu_annex_summary_v0",
        "status": "reference_only",
        "reason": "reference_gpu_directory_only",
        "source_surface": "gpu_reference_directory",
        "baseline_dir_count": 1,
        "counts": {
            "thesis_eligible": 0,
            "reference_only": 1,
            "deferred": 0,
            "decisive": 0,
        },
        "gpu_mode_set_measured": ["practical_reference"],
        "gpu_decisive_modes": [],
        "decisive_case_ids": [],
        "row_ledger": [row],
        "reference_artifact_paths": {
            "qe_timing_json": str(reference_dir / "qe_timing.json"),
            "app_out": str(reference_dir / "qe_iter2_app.out"),
            "cuda_gpu_kernel_summary_csv": str(reference_dir / "qe_si54_profile_cuda_gpu_kern_sum.csv"),
        },
        "annex_note": (
            "GPU annex is currently reference_only because it is built from the reference/qe "
            "trace/profile directory without a frozen cpu_gpu_baseline_manifest or readiness-qualified row set."
        ),
    }


def write_json_text(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_adjudicator_reference_payload(
    *,
    output_dir: Path,
    dse_bundle_path: Path,
    gpu_annex_path: Path | None,
    phase1_closure_path: Path | None,
    board_closure_path: Path | None,
    stage_main_evidence_path: Path | None,
) -> dict[str, Any]:
    adjudicator = load_adjudicator_runner_module()
    reference_path = output_dir / "qe_system_design_adjudicator_reference.json"
    try:
        memo, memo_json_path, memo_md_path = adjudicator.write_decision_memo_artifacts(
            dse_bundle_path=dse_bundle_path,
            output_dir=output_dir / "adjudicator",
            gpu_annex_path=gpu_annex_path,
            phase1_closure_path=phase1_closure_path,
            board_closure_path=board_closure_path,
            stage_main_evidence_path=stage_main_evidence_path,
        )
    except Exception as exc:
        return {
            "artifact_kind": "qe_system_design_adjudicator_reference_v0",
            "authority_scope": "adjudicator_only",
            "reference_status": "error",
            "reference_path": str(reference_path),
            "decision_memo_json": None,
            "decision_memo_md": None,
            "dse_bundle_json": str(dse_bundle_path),
            "gpu_annex_json": None if gpu_annex_path is None else str(gpu_annex_path),
            "phase1_evidence_closure_json": None if phase1_closure_path is None else str(phase1_closure_path),
            "board_closure_json": None if board_closure_path is None else str(board_closure_path),
            "stage_main_evidence_json": None if stage_main_evidence_path is None else str(stage_main_evidence_path),
            "error": str(exc),
            "notes": [
                "Phase summary surfaces remain supporting evidence only. Final decision authority is reserved for the adjudicator memo when present.",
            ],
        }
    return {
        "artifact_kind": "qe_system_design_adjudicator_reference_v0",
        "authority_scope": "adjudicator_only",
        "reference_status": "present",
        "reference_path": str(reference_path),
        "decision_memo_json": str(memo_json_path),
        "decision_memo_md": str(memo_md_path),
        "dse_bundle_json": str(dse_bundle_path),
        "gpu_annex_json": None if gpu_annex_path is None else str(gpu_annex_path),
        "phase1_evidence_closure_json": None if phase1_closure_path is None else str(phase1_closure_path),
        "board_closure_json": None if board_closure_path is None else str(board_closure_path),
        "stage_main_evidence_json": None if stage_main_evidence_path is None else str(stage_main_evidence_path),
        "decision_stage": memo["memo_metadata"]["stage"],
        "public_family_decision_status": memo["decision"]["public_family_decision_status"],
        "recommended_family": memo["decision"]["recommended_family"],
        "release_posture": memo["decision"]["release_posture"],
        "notes": [
            "This reference is evidence-oriented only. The adjudicator memo remains the single top-level decision authority.",
        ],
    }


def materialize_reference_gpu_baseline_bundle(
    reference_dir: Path, output_root: Path
) -> Path:
    case_id = parse_reference_gpu_case_id(reference_dir)
    gpu_mode = "practical"
    run_tag = "reference"
    bundle_dir = output_root / f"{case_id}__cpu_gpu__{gpu_mode}_{run_tag}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    base = f"qe_{case_id}__cpu_gpu__{gpu_mode}__{run_tag}"

    stdout_rel = f"{base}.stdout.txt"
    stderr_rel = f"{base}.stderr.txt"
    timing_rel = f"{base}.timing.json"
    correctness_rel = f"{base}.correctness.json"
    convergence_rel = f"{base}.convergence.json"
    power_rel = f"{base}.power.json"
    summary_rel = f"{base}.summary.md"

    source_stdout = reference_dir / "qe_iter2_app.out"
    (bundle_dir / stdout_rel).write_text(
        source_stdout.read_text(encoding="utf-8", errors="ignore")
        if source_stdout.exists()
        else "reference GPU stdout unavailable\n",
        encoding="utf-8",
    )
    (bundle_dir / stderr_rel).write_text("", encoding="utf-8")
    write_json_text(
        bundle_dir / timing_rel,
        {
            "time_to_convergence_s": parse_reference_gpu_total_wall_s(reference_dir),
            "gpu_measured_ops": parse_reference_gpu_measured_ops(reference_dir),
            "source": "reference_gpu_directory",
        },
    )
    write_json_text(
        bundle_dir / correctness_rel,
        {
            "gold_pass": False,
            "convergence_comparable_pass": False,
            "status": "reference_only",
            "note": "reference trace does not close QE correctness gates",
        },
    )
    write_json_text(
        bundle_dir / convergence_rel,
        {
            "convergence_comparable_pass": False,
            "status": "reference_only",
            "note": "reference trace does not provide readiness-qualified convergence closure",
        },
    )
    write_json_text(
        bundle_dir / power_rel,
        {
            "avg_whole_node_power_w": None,
            "energy_to_solution_j": None,
            "status": "reference_only",
            "note": "reference directory does not provide fairness-qualified whole-node power closure",
        },
    )
    (bundle_dir / summary_rel).write_text(
        "\n".join(
            [
                "# QE CPU+GPU Reference Baseline Summary",
                "",
                f"- source_reference_dir: `{reference_dir}`",
                f"- case_id: `{case_id}`",
                f"- gpu_mode: `{gpu_mode}`",
                "- baseline_state: `reference_only`",
                "- note: `materialized from reference trace/profile data; not a readiness-qualified thesis baseline`",
                "",
            ]
        ),
        encoding="utf-8",
    )

    write_json_text(
        bundle_dir / "cpu_gpu_baseline_manifest.json",
        {
            "schema_version": "qe_cpu_gpu_baseline_manifest_template_v0",
            "baseline_class": "CPU+GPU",
            "case_id": case_id,
            "gpu_mode": gpu_mode,
            "run_tag": run_tag,
            "host_id": "reference-host",
            "gpu_id": parse_reference_gpu_device_name(reference_dir) or "reference-gpu",
            "qe_rev": "reference-trace",
            "correctness_contract_id": "qe_gold_correctness_contract_v0",
            "workload_group_id": "qe_fpga_phase1_workload_group_v0",
            "fairness_policy_id": "qe_cpu_gpu_fpga_fairness_and_power_contract_v0",
            "algorithm_rewrite_manifest_id": "qe_algorithm_rewrite_manifest_v0",
            "gpu_mode_attempts": [gpu_mode],
            "mode_attempt_exemption_note": "strict_fp64 baseline not available in reference trace bundle",
            "shared_rewrite_closed": False,
            "host_platform_comparable": False,
            "rewrite_mode": "reference_trace_only",
            "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
            "accounting_boundary_id": "scf_shell_convergence_scope_v1",
            "power_boundary_id": "whole_node_steady_state_single_cpu_single_accelerator_v0",
            "warmup_policy": "unknown_from_reference",
            "host_normalization_note": "derived from reference trace; host comparability not closed",
            "command": "reference_trace_only",
            "env": {"CUDA_VISIBLE_DEVICES": "reference"},
            "artifact_paths": {
                "stdout": stdout_rel,
                "stderr": stderr_rel,
                "timing": timing_rel,
                "correctness": correctness_rel,
                "convergence": convergence_rel,
                "power": power_rel,
                "summary": summary_rel,
            },
            "baseline_state": "reference_only",
            "notes": [
                "materialized from reference/qe trace/profile data",
                "not a readiness-qualified CPU+GPU thesis baseline",
            ],
        },
    )
    write_json_text(
        bundle_dir / "algorithm_rewrite_manifest.json",
        {
            "schema_version": "qe_algorithm_rewrite_manifest_template_v0",
            "manifest_id": "qe_algorithm_rewrite_manifest_v0",
            "fairness_policy_id": "qe_cpu_gpu_fpga_fairness_and_power_contract_v0",
            "workload_group_id": "qe_fpga_phase1_workload_group_v0",
            "entries": [
                {
                    "rewrite_id": "RW-QE-REF-001",
                    "title": "reference trace import placeholder",
                    "rewrite_class": "shared_semantic",
                    "scope": ["reference_trace_import"],
                    "description": "Imported from an existing GPU reference trace/profile directory.",
                    "motivation": "Allow the GPU annex to consume a manifest-backed reference row.",
                    "changes_algorithm_semantics": "qualified",
                    "correctness_contract_impact": "bounded",
                    "tolerance_contract_note": "Reference trace does not close correctness/tolerance gates.",
                    "gpu_applicable": "yes",
                    "gpu_applicability_basis": "The reference directory was collected from a GPU-enabled QE run.",
                    "gpu_enabled_in_baseline": "deferred",
                    "gpu_enablement_note": "Manifest-backed reference only; readiness-qualified closure not established.",
                    "fpga_required_arch_feature": "none",
                    "expected_benefit_axis": "time",
                    "expected_benefit_note": "Reference trace only; no decisive benefit claim.",
                    "ablation_required": "yes",
                    "admission_risk": "medium",
                    "evidence_note": "reference_trace_only",
                    "review_status": "draft",
                    "owner_note": "generated automatically from reference GPU directory",
                    "affected_workload_ids": [case_id],
                    "affected_family_ids": ["F1", "F2", "F3"],
                    "simulator_hook_ids": ["gpu_reference_annex"],
                    "board_observability_rows": ["OBS-01"],
                    "fallback_behavior": "Remain reference_only until correctness/fairness closure exists.",
                    "shared_rewrite_dependency_ids": [],
                    "claim_dependency_ids": ["CL1"],
                }
            ],
        },
    )
    return bundle_dir


def summarize_manifest_backed_gpu_baseline_dirs(gpu_baseline_dirs: list[Path]) -> dict[str, Any]:
    readiness = load_gpu_baseline_readiness_module()
    validator = readiness.load_validator_module()
    runner = validator.load_runner_module()
    rows = [readiness.classify_row(path, validator, runner) for path in gpu_baseline_dirs]
    rows = readiness.choose_decisive(rows)
    summary = readiness.build_summary(rows)
    decisive_rows = [row for row in rows if row.get("decisive_for_case") is True]
    measured_modes = sorted(
        {
            str(row["gpu_mode"])
            for row in rows
            if row.get("gpu_mode") not in (None, "")
        }
    )
    decisive_modes = sorted(
        {
            str(row["gpu_mode"])
            for row in decisive_rows
            if row.get("gpu_mode") not in (None, "")
        }
    )
    status = (
        "thesis_eligible"
        if summary["counts"]["decisive"] > 0
        else (
            "reference_only"
            if summary["counts"]["reference_only"] > 0
            or summary["counts"]["thesis_eligible"] > 0
            else "deferred"
        )
    )
    return {
        "schema_version": "qe_gpu_annex_summary_v0",
        "status": status,
        "reason": "derived_from_gpu_baseline_readiness_rows",
        "source_surface": "gpu_baseline_readiness",
        "baseline_dir_count": len(gpu_baseline_dirs),
        "counts": summary["counts"],
        "gpu_mode_set_measured": measured_modes,
        "gpu_decisive_modes": decisive_modes,
        "decisive_case_ids": sorted(
            {
                str(row["case_id"])
                for row in decisive_rows
                if row.get("case_id") not in (None, "")
            }
        ),
        "row_ledger": rows,
        "annex_note": (
            "GPU annex status is derived from existing baseline manifests and readiness "
            "assessor outputs; only thesis_eligible rows with decisive_for_case=true may "
            "enter final GPU aggregation."
        ),
    }


def load_gpu_row_manifest(path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    manifest_path = Path(path)
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def classify_gpu_blocker(reason: str | None) -> str:
    if reason is None:
        return "unknown"
    if reason.startswith("missing_artifacts:"):
        return "artifact_missing"
    mapping = {
        "missing_cpu_gpu_baseline_manifest": "manifest_missing",
        "missing_algorithm_rewrite_manifest": "rewrite_manifest_missing",
        "correctness_or_convergence_not_closed": "correctness_or_convergence",
        "missing_decisive_metrics": "metrics_missing",
        "shared_rewrite_not_closed": "shared_rewrite",
        "rewrite_manifest_not_closed": "rewrite_review",
        "host_platform_not_comparable": "host_platform",
        "reference_trace_only_without_manifest": "reference_trace_only",
        "reference_gpu_directory_only": "reference_trace_only",
        "reference_gpu_directory_materialized": "reference_trace_only",
        "derived_from_gpu_baseline_readiness_rows": "mixed",
        "no_gpu_baseline_dirs_configured": "not_configured",
    }
    return mapping.get(reason, "other")


def enrich_gpu_annex_summary(base_summary: dict[str, Any]) -> dict[str, Any]:
    summary = dict(base_summary)
    rows = [dict(row) for row in summary.get("row_ledger", [])]
    workload_group_ids: set[str] = set()
    fairness_policy_ids: set[str] = set()
    power_boundary_ids: set[str] = set()
    rewrite_manifest_ids: set[str] = set()
    correctness_contract_ids: set[str] = set()
    tolerance_schema_ids: set[str] = set()
    for row in rows:
        row["blocker_class"] = classify_gpu_blocker(row.get("reason"))
        manifest = load_gpu_row_manifest(row.get("manifest_path"))
        if manifest is None:
            continue
        contract_ids = {
            "workload_group_id": manifest.get("workload_group_id"),
            "fairness_policy_id": manifest.get("fairness_policy_id"),
            "power_boundary_id": manifest.get("power_boundary_id"),
            "algorithm_rewrite_manifest_id": manifest.get("algorithm_rewrite_manifest_id"),
            "correctness_contract_id": manifest.get("correctness_contract_id"),
            "qe_tolerance_schema_id": manifest.get("qe_tolerance_schema_id"),
        }
        row["contract_ids"] = contract_ids
        row["baseline_state"] = manifest.get("baseline_state", row.get("status"))
        row["rewrite_mode"] = manifest.get("rewrite_mode")
        row["gpu_mode_attempts"] = manifest.get("gpu_mode_attempts", [])
        row["mode_attempt_exemption_note"] = manifest.get("mode_attempt_exemption_note")
        row["artifact_paths"] = {
            key: str(Path(row["baseline_dir"]) / rel)
            for key, rel in (manifest.get("artifact_paths") or {}).items()
        }
        for value, sink in [
            (contract_ids["workload_group_id"], workload_group_ids),
            (contract_ids["fairness_policy_id"], fairness_policy_ids),
            (contract_ids["power_boundary_id"], power_boundary_ids),
            (contract_ids["algorithm_rewrite_manifest_id"], rewrite_manifest_ids),
            (contract_ids["correctness_contract_id"], correctness_contract_ids),
            (contract_ids["qe_tolerance_schema_id"], tolerance_schema_ids),
        ]:
            if value not in (None, ""):
                sink.add(str(value))

    def collapse_or_none(values: set[str]) -> str | None:
        return next(iter(values)) if len(values) == 1 else None

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "unknown_case")
        grouped.setdefault(case_id, []).append(row)

    case_entries: list[dict[str, Any]] = []
    included_cases: list[dict[str, Any]] = []
    excluded_cases: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    for case_id in sorted(grouped):
        case_rows = grouped[case_id]
        decisive_row = next((row for row in case_rows if row.get("decisive_for_case") is True), None)
        available_rows = [
            {
                "baseline_dir": row.get("baseline_dir"),
                "manifest_path": row.get("manifest_path"),
                "gpu_mode": row.get("gpu_mode"),
                "status": row.get("status"),
                "baseline_state": row.get("baseline_state", row.get("status")),
                "reason": row.get("reason"),
                "blocker_class": row.get("blocker_class"),
                "decisive_for_case": bool(row.get("decisive_for_case", False)),
                "case_ready": bool(row.get("case_ready", False)),
                "time_to_convergence_s": row.get("time_to_convergence_s"),
                "avg_whole_node_power_w": row.get("avg_whole_node_power_w"),
                "energy_to_solution_j": row.get("energy_to_solution_j"),
                "rewrite_mode": row.get("rewrite_mode"),
                "contract_ids": row.get("contract_ids"),
            }
            for row in case_rows
        ]
        excluded_rows: list[dict[str, Any]] = []
        for row in case_rows:
            if decisive_row is not None and row is decisive_row:
                continue
            exclusion_reason = (
                "not_selected_for_case_decision"
                if decisive_row is not None and row.get("status") == "thesis_eligible"
                else row.get("reason")
            )
            excluded_rows.append(
                {
                    "baseline_dir": row.get("baseline_dir"),
                    "manifest_path": row.get("manifest_path"),
                    "gpu_mode": row.get("gpu_mode"),
                    "status": row.get("status"),
                    "baseline_state": row.get("baseline_state", row.get("status")),
                    "reason": exclusion_reason,
                    "blocker_class": row.get("blocker_class"),
                }
            )
            unresolved_rows.append(
                {
                    "case_id": case_id,
                    "baseline_dir": row.get("baseline_dir"),
                    "manifest_path": row.get("manifest_path"),
                    "gpu_mode": row.get("gpu_mode"),
                    "status": row.get("status"),
                    "reason": exclusion_reason,
                    "blocker_class": row.get("blocker_class"),
                }
            )

        aggregation_status = "included" if decisive_row is not None else "excluded"
        aggregation_reason = (
            "decisive_for_case_row_available"
            if decisive_row is not None
            else "no_decisive_gpu_row"
        )
        case_entry = {
            "case_id": case_id,
            "available_gpu_rows": available_rows,
            "decisive_for_case_row": (
                None
                if decisive_row is None
                else {
                    "baseline_dir": decisive_row.get("baseline_dir"),
                    "manifest_path": decisive_row.get("manifest_path"),
                    "gpu_mode": decisive_row.get("gpu_mode"),
                    "status": decisive_row.get("status"),
                    "time_to_convergence_s": decisive_row.get("time_to_convergence_s"),
                    "avg_whole_node_power_w": decisive_row.get("avg_whole_node_power_w"),
                    "energy_to_solution_j": decisive_row.get("energy_to_solution_j"),
                }
            ),
            "excluded_rows": excluded_rows,
            "workload_group_aggregation_status": aggregation_status,
            "workload_group_aggregation_reason": aggregation_reason,
        }
        case_entries.append(case_entry)
        if decisive_row is not None:
            included_cases.append(
                {
                    "case_id": case_id,
                    "gpu_mode": decisive_row.get("gpu_mode"),
                    "baseline_dir": decisive_row.get("baseline_dir"),
                    "manifest_path": decisive_row.get("manifest_path"),
                }
            )
        else:
            excluded_cases.append(
                {
                    "case_id": case_id,
                    "reason": aggregation_reason,
                    "available_row_count": len(case_rows),
                    "row_statuses": sorted(
                        {
                            str(row.get("status"))
                            for row in case_rows
                            if row.get("status") not in (None, "")
                        }
                    ),
                    "blockers": sorted(
                        {
                            str(row.get("reason"))
                            for row in case_rows
                            if row.get("reason") not in (None, "")
                        }
                    ),
                }
            )

    summary["row_ledger"] = rows
    summary["case_decision_sheet"] = {
        "schema_version": "qe_gpu_case_decision_sheet_v0",
        "case_count": len(case_entries),
        "cases": case_entries,
    }
    summary["workload_group_gpu_column_manifest"] = {
        "schema_version": "qe_gpu_workload_group_column_manifest_v0",
        "workload_group_id": collapse_or_none(workload_group_ids),
        "fairness_policy_id": collapse_or_none(fairness_policy_ids),
        "power_boundary_id": collapse_or_none(power_boundary_ids),
        "algorithm_rewrite_manifest_id": collapse_or_none(rewrite_manifest_ids),
        "correctness_contract_id": collapse_or_none(correctness_contract_ids),
        "qe_tolerance_schema_id": collapse_or_none(tolerance_schema_ids),
        "thesis_counted_cases": [item["case_id"] for item in included_cases],
        "decisive_row_paths": included_cases,
        "excluded_cases": excluded_cases,
        "unresolved_rows": unresolved_rows,
        "safe_claim_status": (
            "gpu_column_ready"
            if included_cases and not excluded_cases
            else ("partial_gpu_column" if included_cases else "no_gpu_decisive_column")
        ),
    }
    summary["artifact_paths"] = {
        "gpu_annex_json": None,
        "gpu_annex_md": None,
        "case_decision_sheet_json": None,
        "case_decision_sheet_md": None,
        "workload_group_gpu_column_manifest_json": None,
        "workload_group_gpu_column_manifest_md": None,
    }
    return summary


def build_phase1_evidence_closure_info(
    *,
    gpu_baseline_dirs: list[Path],
    board_dirs: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    assessor = load_phase1_evidence_closure_module()
    renderer = load_phase1_evidence_closure_renderer_module()
    gpu_rows, gpu_by_case = assessor.assess_gpu_rows([str(path) for path in gpu_baseline_dirs])
    board_rows, board_by_case = assessor.assess_board_dirs([str(path) for path in board_dirs])
    case_matrix = assessor.build_case_matrix(gpu_by_case, board_by_case)
    report = assessor.build_summary(gpu_rows, board_rows, case_matrix)
    json_path = output_dir / "qe_phase1_evidence_closure_report.json"
    md_path = output_dir / "qe_phase1_evidence_closure_report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(renderer.render_markdown(report), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "summary": report["summary"],
        "case_matrix": report["case_matrix"],
    }


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def build_phase_runner_command(args: argparse.Namespace) -> str:
    parts = [
        "python3",
        "tools/benchmarks/run_qe_next_stage_dse_phase.py",
        "--output-dir",
        str(args.output_dir),
        "--phase-config",
        str(args.phase_config),
    ]
    if args.execute_model:
        parts.append("--execute-model")
    if args.full_cross_product:
        parts.append("--full-cross-product")
    if args.auto_match_baseline_iters:
        parts.append("--auto-match-baseline-iters")
    if args.fail_on_gold_mismatch:
        parts.append("--fail-on-gold-mismatch")
    parts.extend(["--model-bin", str(args.model_bin)])
    parts.extend(["--model-max-scf-iters", str(args.model_max_scf_iters)])
    if args.case_pack is not None:
        parts.extend(["--case-pack", str(args.case_pack)])
    for path in args.gpu_baseline_dir:
        parts.extend(["--gpu-baseline-dir", str(path)])
    for path in args.gpu_reference_dir:
        parts.extend(["--gpu-reference-dir", str(path)])
    for path in args.board_dir:
        parts.extend(["--board-dir", str(path)])
    return shell_join(parts)


def build_release_validator_command(summary_json_path: Path) -> str:
    return shell_join(
        [
            "python3",
            "tools/benchmarks/check_qe_next_stage_release_bundle.py",
            "--summary",
            str(summary_json_path),
        ]
    )


def load_phase_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_case_pack(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_component_registry_registry(registry: dict[str, Any]) -> dict[str, Any]:
    validation = registry["validation"]
    return {
        "schema_version": registry["schema_version"],
        "catalog_version": registry["catalog_version"],
        "seed_template_version": registry["seed_template_version"],
        "all_strict_checks_pass": validation["all_strict_checks_pass"],
        "component_count": validation["component_count"],
        "active_build_source_count": validation["active_build_source_count"],
        "strict_backbone_component_count": validation["strict_backbone_component_count"],
        "future_catalog_expansion_candidate_count": validation[
            "future_catalog_expansion_candidate_count"
        ],
        "intentional_unmapped_active_source_count": validation[
            "intentional_unmapped_active_source_count"
        ],
        "shared_anchor_count": validation["shared_anchor_count"],
        "active_source_gap_categories": validation["active_source_gap_categories"],
    }


def build_gpu_annex_summary(
    gpu_baseline_dirs: list[Path],
    gpu_reference_dirs: list[Path] | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    reference_dirs = [path for path in (gpu_reference_dirs or []) if path.exists()]
    if not gpu_baseline_dirs:
        if reference_dirs:
            if output_root is not None:
                generated_root = output_root / "gpu_reference_baselines"
                bundle_dirs = [
                    materialize_reference_gpu_baseline_bundle(path, generated_root)
                    for path in reference_dirs
                ]
                summary = summarize_manifest_backed_gpu_baseline_dirs(bundle_dirs)
                summary["source_surface"] = "gpu_reference_bundle_readiness"
                summary["reason"] = "reference_gpu_directory_materialized"
                summary["generated_bundle_dirs"] = [str(path) for path in bundle_dirs]
                return summary
            return build_reference_gpu_annex_summary(reference_dirs[0])
        return {
            "schema_version": "qe_gpu_annex_summary_v0",
            "status": "deferred",
            "reason": "no_gpu_baseline_dirs_configured",
            "source_surface": "gpu_baseline_readiness",
            "baseline_dir_count": 0,
            "counts": {
                "thesis_eligible": 0,
                "reference_only": 0,
                "deferred": 0,
                "decisive": 0,
            },
            "gpu_mode_set_measured": [],
            "gpu_decisive_modes": [],
            "decisive_case_ids": [],
            "row_ledger": [],
            "annex_note": (
                "GPU annex is deferred because no baseline directories were configured; "
                "this does not block DSE package closure but it does block any decisive "
                "CPU+FPGA > CPU+GPU thesis claim."
            ),
        }

    return summarize_manifest_backed_gpu_baseline_dirs(gpu_baseline_dirs)


def render_gpu_annex_summary_md(summary: dict[str, Any]) -> str:
    artifact_paths = summary.get("artifact_paths") or {}
    case_sheet = summary.get("case_decision_sheet") or {}
    workload_manifest = summary.get("workload_group_gpu_column_manifest") or {}
    lines = [
        "# QE GPU Annex Summary",
        "",
        f"- schema_version: `{summary['schema_version']}`",
        f"- source_surface: `{summary['source_surface']}`",
        f"- status: `{summary['status']}`",
        f"- reason: `{summary['reason']}`",
        f"- baseline_dir_count: `{summary['baseline_dir_count']}`",
        f"- gpu_mode_set_measured: `{', '.join(summary['gpu_mode_set_measured']) if summary['gpu_mode_set_measured'] else '—'}`",
        f"- gpu_decisive_modes: `{', '.join(summary['gpu_decisive_modes']) if summary['gpu_decisive_modes'] else '—'}`",
        f"- decisive_case_ids: `{', '.join(summary['decisive_case_ids']) if summary['decisive_case_ids'] else '—'}`",
        f"- counts: `{json.dumps(summary['counts'], ensure_ascii=False)}`",
        f"- annex_note: `{summary['annex_note']}`",
        f"- case_decision_sheet_json: `{artifact_paths.get('case_decision_sheet_json') or '—'}`",
        f"- workload_group_gpu_column_manifest_json: `{artifact_paths.get('workload_group_gpu_column_manifest_json') or '—'}`",
        "",
        "## Row ledger",
        "",
        "| case_id | gpu_mode | status | decisive_for_case | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    if summary["row_ledger"]:
        for row in summary["row_ledger"]:
            lines.append(
                f"| {row.get('case_id', '—')} | {row.get('gpu_mode', '—')} | {row.get('status', '—')} | {row.get('decisive_for_case', False)} | {row.get('reason', '—')} |"
            )
    else:
        lines.append("| — | — | — | — | — |")
    reference_paths = summary.get("reference_artifact_paths")
    if reference_paths is not None:
        lines.extend(
            [
                "",
                "## Reference artifacts",
                "",
                f"- qe_timing_json: `{reference_paths['qe_timing_json']}`",
                f"- app_out: `{reference_paths['app_out']}`",
                f"- cuda_gpu_kernel_summary_csv: `{reference_paths['cuda_gpu_kernel_summary_csv']}`",
            ]
        )
    if case_sheet:
        lines.extend(
            [
                "",
                "## Case decision sheet",
                "",
                f"- case_count: `{case_sheet.get('case_count', 0)}`",
            ]
        )
    if workload_manifest:
        lines.extend(
            [
                "",
                "## Workload-group GPU column manifest",
                "",
                f"- workload_group_id: `{workload_manifest.get('workload_group_id') or '—'}`",
                f"- thesis_counted_cases: `{', '.join(workload_manifest.get('thesis_counted_cases', [])) if workload_manifest.get('thesis_counted_cases') else '—'}`",
                f"- safe_claim_status: `{workload_manifest.get('safe_claim_status') or '—'}`",
            ]
        )
    return "\n".join(lines) + "\n"


def render_gpu_case_decision_sheet_md(sheet: dict[str, Any]) -> str:
    lines = [
        "# QE GPU Case Decision Sheet",
        "",
        f"- schema_version: `{sheet['schema_version']}`",
        f"- case_count: `{sheet['case_count']}`",
        "",
    ]
    for case in sheet["cases"]:
        lines.extend(
            [
                f"## {case['case_id']}",
                "",
                f"- workload_group_aggregation_status: `{case['workload_group_aggregation_status']}`",
                f"- workload_group_aggregation_reason: `{case['workload_group_aggregation_reason']}`",
            ]
        )
        decisive = case.get("decisive_for_case_row")
        if decisive is None:
            lines.append("- decisive_for_case_row: `—`")
        else:
            lines.extend(
                [
                    f"- decisive_gpu_mode: `{decisive.get('gpu_mode')}`",
                    f"- decisive_baseline_dir: `{decisive.get('baseline_dir')}`",
                    f"- decisive_manifest_path: `{decisive.get('manifest_path') or '—'}`",
                    f"- decisive_time_to_convergence_s: `{decisive.get('time_to_convergence_s')}`",
                ]
            )
        lines.extend(
            [
                "",
                "### Available GPU rows",
                "",
                "| gpu_mode | status | decisive_for_case | reason | baseline_dir |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row in case["available_gpu_rows"]:
            lines.append(
                f"| `{row.get('gpu_mode')}` | `{row.get('status')}` | `{row.get('decisive_for_case')}` | `{row.get('reason')}` | `{row.get('baseline_dir')}` |"
            )
        if case["excluded_rows"]:
            lines.extend(
                [
                    "",
                    "### Excluded rows",
                    "",
                    "| gpu_mode | status | reason | baseline_dir |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for row in case["excluded_rows"]:
                lines.append(
                    f"| `{row.get('gpu_mode')}` | `{row.get('status')}` | `{row.get('reason')}` | `{row.get('baseline_dir')}` |"
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def render_gpu_workload_group_manifest_md(manifest: dict[str, Any]) -> str:
    lines = [
        "# QE GPU Workload-Group Column Manifest",
        "",
        f"- schema_version: `{manifest['schema_version']}`",
        f"- workload_group_id: `{manifest.get('workload_group_id') or '—'}`",
        f"- fairness_policy_id: `{manifest.get('fairness_policy_id') or '—'}`",
        f"- power_boundary_id: `{manifest.get('power_boundary_id') or '—'}`",
        f"- algorithm_rewrite_manifest_id: `{manifest.get('algorithm_rewrite_manifest_id') or '—'}`",
        f"- correctness_contract_id: `{manifest.get('correctness_contract_id') or '—'}`",
        f"- qe_tolerance_schema_id: `{manifest.get('qe_tolerance_schema_id') or '—'}`",
        f"- thesis_counted_cases: `{', '.join(manifest.get('thesis_counted_cases', [])) if manifest.get('thesis_counted_cases') else '—'}`",
        f"- safe_claim_status: `{manifest.get('safe_claim_status')}`",
        "",
        "## Decisive row paths",
        "",
        "| case_id | gpu_mode | baseline_dir | manifest_path |",
        "| --- | --- | --- | --- |",
    ]
    decisive_rows = manifest.get("decisive_row_paths") or []
    if decisive_rows:
        for row in decisive_rows:
            lines.append(
                f"| `{row.get('case_id')}` | `{row.get('gpu_mode')}` | `{row.get('baseline_dir')}` | `{row.get('manifest_path') or '—'}` |"
            )
    else:
        lines.append("| `—` | `—` | `—` | `—` |")
    lines.extend(
        [
            "",
            "## Excluded cases",
            "",
            "| case_id | reason | row_statuses | blockers |",
            "| --- | --- | --- | --- |",
        ]
    )
    excluded_cases = manifest.get("excluded_cases") or []
    if excluded_cases:
        for row in excluded_cases:
            lines.append(
                f"| `{row.get('case_id')}` | `{row.get('reason')}` | `{', '.join(row.get('row_statuses') or []) or '—'}` | `{', '.join(row.get('blockers') or []) or '—'}` |"
            )
    else:
        lines.append("| `—` | `—` | `—` | `—` |")
    return "\n".join(lines) + "\n"


def build_component_registry_info(output_dir: Path) -> dict[str, Any]:
    builder = load_component_registry_builder()
    catalog = builder.load_json(builder.CATALOG_PATH)
    graph_seeds = builder.load_json(builder.GRAPH_SEEDS_PATH)
    active_sources = builder.load_cmake_active_sources(builder.CMAKE_PATH)
    registry = builder.build_registry(
        catalog,
        graph_seeds,
        active_sources,
        catalog_path=builder.CATALOG_PATH,
        graph_seeds_path=builder.GRAPH_SEEDS_PATH,
        cmake_path=builder.CMAKE_PATH,
        readme_path=builder.README_PATH,
    )
    json_path = output_dir / "qe_ic_component_registry_v0.json"
    json_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "json_path": str(json_path),
        "summary": summarize_component_registry_registry(registry),
    }


CASE_PACK_SECTION_ORDER = [
    "stage_a_bringup_descriptors",
    "stage_b_nonblocking_signature_descriptors",
    "accurate_layer_anchor_descriptors",
    "accurate_layer_coverage_descriptors",
    "accurate_layer_generalization_descriptors",
]


def case_pack_workload_ids(case_pack: dict[str, Any]) -> set[str]:
    workload_ids: set[str] = set()
    for section in CASE_PACK_SECTION_ORDER:
        for item in case_pack.get(section, []):
            workload_id = item.get("workload_id")
            if workload_id:
                workload_ids.add(str(workload_id))
    return workload_ids


def summarize_case_pack(case_pack: dict[str, Any], phase_config: dict[str, Any]) -> dict[str, Any]:
    sections = {
        "stage_a_bringup": [item["workload_id"] for item in case_pack.get("stage_a_bringup_descriptors", [])],
        "stage_b_nonblocking_signature": [
            item["workload_id"] for item in case_pack.get("stage_b_nonblocking_signature_descriptors", [])
        ],
        "accurate_layer_anchor": [
            item["workload_id"] for item in case_pack.get("accurate_layer_anchor_descriptors", [])
        ],
        "accurate_layer_coverage": [
            item["workload_id"] for item in case_pack.get("accurate_layer_coverage_descriptors", [])
        ],
        "accurate_layer_generalization": [
            item["workload_id"] for item in case_pack.get("accurate_layer_generalization_descriptors", [])
        ],
    }
    referenced = {
        *phase_config["layers"]["fast_layer"]["main_cases"],
        *phase_config["layers"]["accurate_layer"].get("anchor_cases", []),
        *phase_config["layers"]["accurate_layer"].get("coverage_cases", []),
        *phase_config["layers"]["accurate_layer"].get("generalization_cases", []),
    }
    available = case_pack_workload_ids(case_pack)
    return {
        "case_pack_schema_version": case_pack.get("schema_version"),
        "matrix_path": case_pack.get("matrix_path"),
        "phase_config_path": case_pack.get("phase_config_path"),
        "bundle_role": case_pack.get("bundle_role"),
        "seed_family": case_pack.get("seed_family"),
        "sections": sections,
        "all_referenced_workloads_present": referenced <= available,
        "missing_referenced_workloads": sorted(referenced - available),
    }


def case_pack_sections_for_lane(lane_name: str) -> list[str]:
    if lane_name == "fast_layer":
        return ["stage_a_bringup_descriptors", "stage_b_nonblocking_signature_descriptors"]
    if lane_name == "accurate_layer":
        return ["accurate_layer_anchor_descriptors"]
    if lane_name == "accurate_coverage":
        return ["accurate_layer_coverage_descriptors"]
    if lane_name == "generalization_coverage":
        return ["accurate_layer_generalization_descriptors"]
    return CASE_PACK_SECTION_ORDER


def normalize_case_pack_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    payload = dict(descriptor)
    if "display_label" in payload and "label" not in payload:
        payload["label"] = payload["display_label"]
    return payload


def workload_rows_from_case_pack(
    case_pack: dict[str, Any],
    lane_name: str,
    workloads: list[str],
    *,
    force_gold_required: bool = False,
) -> list[dict[str, Any]]:
    sections = case_pack_sections_for_lane(lane_name)
    descriptors_by_id: dict[str, dict[str, Any]] = {}
    for section in sections:
        for item in case_pack.get(section, []):
            workload_id = str(item.get("workload_id", ""))
            if workload_id:
                descriptors_by_id[workload_id] = normalize_case_pack_descriptor(item)
    missing = [workload_id for workload_id in workloads if workload_id not in descriptors_by_id]
    if missing:
        raise ValueError(
            f"case pack missing descriptors for lane {lane_name}: {', '.join(missing)}"
        )
    rows = [descriptors_by_id[workload_id] for workload_id in workloads]
    if force_gold_required:
        rows = [{**row, "gold_required": True} for row in rows]
    return rows


def required_fast_layer_metrics(config: dict[str, Any]) -> list[str]:
    fast_layer = config["layers"]["fast_layer"]
    return [
        fast_layer["primary_objective"],
        fast_layer["secondary_objective"],
        *list(fast_layer["constraint_metrics"]),
    ]


def relative_margin(reference: float | None, candidate: float | None) -> float | None:
    if reference is None or candidate is None or reference <= 0.0:
        return None
    return abs(candidate - reference) / reference


def default_partition_strategy(
    family: str | None,
    offload_scope: str | None,
) -> str:
    if family == "F1" or offload_scope == "single_hotpath":
        return "single_hotpath_partition"
    return "operator__build__diag__refresh"


def runtime_observability_summary(runtime: dict[str, Any] | None) -> str | None:
    if not runtime:
        return None
    diag_path = runtime.get("last_diag_path") or "unknown"
    grid = runtime.get("last_support_grid_mode") or "unknown"
    bucket = runtime.get("last_workload_bucket") or "unknown"
    band_count = runtime.get("last_band_count")
    inner_steps = runtime.get("realized_inner_steps")
    configured_inner_steps = runtime.get("configured_max_inner_steps")
    spill_count = runtime.get("spill_active_count")
    host_fallback_count = runtime.get("host_cpu_fallback_count")
    condition_limit = runtime.get("last_max_diag_condition_estimate")
    inner_text = (
        "unknown"
        if inner_steps is None or configured_inner_steps is None
        else f"{inner_steps}/{configured_inner_steps}"
    )
    return (
        f"diag={diag_path}, grid={grid}, bucket={bucket}, band_count={band_count}, "
        f"inner_steps={inner_text}, spill_count={spill_count}, "
        f"host_fallback_count={host_fallback_count}, max_diag_condition={condition_limit}"
    )


def graph_topology_summary(graph: dict[str, Any] | None) -> str | None:
    if not graph:
        return None
    style = graph.get("topology_style")
    control = graph.get("control_plane_summary")
    datapath = graph.get("datapath_stage_summary")
    parts = []
    if style:
        parts.append(f"style={style}")
    if control:
        parts.append(f"control={control}")
    if datapath:
        parts.append(f"datapath={datapath}")
    return " | ".join(parts) if parts else None


def graph_execution_plan_summary(graph: dict[str, Any] | None) -> str | None:
    if not graph:
        return None
    summary = graph.get("execution_plan_summary")
    if summary in (None, ""):
        return None
    return str(summary)


def graph_component_driver_summary(graph: dict[str, Any] | None) -> str | None:
    if not graph:
        return None
    score_source = graph.get("component_score_source")
    execution_summary = graph_execution_plan_summary(graph)
    cluster_cycles = graph.get("cluster_cycle_summary")
    signal_summary = graph.get("component_score_signal_summary")
    iteration_summary_text = graph.get("iteration_behavior_summary")
    bottleneck = graph.get("bottleneck_component_summary")
    leaf_bottleneck = graph.get("leaf_bottleneck_component_summary")
    risk = graph.get("risk_driver_component_summary")
    key_components = graph.get("key_component_refs_summary")
    leaf_components = graph.get("leaf_component_refs_summary")
    component_score = graph.get("component_score_summary")
    parts = []
    if execution_summary:
        parts.append(f"exec={execution_summary}")
    if score_source:
        parts.append(f"source={score_source}")
    if cluster_cycles:
        parts.append(f"cluster={cluster_cycles}")
    if signal_summary:
        parts.append(f"signal={signal_summary}")
    if iteration_summary_text:
        parts.append(f"iter={iteration_summary_text}")
    if key_components:
        parts.append(f"key={key_components}")
    if leaf_components:
        parts.append(f"leaf={leaf_components}")
    if bottleneck:
        parts.append(f"bottleneck={bottleneck}")
    if leaf_bottleneck:
        parts.append(f"leaf_bottleneck={leaf_bottleneck}")
    if risk:
        parts.append(f"risk={risk}")
    if component_score:
        parts.append(f"score={component_score}")
    return " | ".join(parts) if parts else None


def graph_runtime_evidence_fields(graph: dict[str, Any] | None) -> dict[str, Any]:
    if not graph:
        return {
            "graph_topology_summary": None,
            "graph_execution_plan_summary": None,
            "graph_cluster_cycle_summary": None,
            "graph_component_score_signal_summary": None,
            "graph_iteration_behavior_summary": None,
            "graph_component_driver_summary": None,
        }
    return {
        "graph_topology_summary": graph_topology_summary(graph),
        "graph_execution_plan_summary": graph_execution_plan_summary(graph),
        "graph_cluster_cycle_summary": graph.get("cluster_cycle_summary"),
        "graph_component_score_signal_summary": graph.get("component_score_signal_summary"),
        "graph_iteration_behavior_summary": graph.get("iteration_behavior_summary"),
        "graph_component_driver_summary": graph_component_driver_summary(graph),
    }


def runtime_risk_assessment(runtime: dict[str, Any] | None) -> dict[str, Any]:
    if not runtime:
        return {
            "runtime_risk_score": 0,
            "runtime_risk_level": "unknown",
            "runtime_risk_reasons": [],
        }
    score = 0
    reasons: list[str] = []
    if runtime.get("last_diag_path") == "host_cpu_fallback":
        score += 3
        reasons.append("host_cpu_fallback")
    spill_count = runtime.get("spill_active_count")
    if isinstance(spill_count, int) and spill_count > 0:
        score += 2
        reasons.append("spill_active")
    host_fallback_count = runtime.get("host_cpu_fallback_count")
    if isinstance(host_fallback_count, int) and host_fallback_count > 0:
        score += 1
        reasons.append("fallback_observed")
    realized_inner_steps = runtime.get("realized_inner_steps")
    configured_max_inner_steps = runtime.get("configured_max_inner_steps")
    if (
        isinstance(realized_inner_steps, int)
        and isinstance(configured_max_inner_steps, int)
        and configured_max_inner_steps > 0
        and realized_inner_steps >= configured_max_inner_steps
    ):
        score += 1
        reasons.append("inner_steps_at_cap")
    support_grid_mode = runtime.get("last_support_grid_mode")
    if support_grid_mode not in (None, "", "BYPASS"):
        score += 1
        reasons.append("support_grid_active")
    if runtime.get("last_workload_bucket") == "large":
        score += 1
        reasons.append("large_bucket")
    if score >= 5:
        level = "high"
    elif score >= 2:
        level = "medium"
    else:
        level = "low"
    return {
        "runtime_risk_score": score,
        "runtime_risk_level": level,
        "runtime_risk_reasons": reasons,
    }


def candidate_runtime_risk_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    if candidate.get("runtime_risk_level") not in (None, "unknown") and candidate.get(
        "runtime_risk_score"
    ) is not None:
        return {
            "runtime_risk_score": candidate.get("runtime_risk_score"),
            "runtime_risk_level": candidate.get("runtime_risk_level"),
            "runtime_risk_reasons": candidate.get("runtime_risk_reasons") or [],
        }
    return runtime_risk_assessment(candidate.get("runtime_observability"))


def aggregate_runtime_risk(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"low": 0, "medium": 0, "high": 0, "unknown": 0}
    high_risk_result_ids: list[str] = []
    contributing_reasons: dict[str, int] = {}
    max_score = 0
    for candidate in candidates:
        if candidate is None:
            continue
        risk = candidate_runtime_risk_fields(candidate)
        level = str(risk.get("runtime_risk_level") or "unknown")
        score = int(risk.get("runtime_risk_score") or 0)
        counts[level] = counts.get(level, 0) + 1
        max_score = max(max_score, score)
        if level == "high" and candidate.get("result_id") is not None:
            high_risk_result_ids.append(str(candidate["result_id"]))
        for reason in risk.get("runtime_risk_reasons") or []:
            contributing_reasons[str(reason)] = contributing_reasons.get(str(reason), 0) + 1
    if counts["high"] > 0:
        overall = "high"
    elif counts["medium"] > 0:
        overall = "medium"
    elif counts["low"] > 0:
        overall = "low"
    else:
        overall = "unknown"
    return {
        "overall_runtime_risk": overall,
        "candidate_count": sum(counts.values()),
        "max_runtime_risk_score": max_score,
        "counts": counts,
        "high_risk_result_ids": high_risk_result_ids,
        "contributing_reasons": contributing_reasons,
    }


def build_candidate_brief(row: dict[str, Any]) -> dict[str, Any]:
    runtime = row.get("runtime_observability")
    risk = runtime_risk_assessment(runtime)
    candidate_family = row_candidate_family(row)
    runtime_projection_family = row_runtime_projection_family(row)
    return {
        "result_id": row["result_id"],
        "signature_id": row["workload"].get("signature_id"),
        "family": row["design_point"]["family"],
        "candidate_family": candidate_family,
        "runtime_projection_family": runtime_projection_family,
        "architecture_template_id": row.get("architecture_template_id"),
        "candidate_id": row.get("candidate_id"),
        "template_family": row.get("template_family"),
        "support_status": row.get("support_status"),
        "evaluator_backend": row.get("evaluator_backend"),
        "fidelity_class": row.get("fidelity_class"),
        "diag_policy": row["design_point"]["diag_policy"],
        "offload_scope": row["design_point"]["offload_scope"],
        "resident_policy": row["design_point"]["resident_policy"],
        "partition_strategy": row["design_point"].get(
            "partition_strategy",
            default_partition_strategy(
                row["design_point"]["family"],
                row["design_point"]["offload_scope"],
            ),
        ),
        "time_to_convergence_s": row["primary_metrics"]["time_to_convergence_s"],
        "energy_to_convergence_j": row["primary_metrics"]["energy_to_convergence_j"],
        "avg_system_power_proxy_w": row["primary_metrics"].get("avg_system_power_proxy_w"),
        "bytes_moved_to_convergence": row["primary_metrics"]["bytes_moved_to_convergence"],
        "fallback_ratio": row["secondary_metrics"]["fallback_ratio"],
        "spill_ratio": row["secondary_metrics"]["spill_ratio"],
        "runtime_observability": runtime,
        "runtime_risk_score": risk["runtime_risk_score"],
        "runtime_risk_level": risk["runtime_risk_level"],
        "runtime_risk_reasons": risk["runtime_risk_reasons"],
        "graph_evidence": row.get("graph_evidence"),
        "graph_evidence_path": (row.get("artifacts") or {}).get("graph_evidence_path"),
        "ranking_grade_ready": row["projection"]["ranking_grade_ready"],
    }


def design_point_key(
    family: str,
    diag_policy: str,
    offload_scope: str,
    resident_policy: str,
    partition_strategy: str,
) -> tuple[str, str, str, str, str]:
    return (family, diag_policy, offload_scope, resident_policy, partition_strategy)


def row_candidate_family(row: dict[str, Any]) -> str:
    value = row.get("candidate_family")
    if value not in (None, ""):
        return str(value)
    return str(row["design_point"]["family"])


def row_runtime_projection_family(row: dict[str, Any]) -> str:
    value = row.get("runtime_projection_family")
    if value not in (None, ""):
        return str(value)
    return str(row["design_point"]["family"])


def design_point_key_from_mapping(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return design_point_key(
        str(payload["family"]),
        str(payload["diag_policy"]),
        str(payload["offload_scope"]),
        str(payload["resident_policy"]),
        str(
            payload.get(
                "partition_strategy",
                default_partition_strategy(
                    str(payload.get("family")),
                    str(payload.get("offload_scope")),
                ),
            )
        ),
    )


def row_design_point_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return design_point_key_from_mapping(row["design_point"])


def selection_has_candidate_identity(selection: dict[str, Any]) -> bool:
    return any(
        selection.get(field) not in (None, "")
        for field in (
            "candidate_family",
            "runtime_projection_family",
            "architecture_template_id",
            "candidate_id",
        )
    )


def row_matches_selected_design(row: dict[str, Any], selected: dict[str, Any]) -> bool:
    if row_design_point_key(row) != design_point_key_from_mapping(selected):
        return False
    if not selection_has_candidate_identity(selected):
        return True
    if selected.get("candidate_family") not in (None, "") and row_candidate_family(row) != str(selected["candidate_family"]):
        return False
    if selected.get("runtime_projection_family") not in (None, "") and row_runtime_projection_family(row) != str(selected["runtime_projection_family"]):
        return False
    if selected.get("architecture_template_id") not in (None, "") and str(row.get("architecture_template_id") or "") != str(selected["architecture_template_id"]):
        return False
    if selected.get("candidate_id") not in (None, "") and str(row.get("candidate_id") or "") != str(selected["candidate_id"]):
        return False
    return True


def row_is_projection_only_for_summary(row: dict[str, Any], runner: Any) -> bool:
    if hasattr(runner, "row_is_projection_only"):
        return bool(runner.row_is_projection_only(row))
    return str(row.get("support_status") or row.get("fidelity_class") or "") == "projection_only"


def build_equal_candidate_family_summary(
    results: list[dict[str, Any]],
    runner: Any,
) -> list[dict[str, Any]]:
    candidate_families = list(
        getattr(runner, "CANDIDATE_FAMILIES", ["F1", "F2", "F3", "F4", "F5", "custom"])
    )
    for row in results:
        family = row_candidate_family(row)
        if family not in candidate_families:
            candidate_families.append(family)

    out: list[dict[str, Any]] = []
    for candidate_family in candidate_families:
        family_rows = [row for row in results if row_candidate_family(row) == candidate_family]
        support_counts = Counter(str(row.get("support_status") or "unknown") for row in family_rows)
        evaluator_counts = Counter(str(row.get("evaluator_backend") or "unknown") for row in family_rows)
        fidelity_counts = Counter(str(row.get("fidelity_class") or "unknown") for row in family_rows)
        out.append(
            {
                "candidate_family": candidate_family,
                "result_count": len(family_rows),
                "runtime_projection_families": sorted(
                    {row_runtime_projection_family(row) for row in family_rows if row_runtime_projection_family(row)}
                ),
                "architecture_template_ids": sorted(
                    {str(row.get("architecture_template_id")) for row in family_rows if row.get("architecture_template_id")}
                ),
                "candidate_ids": sorted(
                    {str(row.get("candidate_id")) for row in family_rows if row.get("candidate_id")}
                ),
                "support_status_counts": dict(sorted(support_counts.items())),
                "evaluator_backend_counts": dict(sorted(evaluator_counts.items())),
                "fidelity_class_counts": dict(sorted(fidelity_counts.items())),
                "projection_only_rows": sum(
                    1 for row in family_rows if row_is_projection_only_for_summary(row, runner)
                ),
            }
        )
    return out


def refresh_equal_candidate_family_summary(bundle: dict[str, Any], runner: Any) -> None:
    bundle["candidate_family_summary"] = build_equal_candidate_family_summary(
        bundle["results"],
        runner,
    )


def classify_fast_layer_result(
    row: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    primary = row["primary_metrics"]
    secondary = row["secondary_metrics"]
    metric_getters = {
        config["layers"]["fast_layer"]["primary_objective"]: primary.get(config["layers"]["fast_layer"]["primary_objective"]),
        config["layers"]["fast_layer"]["secondary_objective"]: primary.get(config["layers"]["fast_layer"]["secondary_objective"]),
        "bytes_moved_to_convergence": primary.get("bytes_moved_to_convergence"),
        "fallback_ratio": secondary.get("fallback_ratio"),
        "spill_ratio": secondary.get("spill_ratio"),
    }
    missing_metrics = [metric for metric in required_fast_layer_metrics(config) if metric_getters.get(metric) is None]

    result_status = str(row["result_status"])
    correctness_status = str(row["correctness"]["status"])
    reject_statuses = set(config["promotion_policy"]["reject_statuses"])
    if result_status in reject_statuses or correctness_status in BLOCKING_STATUSES:
        state = "reject"
        reason = result_status if result_status in reject_statuses else correctness_status
    elif missing_metrics:
        state = "explain-only"
        reason = "missing_fast_layer_metrics"
    elif not row["projection"]["ranking_grade_ready"]:
        state = "explain-only"
        reason = "ranking_grade_ready_false"
    else:
        state = "promotion-eligible"
        reason = "ranking_grade_ready_true"

    return {
        "result_id": row["result_id"],
        "state": state,
        "reason": reason,
        "missing_metrics": missing_metrics,
        "candidate": build_candidate_brief(row),
    }


def summarize_fast_layer_shortlists(
    bundle: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in bundle["results"]:
        workload_id = str(row["workload"]["workload_id"])
        grouped.setdefault(workload_id, []).append(row)

    tie_band_margin = float(config["promotion_policy"]["tie_band_rule"]["max_relative_margin"])
    summaries: list[dict[str, Any]] = []
    for workload_id, rows in grouped.items():
        classifications = [classify_fast_layer_result(row, config) for row in rows]
        state_counts = {state: 0 for state in config["promotion_policy"]["state_machine"]}
        for item in classifications:
            state_counts[item["state"]] += 1

        promotion_ready = [item for item in classifications if item["state"] == "promotion-eligible"]
        promotion_ready.sort(
            key=lambda item: (
                item["candidate"]["time_to_convergence_s"],
                item["candidate"]["energy_to_convergence_j"],
                item["candidate"]["runtime_risk_score"],
                item["candidate"]["result_id"],
            )
        )

        primary_candidate = promotion_ready[0]["candidate"] if promotion_ready else None
        fallback_candidate = promotion_ready[1]["candidate"] if len(promotion_ready) > 1 else None
        extra_promoted_candidates = []
        if primary_candidate is not None:
            primary_time = primary_candidate["time_to_convergence_s"]
            for item in promotion_ready[2:]:
                margin = relative_margin(primary_time, item["candidate"]["time_to_convergence_s"])
                if margin is not None and margin <= tie_band_margin:
                    promoted = dict(item["candidate"])
                    promoted["relative_time_margin_to_primary"] = margin
                    extra_promoted_candidates.append(promoted)

        selection_notes: list[str] = []
        if primary_candidate is None:
            selection_status = "insufficient_evidence"
            selection_notes.append("no promotion-eligible design point is currently available")
        elif fallback_candidate is None:
            selection_status = "primary_only"
            selection_notes.append("fallback candidate is unavailable because fewer than two promotion-eligible points exist")
        else:
            selection_status = "ready"
            tie_margin = relative_margin(
                primary_candidate["time_to_convergence_s"],
                fallback_candidate["time_to_convergence_s"],
            )
            if tie_margin is not None and tie_margin <= tie_band_margin:
                selection_notes.append(
                    f"primary/fallback stay inside the frozen tie-band (relative margin={tie_margin:.3f})"
                )
        if primary_candidate is not None:
            primary_runtime = runtime_observability_summary(
                primary_candidate.get("runtime_observability")
            )
            primary_risk = runtime_risk_assessment(primary_candidate.get("runtime_observability"))
            if primary_runtime is not None:
                selection_notes.append(f"primary_runtime: {primary_runtime}")
            selection_notes.append(
                "primary_runtime_risk: "
                f"{primary_risk['runtime_risk_level']} ({', '.join(primary_risk['runtime_risk_reasons']) or 'none'})"
            )
            primary_graph = primary_candidate.get("graph_evidence") or {}
            if primary_graph.get("seed_template_id") is not None:
                selection_notes.append(
                    "primary_graph: "
                    f"{primary_graph['seed_template_id']} | {primary_graph.get('dataflow_bottleneck_summary') or 'no_bottleneck_summary'}"
                )
                primary_graph_topology = graph_topology_summary(primary_graph)
                if primary_graph_topology is not None:
                    selection_notes.append(f"primary_graph_topology: {primary_graph_topology}")
                primary_graph_components = graph_component_driver_summary(primary_graph)
                if primary_graph_components is not None:
                    selection_notes.append(f"primary_graph_components: {primary_graph_components}")
            else:
                selection_notes.append(
                    "primary_graph_missing: "
                    f"{primary_graph.get('mapping_risk_summary') or 'no_matching_seed_template'}"
                )
        if fallback_candidate is not None:
            fallback_runtime = runtime_observability_summary(
                fallback_candidate.get("runtime_observability")
            )
            fallback_risk = runtime_risk_assessment(fallback_candidate.get("runtime_observability"))
            if fallback_runtime is not None:
                selection_notes.append(f"fallback_runtime: {fallback_runtime}")
            selection_notes.append(
                "fallback_runtime_risk: "
                f"{fallback_risk['runtime_risk_level']} ({', '.join(fallback_risk['runtime_risk_reasons']) or 'none'})"
            )
            fallback_graph = fallback_candidate.get("graph_evidence") or {}
            if fallback_graph.get("seed_template_id") is not None:
                selection_notes.append(
                    "fallback_graph: "
                    f"{fallback_graph['seed_template_id']} | {fallback_graph.get('dataflow_bottleneck_summary') or 'no_bottleneck_summary'}"
                )
                fallback_graph_topology = graph_topology_summary(fallback_graph)
                if fallback_graph_topology is not None:
                    selection_notes.append(f"fallback_graph_topology: {fallback_graph_topology}")
                fallback_graph_components = graph_component_driver_summary(fallback_graph)
                if fallback_graph_components is not None:
                    selection_notes.append(f"fallback_graph_components: {fallback_graph_components}")
            else:
                selection_notes.append(
                    "fallback_graph_missing: "
                    f"{fallback_graph.get('mapping_risk_summary') or 'no_matching_seed_template'}"
                )
        runtime_risk_summary = aggregate_runtime_risk(
            [
                candidate
                for candidate in [
                    primary_candidate,
                    fallback_candidate,
                    *extra_promoted_candidates,
                ]
                if candidate is not None
            ]
        )

        summaries.append(
            {
                "workload_id": workload_id,
                "workload_label": rows[0]["workload"]["label"],
                "selection_status": selection_status,
                "state_counts": state_counts,
                "primary_candidate": primary_candidate,
                "fallback_candidate": fallback_candidate,
                "extra_promoted_candidates": extra_promoted_candidates,
                "selection_notes": selection_notes,
                "runtime_risk_summary": runtime_risk_summary,
                "design_points": classifications,
            }
        )
    return summaries


def candidate_to_design_point(candidate: dict[str, Any]) -> dict[str, str]:
    design_point = {
        "family": candidate["family"],
        "diag_policy": candidate["diag_policy"],
        "offload_scope": candidate["offload_scope"],
        "resident_policy": candidate["resident_policy"],
        "partition_strategy": candidate.get(
            "partition_strategy",
            default_partition_strategy(
                candidate.get("family"),
                candidate.get("offload_scope"),
            ),
        ),
    }
    candidate_family = candidate.get("candidate_family")
    runtime_projection_family = candidate.get("runtime_projection_family")
    architecture_template_id = candidate.get("architecture_template_id")
    if candidate_family not in (None, "") and (
        str(candidate_family) != str(candidate["family"]) or architecture_template_id not in (None, "")
    ):
        design_point["candidate_family"] = str(candidate_family)
    if runtime_projection_family not in (None, "") and (
        str(runtime_projection_family) != str(candidate["family"]) or "candidate_family" in design_point
    ):
        design_point["runtime_projection_family"] = str(runtime_projection_family)
    if architecture_template_id not in (None, ""):
        design_point["architecture_template_id"] = str(architecture_template_id)
    return design_point


def selected_design_points_for_accurate_layer(
    shortlists: list[dict[str, Any]],
    config: dict[str, Any],
    runner: Any,
) -> list[dict[str, str]]:
    selected: dict[tuple[str, str, str, str, str, str, str, str], dict[str, str]] = {}
    for shortlist in shortlists:
        for role, candidate in (
            ("primary_candidate", shortlist.get("primary_candidate")),
            ("fallback_candidate", shortlist.get("fallback_candidate")),
        ):
            if candidate is not None:
                design_point = candidate_to_design_point(candidate)
                selected.setdefault(
                    selected_design_point_key(design_point),
                    design_point,
                )
        for candidate in shortlist.get("extra_promoted_candidates", []):
            design_point = candidate_to_design_point(candidate)
            selected.setdefault(selected_design_point_key(design_point), design_point)

    if not selected:
        for family in config["scope"]["architecture_families_primary"]:
            profile = runner.FAMILY_PROFILES[family]
            design_point = {
                "family": family,
                "diag_policy": profile["canonical_diag_policy"],
                "offload_scope": profile["canonical_offload_scope"],
                "resident_policy": profile["canonical_resident_policy"],
                "partition_strategy": profile.get(
                    "canonical_partition_strategy", "operator__build__diag__refresh"
                ),
            }
            selected[selected_design_point_key(design_point)] = design_point

    return [selected[key] for key in sorted(selected)]


def selected_design_point_key(
    design_point: dict[str, Any],
) -> tuple[str, str, str, str, str, str, str, str]:
    base_key = design_point_key_from_mapping(design_point)
    return (
        *base_key,
        str(design_point.get("candidate_family") or ""),
        str(design_point.get("runtime_projection_family") or ""),
        str(design_point.get("architecture_template_id") or ""),
    )


def filter_bundle_to_design_points(
    bundle: dict[str, Any],
    selected_design_points: list[dict[str, str]],
    runner: Any,
) -> None:
    bundle["results"] = [
        row
        for row in bundle["results"]
        if any(row_matches_selected_design(row, design_point) for design_point in selected_design_points)
    ]
    bundle["family_summary"] = runner.build_family_summary(bundle["results"])
    refresh_equal_candidate_family_summary(bundle, runner)


def build_accurate_validation_targets(
    shortlists: list[dict[str, Any]],
    accurate_bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    accurate_rows = list(accurate_bundle["results"])
    targets: list[dict[str, Any]] = []

    def note_value(notes: list[str], prefix: str) -> str | None:
        for note in notes:
            if note.startswith(prefix):
                return note.split("=", 1)[1]
        return None

    for shortlist in shortlists:
        source_workload_id = shortlist["workload_id"]
        for role_name, candidate in (
            ("primary_candidate", shortlist.get("primary_candidate")),
            ("fallback_candidate", shortlist.get("fallback_candidate")),
        ):
            if candidate is None:
                continue
            selected_design_point = candidate_to_design_point(candidate)
            accurate_row = next(
                (row for row in accurate_rows if row_matches_selected_design(row, selected_design_point)),
                None,
            )
            if accurate_row is None:
                continue
            correctness_status = accurate_row["correctness"]["status"]
            gold_pass = accurate_row["correctness"]["gold_pass"]
            convergence_comparable_pass = accurate_row["correctness"]["convergence_comparable_pass"]
            required_field_failures = accurate_row["correctness"]["required_field_failures"]
            notes = accurate_row["correctness"].get("notes", [])
            convergence_report_path = note_value(notes, "si8_f1_convergence_report=")
            convergence_summary_path = note_value(notes, "si8_f1_convergence_summary=")
            narrowing_artifact = None
            if convergence_report_path:
                report_path = Path(convergence_report_path)
                if report_path.exists():
                    narrowing_artifact = json.loads(report_path.read_text(encoding="utf-8"))
            recommendation_eligible = bool(gold_pass and convergence_comparable_pass)
            ranking_observation_retained = bool(
                convergence_comparable_pass
                and correctness_status not in BLOCKING_STATUSES
            )
            if recommendation_eligible:
                gate_reason = "accurate_layer_pass"
            elif correctness_status in BLOCKING_STATUSES:
                gate_reason = "accurate_layer_infrastructure_block"
            elif convergence_comparable_pass is False:
                gate_reason = "convergence_not_comparable"
            elif gold_pass is False:
                gate_reason = "gold_mismatch"
            else:
                gate_reason = "accurate_layer_incomplete"
            targets.append(
                {
                    "source_workload_id": source_workload_id,
                    "selection_role": role_name,
                    "fast_layer_result_id": candidate["result_id"],
                    "accurate_layer_result_id": accurate_row["result_id"],
                    "anchor_workload_id": accurate_row["workload"]["workload_id"],
                    "correctness_status": correctness_status,
                    "gold_pass": gold_pass,
                    "convergence_comparable_pass": convergence_comparable_pass,
                    "required_field_failures": required_field_failures,
                    "recommendation_eligible": recommendation_eligible,
                    "ranking_observation_retained": ranking_observation_retained,
                    "gate_reason": gate_reason,
                    "narrowing_report_path": convergence_report_path,
                    "narrowing_summary_path": convergence_summary_path,
                    "dominant_blocker_kind": None
                    if narrowing_artifact is None
                    else narrowing_artifact["dominant_blocker"]["kind"],
                    "explicit_next_narrowing_move": None
                    if narrowing_artifact is None
                    else narrowing_artifact["explicit_next_narrowing_move"],
                    # OBS-derived runtime_observability for shortlist/review narrative
                    "obs_01_time_s": (accurate_row.get("primary_metrics") or {}).get("time_to_convergence_s"),
                    "obs_02_scf_iters": (accurate_row.get("primary_metrics") or {}).get("scf_iterations_to_convergence"),
                    "obs_04_bytes": (accurate_row.get("primary_metrics") or {}).get("bytes_moved_to_convergence"),
                    "obs_05_device_busy_cycles": (accurate_row.get("secondary_metrics") or {}).get("device_busy_ref_cycles"),
                    "obs_06_dma_cycles": (accurate_row.get("secondary_metrics") or {}).get("dma_ref_cycles"),
                    "obs_07_host_assist_cycles": (accurate_row.get("secondary_metrics") or {}).get("host_assist_ref_cycles"),
                    "obs_08_fallback_count": (accurate_row.get("primary_metrics") or {}).get("fallback_count_to_convergence"),
                    "obs_08_fallback_ratio": (accurate_row.get("secondary_metrics") or {}).get("fallback_ratio"),
                    "obs_09_resident_hits": (accurate_row.get("secondary_metrics") or {}).get("resident_reuse_hits"),
                    "obs_10_spill_ratio": (accurate_row.get("secondary_metrics") or {}).get("spill_ratio"),
                    "obs_11_ref_cycles": (accurate_row.get("secondary_metrics") or {}).get("total_ref_cycles"),
                    "obs_12_energy_j": (accurate_row.get("primary_metrics") or {}).get("energy_to_convergence_j"),
                }
            )
        for index, candidate in enumerate(shortlist.get("extra_promoted_candidates", []), start=1):
            selected_design_point = candidate_to_design_point(candidate)
            accurate_row = next(
                (row for row in accurate_rows if row_matches_selected_design(row, selected_design_point)),
                None,
            )
            if accurate_row is None:
                continue
            correctness_status = accurate_row["correctness"]["status"]
            gold_pass = accurate_row["correctness"]["gold_pass"]
            convergence_comparable_pass = accurate_row["correctness"]["convergence_comparable_pass"]
            required_field_failures = accurate_row["correctness"]["required_field_failures"]
            notes = accurate_row["correctness"].get("notes", [])
            convergence_report_path = note_value(notes, "si8_f1_convergence_report=")
            convergence_summary_path = note_value(notes, "si8_f1_convergence_summary=")
            narrowing_artifact = None
            if convergence_report_path:
                report_path = Path(convergence_report_path)
                if report_path.exists():
                    narrowing_artifact = json.loads(report_path.read_text(encoding="utf-8"))
            recommendation_eligible = bool(gold_pass and convergence_comparable_pass)
            ranking_observation_retained = bool(
                convergence_comparable_pass
                and correctness_status not in BLOCKING_STATUSES
            )
            if recommendation_eligible:
                gate_reason = "accurate_layer_pass"
            elif correctness_status in BLOCKING_STATUSES:
                gate_reason = "accurate_layer_infrastructure_block"
            elif convergence_comparable_pass is False:
                gate_reason = "convergence_not_comparable"
            elif gold_pass is False:
                gate_reason = "gold_mismatch"
            else:
                gate_reason = "accurate_layer_incomplete"
            targets.append(
                {
                    "source_workload_id": source_workload_id,
                    "selection_role": f"extra_promoted_candidate_{index}",
                    "fast_layer_result_id": candidate["result_id"],
                    "accurate_layer_result_id": accurate_row["result_id"],
                    "anchor_workload_id": accurate_row["workload"]["workload_id"],
                    "correctness_status": correctness_status,
                    "gold_pass": gold_pass,
                    "convergence_comparable_pass": convergence_comparable_pass,
                    "required_field_failures": required_field_failures,
                    "recommendation_eligible": recommendation_eligible,
                    "ranking_observation_retained": ranking_observation_retained,
                    "gate_reason": gate_reason,
                    "narrowing_report_path": convergence_report_path,
                    "narrowing_summary_path": convergence_summary_path,
                    "dominant_blocker_kind": None
                    if narrowing_artifact is None
                    else narrowing_artifact["dominant_blocker"]["kind"],
                    "explicit_next_narrowing_move": None
                    if narrowing_artifact is None
                    else narrowing_artifact["explicit_next_narrowing_move"],
                    # OBS-derived runtime_observability for shortlist/review narrative
                    "obs_01_time_s": (accurate_row.get("primary_metrics") or {}).get("time_to_convergence_s"),
                    "obs_02_scf_iters": (accurate_row.get("primary_metrics") or {}).get("scf_iterations_to_convergence"),
                    "obs_04_bytes": (accurate_row.get("primary_metrics") or {}).get("bytes_moved_to_convergence"),
                    "obs_05_device_busy_cycles": (accurate_row.get("secondary_metrics") or {}).get("device_busy_ref_cycles"),
                    "obs_06_dma_cycles": (accurate_row.get("secondary_metrics") or {}).get("dma_ref_cycles"),
                    "obs_07_host_assist_cycles": (accurate_row.get("secondary_metrics") or {}).get("host_assist_ref_cycles"),
                    "obs_08_fallback_count": (accurate_row.get("primary_metrics") or {}).get("fallback_count_to_convergence"),
                    "obs_08_fallback_ratio": (accurate_row.get("secondary_metrics") or {}).get("fallback_ratio"),
                    "obs_09_resident_hits": (accurate_row.get("secondary_metrics") or {}).get("resident_reuse_hits"),
                    "obs_10_spill_ratio": (accurate_row.get("secondary_metrics") or {}).get("spill_ratio"),
                    "obs_11_ref_cycles": (accurate_row.get("secondary_metrics") or {}).get("total_ref_cycles"),
                    "obs_12_energy_j": (accurate_row.get("primary_metrics") or {}).get("energy_to_convergence_j"),
                }
            )
    return targets


def summarize_accurate_validation_targets(
    validation_targets: list[dict[str, Any]],
    source_workload_ids: list[str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in validation_targets:
        grouped.setdefault(item["source_workload_id"], []).append(item)

    summaries: list[dict[str, Any]] = []
    ordered_workloads = list(dict.fromkeys(source_workload_ids))
    for source_workload_id in ordered_workloads:
        items = grouped.get(source_workload_id, [])
        eligible = [item for item in items if item["recommendation_eligible"]]
        retained = [item for item in items if item["ranking_observation_retained"]]
        blocked = [item for item in items if not item["recommendation_eligible"]]
        if eligible:
            validation_gate_status = "eligible_candidate_available"
        elif blocked:
            validation_gate_status = "all_candidates_blocked"
        else:
            validation_gate_status = "not_assessed"
        summaries.append(
            {
                "source_workload_id": source_workload_id,
                "validation_target_count": len(items),
                "eligible_candidate_count": len(eligible),
                "ranking_observation_count": len(retained),
                "blocked_candidate_count": len(blocked),
                "validation_gate_status": validation_gate_status,
                "blocked_selection_roles": [item["selection_role"] for item in blocked],
                "gate_reasons": sorted({item["gate_reason"] for item in items}),
            }
        )
    return summaries


def build_stage_recommendation_gate(
    validation_summary_by_source_workload: list[dict[str, Any]],
) -> dict[str, Any]:
    eligible = [
        item
        for item in validation_summary_by_source_workload
        if item["validation_gate_status"] == "eligible_candidate_available"
    ]
    blocked = [
        item
        for item in validation_summary_by_source_workload
        if item["validation_gate_status"] == "all_candidates_blocked"
    ]
    not_assessed = [
        item
        for item in validation_summary_by_source_workload
        if item["validation_gate_status"] == "not_assessed"
    ]
    if validation_summary_by_source_workload and len(eligible) == len(validation_summary_by_source_workload):
        status = "projection_eligible"
    elif blocked:
        status = "blocked_by_accurate_layer"
    else:
        status = "awaiting_accurate_layer"
    return {
        "stage_main_recommendation_status": status,
        "eligible_source_workload_count": len(eligible),
        "blocked_source_workload_count": len(blocked),
        "not_assessed_source_workload_count": len(not_assessed),
        "blocked_source_workloads": [item["source_workload_id"] for item in blocked],
        "not_assessed_source_workloads": [item["source_workload_id"] for item in not_assessed],
    }


def build_public_recommendation_summary(
    shortlists: list[dict[str, Any]],
    validation_summary_by_source_workload: list[dict[str, Any]],
    stage_gate: dict[str, Any],
) -> dict[str, Any]:
    retained_workloads = [
        item["source_workload_id"]
        for item in validation_summary_by_source_workload
        if item["ranking_observation_count"] > 0
    ]
    narrowing_moves = sorted(
        {
            item["next_narrowing_move"]
            for item in shortlists
            if item.get("next_narrowing_move")
        }
    )
    if stage_gate["stage_main_recommendation_status"] == "projection_eligible":
        primary_families = [
            item["primary_candidate"]["family"]
            for item in shortlists
            if item.get("primary_candidate") is not None
        ]
        recommended_family = (
            primary_families[0]
            if primary_families and len(set(primary_families)) == 1
            else "none-yet"
        )
        recommendation_type = "projection-grade"
        projection_reporting_allowed = True
        suppression_reason = "none"
    elif retained_workloads:
        recommended_family = "none-yet"
        recommendation_type = "evidence-incomplete"
        projection_reporting_allowed = False
        suppression_reason = stage_gate["stage_main_recommendation_status"]
    else:
        recommended_family = "none-yet"
        recommendation_type = "evidence-incomplete"
        projection_reporting_allowed = False
        suppression_reason = "awaiting_fast_or_accurate_layer"
    runtime_risk_summary = aggregate_runtime_risk(
        [
            candidate
            for item in shortlists
            for candidate in [
                item.get("primary_candidate"),
                item.get("fallback_candidate"),
                *item.get("extra_promoted_candidates", []),
            ]
            if candidate is not None
        ]
    )
    return {
        "public_recommended_family": recommended_family,
        "public_recommendation_type": recommendation_type,
        "authority_scope": "supporting_evidence_only",
        "authority_notes": [
            "This summary is a non-authoritative narrowing/evidence surface.",
            "The adjudicator memo remains the single top-level decision authority.",
        ],
        "ranking_observations_retained": bool(retained_workloads),
        "ranking_observation_source_workloads": retained_workloads,
        "projection_reporting_allowed": projection_reporting_allowed,
        "suppression_reason": suppression_reason,
        "next_narrowing_moves": narrowing_moves,
        "runtime_risk_summary": runtime_risk_summary,
    }


def build_best_point_summary(
    public_recommendation: dict[str, Any],
    stage_gate: dict[str, Any],
    projection_review: dict[str, Any] | None,
    stage_main_package: dict[str, Any] | None,
) -> dict[str, Any]:
    if stage_main_package is not None:
        best = stage_main_package.get("best_performance_candidate") or {}
        trusted = stage_main_package.get("best_trusted_point") or {}
        return {
            "status": (
                "ready"
                if stage_main_package.get("recommendation_status") == "ready"
                else "incomplete"
            ),
            "source_surface": "stage_main_recommendation_package",
            "stage_main_recommendation_status": stage_main_package.get(
                "stage_main_recommendation_status"
            ),
            "public_recommended_family": public_recommendation.get(
                "public_recommended_family"
            ),
            "recommendation_family": stage_main_package.get("recommended_family"),
            "trusted_family": trusted.get("recommended_family"),
            "performance_family": best.get("family"),
            "supported_source_workloads": stage_main_package.get(
                "supported_source_workloads", []
            ),
            "projection_reporting_allowed": stage_main_package.get(
                "projection_reporting_allowed"
            ),
            "recommendation_type": stage_main_package.get("recommendation_type"),
            "runtime_risk_overall": (
                (stage_main_package.get("runtime_risk_summary") or {}).get(
                    "overall_runtime_risk"
                )
            ),
            "best_point_fast_layer_result_id": best.get("fast_layer_result_id"),
            "best_point_accurate_layer_result_id": best.get(
                "accurate_layer_result_id"
            ),
            "best_point_time_to_convergence_s": best.get("time_to_convergence_s"),
            "best_point_energy_to_convergence_j": best.get(
                "energy_to_convergence_j"
            ),
            "best_point_avg_system_power_proxy_w": best.get(
                "avg_system_power_proxy_w"
            ),
            "best_point_runtime_risk_level": best.get("runtime_risk_level"),
            "best_point_runtime_risk_score": best.get("runtime_risk_score"),
            "best_point_graph_topology_summary": best.get("graph_topology_summary"),
            "best_point_graph_execution_plan_summary": best.get(
                "graph_execution_plan_summary"
            ),
            "best_point_graph_component_driver_summary": best.get(
                "graph_component_driver_summary"
            ),
            "next_action": stage_main_package.get("next_action"),
        }
    if projection_review is not None:
        return {
            "status": (
                "projection_review_ready"
                if projection_review.get("review_readiness") == "ready"
                else "projection_review_incomplete"
            ),
            "source_surface": "projection_review",
            "stage_main_recommendation_status": stage_gate.get(
                "stage_main_recommendation_status"
            ),
            "public_recommended_family": public_recommendation.get(
                "public_recommended_family"
            ),
            "recommendation_family": public_recommendation.get(
                "public_recommended_family"
            ),
            "trusted_family": None,
            "performance_family": None,
            "supported_source_workloads": projection_review.get(
                "promoted_source_workloads", []
            ),
            "projection_reporting_allowed": public_recommendation.get(
                "projection_reporting_allowed"
            ),
            "recommendation_type": public_recommendation.get(
                "public_recommendation_type"
            ),
            "runtime_risk_overall": (
                (projection_review.get("runtime_risk_summary") or {}).get(
                    "overall_runtime_risk"
                )
            ),
            "best_point_fast_layer_result_id": None,
            "best_point_accurate_layer_result_id": None,
            "best_point_time_to_convergence_s": None,
            "best_point_energy_to_convergence_j": None,
            "best_point_avg_system_power_proxy_w": None,
            "best_point_runtime_risk_level": None,
            "best_point_runtime_risk_score": None,
            "best_point_graph_topology_summary": None,
            "best_point_graph_execution_plan_summary": None,
            "best_point_graph_component_driver_summary": None,
            "next_action": projection_review.get("next_action"),
        }
    return {
        "status": stage_gate.get("stage_main_recommendation_status"),
        "source_surface": "public_recommendation",
        "stage_main_recommendation_status": stage_gate.get(
            "stage_main_recommendation_status"
        ),
        "public_recommended_family": public_recommendation.get(
            "public_recommended_family"
        ),
        "recommendation_family": public_recommendation.get(
            "public_recommended_family"
        ),
        "trusted_family": None,
        "performance_family": None,
        "supported_source_workloads": public_recommendation.get(
            "ranking_observation_source_workloads", []
        ),
        "projection_reporting_allowed": public_recommendation.get(
            "projection_reporting_allowed"
        ),
        "recommendation_type": public_recommendation.get(
            "public_recommendation_type"
        ),
        "runtime_risk_overall": (
            (public_recommendation.get("runtime_risk_summary") or {}).get(
                "overall_runtime_risk"
            )
        ),
        "best_point_fast_layer_result_id": None,
        "best_point_accurate_layer_result_id": None,
        "best_point_time_to_convergence_s": None,
        "best_point_energy_to_convergence_j": None,
        "best_point_avg_system_power_proxy_w": None,
        "best_point_runtime_risk_level": None,
        "best_point_runtime_risk_score": None,
        "best_point_graph_topology_summary": None,
        "best_point_graph_execution_plan_summary": None,
        "best_point_graph_component_driver_summary": None,
        "next_action": (
            " | ".join(public_recommendation.get("next_narrowing_moves", []))
            if public_recommendation.get("next_narrowing_moves")
            else None
        ),
    }


def build_projection_review_summary(
    shortlists: list[dict[str, Any]],
    stage_gate: dict[str, Any],
    public_recommendation: dict[str, Any],
) -> dict[str, Any] | None:
    if stage_gate["stage_main_recommendation_status"] != "projection_eligible":
        return None

    promoted_candidates: list[dict[str, Any]] = []
    for shortlist in shortlists:
        candidate_slots = [
            ("primary_candidate", shortlist.get("primary_candidate")),
            ("fallback_candidate", shortlist.get("fallback_candidate")),
        ]
        candidate_slots.extend(
            [
                ("extra_promoted_candidate", candidate)
                for candidate in shortlist.get("extra_promoted_candidates", [])
            ]
        )
        for selection_role, candidate in candidate_slots:
            if candidate is None or not candidate.get("recommendation_eligible"):
                continue
            risk = candidate_runtime_risk_fields(candidate)
            graph = candidate.get("graph_evidence")
            promoted_candidates.append(
                {
                    "source_workload_id": shortlist["workload_id"],
                    "source_workload_label": shortlist["workload_label"],
                    "signature_id": candidate.get("signature_id"),
                    "selection_role": selection_role,
                    "fast_layer_result_id": candidate["result_id"],
                    "accurate_layer_result_id": candidate.get("accurate_layer_result_id"),
                    "family": candidate["family"],
                    "diag_policy": candidate["diag_policy"],
                    "offload_scope": candidate["offload_scope"],
                    "resident_policy": candidate["resident_policy"],
                    "partition_strategy": candidate.get(
                        "partition_strategy",
                        default_partition_strategy(
                            candidate.get("family"),
                            candidate.get("offload_scope"),
                        ),
                    ),
                    "time_to_convergence_s": candidate.get("time_to_convergence_s"),
                    "energy_to_convergence_j": candidate.get("energy_to_convergence_j"),
                    "avg_system_power_proxy_w": candidate.get("avg_system_power_proxy_w"),
                    "bytes_moved_to_convergence": candidate.get("bytes_moved_to_convergence"),
                    "fallback_ratio": candidate.get("fallback_ratio"),
                    "spill_ratio": candidate.get("spill_ratio"),
                    "runtime_observability": candidate.get("runtime_observability"),
                    "runtime_risk_score": risk["runtime_risk_score"],
                    "runtime_risk_level": risk["runtime_risk_level"],
                    "runtime_risk_reasons": risk["runtime_risk_reasons"],
                    "graph_evidence": graph,
                    "graph_evidence_path": candidate.get("graph_evidence_path"),
                    **graph_runtime_evidence_fields(graph),
                    "correctness_status": candidate.get("correctness_status"),
                    "gold_pass": candidate.get("gold_pass"),
                    "convergence_comparable_pass": candidate.get("convergence_comparable_pass"),
                    "gate_reason": candidate.get("gate_reason"),
                    "narrowing_report_path": candidate.get("narrowing_report_path"),
                    "narrowing_summary_path": candidate.get("narrowing_summary_path"),
                }
            )

    runtime_risk_summary = aggregate_runtime_risk(promoted_candidates)
    return {
        "package_kind": "qe_next_stage_projection_review_v0",
        "stage_main_recommendation_status": stage_gate["stage_main_recommendation_status"],
        "public_recommended_family": public_recommendation["public_recommended_family"],
        "public_recommendation_type": public_recommendation["public_recommendation_type"],
        "projection_reporting_allowed": public_recommendation["projection_reporting_allowed"],
        "promoted_candidate_count": len(promoted_candidates),
        "promoted_source_workloads": [
            item["source_workload_id"]
            for item in promoted_candidates
        ],
        "recommended_validated_candidates": promoted_candidates,
        "runtime_risk_summary": runtime_risk_summary,
        "review_readiness": "ready" if promoted_candidates else "incomplete",
        "next_action": (
            "Prepare the projection-grade recommendation review package from the "
            "accurate-layer-passing shortlisted candidate(s)."
        ),
    }


def render_projection_review_md(review: dict[str, Any]) -> str:
    component_registry_summary = review.get("component_registry_summary")
    family_counts: dict[str, int] = {}
    for candidate in review.get("recommended_validated_candidates", []):
        family = str(candidate.get("family") or "unknown")
        family_counts[family] = family_counts.get(family, 0) + 1
    lines = [
        "# QE Next-Stage Projection Review Package",
        "",
        f"- package_kind: `{review['package_kind']}`",
        f"- stage_main_recommendation_status: `{review['stage_main_recommendation_status']}`",
        f"- public_recommended_family: `{review['public_recommended_family']}`",
        f"- public_recommendation_type: `{review['public_recommendation_type']}`",
        f"- projection_reporting_allowed: `{review['projection_reporting_allowed']}`",
        f"- promoted_candidate_count: `{review['promoted_candidate_count']}`",
        f"- promoted_source_workloads: `{', '.join(review['promoted_source_workloads']) if review['promoted_source_workloads'] else '—'}`",
        f"- review_readiness: `{review['review_readiness']}`",
        f"- runtime_risk_overall: `{review['runtime_risk_summary']['overall_runtime_risk']}`",
        f"- runtime_risk_counts: `{json.dumps(review['runtime_risk_summary']['counts'], ensure_ascii=False)}`",
        f"- family_candidate_counts: `{json.dumps(family_counts, ensure_ascii=False)}`",
    ]
    if component_registry_summary is not None:
        lines.extend(
            [
                f"- component_registry_path: `{review.get('component_registry_path') or '—'}`",
                f"- component_registry_strict_pass: `{component_registry_summary['all_strict_checks_pass']}`",
                f"- component_registry_component_count: `{component_registry_summary['component_count']}`",
                f"- component_registry_future_expansion_candidate_count: `{component_registry_summary['future_catalog_expansion_candidate_count']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Recommended validated candidates",
            "",
            "| Source workload | signature_id | Selection role | Family | partition_strategy | graph_seed | Fast-layer result | Accurate-layer result | time_to_convergence_s | energy_to_convergence_j | avg_system_power_proxy_w | gold_pass | convergence_comparable_pass | runtime risk | runtime note |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if review["recommended_validated_candidates"]:
        for candidate in review["recommended_validated_candidates"]:
            runtime_note = runtime_observability_summary(candidate.get("runtime_observability")) or "—"
            runtime_risk = (
                f"{candidate.get('runtime_risk_level')}[{candidate.get('runtime_risk_score')}]"
                if candidate.get("runtime_risk_level") not in (None, "unknown")
                else "—"
            )
            graph_seed = ((candidate.get("graph_evidence") or {}).get("seed_template_id")) or "—"
            graph_path = candidate.get("graph_evidence_path") or "—"
            lines.append(
                f"| {candidate['source_workload_id']} | {candidate['signature_id']} | {candidate['selection_role']} | "
                f"{candidate['family']} | {candidate['partition_strategy']} | {graph_seed} | {candidate['fast_layer_result_id']} | "
                f"{candidate['accurate_layer_result_id']} | {candidate['time_to_convergence_s']} | "
                f"{candidate['energy_to_convergence_j']} | {candidate.get('avg_system_power_proxy_w')} | {candidate['gold_pass']} | "
                f"{candidate['convergence_comparable_pass']} | {runtime_risk} | {runtime_note} |"
            )
            lines.append(f"  - graph_evidence_path: `{graph_path}`")
            execution_plan_note = candidate.get("graph_execution_plan_summary")
            if execution_plan_note is not None:
                lines.append(f"  - graph_execution_plan: `{execution_plan_note}`")
            topology_note = graph_topology_summary(candidate.get("graph_evidence"))
            if topology_note is not None:
                lines.append(f"  - graph_topology: `{topology_note}`")
            component_note = graph_component_driver_summary(candidate.get("graph_evidence"))
            if component_note is not None:
                lines.append(f"  - graph_components: `{component_note}`")
    else:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | — | — | — |")
    lines.extend(["", "## Next action", "", review["next_action"], ""])
    return "\n".join(lines)


def choose_best_performance_candidate(
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    comparable = [
        candidate
        for candidate in candidates
        if candidate.get("time_to_convergence_s") is not None
    ]
    if not comparable:
        return None
    best = min(
        comparable,
        key=lambda candidate: (
            candidate["time_to_convergence_s"],
            candidate.get("energy_to_convergence_j")
            if candidate.get("energy_to_convergence_j") is not None
            else float("inf"),
            candidate_runtime_risk_fields(candidate)["runtime_risk_score"],
            candidate.get("fast_layer_result_id", ""),
        ),
    )
    risk = candidate_runtime_risk_fields(best)
    graph = best.get("graph_evidence")
    return {
        "signature_id": best.get("signature_id"),
        "source_workload_id": best.get("source_workload_id"),
        "selection_role": best.get("selection_role"),
        "family": best.get("family"),
        "diag_policy": best.get("diag_policy"),
        "offload_scope": best.get("offload_scope"),
        "resident_policy": best.get("resident_policy"),
        "partition_strategy": best.get("partition_strategy"),
        "fast_layer_result_id": best.get("fast_layer_result_id"),
        "accurate_layer_result_id": best.get("accurate_layer_result_id"),
        "time_to_convergence_s": best.get("time_to_convergence_s"),
        "energy_to_convergence_j": best.get("energy_to_convergence_j"),
        "avg_system_power_proxy_w": best.get("avg_system_power_proxy_w"),
        "runtime_observability": best.get("runtime_observability"),
        "runtime_risk_score": risk["runtime_risk_score"],
        "runtime_risk_level": risk["runtime_risk_level"],
        "runtime_risk_reasons": risk["runtime_risk_reasons"],
        "graph_evidence": graph,
        "graph_evidence_path": best.get("graph_evidence_path"),
        **graph_runtime_evidence_fields(graph),
    }


def relative_relation_label(
    reference: float | None,
    candidate: float | None,
    *,
    invert_better: bool = False,
) -> str:
    if reference is None or candidate is None:
        return "unknown"
    if abs(candidate - reference) <= 1e-12:
        return "equal"
    if invert_better:
        return "higher" if candidate > reference else "lower"
    return "faster" if candidate < reference else "slower"


def runtime_risk_relation_label(
    reference_score: int | None,
    candidate_score: int | None,
) -> str:
    if reference_score is None or candidate_score is None:
        return "unknown"
    if candidate_score == reference_score:
        return "equal"
    return "higher" if candidate_score > reference_score else "lower"


def build_why_not_other_families_notes(
    recommended_primary_candidates: list[dict[str, Any]],
    validated_alternative_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    primary_by_source = {
        candidate["source_workload_id"]: candidate for candidate in recommended_primary_candidates
    }
    notes: list[dict[str, Any]] = []
    for alternative in validated_alternative_candidates:
        source_workload_id = alternative["source_workload_id"]
        baseline = primary_by_source.get(source_workload_id)
        if baseline is None:
            continue
        time_margin = relative_margin(
            baseline.get("time_to_convergence_s"),
            alternative.get("time_to_convergence_s"),
        )
        energy_margin = relative_margin(
            baseline.get("energy_to_convergence_j"),
            alternative.get("energy_to_convergence_j"),
        )
        time_relation = relative_relation_label(
            baseline.get("time_to_convergence_s"),
            alternative.get("time_to_convergence_s"),
        )
        energy_relation = relative_relation_label(
            baseline.get("energy_to_convergence_j"),
            alternative.get("energy_to_convergence_j"),
        )
        risk_relation = runtime_risk_relation_label(
            baseline.get("runtime_risk_score"),
            alternative.get("runtime_risk_score"),
        )
        note_parts = []
        if time_relation != "unknown":
            note_parts.append(f"time={time_relation}")
        if time_margin is not None:
            note_parts.append(f"time_margin={time_margin:.3f}")
        if energy_relation != "unknown":
            note_parts.append(f"energy={energy_relation}")
        if energy_margin is not None:
            note_parts.append(f"energy_margin={energy_margin:.3f}")
        if risk_relation != "unknown":
            note_parts.append(f"risk={risk_relation}")
        alt_graph = graph_component_driver_summary(alternative.get("graph_evidence"))
        if alt_graph:
            note_parts.append(f"alt_graph={alt_graph}")
        baseline_graph = graph_component_driver_summary(baseline.get("graph_evidence"))
        if baseline_graph:
            note_parts.append(f"baseline_graph={baseline_graph}")
        notes.append(
            {
                "source_workload_id": source_workload_id,
                "source_workload_label": alternative.get("source_workload_label"),
                "recommended_family": baseline.get("family"),
                "alternative_family": alternative.get("family"),
                "selection_role": alternative.get("selection_role"),
                "baseline_fast_layer_result_id": baseline.get("fast_layer_result_id"),
                "alternative_fast_layer_result_id": alternative.get("fast_layer_result_id"),
                "time_relation_to_recommended": time_relation,
                "relative_time_margin_to_recommended": time_margin,
                "energy_relation_to_recommended": energy_relation,
                "relative_energy_margin_to_recommended": energy_margin,
                "runtime_risk_relation_to_recommended": risk_relation,
                "recommended_runtime_risk_level": baseline.get("runtime_risk_level"),
                "alternative_runtime_risk_level": alternative.get("runtime_risk_level"),
                "recommended_graph_topology": graph_topology_summary(baseline.get("graph_evidence")),
                "alternative_graph_topology": graph_topology_summary(alternative.get("graph_evidence")),
                "recommended_graph_components": baseline_graph,
                "alternative_graph_components": alt_graph,
                "why_not_summary": " | ".join(note_parts) if note_parts else "no_comparison_summary",
            }
        )
    return notes


def build_stage_main_recommendation_package(
    shortlists: list[dict[str, Any]],
    stage_gate: dict[str, Any],
    public_recommendation: dict[str, Any],
) -> dict[str, Any] | None:
    recommended_family = public_recommendation["public_recommended_family"]
    if (
        stage_gate["stage_main_recommendation_status"] != "projection_eligible"
        or recommended_family == "none-yet"
    ):
        return None

    recommended_primary_candidates: list[dict[str, Any]] = []
    validated_alternative_candidates: list[dict[str, Any]] = []
    for shortlist in shortlists:
        primary = shortlist.get("primary_candidate")
        if primary is not None and primary.get("recommendation_eligible"):
            primary_risk = candidate_runtime_risk_fields(primary)
            primary_graph = primary.get("graph_evidence")
            candidate_payload = {
                "source_workload_id": shortlist["workload_id"],
                "source_workload_label": shortlist["workload_label"],
                "signature_id": primary.get("signature_id"),
                "selection_role": "primary_candidate",
                "fast_layer_result_id": primary["result_id"],
                "accurate_layer_result_id": primary.get("accurate_layer_result_id"),
                "family": primary["family"],
                "diag_policy": primary["diag_policy"],
                "offload_scope": primary["offload_scope"],
                "resident_policy": primary["resident_policy"],
                "partition_strategy": primary.get(
                    "partition_strategy",
                    default_partition_strategy(
                        primary.get("family"),
                        primary.get("offload_scope"),
                    ),
                ),
                "time_to_convergence_s": primary.get("time_to_convergence_s"),
                "energy_to_convergence_j": primary.get("energy_to_convergence_j"),
                "avg_system_power_proxy_w": primary.get("avg_system_power_proxy_w"),
                "runtime_observability": primary.get("runtime_observability"),
                "runtime_risk_score": primary_risk["runtime_risk_score"],
                "runtime_risk_level": primary_risk["runtime_risk_level"],
                "runtime_risk_reasons": primary_risk["runtime_risk_reasons"],
                "graph_evidence": primary_graph,
                "graph_evidence_path": primary.get("graph_evidence_path"),
                **graph_runtime_evidence_fields(primary_graph),
                "correctness_status": primary.get("correctness_status"),
                "gold_pass": primary.get("gold_pass"),
                "convergence_comparable_pass": primary.get("convergence_comparable_pass"),
                "gate_reason": primary.get("gate_reason"),
            }
            if primary["family"] == recommended_family:
                recommended_primary_candidates.append(candidate_payload)
            else:
                validated_alternative_candidates.append(candidate_payload)

        for selection_role, candidate in (
            ("fallback_candidate", shortlist.get("fallback_candidate")),
            *[
                ("extra_promoted_candidate", candidate)
                for candidate in shortlist.get("extra_promoted_candidates", [])
            ],
        ):
            if candidate is None or not candidate.get("recommendation_eligible"):
                continue
            candidate_risk = candidate_runtime_risk_fields(candidate)
            graph = candidate.get("graph_evidence")
            validated_alternative_candidates.append(
                {
                    "source_workload_id": shortlist["workload_id"],
                    "source_workload_label": shortlist["workload_label"],
                    "signature_id": candidate.get("signature_id"),
                    "selection_role": selection_role,
                    "fast_layer_result_id": candidate["result_id"],
                    "accurate_layer_result_id": candidate.get("accurate_layer_result_id"),
                    "family": candidate["family"],
                    "diag_policy": candidate["diag_policy"],
                    "offload_scope": candidate["offload_scope"],
                    "resident_policy": candidate["resident_policy"],
                    "partition_strategy": candidate.get(
                        "partition_strategy",
                        default_partition_strategy(
                            candidate.get("family"),
                            candidate.get("offload_scope"),
                        ),
                    ),
                    "time_to_convergence_s": candidate.get("time_to_convergence_s"),
                    "energy_to_convergence_j": candidate.get("energy_to_convergence_j"),
                    "avg_system_power_proxy_w": candidate.get("avg_system_power_proxy_w"),
                    "runtime_observability": candidate.get("runtime_observability"),
                    "runtime_risk_score": candidate_risk["runtime_risk_score"],
                    "runtime_risk_level": candidate_risk["runtime_risk_level"],
                    "runtime_risk_reasons": candidate_risk["runtime_risk_reasons"],
                    "graph_evidence": graph,
                    "graph_evidence_path": candidate.get("graph_evidence_path"),
                    **graph_runtime_evidence_fields(graph),
                    "correctness_status": candidate.get("correctness_status"),
                    "gold_pass": candidate.get("gold_pass"),
                    "convergence_comparable_pass": candidate.get("convergence_comparable_pass"),
                    "gate_reason": candidate.get("gate_reason"),
                }
            )

    supported_source_workloads = [
        item["source_workload_id"] for item in recommended_primary_candidates
    ]
    all_validated_candidates = recommended_primary_candidates + validated_alternative_candidates
    best_performance_candidate = choose_best_performance_candidate(all_validated_candidates)
    runtime_risk_summary = aggregate_runtime_risk(all_validated_candidates)
    why_not_other_families = build_why_not_other_families_notes(
        recommended_primary_candidates,
        validated_alternative_candidates,
    )
    return {
        "package_kind": "qe_next_stage_stage_main_recommendation_v0",
        "stage_main_recommendation_status": stage_gate["stage_main_recommendation_status"],
        "recommendation_status": "ready" if recommended_primary_candidates else "incomplete",
        "recommended_family": recommended_family,
        "recommendation_type": public_recommendation["public_recommendation_type"],
        "authority_scope": "supporting_evidence_only",
        "authority_notes": [
            "This package is an evidence package for later adjudication and release review.",
            "It must not be treated as a parallel top-level decision authority.",
        ],
        "projection_reporting_allowed": public_recommendation["projection_reporting_allowed"],
        "supported_source_workloads": supported_source_workloads,
        "recommended_primary_candidate_count": len(recommended_primary_candidates),
        "validated_alternative_candidate_count": len(validated_alternative_candidates),
        "recommended_primary_candidates": recommended_primary_candidates,
        "validated_alternative_candidates": validated_alternative_candidates,
        "why_not_other_families": why_not_other_families,
        "best_trusted_point": {
            "recommended_family": recommended_family,
            "supported_source_workloads": supported_source_workloads,
            "recommended_primary_candidate_count": len(recommended_primary_candidates),
        },
        "best_performance_candidate": best_performance_candidate,
        "runtime_risk_summary": runtime_risk_summary,
        "claim_discipline": {
            "evidence_tier": "projection-grade",
            "grounded_from_accurate_layer": True,
            "ranking_observations_retained": public_recommendation["ranking_observations_retained"],
        },
        "next_action": (
            "Use the recommended family and its accurate-layer-passing primary candidates as "
            "the stage-main recommendation package, while retaining validated alternatives for "
            "why-not-other-families and risk discussion."
        ),
    }


def render_stage_main_recommendation_md(package: dict[str, Any]) -> str:
    component_registry_summary = package.get("component_registry_summary")
    lines = [
        "# QE Next-Stage Stage-Main Recommendation Package",
        "",
        f"- package_kind: `{package['package_kind']}`",
        f"- stage_main_recommendation_status: `{package['stage_main_recommendation_status']}`",
        f"- recommendation_status: `{package['recommendation_status']}`",
        f"- recommended_family: `{package['recommended_family']}`",
        f"- recommendation_type: `{package['recommendation_type']}`",
        f"- projection_reporting_allowed: `{package['projection_reporting_allowed']}`",
        f"- supported_source_workloads: `{', '.join(package['supported_source_workloads']) if package['supported_source_workloads'] else '—'}`",
        f"- recommended_primary_candidate_count: `{package['recommended_primary_candidate_count']}`",
        f"- validated_alternative_candidate_count: `{package['validated_alternative_candidate_count']}`",
        f"- runtime_risk_overall: `{package['runtime_risk_summary']['overall_runtime_risk']}`",
        f"- runtime_risk_counts: `{json.dumps(package['runtime_risk_summary']['counts'], ensure_ascii=False)}`",
    ]
    if component_registry_summary is not None:
        lines.extend(
            [
                f"- component_registry_path: `{package.get('component_registry_path') or '—'}`",
                f"- component_registry_strict_pass: `{component_registry_summary['all_strict_checks_pass']}`",
                f"- component_registry_component_count: `{component_registry_summary['component_count']}`",
                f"- component_registry_future_expansion_candidate_count: `{component_registry_summary['future_catalog_expansion_candidate_count']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Best trusted point",
            "",
            f"- recommended_family: `{package['best_trusted_point']['recommended_family']}`",
            f"- supported_source_workloads: `{', '.join(package['best_trusted_point']['supported_source_workloads']) if package['best_trusted_point']['supported_source_workloads'] else '—'}`",
            f"- recommended_primary_candidate_count: `{package['best_trusted_point']['recommended_primary_candidate_count']}`",
            "",
            "## Best performance candidate",
            "",
        ]
    )
    best_performance_candidate = package.get("best_performance_candidate")
    if best_performance_candidate is None:
        lines.extend(["- `none`", ""])
    else:
        lines.extend(
            [
                f"- signature_id: `{best_performance_candidate['signature_id']}`",
                f"- source_workload_id: `{best_performance_candidate['source_workload_id']}`",
                f"- selection_role: `{best_performance_candidate['selection_role']}`",
                f"- family: `{best_performance_candidate['family']}`",
                f"- diag_policy: `{best_performance_candidate['diag_policy']}`",
                f"- offload_scope: `{best_performance_candidate['offload_scope']}`",
                f"- resident_policy: `{best_performance_candidate['resident_policy']}`",
                f"- partition_strategy: `{best_performance_candidate['partition_strategy']}`",
                f"- fast_layer_result_id: `{best_performance_candidate['fast_layer_result_id']}`",
                f"- accurate_layer_result_id: `{best_performance_candidate['accurate_layer_result_id']}`",
                f"- time_to_convergence_s: `{best_performance_candidate['time_to_convergence_s']}`",
                f"- energy_to_convergence_j: `{best_performance_candidate['energy_to_convergence_j']}`",
                f"- avg_system_power_proxy_w: `{best_performance_candidate.get('avg_system_power_proxy_w')}`",
                f"- runtime_risk: `{best_performance_candidate.get('runtime_risk_level')}[{best_performance_candidate.get('runtime_risk_score')}]`",
                f"- runtime: `{runtime_observability_summary(best_performance_candidate.get('runtime_observability')) or '—'}`",
                f"- graph_evidence_path: `{best_performance_candidate.get('graph_evidence_path') or '—'}`",
            ]
        )
        execution_plan_note = best_performance_candidate.get("graph_execution_plan_summary")
        if execution_plan_note is not None:
            lines.append(f"- graph_execution_plan: `{execution_plan_note}`")
        topology_note = graph_topology_summary(best_performance_candidate.get("graph_evidence"))
        if topology_note is not None:
            lines.append(f"- graph_topology: `{topology_note}`")
        component_note = graph_component_driver_summary(best_performance_candidate.get("graph_evidence"))
        if component_note is not None:
            lines.append(f"- graph_components: `{component_note}`")
        lines.append("")
    lines.extend(
        [
            "## Recommended primary candidates",
            "",
            "| Source workload | signature_id | Family | partition_strategy | graph_seed | Fast-layer result | Accurate-layer result | time_to_convergence_s | energy_to_convergence_j | avg_system_power_proxy_w |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if package["recommended_primary_candidates"]:
        for candidate in package["recommended_primary_candidates"]:
            graph_seed = ((candidate.get("graph_evidence") or {}).get("seed_template_id")) or "—"
            lines.append(
                f"| {candidate['source_workload_id']} | {candidate['signature_id']} | {candidate['family']} | {candidate['partition_strategy']} | {graph_seed} | {candidate['fast_layer_result_id']} | {candidate['accurate_layer_result_id']} | {candidate['time_to_convergence_s']} | {candidate['energy_to_convergence_j']} | {candidate.get('avg_system_power_proxy_w')} |"
            )
    else:
        lines.append("| — | — | — | — | — | — | — | — | — |")
    lines.extend(
        [
            "",
            "## Validated alternatives",
            "",
            "| Source workload | signature_id | Selection role | Family | partition_strategy | graph_seed | Fast-layer result | Accurate-layer result | gold_pass | convergence_comparable_pass |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if package["validated_alternative_candidates"]:
        for candidate in package["validated_alternative_candidates"]:
            graph_seed = ((candidate.get("graph_evidence") or {}).get("seed_template_id")) or "—"
            lines.append(
                f"| {candidate['source_workload_id']} | {candidate['signature_id']} | {candidate['selection_role']} | {candidate['family']} | {candidate['partition_strategy']} | {graph_seed} | {candidate['fast_layer_result_id']} | {candidate['accurate_layer_result_id']} | {candidate['gold_pass']} | {candidate['convergence_comparable_pass']} |"
            )
    else:
        lines.append("| — | — | — | — | — | — | — | — | — | — |")
    why_not_notes = package.get("why_not_other_families") or []
    lines.extend(["", "## Why not other families", ""])
    if why_not_notes:
        lines.extend(
            [
                "| Source workload | Recommended | Alternative | Selection role | Time relation | Energy relation | Runtime risk relation | Why-not summary |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in why_not_notes:
            lines.append(
                f"| {item['source_workload_id']} | {item['recommended_family']} | {item['alternative_family']} | "
                f"{item['selection_role']} | {item['time_relation_to_recommended']} | "
                f"{item['energy_relation_to_recommended']} | {item['runtime_risk_relation_to_recommended']} | "
                f"{item['why_not_summary']} |"
            )
    else:
        lines.append("- `none`")
    lines.extend(["", "## Next action", "", package["next_action"], ""])
    return "\n".join(lines)


def summarize_accurate_coverage_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    rows = list(bundle.get("results", []))
    passed = [row for row in rows if row["correctness"]["gold_pass"] is True]
    mismatched = [row for row in rows if row["correctness"]["status"] == "mismatch"]
    return {
        "coverage_workload_count": len({row["workload"]["workload_id"] for row in rows}),
        "coverage_result_count": len(rows),
        "coverage_pass_count": len(passed),
        "coverage_mismatch_count": len(mismatched),
        "coverage_ready": bool(rows) and len(passed) == len(rows),
    }


def summarize_generalization_coverage_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    rows = list(bundle.get("results", []))
    passed = [row for row in rows if row["correctness"]["gold_pass"] is True]
    mismatched = [row for row in rows if row["correctness"]["status"] == "mismatch"]
    return {
        "generalization_workload_count": len({row["workload"]["workload_id"] for row in rows}),
        "generalization_result_count": len(rows),
        "generalization_pass_count": len(passed),
        "generalization_mismatch_count": len(mismatched),
        "generalization_ready": bool(rows) and len(passed) == len(rows),
    }


def build_stage_artifact_bundle_manifest(
    *,
    phase_id: str,
    phase_config_path: str,
    execute_model: bool,
    source_kind: str,
    fast_info: dict[str, Any],
    accurate_info: dict[str, Any],
    accurate_coverage_info: dict[str, Any] | None,
    accurate_coverage_summary: dict[str, Any] | None,
    generalization_coverage_info: dict[str, Any] | None,
    generalization_coverage_summary: dict[str, Any] | None,
    gpu_annex_summary: dict[str, Any] | None,
    phase1_evidence_closure: dict[str, Any] | None,
    stage_gate: dict[str, Any],
    public_recommendation: dict[str, Any],
    projection_review: dict[str, Any] | None,
    stage_main_package: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if stage_main_package is None:
        return None

    projection_ready = (
        projection_review is not None and projection_review.get("review_readiness") == "ready"
    )
    stage_main_ready = stage_main_package.get("recommendation_status") == "ready"
    coverage_ready = (
        accurate_coverage_summary is None or accurate_coverage_summary.get("coverage_ready") is True
    )
    bundle_readiness = (
        "ready"
        if stage_gate["stage_main_recommendation_status"] == "projection_eligible"
        and projection_ready
        and stage_main_ready
        and coverage_ready
        else "incomplete"
    )
    return {
        "package_kind": "qe_next_stage_artifact_bundle_manifest_v0",
        "phase_id": phase_id,
        "phase_config_path": phase_config_path,
        "execute_model": execute_model,
        "source_kind": source_kind,
        "stage_main_recommendation_status": stage_gate["stage_main_recommendation_status"],
        "public_recommended_family": public_recommendation["public_recommended_family"],
        "public_recommendation_type": public_recommendation["public_recommendation_type"],
        "authority_scope": "supporting_evidence_only",
        "authority_notes": [
            "This manifest is the top-level release evidence entrypoint for the phase bundle, not the final decision authority.",
            "The adjudicator memo remains the only top-level decision authority.",
        ],
        "bundle_readiness": bundle_readiness,
        "release_ready_recommendation": bundle_readiness == "ready",
        "recommended_primary_candidate_count": stage_main_package.get(
            "recommended_primary_candidate_count", 0
        ),
        "validated_alternative_candidate_count": stage_main_package.get(
            "validated_alternative_candidate_count", 0
        ),
        "projection_review_candidate_count": (
            0 if projection_review is None else projection_review.get("promoted_candidate_count", 0)
        ),
        "accurate_coverage_summary": accurate_coverage_summary,
        "generalization_coverage_summary": generalization_coverage_summary,
        "gpu_annex_summary": gpu_annex_summary,
        "phase1_evidence_closure_summary": None
        if phase1_evidence_closure is None
        else phase1_evidence_closure["summary"],
        "artifact_paths": {
            "fast_layer_json": fast_info["json_path"],
            "fast_layer_csv": fast_info["csv_path"],
            "accurate_layer_json": accurate_info["json_path"],
            "accurate_layer_csv": accurate_info["csv_path"],
            "accurate_coverage_json": None if accurate_coverage_info is None else accurate_coverage_info["json_path"],
            "accurate_coverage_csv": None if accurate_coverage_info is None else accurate_coverage_info["csv_path"],
            "generalization_coverage_json": None if generalization_coverage_info is None else generalization_coverage_info["json_path"],
            "generalization_coverage_csv": None if generalization_coverage_info is None else generalization_coverage_info["csv_path"],
            "gpu_annex_json": None,
            "gpu_annex_md": None,
            "gpu_case_decision_sheet_json": None,
            "gpu_case_decision_sheet_md": None,
            "gpu_workload_group_manifest_json": None,
            "gpu_workload_group_manifest_md": None,
            "phase1_evidence_closure_json": None if phase1_evidence_closure is None else phase1_evidence_closure["json_path"],
            "phase1_evidence_closure_md": None if phase1_evidence_closure is None else phase1_evidence_closure["md_path"],
            "phase_summary_json": None,
            "phase_summary_md": None,
            "projection_review_json": None if projection_review is None else projection_review["json_path"],
            "projection_review_md": None if projection_review is None else projection_review["md_path"],
            "stage_main_recommendation_json": stage_main_package["json_path"],
            "stage_main_recommendation_md": stage_main_package["md_path"],
            "advisor_pack_json": None,
            "advisor_pack_md": None,
            "release_evidence_json": None,
            "release_evidence_md": None,
        },
        "next_action": stage_main_package["next_action"],
    }


def build_advisor_pack_summary(
    *,
    phase_id: str,
    phase_config_path: str,
    stage_artifact_bundle_manifest: dict[str, Any] | None,
    public_recommendation: dict[str, Any],
    best_point_summary: dict[str, Any],
    gpu_annex_summary: dict[str, Any],
    phase1_evidence_closure: dict[str, Any],
    projection_review: dict[str, Any] | None,
    stage_main_package: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if stage_artifact_bundle_manifest is None or stage_main_package is None:
        return None
    trusted_family = best_point_summary.get("trusted_family")
    performance_family = best_point_summary.get("performance_family")
    divergence = (
        trusted_family is not None
        and performance_family is not None
        and trusted_family != performance_family
    )
    gpu_status = gpu_annex_summary.get("status")
    if gpu_status == "thesis_eligible":
        thesis_claim_status = "gpu_annex_ready_but_not_auto_claimed"
    elif gpu_status == "reference_only":
        thesis_claim_status = "reference_only"
    else:
        thesis_claim_status = "deferred"
    limitations: list[str] = []
    if divergence:
        limitations.append("trusted_family_differs_from_performance_family")
    if gpu_status != "thesis_eligible":
        limitations.append(f"gpu_annex_{gpu_status}")
    phase1_summary = phase1_evidence_closure["summary"]
    if not phase1_summary.get("decisive_lane_closed", False):
        limitations.append(
            f"phase1_evidence_{phase1_summary.get('next_blocker_class', 'unknown')}"
        )
    return {
        "package_kind": "qe_next_stage_advisor_pack_summary_v0",
        "phase_id": phase_id,
        "phase_config_path": phase_config_path,
        "closure_scope": "qe_ic_dse_recommendation_package_only",
        "release_entry_kind": "stage_artifact_bundle_manifest",
        "authority_scope": "supporting_evidence_only",
        "public_recommended_family": public_recommendation["public_recommended_family"],
        "public_recommendation_type": public_recommendation["public_recommendation_type"],
        "advisor_release_ready": stage_artifact_bundle_manifest["release_ready_recommendation"],
        "trusted_family": trusted_family,
        "performance_family": performance_family,
        "trusted_performance_divergence": divergence,
        "gpu_annex_status": gpu_status,
        "gpu_annex_reason": gpu_annex_summary.get("reason"),
        "thesis_claim_status": thesis_claim_status,
        "phase1_decisive_lane_closed": phase1_summary["decisive_lane_closed"],
        "phase1_next_blocker_class": phase1_summary["next_blocker_class"],
        "best_point_summary": best_point_summary,
        "known_limitations": limitations,
        "artifact_paths": {
            "manifest_json": stage_artifact_bundle_manifest["json_path"],
            "manifest_md": stage_artifact_bundle_manifest["md_path"],
            "projection_review_json": None if projection_review is None else projection_review["json_path"],
            "projection_review_md": None if projection_review is None else projection_review["md_path"],
            "stage_main_recommendation_json": stage_main_package["json_path"],
            "stage_main_recommendation_md": stage_main_package["md_path"],
            "gpu_annex_json": stage_artifact_bundle_manifest["artifact_paths"]["gpu_annex_json"],
            "gpu_annex_md": stage_artifact_bundle_manifest["artifact_paths"]["gpu_annex_md"],
            "phase1_evidence_closure_json": phase1_evidence_closure["json_path"],
            "phase1_evidence_closure_md": phase1_evidence_closure["md_path"],
            "release_evidence_json": None,
            "release_evidence_md": None,
        },
        "next_action": (
            "Use the manifest as the top-level release evidence entry, keep the stage-main package "
            "as supporting trusted/performance context only, and rely on the adjudicator memo for "
            "any top-level decision authority while presenting GPU status only through the annex."
        ),
    }


def render_advisor_pack_summary_md(summary: dict[str, Any]) -> str:
    paths = summary["artifact_paths"]
    best = summary["best_point_summary"]
    lines = [
        "# QE Next-Stage Advisor Pack Summary",
        "",
        f"- package_kind: `{summary['package_kind']}`",
        f"- phase_id: `{summary['phase_id']}`",
        f"- closure_scope: `{summary['closure_scope']}`",
        f"- release_entry_kind: `{summary['release_entry_kind']}`",
        f"- public_recommended_family: `{summary['public_recommended_family']}`",
        f"- public_recommendation_type: `{summary['public_recommendation_type']}`",
        f"- advisor_release_ready: `{summary['advisor_release_ready']}`",
        f"- trusted_family: `{summary['trusted_family'] or '—'}`",
        f"- performance_family: `{summary['performance_family'] or '—'}`",
        f"- trusted_performance_divergence: `{summary['trusted_performance_divergence']}`",
        f"- gpu_annex_status: `{summary['gpu_annex_status']}`",
        f"- gpu_annex_reason: `{summary['gpu_annex_reason']}`",
        f"- thesis_claim_status: `{summary['thesis_claim_status']}`",
        f"- phase1_decisive_lane_closed: `{summary['phase1_decisive_lane_closed']}`",
        f"- phase1_next_blocker_class: `{summary['phase1_next_blocker_class']}`",
        f"- known_limitations: `{', '.join(summary['known_limitations']) if summary['known_limitations'] else '—'}`",
        "",
        "## Best-point view",
        "",
        f"- status: `{best['status']}`",
        f"- recommendation_family: `{best['recommendation_family']}`",
        f"- best_point_fast_layer_result_id: `{best['best_point_fast_layer_result_id'] or '—'}`",
        f"- best_point_accurate_layer_result_id: `{best['best_point_accurate_layer_result_id'] or '—'}`",
        f"- best_point_time_to_convergence_s: `{best['best_point_time_to_convergence_s']}`",
        f"- best_point_energy_to_convergence_j: `{best['best_point_energy_to_convergence_j']}`",
        f"- best_point_avg_system_power_proxy_w: `{best.get('best_point_avg_system_power_proxy_w')}`",
        "",
        "## Artifact entrypoints",
        "",
        f"- manifest_json: `{paths['manifest_json']}`",
        f"- manifest_md: `{paths['manifest_md']}`",
        f"- stage_main_recommendation_json: `{paths['stage_main_recommendation_json']}`",
        f"- stage_main_recommendation_md: `{paths['stage_main_recommendation_md']}`",
        f"- gpu_annex_json: `{paths['gpu_annex_json']}`",
        f"- gpu_annex_md: `{paths['gpu_annex_md']}`",
        f"- phase1_evidence_closure_json: `{paths['phase1_evidence_closure_json']}`",
        f"- phase1_evidence_closure_md: `{paths['phase1_evidence_closure_md']}`",
        f"- release_evidence_json: `{paths['release_evidence_json'] or '—'}`",
        f"- release_evidence_md: `{paths['release_evidence_md'] or '—'}`",
        f"- projection_review_json: `{paths['projection_review_json'] or '—'}`",
        f"- projection_review_md: `{paths['projection_review_md'] or '—'}`",
        "",
        "## Next action",
        "",
        summary["next_action"],
        "",
    ]
    return "\n".join(lines)


def build_release_evidence_summary(
    *,
    phase_id: str,
    phase_config_path: str,
    phase_runner_command: str,
    release_validator_command: str,
    manifest: dict[str, Any],
    public_recommendation: dict[str, Any],
    gpu_annex_summary: dict[str, Any],
    phase1_evidence_closure: dict[str, Any],
    best_point_summary: dict[str, Any],
    advisor_pack_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    phase1_summary = phase1_evidence_closure["summary"]
    residual_risks: list[str] = []
    if gpu_annex_summary.get("status") != "thesis_eligible":
        residual_risks.append(f"gpu_annex_{gpu_annex_summary.get('status')}")
    if not phase1_summary.get("decisive_lane_closed", False):
        residual_risks.append(
            f"phase1_evidence_{phase1_summary.get('next_blocker_class', 'unknown')}"
        )
    if best_point_summary.get("trusted_family") != best_point_summary.get("performance_family"):
        residual_risks.append("trusted_family_differs_from_performance_family")
    safe_claims = [
        "manifest_is_top_level_release_entry",
        "stage_main_package_is_supporting_context_only",
        "best_point_summary_is_derived_only",
    ]
    if gpu_annex_summary.get("status") != "thesis_eligible":
        safe_claims.append("gpu_thesis_claim_not_ready")
    return {
        "package_kind": "qe_next_stage_release_evidence_v0",
        "phase_id": phase_id,
        "phase_config_path": phase_config_path,
        "release_entry_kind": "stage_artifact_bundle_manifest",
        "bundle_readiness": manifest["bundle_readiness"],
        "release_ready_recommendation": manifest["release_ready_recommendation"],
        "public_recommended_family": public_recommendation["public_recommended_family"],
        "public_recommendation_type": public_recommendation["public_recommendation_type"],
        "best_point_source_surface": best_point_summary["source_surface"],
        "best_point_fast_layer_result_id": best_point_summary["best_point_fast_layer_result_id"],
        "best_point_accurate_layer_result_id": best_point_summary["best_point_accurate_layer_result_id"],
        "gpu_annex_status": gpu_annex_summary["status"],
        "gpu_annex_reason": gpu_annex_summary["reason"],
        "phase1_decisive_lane_closed": phase1_summary["decisive_lane_closed"],
        "phase1_next_blocker_class": phase1_summary["next_blocker_class"],
        "verification_commands": {
            "phase_runner_command": phase_runner_command,
            "release_validator_command": release_validator_command,
        },
        "artifact_paths": {
            "manifest_json": manifest["json_path"],
            "manifest_md": manifest["md_path"],
            "advisor_pack_json": None if advisor_pack_summary is None else advisor_pack_summary["json_path"],
            "advisor_pack_md": None if advisor_pack_summary is None else advisor_pack_summary["md_path"],
            "gpu_annex_json": manifest["artifact_paths"]["gpu_annex_json"],
            "gpu_annex_md": manifest["artifact_paths"]["gpu_annex_md"],
            "phase1_evidence_closure_json": phase1_evidence_closure["json_path"],
            "phase1_evidence_closure_md": phase1_evidence_closure["md_path"],
            "phase_summary_json": manifest["artifact_paths"]["phase_summary_json"],
            "phase_summary_md": manifest["artifact_paths"]["phase_summary_md"],
        },
        "safe_claims": safe_claims,
        "residual_risks": residual_risks,
    }


def render_release_evidence_summary_md(summary: dict[str, Any]) -> str:
    paths = summary["artifact_paths"]
    commands = summary["verification_commands"]
    lines = [
        "# QE Next-Stage Release Evidence",
        "",
        f"- package_kind: `{summary['package_kind']}`",
        f"- phase_id: `{summary['phase_id']}`",
        f"- release_entry_kind: `{summary['release_entry_kind']}`",
        f"- bundle_readiness: `{summary['bundle_readiness']}`",
        f"- release_ready_recommendation: `{summary['release_ready_recommendation']}`",
        f"- public_recommended_family: `{summary['public_recommended_family']}`",
        f"- public_recommendation_type: `{summary['public_recommendation_type']}`",
        f"- best_point_source_surface: `{summary['best_point_source_surface']}`",
        f"- best_point_fast_layer_result_id: `{summary['best_point_fast_layer_result_id'] or '—'}`",
        f"- best_point_accurate_layer_result_id: `{summary['best_point_accurate_layer_result_id'] or '—'}`",
        f"- gpu_annex_status: `{summary['gpu_annex_status']}`",
        f"- gpu_annex_reason: `{summary['gpu_annex_reason']}`",
        f"- phase1_decisive_lane_closed: `{summary['phase1_decisive_lane_closed']}`",
        f"- phase1_next_blocker_class: `{summary['phase1_next_blocker_class']}`",
        "",
        "## Verification commands",
        "",
        f"- phase_runner_command: `{commands['phase_runner_command']}`",
        f"- release_validator_command: `{commands['release_validator_command']}`",
        "",
        "## Artifact paths",
        "",
        f"- manifest_json: `{paths['manifest_json']}`",
        f"- manifest_md: `{paths['manifest_md']}`",
        f"- advisor_pack_json: `{paths['advisor_pack_json'] or '—'}`",
        f"- advisor_pack_md: `{paths['advisor_pack_md'] or '—'}`",
        f"- gpu_annex_json: `{paths['gpu_annex_json']}`",
        f"- gpu_annex_md: `{paths['gpu_annex_md']}`",
        f"- phase1_evidence_closure_json: `{paths['phase1_evidence_closure_json']}`",
        f"- phase1_evidence_closure_md: `{paths['phase1_evidence_closure_md']}`",
        f"- phase_summary_json: `{paths['phase_summary_json']}`",
        f"- phase_summary_md: `{paths['phase_summary_md']}`",
        "",
        "## Safe claims",
        "",
    ]
    for item in summary["safe_claims"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Residual risks", ""])
    if summary["residual_risks"]:
        for item in summary["residual_risks"]:
            lines.append(f"- `{item}`")
    else:
        lines.append("- `none`")
    lines.append("")
    return "\n".join(lines)


def render_stage_artifact_bundle_manifest_md(manifest: dict[str, Any]) -> str:
    paths = manifest["artifact_paths"]
    component_registry_summary = manifest.get("component_registry_summary")
    lines = [
        "# QE Next-Stage Artifact Bundle Manifest",
        "",
        f"- package_kind: `{manifest['package_kind']}`",
        f"- phase_id: `{manifest['phase_id']}`",
        f"- stage_main_recommendation_status: `{manifest['stage_main_recommendation_status']}`",
        f"- public_recommended_family: `{manifest['public_recommended_family']}`",
        f"- bundle_readiness: `{manifest['bundle_readiness']}`",
        f"- release_ready_recommendation: `{manifest['release_ready_recommendation']}`",
        f"- recommended_primary_candidate_count: `{manifest['recommended_primary_candidate_count']}`",
        f"- validated_alternative_candidate_count: `{manifest['validated_alternative_candidate_count']}`",
        f"- projection_review_candidate_count: `{manifest['projection_review_candidate_count']}`",
    ]
    if component_registry_summary is not None:
        lines.extend(
            [
                f"- component_registry_strict_pass: `{component_registry_summary['all_strict_checks_pass']}`",
                f"- component_registry_component_count: `{component_registry_summary['component_count']}`",
                f"- component_registry_future_expansion_candidate_count: `{component_registry_summary['future_catalog_expansion_candidate_count']}`",
            ]
        )
    coverage = manifest.get("accurate_coverage_summary")
    if coverage is not None:
        lines.extend(
            [
                f"- accurate_coverage_result_count: `{coverage['coverage_result_count']}`",
                f"- accurate_coverage_pass_count: `{coverage['coverage_pass_count']}`",
                f"- accurate_coverage_mismatch_count: `{coverage['coverage_mismatch_count']}`",
                f"- accurate_coverage_ready: `{coverage['coverage_ready']}`",
            ]
        )
    generalization = manifest.get("generalization_coverage_summary")
    if generalization is not None:
        lines.extend(
            [
                f"- generalization_result_count: `{generalization['generalization_result_count']}`",
                f"- generalization_pass_count: `{generalization['generalization_pass_count']}`",
                f"- generalization_mismatch_count: `{generalization['generalization_mismatch_count']}`",
                f"- generalization_ready: `{generalization['generalization_ready']}`",
            ]
        )
    gpu_annex = manifest.get("gpu_annex_summary")
    if gpu_annex is not None:
        lines.extend(
            [
                f"- gpu_annex_status: `{gpu_annex['status']}`",
                f"- gpu_annex_reason: `{gpu_annex['reason']}`",
                f"- gpu_annex_decisive_cases: `{', '.join(gpu_annex['decisive_case_ids']) if gpu_annex['decisive_case_ids'] else '—'}`",
                f"- gpu_annex_json: `{paths['gpu_annex_json'] or '—'}`",
                f"- gpu_annex_md: `{paths['gpu_annex_md'] or '—'}`",
                f"- gpu_case_decision_sheet_json: `{paths['gpu_case_decision_sheet_json'] or '—'}`",
                f"- gpu_workload_group_manifest_json: `{paths['gpu_workload_group_manifest_json'] or '—'}`",
            ]
        )
    phase1_summary = manifest.get("phase1_evidence_closure_summary")
    if phase1_summary is not None:
        lines.extend(
            [
                f"- phase1_repo_internal_status: `{phase1_summary['repo_internal_status']}`",
                f"- phase1_decisive_lane_closed: `{phase1_summary['decisive_lane_closed']}`",
                f"- phase1_next_blocker_class: `{phase1_summary['next_blocker_class']}`",
                f"- phase1_gpu_decisive_ready_cases: `{phase1_summary['gpu_decisive_ready_cases']}`",
                f"- phase1_board_ready_cases: `{phase1_summary['board_ready_cases']}`",
                f"- phase1_thesis_count_candidate_ready_cases: `{phase1_summary['thesis_count_candidate_ready_cases']}`",
                f"- phase1_evidence_closure_json: `{paths['phase1_evidence_closure_json'] or '—'}`",
                f"- phase1_evidence_closure_md: `{paths['phase1_evidence_closure_md'] or '—'}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Artifact paths",
            "",
            f"- fast_layer_json: `{paths['fast_layer_json']}`",
            f"- accurate_layer_json: `{paths['accurate_layer_json']}`",
            f"- accurate_coverage_json: `{paths['accurate_coverage_json'] or '—'}`",
            f"- generalization_coverage_json: `{paths['generalization_coverage_json'] or '—'}`",
            f"- component_registry_json: `{paths['component_registry_json']}`",
            f"- phase1_evidence_closure_json: `{paths['phase1_evidence_closure_json'] or '—'}`",
            f"- phase1_evidence_closure_md: `{paths['phase1_evidence_closure_md'] or '—'}`",
            f"- phase_summary_json: `{paths['phase_summary_json']}`",
            f"- phase_summary_md: `{paths['phase_summary_md']}`",
            f"- projection_review_json: `{paths['projection_review_json'] or '—'}`",
            f"- projection_review_md: `{paths['projection_review_md'] or '—'}`",
            f"- stage_main_recommendation_json: `{paths['stage_main_recommendation_json']}`",
            f"- stage_main_recommendation_md: `{paths['stage_main_recommendation_md']}`",
            f"- advisor_pack_json: `{paths['advisor_pack_json'] or '—'}`",
            f"- advisor_pack_md: `{paths['advisor_pack_md'] or '—'}`",
            f"- release_evidence_json: `{paths['release_evidence_json'] or '—'}`",
            f"- release_evidence_md: `{paths['release_evidence_md'] or '—'}`",
            "",
            "## Next action",
            "",
            manifest["next_action"],
            "",
        ]
    )
    return "\n".join(lines)


def annotate_shortlists_with_accurate_layer(
    shortlists: list[dict[str, Any]],
    validation_targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target_by_fast_result_id = {
        item["fast_layer_result_id"]: item for item in validation_targets
    }
    annotated: list[dict[str, Any]] = []
    for shortlist in shortlists:
        item = dict(shortlist)
        source_workload_id = item["workload_id"]

        def annotate_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
            if candidate is None:
                return None
            enriched = dict(candidate)
            target = target_by_fast_result_id.get(candidate["result_id"])
            if target is None:
                enriched["accurate_layer_status"] = "not_assessed"
                return enriched
            enriched["accurate_layer_status"] = "assessed"
            enriched["accurate_layer_result_id"] = target["accurate_layer_result_id"]
            enriched["correctness_status"] = target["correctness_status"]
            enriched["gold_pass"] = target["gold_pass"]
            enriched["convergence_comparable_pass"] = target["convergence_comparable_pass"]
            enriched["recommendation_eligible"] = target["recommendation_eligible"]
            enriched["ranking_observation_retained"] = target["ranking_observation_retained"]
            enriched["gate_reason"] = target["gate_reason"]
            enriched["required_field_failures"] = target["required_field_failures"]
            enriched["narrowing_report_path"] = target.get("narrowing_report_path")
            enriched["narrowing_summary_path"] = target.get("narrowing_summary_path")
            enriched["dominant_blocker_kind"] = target.get("dominant_blocker_kind")
            enriched["explicit_next_narrowing_move"] = target.get("explicit_next_narrowing_move")
            return enriched

        item["primary_candidate"] = annotate_candidate(item.get("primary_candidate"))
        item["fallback_candidate"] = annotate_candidate(item.get("fallback_candidate"))
        item["extra_promoted_candidates"] = [
            annotate_candidate(candidate) for candidate in item.get("extra_promoted_candidates", [])
        ]

        assessed_targets = [
            target for target in validation_targets if target["source_workload_id"] == source_workload_id
        ]
        if not assessed_targets:
            item["recommendation_status"] = "awaiting_accurate_layer"
            item["next_narrowing_move"] = (
                "Run accurate-layer validation for shortlisted candidates before promoting any stage-main recommendation."
            )
            item["publication_status"] = "awaiting_accurate_layer"
            item["projection_reporting_allowed"] = False
        elif any(target["recommendation_eligible"] for target in assessed_targets):
            item["recommendation_status"] = "projection_eligible"
            item["next_narrowing_move"] = "Promote the accurate-layer-passing candidate into projection-grade recommendation review."
            item["publication_status"] = "projection_eligible"
            item["projection_reporting_allowed"] = True
        else:
            gate_reasons = sorted({target["gate_reason"] for target in assessed_targets})
            if gate_reasons == ["gold_mismatch"]:
                item["recommendation_status"] = "blocked_by_accurate_layer"
                item["next_narrowing_move"] = (
                    "Narrow the final_total_energy_ry mismatch on si8_pbe_nc for the shortlisted candidate(s) before allowing projection-grade recommendation."
                )
            else:
                item["recommendation_status"] = "blocked_by_accurate_layer"
                item["next_narrowing_move"] = (
                    "Resolve the accurate-layer blocker(s) for the shortlisted candidate(s) before allowing projection-grade recommendation."
                )
            item["publication_status"] = "ranking_observation_only"
            item["projection_reporting_allowed"] = False
        annotated.append(item)
    return annotated


def render_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# QE Next-Stage DSE / Simulator Phase Summary",
        "",
        f"- phase_id: `{summary['phase_id']}`",
        f"- source_kind: `{summary['source_kind']}`",
        f"- execute_model: `{summary['execute_model']}`",
        f"- phase_config: `{summary['phase_config_path']}`",
        "",
        "## Component registry evidence",
        "",
        f"- json: `{summary['component_registry']['json_path']}`",
        f"- strict_pass: `{summary['component_registry']['summary']['all_strict_checks_pass']}`",
        f"- component_count: `{summary['component_registry']['summary']['component_count']}`",
        f"- active_build_source_count: `{summary['component_registry']['summary']['active_build_source_count']}`",
        f"- future_catalog_expansion_candidate_count: `{summary['component_registry']['summary']['future_catalog_expansion_candidate_count']}`",
        f"- active_source_gap_categories: `{json.dumps(summary['component_registry']['summary']['active_source_gap_categories'], ensure_ascii=False)}`",
        "",
        "## Fast layer",
        "",
        f"- families: `{', '.join(summary['fast_layer']['families'])}`",
        f"- workloads: `{', '.join(summary['fast_layer']['workloads'])}`",
        f"- json: `{summary['fast_layer']['json_path']}`",
        f"- csv: `{summary['fast_layer']['csv_path']}`",
        "",
        "## Accurate layer",
        "",
        f"- families: `{', '.join(summary['accurate_layer']['families'])}`",
        f"- anchors: `{', '.join(summary['accurate_layer']['workloads'])}`",
        f"- json: `{summary['accurate_layer']['json_path']}`",
        f"- csv: `{summary['accurate_layer']['csv_path']}`",
    ]
    accurate_coverage = summary.get("accurate_coverage")
    if accurate_coverage is not None:
        lines.extend(
            [
                "",
                "## Accurate-layer canonical coverage",
                "",
                f"- families: `{', '.join(accurate_coverage['families'])}`",
                f"- workloads: `{', '.join(accurate_coverage['workloads'])}`",
                f"- json: `{accurate_coverage['json_path']}`",
                f"- csv: `{accurate_coverage['csv_path']}`",
            ]
        )
        if accurate_coverage.get("gold_summary_json_path"):
            lines.extend(
                [
                    f"- gold summary json: `{accurate_coverage['gold_summary_json_path']}`",
                    f"- gold summary md: `{accurate_coverage['gold_summary_md_path']}`",
                ]
            )
        coverage_summary = accurate_coverage.get("summary")
        if coverage_summary is not None:
            lines.extend(
                [
                    f"- coverage_pass_count: `{coverage_summary['coverage_pass_count']}`",
                    f"- coverage_mismatch_count: `{coverage_summary['coverage_mismatch_count']}`",
                    f"- coverage_ready: `{coverage_summary['coverage_ready']}`",
                ]
            )
    generalization_coverage = summary.get("generalization_coverage")
    if generalization_coverage is not None:
        lines.extend(
            [
                "",
                "## Accurate-layer nonblocking generalization coverage",
                "",
                f"- families: `{', '.join(generalization_coverage['families'])}`",
                f"- workloads: `{', '.join(generalization_coverage['workloads'])}`",
                f"- json: `{generalization_coverage['json_path']}`",
                f"- csv: `{generalization_coverage['csv_path']}`",
            ]
        )
        if generalization_coverage.get("gold_summary_json_path"):
            lines.extend(
                [
                    f"- gold summary json: `{generalization_coverage['gold_summary_json_path']}`",
                    f"- gold summary md: `{generalization_coverage['gold_summary_md_path']}`",
                ]
            )
        generalization_summary = generalization_coverage.get("summary")
        if generalization_summary is not None:
            lines.extend(
                [
                    f"- generalization_pass_count: `{generalization_summary['generalization_pass_count']}`",
                    f"- generalization_mismatch_count: `{generalization_summary['generalization_mismatch_count']}`",
                    f"- generalization_ready: `{generalization_summary['generalization_ready']}`",
                ]
            )
    if summary["accurate_layer"].get("gold_summary_json_path"):
        lines.extend(
            [
                f"- gold summary json: `{summary['accurate_layer']['gold_summary_json_path']}`",
                f"- gold summary md: `{summary['accurate_layer']['gold_summary_md_path']}`",
            ]
        )
    validation_targets = summary["accurate_layer"].get("validation_targets", [])
    lines.extend(
        [
            f"- candidate validation targets: `{len(validation_targets)}`",
            "",
            "## Accurate-layer validation targets",
            "",
            "| Source workload | Selection role | Fast-layer result | Accurate-layer result | Anchor workload | correctness_status | gold_pass | convergence_comparable_pass | recommendation_eligible | ranking_observation_retained | gate_reason | failed fields |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if validation_targets:
        for item in validation_targets:
            failed_fields = ", ".join(item["required_field_failures"]) if item["required_field_failures"] else "—"
            lines.append(
                "| {source_workload_id} | {selection_role} | {fast_layer_result_id} | {accurate_layer_result_id} | {anchor_workload_id} | {correctness_status} | {gold_pass} | {convergence_comparable_pass} | {recommendation_eligible} | {ranking_observation_retained} | {gate_reason} | {failed_fields} |".format(
                    failed_fields=failed_fields,
                    **item,
                )
            )
    else:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | — |")
    narrowing_targets = [
        item for item in validation_targets if item.get("narrowing_report_path") is not None
    ]
    if narrowing_targets:
        lines.extend(
            [
                "",
                "## Narrowing artifacts",
                "",
                "| Source workload | Selection role | blocker | narrowing report | narrowing summary | next narrowing move |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in narrowing_targets:
            lines.append(
                "| {source_workload_id} | {selection_role} | {dominant_blocker_kind} | {narrowing_report_path} | {narrowing_summary_path} | {explicit_next_narrowing_move} |".format(
                    **item,
                )
            )
    accurate_validation_summary = summary["accurate_layer"].get("validation_summary_by_source_workload", [])
    if accurate_validation_summary:
        lines.extend(
            [
                "",
                "## Accurate-layer gating by source workload",
                "",
                "| Source workload | validation_gate_status | targets | eligible candidates | ranking observations | blocked candidates | blocked roles | gate reasons |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for item in accurate_validation_summary:
            blocked_roles = ", ".join(item["blocked_selection_roles"]) if item["blocked_selection_roles"] else "—"
            gate_reasons = ", ".join(item["gate_reasons"]) if item["gate_reasons"] else "—"
            lines.append(
                "| {source_workload_id} | {validation_gate_status} | {validation_target_count} | {eligible_candidate_count} | {ranking_observation_count} | {blocked_candidate_count} | {blocked_roles_display} | {gate_reasons_display} |".format(
                    blocked_roles_display=blocked_roles,
                    gate_reasons_display=gate_reasons,
                    **item,
                )
            )
    stage_gate = summary["accurate_layer"].get("stage_recommendation_gate")
    if stage_gate is not None:
        lines.extend(
            [
                "",
                "## Stage recommendation gate",
                "",
                f"- stage_main_recommendation_status: `{stage_gate['stage_main_recommendation_status']}`",
                f"- eligible_source_workload_count: `{stage_gate['eligible_source_workload_count']}`",
                f"- blocked_source_workload_count: `{stage_gate['blocked_source_workload_count']}`",
                f"- not_assessed_source_workload_count: `{stage_gate['not_assessed_source_workload_count']}`",
                f"- blocked_source_workloads: `{', '.join(stage_gate['blocked_source_workloads']) if stage_gate['blocked_source_workloads'] else '—'}`",
                f"- not_assessed_source_workloads: `{', '.join(stage_gate['not_assessed_source_workloads']) if stage_gate['not_assessed_source_workloads'] else '—'}`",
            ]
        )
    public_recommendation = summary.get("public_recommendation")
    if public_recommendation is not None:
        runtime_risk_summary = public_recommendation.get("runtime_risk_summary") or {
            "overall_runtime_risk": "unknown",
            "counts": {"low": 0, "medium": 0, "high": 0, "unknown": 0},
        }
        lines.extend(
            [
                "",
                "## Public recommendation view",
                "",
                f"- public_recommended_family: `{public_recommendation['public_recommended_family']}`",
                f"- public_recommendation_type: `{public_recommendation['public_recommendation_type']}`",
                f"- ranking_observations_retained: `{public_recommendation['ranking_observations_retained']}`",
                f"- ranking_observation_source_workloads: `{', '.join(public_recommendation['ranking_observation_source_workloads']) if public_recommendation['ranking_observation_source_workloads'] else '—'}`",
                f"- projection_reporting_allowed: `{public_recommendation['projection_reporting_allowed']}`",
                f"- suppression_reason: `{public_recommendation['suppression_reason']}`",
                f"- next_narrowing_moves: `{ ' | '.join(public_recommendation['next_narrowing_moves']) if public_recommendation['next_narrowing_moves'] else '—'}`",
                f"- runtime_risk_overall: `{runtime_risk_summary['overall_runtime_risk']}`",
                f"- runtime_risk_counts: `{json.dumps(runtime_risk_summary['counts'], ensure_ascii=False)}`",
            ]
        )
    gpu_annex_summary = summary.get("gpu_annex_summary")
    if gpu_annex_summary is not None:
        lines.extend(
            [
                "",
                "## GPU annex summary",
                "",
                f"- status: `{gpu_annex_summary['status']}`",
                f"- reason: `{gpu_annex_summary['reason']}`",
                f"- baseline_dir_count: `{gpu_annex_summary['baseline_dir_count']}`",
                f"- gpu_mode_set_measured: `{', '.join(gpu_annex_summary['gpu_mode_set_measured']) if gpu_annex_summary['gpu_mode_set_measured'] else '—'}`",
                f"- gpu_decisive_modes: `{', '.join(gpu_annex_summary['gpu_decisive_modes']) if gpu_annex_summary['gpu_decisive_modes'] else '—'}`",
                f"- decisive_case_ids: `{', '.join(gpu_annex_summary['decisive_case_ids']) if gpu_annex_summary['decisive_case_ids'] else '—'}`",
                f"- counts: `{json.dumps(gpu_annex_summary['counts'], ensure_ascii=False)}`",
                f"- case_decision_sheet_count: `{(gpu_annex_summary.get('case_decision_sheet') or {}).get('case_count', 0)}`",
                f"- workload_group_safe_claim_status: `{((gpu_annex_summary.get('workload_group_gpu_column_manifest') or {}).get('safe_claim_status')) or '—'}`",
            ]
        )
    phase1_evidence_closure = summary.get("phase1_evidence_closure")
    if phase1_evidence_closure is not None:
        phase1_summary = phase1_evidence_closure["summary"]
        lines.extend(
            [
                "",
                "## Phase-1 evidence closure",
                "",
                f"- json: `{phase1_evidence_closure['json_path']}`",
                f"- md: `{phase1_evidence_closure['md_path']}`",
                f"- repo_internal_status: `{phase1_summary['repo_internal_status']}`",
                f"- decisive_lane_closed: `{phase1_summary['decisive_lane_closed']}`",
                f"- next_blocker_class: `{phase1_summary['next_blocker_class']}`",
                f"- gpu_decisive_ready_cases: `{phase1_summary['gpu_decisive_ready_cases']}`",
                f"- board_ready_cases: `{phase1_summary['board_ready_cases']}`",
                f"- thesis_count_candidate_ready_cases: `{phase1_summary['thesis_count_candidate_ready_cases']}`",
            ]
        )
    release_evidence_summary = summary.get("release_evidence_summary")
    if release_evidence_summary is not None:
        lines.extend(
            [
                "",
                "## Release evidence",
                "",
                f"- json: `{release_evidence_summary['json_path']}`",
                f"- md: `{release_evidence_summary['md_path']}`",
                f"- bundle_readiness: `{release_evidence_summary['bundle_readiness']}`",
                f"- release_ready_recommendation: `{release_evidence_summary['release_ready_recommendation']}`",
                f"- gpu_annex_status: `{release_evidence_summary['gpu_annex_status']}`",
                f"- phase1_decisive_lane_closed: `{release_evidence_summary['phase1_decisive_lane_closed']}`",
                f"- residual_risks: `{', '.join(release_evidence_summary['residual_risks']) if release_evidence_summary['residual_risks'] else '—'}`",
            ]
        )
    projection_review = summary.get("projection_review")
    if projection_review is not None:
        lines.extend(
            [
                "",
                "## Projection review package",
                "",
                f"- json: `{projection_review['json_path']}`",
                f"- md: `{projection_review['md_path']}`",
                f"- public_recommended_family: `{projection_review['public_recommended_family']}`",
                f"- promoted_candidate_count: `{projection_review['promoted_candidate_count']}`",
                f"- review_readiness: `{projection_review['review_readiness']}`",
            ]
        )
    best_point_summary = summary.get("best_point_summary")
    if best_point_summary is not None:
        lines.extend(
            [
                "",
                "## Best-point summary",
                "",
                f"- status: `{best_point_summary['status']}`",
                f"- source_surface: `{best_point_summary['source_surface']}`",
                f"- recommendation_family: `{best_point_summary['recommendation_family']}`",
                f"- trusted_family: `{best_point_summary['trusted_family'] or '—'}`",
                f"- performance_family: `{best_point_summary['performance_family'] or '—'}`",
                f"- projection_reporting_allowed: `{best_point_summary['projection_reporting_allowed']}`",
                f"- recommendation_type: `{best_point_summary['recommendation_type']}`",
                f"- supported_source_workloads: `{', '.join(best_point_summary['supported_source_workloads']) if best_point_summary['supported_source_workloads'] else '—'}`",
                f"- runtime_risk_overall: `{best_point_summary['runtime_risk_overall'] or 'unknown'}`",
                f"- best_point_fast_layer_result_id: `{best_point_summary['best_point_fast_layer_result_id'] or '—'}`",
                f"- best_point_accurate_layer_result_id: `{best_point_summary['best_point_accurate_layer_result_id'] or '—'}`",
                f"- best_point_time_to_convergence_s: `{best_point_summary['best_point_time_to_convergence_s']}`",
                f"- best_point_energy_to_convergence_j: `{best_point_summary['best_point_energy_to_convergence_j']}`",
                f"- best_point_avg_system_power_proxy_w: `{best_point_summary.get('best_point_avg_system_power_proxy_w')}`",
            ]
        )
        if best_point_summary.get("best_point_graph_topology_summary") is not None:
            lines.append(
                f"- best_point_graph_topology: `{best_point_summary['best_point_graph_topology_summary']}`"
            )
        if best_point_summary.get("best_point_graph_execution_plan_summary") is not None:
            lines.append(
                f"- best_point_graph_execution_plan: `{best_point_summary['best_point_graph_execution_plan_summary']}`"
            )
        if best_point_summary.get("best_point_graph_component_driver_summary") is not None:
            lines.append(
                f"- best_point_graph_components: `{best_point_summary['best_point_graph_component_driver_summary']}`"
            )
        lines.append(
            f"- next_action: `{best_point_summary['next_action'] or '—'}`"
        )
    stage_main_package = summary.get("stage_main_recommendation_package")
    if stage_main_package is not None:
        lines.extend(
            [
                "",
                "## Stage-main recommendation package",
                "",
                f"- json: `{stage_main_package['json_path']}`",
                f"- md: `{stage_main_package['md_path']}`",
                f"- recommended_family: `{stage_main_package['recommended_family']}`",
                f"- recommendation_status: `{stage_main_package['recommendation_status']}`",
                f"- recommended_primary_candidate_count: `{stage_main_package['recommended_primary_candidate_count']}`",
                f"- validated_alternative_candidate_count: `{stage_main_package['validated_alternative_candidate_count']}`",
            ]
        )
    stage_artifact_bundle = summary.get("stage_artifact_bundle_manifest")
    if stage_artifact_bundle is not None:
        lines.extend(
            [
                "",
                "## Stage artifact bundle manifest",
                "",
                f"- json: `{stage_artifact_bundle['json_path']}`",
                f"- md: `{stage_artifact_bundle['md_path']}`",
                f"- bundle_readiness: `{stage_artifact_bundle['bundle_readiness']}`",
                f"- release_ready_recommendation: `{stage_artifact_bundle['release_ready_recommendation']}`",
            ]
        )
    advisor_pack_summary = summary.get("advisor_pack_summary")
    if advisor_pack_summary is not None:
        lines.extend(
            [
                "",
                "## Advisor-pack summary",
                "",
                f"- json: `{advisor_pack_summary['json_path']}`",
                f"- md: `{advisor_pack_summary['md_path']}`",
                f"- closure_scope: `{advisor_pack_summary['closure_scope']}`",
                f"- release_entry_kind: `{advisor_pack_summary['release_entry_kind']}`",
                f"- advisor_release_ready: `{advisor_pack_summary['advisor_release_ready']}`",
                f"- trusted_family: `{advisor_pack_summary['trusted_family'] or '—'}`",
                f"- performance_family: `{advisor_pack_summary['performance_family'] or '—'}`",
                f"- trusted_performance_divergence: `{advisor_pack_summary['trusted_performance_divergence']}`",
                f"- gpu_annex_status: `{advisor_pack_summary['gpu_annex_status']}`",
                f"- thesis_claim_status: `{advisor_pack_summary['thesis_claim_status']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Frozen objective stack",
            "",
            f"- primary objective: `{summary['fast_layer']['primary_objective']}`",
            f"- secondary objective: `{summary['fast_layer']['secondary_objective']}`",
            f"- constraints: `{', '.join(summary['fast_layer']['constraint_metrics'])}`",
            "",
            "## Promotion policy",
            "",
            f"- state machine: `{', '.join(summary['fast_layer']['promotion_policy']['state_machine'])}`",
            (
                "- tie-band rule: "
                f"`{summary['fast_layer']['promotion_policy']['tie_band_rule']['kind']}` "
                f"with `max_relative_margin={summary['fast_layer']['promotion_policy']['tie_band_rule']['max_relative_margin']:.2f}`"
            ),
            "",
        ]
    )
    shortlists = summary["fast_layer"].get("shortlists", [])
    if shortlists:
        lines.extend(["", "## Fast-layer shortlist status", ""])
        for item in shortlists:
            lines.extend(
                [
                    f"### {item['workload_id']}",
                    "",
                    f"- selection status: `{item['selection_status']}`",
                    f"- state counts: `{json.dumps(item['state_counts'], ensure_ascii=False)}`",
                    (
                        f"- primary candidate: `{item['primary_candidate']['result_id']}`"
                        if item["primary_candidate"] is not None
                        else "- primary candidate: `unavailable`"
                    ),
                    (
                        f"- fallback candidate: `{item['fallback_candidate']['result_id']}`"
                        if item["fallback_candidate"] is not None
                        else "- fallback candidate: `unavailable`"
                    ),
                    f"- recommendation_status: `{item.get('recommendation_status', 'unknown')}`",
                    f"- publication_status: `{item.get('publication_status', 'unknown')}`",
                    f"- projection_reporting_allowed: `{item.get('projection_reporting_allowed', False)}`",
                    f"- next_narrowing_move: `{item.get('next_narrowing_move', '—')}`",
                    f"- runtime_risk_overall: `{item.get('runtime_risk_summary', {}).get('overall_runtime_risk', 'unknown')}`",
                ]
            )
            if item["extra_promoted_candidates"]:
                promoted = ", ".join(candidate["result_id"] for candidate in item["extra_promoted_candidates"])
                lines.append(f"- extra promoted candidates: `{promoted}`")
            if item["selection_notes"]:
                lines.append(f"- notes: `{' | '.join(item['selection_notes'])}`")
            assessed_candidates = [
                candidate
                for candidate in [item.get("primary_candidate"), item.get("fallback_candidate"), *item.get("extra_promoted_candidates", [])]
                if candidate is not None and candidate.get("accurate_layer_status") == "assessed"
            ]
            if assessed_candidates:
                lines.extend(
                    [
                        "",
                        "| candidate | accurate_layer_result_id | correctness_status | gold_pass | convergence_comparable_pass | recommendation_eligible | gate_reason | failed fields |",
                        "| --- | --- | --- | --- | --- | --- | --- | --- |",
                    ]
                )
                for candidate in assessed_candidates:
                    failed_fields = ", ".join(candidate.get("required_field_failures", [])) or "—"
                    lines.append(
                        "| {result_id} | {accurate_layer_result_id} | {correctness_status} | {gold_pass} | {convergence_comparable_pass} | {recommendation_eligible} | {gate_reason} | {failed_fields} |".format(
                            failed_fields=failed_fields,
                            **candidate,
                        )
                    )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This phase runner does not replace the underlying DSE runner; it narrows it to the frozen 2+1 next-stage case set.",
            "- `F3` is excluded by default and must be explicitly enabled because it remains conditional/exploratory in the current phase config.",
        ]
    )
    return "\n".join(lines) + "\n"


def base_args(args: argparse.Namespace, runner: Any) -> SimpleNamespace:
    return SimpleNamespace(
        output_dir=args.output_dir,
        json_name="",
        csv_name="",
        run_id=None,
        workloads=[],
        gold_required_only=False,
        families=[],
        diag_policies=None,
        offload_scopes=None,
        resident_policies=None,
        canonical_only=not args.full_cross_product,
        max_design_points=None,
        assumption_set_id=args.assumption_set_id,
        qe_tolerance_schema_id=args.qe_tolerance_schema_id,
        source_model=args.source_model,
        source_kind=args.source_kind,
        execute_model=args.execute_model,
        model_bin=args.model_bin,
        model_max_scf_iters=args.model_max_scf_iters,
        auto_match_baseline_iters=args.auto_match_baseline_iters or args.execute_model,
        cpu_shell_aggregate_path=runner.DEFAULT_CPU_SHELL_AGGREGATE_PATH,
        fast_layer_proxy_assumptions_path=runner.DEFAULT_FAST_LAYER_PROXY_ASSUMPTIONS_PATH,
        compare_helper=args.compare_helper,
        normalize_gold_helper=args.normalize_gold_helper,
        gold_baseline_root=args.gold_baseline_root,
        fail_on_gold_mismatch=args.fail_on_gold_mismatch,
        list_workloads=False,
    )


def write_bundle_for_lane(
    lane_name: str,
    workloads: list[str],
    families: list[str],
    args: argparse.Namespace,
    runner: Any,
    case_pack: dict[str, Any] | None = None,
    selected_design_points: list[dict[str, str]] | None = None,
    force_gold_required: bool = False,
) -> dict[str, Any]:
    lane_dir = args.output_dir / lane_name
    lane_dir.mkdir(parents=True, exist_ok=True)
    lane_args = base_args(args, runner)
    lane_args.output_dir = lane_dir
    lane_args.json_name = f"{lane_name}_bundle.json"
    lane_args.csv_name = f"{lane_name}_bundle.csv"
    lane_args.workloads = workloads
    lane_args.families = families

    ts = runner.utc_now()
    if case_pack is not None:
        case_pack_rows = workload_rows_from_case_pack(
            case_pack,
            lane_name,
            workloads,
            force_gold_required=force_gold_required,
        )
        default_rows = {
            row["workload_id"]: row for row in runner.validate_workloads(workloads)
        }
        workload_rows = [
            {**default_rows[row["workload_id"]], **row}
            for row in case_pack_rows
        ]
    else:
        workload_rows = runner.validate_workloads(workloads)
        if force_gold_required:
            workload_rows = [
                {**workload, "gold_required": True} for workload in workload_rows
            ]
    bundle = runner.build_bundle(
        lane_args,
        ts,
        workload_rows,
        families,
        runner.validate_axis_subset("diag policies", lane_args.diag_policies, runner.DIAG_POLICIES),
        runner.validate_axis_subset("offload scopes", lane_args.offload_scopes, runner.OFFLOAD_SCOPES),
        runner.validate_axis_subset("resident policies", lane_args.resident_policies, runner.RESIDENT_POLICIES),
        None
        if getattr(lane_args, "partition_strategies", None) is None
        else runner.validate_axis_subset(
            "partition strategies",
            lane_args.partition_strategies,
            runner.PARTITION_STRATEGIES,
        ),
    )
    if selected_design_points is not None:
        filter_bundle_to_design_points(bundle, selected_design_points, runner)
    if args.execute_model:
        runner.execute_bundle(bundle, lane_args, lane_dir / "artifacts")
        runner.refresh_projection_grade_readiness(bundle)
        runner.refresh_family_summary(bundle)
        refresh_equal_candidate_family_summary(bundle, runner)
    runner.write_graph_evidence_sidecars(lane_dir, bundle)
    json_path = lane_dir / lane_args.json_name
    csv_path = lane_dir / lane_args.csv_name
    runner.write_json(json_path, bundle)
    runner.write_csv(csv_path, bundle)
    gold_paths = runner.write_gold_gate_summary(lane_dir, bundle)
    info = {
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "graph_evidence_dir": str(lane_dir / "graph_evidence"),
        "workloads": workloads,
        "families": families,
    }
    if selected_design_points is not None:
        info["selected_design_points"] = selected_design_points
    if gold_paths is not None:
        info["gold_summary_json_path"] = str(gold_paths[0])
        info["gold_summary_md_path"] = str(gold_paths[1])
    return info


def parse_args() -> argparse.Namespace:
    runner = load_runner()
    parser = argparse.ArgumentParser(
        description="Run the frozen next-stage QE DSE/simulator phase on the 2+1 case set."
    )
    parser.add_argument("--phase-config", type=Path, default=PHASE_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--include-conditional-families", action="store_true")
    parser.add_argument("--full-cross-product", action="store_true")
    parser.add_argument("--execute-model", action="store_true")
    parser.add_argument("--assumption-set-id", default="qe_next_stage_phase_v0")
    parser.add_argument("--qe-tolerance-schema-id", default="qe_gold_numerical_tolerance_schema_v0")
    parser.add_argument("--source-model", default="model/qe_band_solver_model")
    parser.add_argument(
        "--source-kind",
        default="timed_functional_proxy",
        choices=["stub", "timed_functional_proxy", "trace_calibrated_proxy", "measured", "mixed"],
    )
    parser.add_argument("--model-bin", type=Path, default=runner.DEFAULT_MODEL_BIN)
    parser.add_argument("--model-max-scf-iters", type=int, default=1)
    parser.add_argument("--auto-match-baseline-iters", action="store_true")
    parser.add_argument("--compare-helper", type=Path, default=runner.DEFAULT_COMPARE_HELPER)
    parser.add_argument("--normalize-gold-helper", type=Path, default=runner.DEFAULT_NORMALIZE_GOLD_HELPER)
    parser.add_argument("--gold-baseline-root", type=Path, default=runner.DEFAULT_GOLD_BASELINE_ROOT)
    parser.add_argument(
        "--gpu-baseline-dir",
        type=Path,
        action="append",
        default=[],
        help="Optional CPU+GPU baseline artifact directory. May be repeated.",
    )
    parser.add_argument(
        "--gpu-reference-dir",
        type=Path,
        action="append",
        default=[],
        help="Optional GPU reference trace/profile directory. May be repeated.",
    )
    parser.add_argument(
        "--board-dir",
        type=Path,
        action="append",
        default=[],
        help="Optional board artifact directory for phase-1 evidence closure. May be repeated.",
    )
    parser.add_argument("--fail-on-gold-mismatch", action="store_true")
    parser.add_argument("--case-pack", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = load_runner()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = load_phase_config(args.phase_config)
    component_registry_info = build_component_registry_info(args.output_dir)
    case_pack_summary = None
    case_pack = None
    if args.case_pack is not None:
        case_pack = load_case_pack(args.case_pack)
        case_pack_summary = summarize_case_pack(case_pack, config)
        if not case_pack_summary["all_referenced_workloads_present"]:
            missing = ", ".join(case_pack_summary["missing_referenced_workloads"])
            raise ValueError(f"case pack missing referenced workloads: {missing}")

    families = list(config["scope"]["architecture_families_primary"])
    if args.include_conditional_families:
        families.extend(config["scope"]["architecture_families_conditional"])

    fast_info = write_bundle_for_lane(
        "fast_layer",
        list(config["layers"]["fast_layer"]["main_cases"]),
        families,
        args,
        runner,
        case_pack=case_pack,
    )
    fast_bundle = json.loads(Path(fast_info["json_path"]).read_text(encoding="utf-8"))
    shortlists = summarize_fast_layer_shortlists(fast_bundle, config)
    accurate_design_points = selected_design_points_for_accurate_layer(shortlists, config, runner)
    accurate_info = write_bundle_for_lane(
        "accurate_layer",
        list(config["layers"]["accurate_layer"]["anchor_cases"]),
        families,
        args,
        runner,
        case_pack=case_pack,
        selected_design_points=accurate_design_points,
    )
    accurate_bundle = json.loads(Path(accurate_info["json_path"]).read_text(encoding="utf-8"))
    accurate_coverage_info = None
    coverage_cases = list(config["layers"]["accurate_layer"].get("coverage_cases", []))
    if coverage_cases:
        accurate_coverage_info = write_bundle_for_lane(
            "accurate_coverage",
            coverage_cases,
            families,
            args,
            runner,
            case_pack=case_pack,
            selected_design_points=accurate_design_points,
        )
    accurate_coverage_summary = None
    if accurate_coverage_info is not None:
        accurate_coverage_bundle = json.loads(
            Path(accurate_coverage_info["json_path"]).read_text(encoding="utf-8")
        )
        accurate_coverage_summary = summarize_accurate_coverage_bundle(
            accurate_coverage_bundle
        )
    generalization_coverage_info = None
    generalization_cases = list(config["layers"]["accurate_layer"].get("generalization_cases", []))
    generalization_coverage_summary = None
    if args.execute_model and generalization_cases:
        generalization_coverage_info = write_bundle_for_lane(
            "generalization_coverage",
            generalization_cases,
            families,
            args,
            runner,
            case_pack=case_pack,
            selected_design_points=accurate_design_points,
            force_gold_required=True,
        )
        generalization_coverage_bundle = json.loads(
            Path(generalization_coverage_info["json_path"]).read_text(encoding="utf-8")
        )
        generalization_coverage_summary = summarize_generalization_coverage_bundle(
            generalization_coverage_bundle
        )
    validation_targets = build_accurate_validation_targets(shortlists, accurate_bundle)
    validation_summary_by_source_workload = summarize_accurate_validation_targets(
        validation_targets,
        [shortlist["workload_id"] for shortlist in shortlists],
    )
    annotated_shortlists = annotate_shortlists_with_accurate_layer(shortlists, validation_targets)
    stage_recommendation_gate = build_stage_recommendation_gate(
        validation_summary_by_source_workload
    )
    public_recommendation = build_public_recommendation_summary(
        annotated_shortlists,
        validation_summary_by_source_workload,
        stage_recommendation_gate,
    )
    gpu_annex_summary = enrich_gpu_annex_summary(build_gpu_annex_summary(
        args.gpu_baseline_dir, args.gpu_reference_dir, args.output_dir
    ))
    gpu_annex_json_path = args.output_dir / "qe_gpu_annex_summary.json"
    gpu_annex_md_path = args.output_dir / "qe_gpu_annex_summary.md"
    gpu_case_decision_json_path = args.output_dir / "qe_gpu_case_decision_sheet.json"
    gpu_case_decision_md_path = args.output_dir / "qe_gpu_case_decision_sheet.md"
    gpu_workload_manifest_json_path = args.output_dir / "qe_gpu_workload_group_column_manifest.json"
    gpu_workload_manifest_md_path = args.output_dir / "qe_gpu_workload_group_column_manifest.md"
    gpu_annex_summary["artifact_paths"]["gpu_annex_json"] = str(gpu_annex_json_path)
    gpu_annex_summary["artifact_paths"]["gpu_annex_md"] = str(gpu_annex_md_path)
    gpu_annex_summary["artifact_paths"]["case_decision_sheet_json"] = str(gpu_case_decision_json_path)
    gpu_annex_summary["artifact_paths"]["case_decision_sheet_md"] = str(gpu_case_decision_md_path)
    gpu_annex_summary["artifact_paths"]["workload_group_gpu_column_manifest_json"] = str(
        gpu_workload_manifest_json_path
    )
    gpu_annex_summary["artifact_paths"]["workload_group_gpu_column_manifest_md"] = str(
        gpu_workload_manifest_md_path
    )
    phase1_gpu_dirs = [
        Path(path)
        for path in {
            str(row.get("baseline_dir"))
            for row in gpu_annex_summary.get("row_ledger", [])
            if row.get("baseline_dir")
        }
    ]
    phase1_evidence_closure = build_phase1_evidence_closure_info(
        gpu_baseline_dirs=phase1_gpu_dirs,
        board_dirs=args.board_dir,
        output_dir=args.output_dir,
    )
    projection_review = build_projection_review_summary(
        annotated_shortlists,
        stage_recommendation_gate,
        public_recommendation,
    )
    if projection_review is not None:
        projection_review["phase_id"] = config["phase_id"]
        projection_review["phase_config_path"] = str(args.phase_config)
        projection_review["fast_layer_json_path"] = fast_info["json_path"]
        projection_review["accurate_layer_json_path"] = accurate_info["json_path"]
        projection_review["component_registry_path"] = component_registry_info["json_path"]
        projection_review["component_registry_summary"] = component_registry_info["summary"]
        projection_review["json_path"] = str(
            args.output_dir / "qe_next_stage_projection_review.json"
        )
        projection_review["md_path"] = str(
            args.output_dir / "qe_next_stage_projection_review.md"
        )
    stage_main_recommendation_package = build_stage_main_recommendation_package(
        annotated_shortlists,
        stage_recommendation_gate,
        public_recommendation,
    )
    if stage_main_recommendation_package is not None:
        stage_main_recommendation_package["phase_id"] = config["phase_id"]
        stage_main_recommendation_package["phase_config_path"] = str(args.phase_config)
        stage_main_recommendation_package["fast_layer_json_path"] = fast_info["json_path"]
        stage_main_recommendation_package["accurate_layer_json_path"] = accurate_info["json_path"]
        stage_main_recommendation_package["component_registry_path"] = component_registry_info[
            "json_path"
        ]
        stage_main_recommendation_package["component_registry_summary"] = component_registry_info[
            "summary"
        ]
        stage_main_recommendation_package["json_path"] = str(
            args.output_dir / "qe_next_stage_stage_main_recommendation.json"
        )
        stage_main_recommendation_package["md_path"] = str(
            args.output_dir / "qe_next_stage_stage_main_recommendation.md"
        )
    best_point_summary = build_best_point_summary(
        public_recommendation,
        stage_recommendation_gate,
        projection_review,
        stage_main_recommendation_package,
    )
    stage_artifact_bundle_manifest = build_stage_artifact_bundle_manifest(
        phase_id=config["phase_id"],
        phase_config_path=str(args.phase_config),
        execute_model=args.execute_model,
        source_kind=args.source_kind,
        fast_info=fast_info,
        accurate_info=accurate_info,
        accurate_coverage_info=accurate_coverage_info,
        accurate_coverage_summary=accurate_coverage_summary,
        generalization_coverage_info=generalization_coverage_info,
        generalization_coverage_summary=generalization_coverage_summary,
        gpu_annex_summary=gpu_annex_summary,
        phase1_evidence_closure=phase1_evidence_closure,
        stage_gate=stage_recommendation_gate,
        public_recommendation=public_recommendation,
        projection_review=projection_review,
        stage_main_package=stage_main_recommendation_package,
    )
    if stage_artifact_bundle_manifest is not None:
        stage_artifact_bundle_manifest["component_registry_summary"] = component_registry_info[
            "summary"
        ]
        stage_artifact_bundle_manifest["json_path"] = str(
            args.output_dir / "qe_next_stage_artifact_bundle_manifest.json"
        )
        stage_artifact_bundle_manifest["md_path"] = str(
            args.output_dir / "qe_next_stage_artifact_bundle_manifest.md"
        )
        stage_artifact_bundle_manifest["artifact_paths"]["component_registry_json"] = (
            component_registry_info["json_path"]
        )
        stage_artifact_bundle_manifest["artifact_paths"]["gpu_annex_json"] = str(
            gpu_annex_json_path
        )
        stage_artifact_bundle_manifest["artifact_paths"]["gpu_annex_md"] = str(
            gpu_annex_md_path
        )
        stage_artifact_bundle_manifest["artifact_paths"]["gpu_case_decision_sheet_json"] = str(
            gpu_case_decision_json_path
        )
        stage_artifact_bundle_manifest["artifact_paths"]["gpu_case_decision_sheet_md"] = str(
            gpu_case_decision_md_path
        )
        stage_artifact_bundle_manifest["artifact_paths"]["gpu_workload_group_manifest_json"] = str(
            gpu_workload_manifest_json_path
        )
        stage_artifact_bundle_manifest["artifact_paths"]["gpu_workload_group_manifest_md"] = str(
            gpu_workload_manifest_md_path
        )
        stage_artifact_bundle_manifest["artifact_paths"]["phase1_evidence_closure_json"] = (
            phase1_evidence_closure["json_path"]
        )
        stage_artifact_bundle_manifest["artifact_paths"]["phase1_evidence_closure_md"] = (
            phase1_evidence_closure["md_path"]
        )
        stage_artifact_bundle_manifest["artifact_paths"]["phase_summary_json"] = str(
            args.output_dir / "qe_next_stage_dse_phase_summary.json"
        )
        stage_artifact_bundle_manifest["artifact_paths"]["phase_summary_md"] = str(
            args.output_dir / "qe_next_stage_dse_phase_summary.md"
        )

    advisor_pack_summary = build_advisor_pack_summary(
        phase_id=config["phase_id"],
        phase_config_path=str(args.phase_config),
        stage_artifact_bundle_manifest=stage_artifact_bundle_manifest,
        public_recommendation=public_recommendation,
        best_point_summary=best_point_summary,
        gpu_annex_summary=gpu_annex_summary,
        phase1_evidence_closure=phase1_evidence_closure,
        projection_review=projection_review,
        stage_main_package=stage_main_recommendation_package,
    )
    if advisor_pack_summary is not None:
        advisor_pack_summary["json_path"] = str(
            args.output_dir / "qe_next_stage_advisor_pack_summary.json"
        )
        advisor_pack_summary["md_path"] = str(
            args.output_dir / "qe_next_stage_advisor_pack_summary.md"
        )
        if stage_artifact_bundle_manifest is not None:
            stage_artifact_bundle_manifest["artifact_paths"]["advisor_pack_json"] = advisor_pack_summary[
                "json_path"
            ]
            stage_artifact_bundle_manifest["artifact_paths"]["advisor_pack_md"] = advisor_pack_summary[
                "md_path"
            ]
    release_evidence_summary = None
    if stage_artifact_bundle_manifest is not None:
        summary_json_path = args.output_dir / "qe_next_stage_dse_phase_summary.json"
        release_evidence_summary = build_release_evidence_summary(
            phase_id=config["phase_id"],
            phase_config_path=str(args.phase_config),
            phase_runner_command=build_phase_runner_command(args),
            release_validator_command=build_release_validator_command(summary_json_path),
            manifest=stage_artifact_bundle_manifest,
            public_recommendation=public_recommendation,
            gpu_annex_summary=gpu_annex_summary,
            phase1_evidence_closure=phase1_evidence_closure,
            best_point_summary=best_point_summary,
            advisor_pack_summary=advisor_pack_summary,
        )
        release_evidence_summary["json_path"] = str(
            args.output_dir / "qe_next_stage_release_evidence.json"
        )
        release_evidence_summary["md_path"] = str(
            args.output_dir / "qe_next_stage_release_evidence.md"
        )
        stage_artifact_bundle_manifest["artifact_paths"]["release_evidence_json"] = (
            release_evidence_summary["json_path"]
        )
        stage_artifact_bundle_manifest["artifact_paths"]["release_evidence_md"] = (
            release_evidence_summary["md_path"]
        )
        if advisor_pack_summary is not None:
            advisor_pack_summary["artifact_paths"]["release_evidence_json"] = (
                release_evidence_summary["json_path"]
            )
            advisor_pack_summary["artifact_paths"]["release_evidence_md"] = (
                release_evidence_summary["md_path"]
            )

    summary_json = args.output_dir / "qe_next_stage_dse_phase_summary.json"
    summary_md = args.output_dir / "qe_next_stage_dse_phase_summary.md"
    gpu_annex_json_path.write_text(
        json.dumps(gpu_annex_summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    gpu_annex_md_path.write_text(
        render_gpu_annex_summary_md(gpu_annex_summary),
        encoding="utf-8",
    )
    gpu_case_decision_json_path.write_text(
        json.dumps(gpu_annex_summary["case_decision_sheet"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    gpu_case_decision_md_path.write_text(
        render_gpu_case_decision_sheet_md(gpu_annex_summary["case_decision_sheet"]),
        encoding="utf-8",
    )
    gpu_workload_manifest_json_path.write_text(
        json.dumps(gpu_annex_summary["workload_group_gpu_column_manifest"], indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    gpu_workload_manifest_md_path.write_text(
        render_gpu_workload_group_manifest_md(gpu_annex_summary["workload_group_gpu_column_manifest"]),
        encoding="utf-8",
    )
    if advisor_pack_summary is not None:
        Path(advisor_pack_summary["json_path"]).write_text(
            json.dumps(advisor_pack_summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        Path(advisor_pack_summary["md_path"]).write_text(
            render_advisor_pack_summary_md(advisor_pack_summary),
            encoding="utf-8",
        )
    if release_evidence_summary is not None:
        Path(release_evidence_summary["json_path"]).write_text(
            json.dumps(release_evidence_summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        Path(release_evidence_summary["md_path"]).write_text(
            render_release_evidence_summary_md(release_evidence_summary),
            encoding="utf-8",
        )
    if projection_review is not None:
        Path(projection_review["json_path"]).write_text(
            json.dumps(projection_review, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        Path(projection_review["md_path"]).write_text(
            render_projection_review_md(projection_review),
            encoding="utf-8",
        )
    if stage_main_recommendation_package is not None:
        Path(stage_main_recommendation_package["json_path"]).write_text(
            json.dumps(stage_main_recommendation_package, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        Path(stage_main_recommendation_package["md_path"]).write_text(
            render_stage_main_recommendation_md(stage_main_recommendation_package),
            encoding="utf-8",
        )
    if stage_artifact_bundle_manifest is not None:
        Path(stage_artifact_bundle_manifest["json_path"]).write_text(
            json.dumps(stage_artifact_bundle_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        Path(stage_artifact_bundle_manifest["md_path"]).write_text(
            render_stage_artifact_bundle_manifest_md(stage_artifact_bundle_manifest),
            encoding="utf-8",
        )

    stage_main_evidence_path = None
    if stage_main_recommendation_package is not None:
        stage_main_evidence_path = Path(stage_main_recommendation_package["json_path"])
    board_closure_path = None
    for board_dir in args.board_dir:
        matches = sorted(board_dir.glob("board_compare.json"))
        if matches:
            board_closure_path = matches[0]
            break
        matches = sorted(board_dir.glob("*.board_compare.json"))
        if matches:
            board_closure_path = matches[0]
            break
    adjudicator_reference = build_adjudicator_reference_payload(
        output_dir=args.output_dir,
        dse_bundle_path=Path(accurate_info["json_path"]),
        gpu_annex_path=gpu_annex_json_path,
        phase1_closure_path=Path(phase1_evidence_closure["json_path"]),
        board_closure_path=board_closure_path,
        stage_main_evidence_path=stage_main_evidence_path,
    )
    write_json_text(Path(adjudicator_reference["reference_path"]), adjudicator_reference)

    summary = {
        "schema_version": "qe_next_stage_dse_phase_summary_v0",
        "phase_id": config["phase_id"],
        "phase_config_path": str(args.phase_config),
        "case_pack_path": None if args.case_pack is None else str(args.case_pack),
        "case_pack_summary": case_pack_summary,
        "decision_authority": {
            "authority_scope": "adjudicator_only",
            "adjudicator_reference_path": adjudicator_reference["reference_path"],
            "reference_status": adjudicator_reference["reference_status"],
            "decision_memo_json": adjudicator_reference.get("decision_memo_json"),
            "decision_memo_md": adjudicator_reference.get("decision_memo_md"),
        },
        "component_registry": component_registry_info,
        "execute_model": args.execute_model,
        "source_kind": args.source_kind,
        "public_recommendation": public_recommendation,
        "gpu_annex_summary": gpu_annex_summary,
        "phase1_evidence_closure": phase1_evidence_closure,
        "best_point_summary": best_point_summary,
        "release_evidence_summary": release_evidence_summary,
        "adjudicator_reference": adjudicator_reference,
        "projection_review": projection_review,
        "stage_main_recommendation_package": stage_main_recommendation_package,
        "stage_artifact_bundle_manifest": stage_artifact_bundle_manifest,
        "advisor_pack_summary": advisor_pack_summary,
        "fast_layer": {
            **fast_info,
            "primary_objective": config["layers"]["fast_layer"]["primary_objective"],
            "secondary_objective": config["layers"]["fast_layer"]["secondary_objective"],
            "constraint_metrics": config["layers"]["fast_layer"]["constraint_metrics"],
            "promotion_policy": config["promotion_policy"],
            "shortlists": annotated_shortlists,
        },
        "accurate_layer": {
            **accurate_info,
            "validation_targets": validation_targets,
            "validation_summary_by_source_workload": validation_summary_by_source_workload,
            "stage_recommendation_gate": stage_recommendation_gate,
        },
    }
    if accurate_coverage_info is not None:
        summary["accurate_coverage"] = accurate_coverage_info
        summary["accurate_coverage"]["summary"] = accurate_coverage_summary
    if generalization_coverage_info is not None:
        summary["generalization_coverage"] = generalization_coverage_info
        summary["generalization_coverage"]["summary"] = generalization_coverage_summary
    summary["fast_layer"]["authority_scope"] = "supporting_evidence_only"
    summary["accurate_layer"]["authority_scope"] = "supporting_evidence_only"

    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary_md.write_text(render_summary_md(summary), encoding="utf-8")
    print(summary_json)
    print(summary_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
