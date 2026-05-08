#!/usr/bin/env python3
"""
Test Fixture Generator

Generates mock DSE results and GPU baselines for integration testing
without requiring a real GPU or actual QE execution.

Generated fixtures:
  - Layer 1 (analytical) results
  - Layer 2 (SystemC TLM) results
  - Layer 3 (cycle-accurate proxy) results
  - Mock GPU baselines for all 6 core cases
  - Confidence validation test data

Usage:
    python3 tests/fixtures/generate_test_fixtures.py --output-dir tests/fixtures/data

    # Regenerate specific fixture
    python3 tests/fixtures/generate_test_fixtures.py --output-dir tests/fixtures/data --fixture gpu_baselines
"""

import json
import argparse
import math
import random
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List


# ============================================================================
# Constants
# ============================================================================

CORE_CASES = [
    "si8_pbe_nc",
    "si8_pbe_uspp",
    "si4_pbe_uspp_small",
    "graphene_pbe_uspp",
    "au_slab_subspace",
    "sic32_subspace",
]

CASE_PARAMS = {
    "si8_pbe_nc": {"npw": 2945, "nkb": 144, "nbnd": 16, "niters": 20},
    "si8_pbe_uspp": {"npw": 2945, "nkb": 144, "nbnd": 16, "niters": 20},
    "si4_pbe_uspp_small": {"npw": 1473, "nkb": 72, "nbnd": 8, "niters": 15},
    "graphene_pbe_uspp": {"npw": 3200, "nkb": 160, "nbnd": 20, "niters": 25},
    "au_slab_subspace": {"npw": 4800, "nkb": 240, "nbnd": 32, "niters": 30},
    "sic32_subspace": {"npw": 6400, "nkb": 320, "nbnd": 48, "niters": 35},
}

FAMILY_VARIANTS = ["F1", "F2", "F3", "F4", "F5", "F6"]

random.seed(42)


# ============================================================================
# Layer 1: Analytical Results
# ============================================================================

def generate_layer1_results() -> Dict:
    results = []
    for case_id in CORE_CASES:
        params = CASE_PARAMS[case_id]
        npw, nkb, nbnd, niters = params["npw"], params["nkb"], params["nbnd"], params["niters"]

        total_flops = (
            2.0 * npw * nkb * nbnd * niters * 2 +  # h_psi + s_psi
            2.0 * npw * nbnd * nbnd * niters +       # build_H_sub
            10.0 * nbnd ** 3 * niters +              # cdiaghg
            8.0 * npw * nbnd * niters                # refresh
        )

        for family in FAMILY_VARIANTS:
            family_factor = {"F1": 0.6, "F2": 0.8, "F3": 0.9, "F4": 1.0, "F5": 0.85, "F6": 0.75}
            factor = family_factor.get(family, 0.7)
            noise = random.uniform(0.9, 1.1)

            latency_s = (total_flops / 500e9) * noise / factor
            throughput_gops = total_flops / latency_s / 1e9
            power_w = 60 + 10 * FAMILY_VARIANTS.index(family)

            results.append({
                "case_id": case_id,
                "family": family,
                "fidelity": "L0",
                "latency_s": latency_s,
                "throughput_gops": throughput_gops,
                "power_w": power_w,
                "accuracy": 0.50,
                "total_flops": total_flops,
            })

    return {
        "schema_version": "dse_layer1_results_v0",
        "fidelity": "L0",
        "model": "analytical",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "result_count": len(results),
        "results": results,
    }


# ============================================================================
# Layer 2: SystemC TLM Results
# ============================================================================

