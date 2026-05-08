#!/usr/bin/env python3
"""GPU baseline acquisition status reporter.

This script no longer fabricates benchmark numbers. It preflights the current
GPU/software environment and writes truthful manifests:
- `completed` only when a real acquisition backend is present and a manifest is
  supplied by the caller
- `deferred_oom` when the GPU exists but the estimated working set is too large
- `deferred_software_stack` when GPU / CUDA / QE execution support is missing

The current repository does not wire a synthetic fallback path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CORE_CASES = [
    "si8_pbe_nc",
    "si8_pbe_uspp",
    "si4_pbe_uspp_small",
    "graphene_pbe_uspp",
    "au_slab_subspace",
    "sic32_subspace",
]

GPU_MODES = ["strict_fp64", "practical"]

CORRECTNESS_CONTRACT_ID = "qe_gold_correctness_contract_v0"
WORKLOAD_GROUP_ID = "qe_fpga_phase1_workload_group_v0"
FAIRNESS_POLICY_ID = "qe_cpu_gpu_fpga_fairness_and_power_contract_v0"
ALGORITHM_REWRITE_MANIFEST_ID = "qe_algorithm_rewrite_manifest_v0"
QE_TOLERANCE_SCHEMA_ID = "qe_gold_numerical_tolerance_schema_v0"
ACCOUNTING_BOUNDARY_ID = "scf_shell_convergence_scope_v1"
POWER_BOUNDARY_ID = "whole_node_steady_state_single_cpu_single_accelerator_v0"
WARMUP_POLICY = "symmetric_warmup_once"

CASE_PARAMS = {
    "si8_pbe_nc": {"npw": 4553, "nkb": 64, "nbnd": 16, "niters": 20},
    "si8_pbe_uspp": {"npw": 2945, "nkb": 144, "nbnd": 16, "niters": 20},
    "si4_pbe_uspp_small": {"npw": 1473, "nkb": 72, "nbnd": 8, "niters": 15},
    "graphene_pbe_uspp": {"npw": 1105, "nkb": 16, "nbnd": 4, "niters": 25},
    "au_slab_subspace": {"npw": 4800, "nkb": 240, "nbnd": 32, "niters": 30},
    "sic32_subspace": {"npw": 6400, "nkb": 320, "nbnd": 48, "niters": 35},
}


@dataclass
class GPUBaselineResult:
    case_id: str
    gpu_mode: str
    run_tag: str
    host_id: str
    gpu_id: str
    qe_rev: str
    baseline_state: str
    notes: List[str]
    success: bool
    error_message: str = ""
    measurements: Optional[Dict] = None


def _parse_memory_mib(raw: str) -> Optional[float]:
    try:
        token = raw.strip().split()[0]
        return float(token)
    except Exception:
        return None


def detect_gpu() -> Tuple[str, str, Dict]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,uuid,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            gpu_name = parts[0] if len(parts) > 0 else "unknown"
            gpu_uuid = parts[1] if len(parts) > 1 else "unknown"
            memory_total = parts[2] if len(parts) > 2 else "unknown"
            mem_mib = _parse_memory_mib(memory_total)
            fp64_ratio = _estimate_fp64_ratio(gpu_name)
            return gpu_name, gpu_uuid, {
                "available": True,
                "memory_total": memory_total,
                "memory_total_mib": mem_mib,
                "fp64_ratio_vs_fp32": fp64_ratio,
                "supports_strict_fp64": fp64_ratio > 0.01,
            }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return "no_gpu_detected", "N/A", {
        "available": False,
        "memory_total": "N/A",
        "memory_total_mib": None,
        "fp64_ratio_vs_fp32": 0.0,
        "supports_strict_fp64": False,
    }


def _estimate_fp64_ratio(gpu_name: str) -> float:
    name_lower = gpu_name.lower()
    if "a100" in name_lower or "v100" in name_lower:
        return 0.5
    if "a6000" in name_lower:
        return 1.0 / 32.0
    if "rtx 4090" in name_lower:
        return 1.0 / 64.0
    if "rtx 3090" in name_lower:
        return 1.0 / 32.0
    if "rtx 3080" in name_lower:
        return 1.0 / 64.0
    if "rtx 3070" in name_lower:
        return 1.0 / 64.0
    if "rtx" in name_lower:
        return 1.0 / 32.0
    if "tesla" in name_lower or "quadro" in name_lower:
        return 0.5
    return 1.0 / 64.0


def estimate_working_set_mib(case_params: Dict) -> float:
    npw = case_params["npw"]
    nkb = case_params["nkb"]
    nbnd = case_params["nbnd"]
    bytes_est = 8.0 * (npw * nkb + nkb * nbnd + npw * nbnd)
    return bytes_est / (1024.0 * 1024.0)


def classify_deferred(case_params: Dict, gpu_caps: Dict, qe_bin: Optional[Path]) -> Tuple[str, str]:
    if not gpu_caps.get("available"):
        return "deferred_software_stack", "GPU unavailable or nvidia-smi missing"
    if qe_bin is None:
        return "deferred_software_stack", "QE binary path not supplied; acquisition backend not wired"
    mem_mib = gpu_caps.get("memory_total_mib")
    if mem_mib is not None:
        working_set = estimate_working_set_mib(case_params)
        if working_set > mem_mib * 0.85:
            return "deferred_oom", f"estimated working set {working_set:.1f} MiB exceeds safe GPU headroom on {mem_mib:.0f} MiB device"
    return "deferred_software_stack", "Real QE GPU acquisition backend is not implemented in this repository path"


def run_qe_gpu_baseline(case_id: str, gpu_mode: str, output_dir: Path, qe_bin: Optional[Path] = None, dry_run: bool = False) -> GPUBaselineResult:
    _ = output_dir
    _ = dry_run
    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    host_id = os.uname().nodename
    gpu_name, gpu_uuid, gpu_caps = detect_gpu()
    case_params = CASE_PARAMS[case_id]
    baseline_state, blocker = classify_deferred(case_params, gpu_caps, qe_bin)

    notes = [
        f"preflight blocker: {blocker}",
        "no synthetic measurements were generated",
    ]
    if gpu_mode == "practical":
        notes.append("practical mode requested, but acquisition remains deferred until a real backend is available")
    if gpu_mode == "strict_fp64" and not gpu_caps.get("supports_strict_fp64"):
        notes.append("strict_fp64 unsupported on detected GPU")

    return GPUBaselineResult(
        case_id=case_id,
        gpu_mode=gpu_mode,
        run_tag=run_tag,
        host_id=host_id,
        gpu_id=gpu_uuid,
        qe_rev="unavailable",
        baseline_state=baseline_state,
        notes=notes,
        success=False,
        error_message=blocker,
        measurements=None,
    )


def generate_manifest(result: GPUBaselineResult) -> Dict:
    manifest = {
        "schema_version": "qe_cpu_gpu_baseline_manifest_template_v0",
        "baseline_class": "CPU+GPU",
        "case_id": result.case_id,
        "gpu_mode": result.gpu_mode,
        "run_tag": result.run_tag,
        "host_id": result.host_id,
        "gpu_id": result.gpu_id,
        "qe_rev": result.qe_rev,
        "correctness_contract_id": CORRECTNESS_CONTRACT_ID,
        "workload_group_id": WORKLOAD_GROUP_ID,
        "fairness_policy_id": FAIRNESS_POLICY_ID,
        "algorithm_rewrite_manifest_id": ALGORITHM_REWRITE_MANIFEST_ID,
        "gpu_mode_attempts": [result.gpu_mode],
        "mode_attempt_exemption_note": result.error_message,
        "shared_rewrite_closed": False,
        "host_platform_comparable": False,
        "rewrite_mode": "none",
        "qe_tolerance_schema_id": QE_TOLERANCE_SCHEMA_ID,
        "accounting_boundary_id": ACCOUNTING_BOUNDARY_ID,
        "power_boundary_id": POWER_BOUNDARY_ID,
        "warmup_policy": WARMUP_POLICY,
        "host_normalization_note": "",
        "command": f"gpu_baseline_status_only_{result.case_id}_{result.gpu_mode}",
        "env": {"CUDA_VISIBLE_DEVICES": "N/A"},
        "artifact_paths": {},
        "baseline_state": result.baseline_state,
        "notes": result.notes,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if result.measurements is not None:
        manifest["measurements"] = result.measurements
    if result.error_message:
        manifest["error_message"] = result.error_message
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="GPU baseline acquisition status reporter for QE workloads")
    parser.add_argument("--case", type=str, choices=CORE_CASES, help="Run one case only")
    parser.add_argument("--mode", type=str, choices=GPU_MODES, default="strict_fp64", help="GPU precision mode")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for manifests")
    parser.add_argument("--dry-run", action="store_true", help="Retained for compatibility; emits status-only manifests")
    parser.add_argument("--qe-bin", type=Path, default=None, help="Path to QE pw.x binary")
    args = parser.parse_args()

    cases = [args.case] if args.case else CORE_CASES
    args.output_dir.mkdir(parents=True, exist_ok=True)

    gpu_name, gpu_uuid, gpu_caps = detect_gpu()
    print(f"GPU detected: {gpu_name}")
    print(f"GPU UUID: {gpu_uuid}")
    print(f"FP64/FP32 ratio: {gpu_caps['fp64_ratio_vs_fp32']:.4f}")
    print(f"Strict FP64 support: {gpu_caps['supports_strict_fp64']}")
    print()

    manifests = []
    for case_id in cases:
        print("=" * 60)
        print(f"Preflighting baseline: {case_id} / {args.mode}")
        print("=" * 60)
        result = run_qe_gpu_baseline(case_id, args.mode, args.output_dir, qe_bin=args.qe_bin, dry_run=args.dry_run)
        manifest = generate_manifest(result)
        manifests.append(manifest)

        case_dir = args.output_dir / case_id / args.mode / result.run_tag
        case_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = case_dir / "cpu_gpu_baseline_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"  Manifest written: {manifest_path}")
        print(f"  baseline_state: {manifest['baseline_state']}")
        print(f"  blocker: {result.error_message}")
        print()

    summary = {
        "schema_version": "gpu_baseline_summary_v0",
        "mode": args.mode,
        "gpu_name": gpu_name,
        "gpu_uuid": gpu_uuid,
        "gpu_capabilities": gpu_caps,
        "dry_run": bool(args.dry_run),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": len(manifests),
        "completed_count": sum(1 for m in manifests if m["baseline_state"] == "completed"),
        "deferred_oom_count": sum(1 for m in manifests if m["baseline_state"] == "deferred_oom"),
        "deferred_software_stack_count": sum(1 for m in manifests if m["baseline_state"] == "deferred_software_stack"),
        "manifests": manifests,
    }
    summary_path = args.output_dir / f"gpu_baseline_summary_{args.mode}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Summary written: {summary_path}")
    print()
    print("GPU baseline status report complete")
    print(f"Cases run: {len(manifests)}")
    print(f"Completed: {summary['completed_count']}")
    print(f"Deferred OOM: {summary['deferred_oom_count']}")
    print(f"Deferred software stack: {summary['deferred_software_stack_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