def generate_layer2_results() -> Dict:
    results = []
    for case_id in CORE_CASES:
        params = CASE_PARAMS[case_id]
        npw, nkb, nbnd, niters = params["npw"], params["nkb"], params["nbnd"], params["niters"]

        total_flops = (
            2.0 * npw * nkb * nbnd * niters * 2 +
            2.0 * npw * nbnd * nbnd * niters +
            10.0 * nbnd ** 3 * niters +
            8.0 * npw * nbnd * niters
        )

        for family in FAMILY_VARIANTS:
            family_factor = {"F1": 0.55, "F2": 0.75, "F3": 0.85, "F4": 0.95, "F5": 0.80, "F6": 0.70}
            factor = family_factor.get(family, 0.65)
            noise = random.uniform(0.95, 1.05)

            latency_s = (total_flops / 500e9) * noise / factor
            throughput_gops = total_flops / latency_s / 1e9
            power_w = 55 + 12 * FAMILY_VARIANTS.index(family)
            compute_util = random.uniform(0.65, 0.85)
            memory_util = random.uniform(0.50, 0.75)

            results.append({
                "case_id": case_id,
                "family": family,
                "fidelity": "L2",
                "latency_s": latency_s,
                "throughput_gops": throughput_gops,
                "power_w": power_w,
                "accuracy": 0.85,
                "total_flops": total_flops,
                "compute_utilization": compute_util,
                "memory_utilization": memory_util,
                "systemc_cycles": int(latency_s * 1e9),
            })

    return {
        "schema_version": "dse_layer2_results_v0",
        "fidelity": "L2",
        "model": "systemc_tlm",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "result_count": len(results),
        "results": results,
    }


# ============================================================================
# Layer 3: Cycle-Accurate Proxy Results
# ============================================================================

def generate_layer3_results() -> Dict:
    results = []
    for case_id in CORE_CASES[:3]:
        params = CASE_PARAMS[case_id]
        npw, nkb, nbnd, niters = params["npw"], params["nkb"], params["nbnd"], params["niters"]

        total_flops = (
            2.0 * npw * nkb * nbnd * niters * 2 +
            2.0 * npw * nbnd * nbnd * niters +
            10.0 * nbnd ** 3 * niters +
            8.0 * npw * nbnd * niters
        )

        for family in ["F4"]:
            noise = random.uniform(0.98, 1.02)
            latency_s = (total_flops / 500e9) * noise / 0.95
            throughput_gops = total_flops / latency_s / 1e9

            results.append({
                "case_id": case_id,
                "family": family,
                "fidelity": "L3",
                "latency_s": latency_s,
                "throughput_gops": throughput_gops,
                "power_w": 63,
                "accuracy": 0.95,
                "total_flops": total_flops,
                "compute_utilization": random.uniform(0.75, 0.90),
                "memory_utilization": random.uniform(0.60, 0.80),
                "systemc_cycles": int(latency_s * 1e9),
                "cycle_breakdown": {
                    "gemm_cycles": int(latency_s * 1e9 * 0.65),
                    "eigen_cycles": int(latency_s * 1e9 * 0.20),
                    "memory_cycles": int(latency_s * 1e9 * 0.10),
                    "control_cycles": int(latency_s * 1e9 * 0.05),
                },
            })

    return {
        "schema_version": "dse_layer3_results_v0",
        "fidelity": "L3",
        "model": "cycle_accurate_proxy",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "result_count": len(results),
        "results": results,
    }


# ============================================================================
# Mock GPU Baselines
# ============================================================================

def generate_gpu_baselines() -> Dict:
    manifests = []
    for case_id in CORE_CASES:
        params = CASE_PARAMS[case_id]
        npw, nkb, nbnd, niters = params["npw"], params["nkb"], params["nbnd"], params["niters"]

        total_flops = (
            2.0 * npw * nkb * nbnd * niters * 2 +
            2.0 * npw * nbnd * nbnd * niters +
            10.0 * nbnd ** 3 * niters +
            8.0 * npw * nbnd * niters
        )

        for gpu_mode in ["strict_fp64", "practical"]:
            if gpu_mode == "strict_fp64":
                effective_gflops = random.uniform(0.15, 0.25)
            else:
                effective_gflops = random.uniform(8.0, 15.0)

            time_to_convergence_s = total_flops / (effective_gflops * 1e9)

            stage_fractions = {
                "h_psi": 0.45,
                "s_psi": 0.25,
                "build_H_sub": 0.15,
                "cdiaghg": 0.10,
                "refresh": 0.05,
            }
            per_stage_time_s = {
                stage: time_to_convergence_s * frac
                for stage, frac in stage_fractions.items()
            }

            power_w = 220 * 0.75 if gpu_mode == "strict_fp64" else 220 * 0.85

            manifest = {
                "schema_version": "qe_cpu_gpu_baseline_manifest_template_v0",
                "baseline_class": "CPU+GPU",
                "case_id": case_id,
                "gpu_mode": gpu_mode,
                "run_tag": "20260508-120000",
                "host_id": "mock-host",
                "gpu_id": "mock-gpu-rtx3070",
                "qe_rev": "mock-qe-7.5",
                "correctness_contract_id": "qe_gold_correctness_contract_v0",
                "workload_group_id": "qe_fpga_phase1_workload_group_v0",
                "fairness_policy_id": "qe_cpu_gpu_fpga_fairness_and_power_contract_v0",
                "algorithm_rewrite_manifest_id": "qe_algorithm_rewrite_manifest_v0",
                "gpu_mode_attempts": [gpu_mode],
                "mode_attempt_exemption_note": "",
                "shared_rewrite_closed": False,
                "host_platform_comparable": False,
                "rewrite_mode": "none",
                "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                "accounting_boundary_id": "scf_shell_convergence_scope_v1",
                "power_boundary_id": "whole_node_steady_state_single_cpu_single_accelerator_v0",
                "warmup_policy": "symmetric_warmup_once",
                "host_normalization_note": "",
                "command": f"mock_qe_run_{case_id}_{gpu_mode}",
                "env": {"CUDA_VISIBLE_DEVICES": "0"},
                "artifact_paths": {
                    "stdout": f"qe_{case_id}__cpu_gpu__{gpu_mode}__20260508-120000.stdout.txt",
                    "stderr": f"qe_{case_id}__cpu_gpu__{gpu_mode}__20260508-120000.stderr.txt",
                    "timing": f"qe_{case_id}__cpu_gpu__{gpu_mode}__20260508-120000.timing.json",
                    "correctness": f"qe_{case_id}__cpu_gpu__{gpu_mode}__20260508-120000.correctness.json",
                    "convergence": f"qe_{case_id}__cpu_gpu__{gpu_mode}__20260508-120000.convergence.json",
                    "power": f"qe_{case_id}__cpu_gpu__{gpu_mode}__20260508-120000.power.json",
                    "summary": f"qe_{case_id}__cpu_gpu__{gpu_mode}__20260508-120000.summary.md",
                },
                "baseline_state": "completed",
                "notes": ["MOCK DATA: Generated for testing purposes only"],
                "measurements": {
                    "time_to_convergence_s": time_to_convergence_s,
                    "per_stage_time_s": per_stage_time_s,
                    "effective_gflops": effective_gflops,
                    "avg_gpu_board_power_w": power_w,
                    "total_flops": total_flops,
                    "correctness_validated": True,
                },
                "gpu_capabilities": {
                    "fp64_ratio_vs_fp32": 1.0 / 64.0,
                    "is_approximate": gpu_mode == "practical",
                },
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            manifests.append(manifest)

    return {
        "schema_version": "gpu_baseline_summary_v0",
        "mode": "all",
        "gpu_name": "NVIDIA GeForce RTX 3070 (MOCK)",
        "gpu_uuid": "mock-uuid-12345",
        "gpu_capabilities": {
            "memory_total": "8192 MiB",
            "fp64_ratio_vs_fp32": 1.0 / 64.0,
            "supports_strict_fp64": True,
        },
        "dry_run": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": len(manifests),
        "manifests": manifests,
    }


# ============================================================================
# Confidence Validation Test Data
# ============================================================================

def generate_confidence_test_data() -> Dict:
    dse_predictions = {}
    gpu_baselines = {}

    for case_id in CORE_CASES:
        params = CASE_PARAMS[case_id]
        npw, nkb, nbnd, niters = params["npw"], params["nkb"], params["nbnd"], params["niters"]

        total_flops = (
            2.0 * npw * nkb * nbnd * niters * 2 +
            2.0 * npw * nbnd * nbnd * niters +
            10.0 * nbnd ** 3 * niters +
            8.0 * npw * nbnd * niters
        )

        actual_latency_s = total_flops / (10.0 * 1e9)
        noise = random.uniform(0.85, 1.15)
        predicted_latency_s = actual_latency_s * noise

        dse_predictions[case_id] = {
            "latency_s": predicted_latency_s,
            "throughput_gops": total_flops / predicted_latency_s / 1e9,
            "power_w": 63,
            "family": "F4",
        }

        gpu_baselines[case_id] = {
            "latency_s": actual_latency_s,
            "effective_gflops": 10.0,
            "avg_gpu_board_power_w": 165.0,
            "gpu_mode": "strict_fp64",
            "baseline_state": "completed",
        }

    return {
        "dse_predictions": dse_predictions,
        "gpu_baselines": gpu_baselines,
        "expected_weighted_mape_range": [0.05, 0.15],
        "expected_coverage_range": [0.6, 1.0],
    }


# ============================================================================
# 3-Layer Pipeline Integration Test Data
# ============================================================================

def generate_pipeline_test_data() -> Dict:
    case_id = "si4_pbe_uspp_small"
    params = CASE_PARAMS[case_id]
    npw, nkb, nbnd, niters = params["npw"], params["nkb"], params["nbnd"], params["niters"]

    total_flops = (
        2.0 * npw * nkb * nbnd * niters * 2 +
        2.0 * npw * nbnd * nbnd * niters +
        10.0 * nbnd ** 3 * niters +
        8.0 * npw * nbnd * niters
    )

    workload_profile = {
        "schema_version": "workload_profile_v1",
        "workload_id": case_id,
        "source": {"software": "Quantum ESPRESSO", "version": "7.5", "case": case_id},
        "compute_graph": {
            "nodes": [
                {"id": "h_psi", "type": "GEMM", "dominance": 0.45,
                 "flops_per_call": 2.0 * npw * nkb * nbnd, "call_count": niters,
                 "typical_sizes": {"M": [nbnd], "N": [npw], "K": [nkb]}},
                {"id": "s_psi", "type": "GEMM", "dominance": 0.25,
                 "flops_per_call": 2.0 * npw * nkb * nbnd, "call_count": niters,
                 "typical_sizes": {"M": [nbnd], "N": [npw], "K": [nkb]}},
                {"id": "build_H_sub", "type": "REDUCTION", "dominance": 0.15,
                 "flops_per_call": 2.0 * npw * nbnd * nbnd, "call_count": niters,
                 "typical_sizes": {"M": [nbnd], "N": [nbnd], "K": [npw]}},
                {"id": "cdiaghg", "type": "EIGEN", "dominance": 0.10,
                 "flops_per_call": 10.0 * nbnd ** 3, "call_count": niters,
                 "typical_sizes": {"N": [nbnd], "M": [nbnd]}},
                {"id": "refresh", "type": "VECTOR", "dominance": 0.05,
                 "flops_per_call": 8.0 * npw * nbnd, "call_count": niters,
                 "typical_sizes": {"M": [nbnd], "N": [npw]}},
            ],
            "edges": [
                {"from": "h_psi", "to": "build_H_sub", "data_type": "Hpsi(G)"},
                {"from": "s_psi", "to": "build_H_sub", "data_type": "Spsi(G)"},
                {"from": "build_H_sub", "to": "cdiaghg", "data_type": "H_sub/S_sub"},
                {"from": "cdiaghg", "to": "refresh", "data_type": "eigenvectors"},
            ],
        },
        "execution_profile": {"total_iterations": niters, "stability": "converging"},
        "memory_profile": {"working_set_mb": 0.001, "peak_mb": 0.002},
        "data_movement": {"host_to_device_mb_per_iter": 0.001},
    }

    architecture_spec = {
        "schema_version": "architecture_spec_v1",
        "spec_id": f"arch_{case_id}",
        "selected_family": "F4",
        "family_rationale": "Tile-based architecture matches GEMM-heavy workload",
        "partition": {
            "host_scope": ["rho_Veff", "mix_rho", "convergence"],
            "device_scope": ["h_psi", "s_psi", "build_H_sub", "refresh"],
            "fallback_scope": ["cdiaghg"],
        },
    }

    design_point = {
        "schema_version": "design_point_v1",
        "design_point_id": f"dp_{case_id}_001",
        "parameters": {
            "system_level": {
                "family": "F4",
                "n_gemm_tiles": 6,
                "n_eigen_tiles": 2,
                "tile_local_mem_kb": 1024,
                "mesh_topology": "2x4",
                "tile_link_bw_gbps": 64,
            }
        },
    }

    layer1_results = {
        "schema_version": "dse_layer1_results_v0",
        "fidelity": "L0",
        "results": [{
            "case_id": case_id,
            "family": "F4",
            "latency_s": total_flops / (400e9),
            "throughput_gops": 400.0,
            "power_w": 60.0,
            "accuracy": 0.50,
        }],
    }

    layer2_results = {
        "schema_version": "dse_layer2_results_v0",
        "fidelity": "L2",
        "results": [{
            "case_id": case_id,
            "family": "F4",
            "latency_s": total_flops / (475e9),
            "throughput_gops": 475.0,
            "power_w": 63.0,
            "accuracy": 0.85,
            "systemc_cycles": int(total_flops / 475e9 * 1e9),
        }],
    }

    layer3_results = {
        "schema_version": "dse_layer3_results_v0",
        "fidelity": "L3",
        "results": [{
            "case_id": case_id,
            "family": "F4",
            "latency_s": total_flops / (475e9) * 1.02,
            "throughput_gops": 465.0,
            "power_w": 63.0,
            "accuracy": 0.95,
            "systemc_cycles": int(total_flops / 475e9 * 1.02 * 1e9),
        }],
    }

    return {
        "workload_profile": workload_profile,
        "architecture_spec": architecture_spec,
        "design_point": design_point,
        "layer1_results": layer1_results,
        "layer2_results": layer2_results,
        "layer3_results": layer3_results,
    }


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate test fixtures for DSE pipeline testing")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Output directory for fixture data")
    parser.add_argument("--fixture", type=str,
                        choices=["all", "layer1", "layer2", "layer3", "gpu_baselines",
                                 "confidence", "pipeline"],
                        default="all", help="Which fixture to generate")

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    fixtures = {}

    if args.fixture in ["all", "layer1"]:
        layer1 = generate_layer1_results()
        path = args.output_dir / "layer1_results.json"
        path.write_text(json.dumps(layer1, indent=2))
        fixtures["layer1"] = str(path)
        print(f"Layer 1 results: {path} ({layer1['result_count']} entries)")

    if args.fixture in ["all", "layer2"]:
        layer2 = generate_layer2_results()
        path = args.output_dir / "layer2_results.json"
        path.write_text(json.dumps(layer2, indent=2))
        fixtures["layer2"] = str(path)
        print(f"Layer 2 results: {path} ({layer2['result_count']} entries)")

    if args.fixture in ["all", "layer3"]:
        layer3 = generate_layer3_results()
        path = args.output_dir / "layer3_results.json"
        path.write_text(json.dumps(layer3, indent=2))
        fixtures["layer3"] = str(path)
        print(f"Layer 3 results: {path} ({layer3['result_count']} entries)")

    if args.fixture in ["all", "gpu_baselines"]:
        gpu = generate_gpu_baselines()
        path = args.output_dir / "gpu_baseline_summary_all.json"
        path.write_text(json.dumps(gpu, indent=2))
        fixtures["gpu_baselines"] = str(path)
        print(f"GPU baselines: {path} ({gpu['case_count']} manifests)")

    if args.fixture in ["all", "confidence"]:
        conf = generate_confidence_test_data()
        path = args.output_dir / "confidence_test_data.json"
        path.write_text(json.dumps(conf, indent=2))
        fixtures["confidence"] = str(path)
        print(f"Confidence test data: {path}")

    if args.fixture in ["all", "pipeline"]:
        pipeline = generate_pipeline_test_data()
        for key, data in pipeline.items():
            path = args.output_dir / f"pipeline_{key}.json"
            path.write_text(json.dumps(data, indent=2))
            fixtures[f"pipeline_{key}"] = str(path)
            print(f"Pipeline {key}: {path}")

    index = {
        "schema_version": "test_fixtures_index_v0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixture_count": len(fixtures),
        "fixtures": fixtures,
    }
    index_path = args.output_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2))
    print(f"\nIndex: {index_path}")
    print(f"Total fixtures generated: {len(fixtures)}")

    return 0


if __name__ == "__main__":
    exit(main())
