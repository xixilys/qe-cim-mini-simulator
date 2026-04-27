from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check_qe_phase1_artifact_contracts.py")
SPEC = importlib.util.spec_from_file_location("check_qe_phase1_artifact_contracts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Phase1ArtifactContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = MODULE.load_runner_module()

    def test_repo_templates_pass_contract_validation(self) -> None:
        baseline = MODULE.load_json(MODULE.BASELINE_TEMPLATE_PATH)
        rewrite = MODULE.load_json(MODULE.REWRITE_TEMPLATE_PATH)
        MODULE.validate_baseline_manifest_template(baseline, self.runner, MODULE.BASELINE_TEMPLATE_PATH)
        MODULE.validate_algorithm_rewrite_manifest_template(
            rewrite,
            self.runner,
            MODULE.REWRITE_TEMPLATE_PATH,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = Path(tmpdir)
            template_map = {
                MODULE.DEFAULT_BOARD_FILES["manifest"]: "qe_fpga_board_manifest_template_v0.json",
                MODULE.DEFAULT_BOARD_FILES["metrics"]: "qe_fpga_board_metrics_template_v0.json",
                MODULE.DEFAULT_BOARD_FILES["power"]: "qe_fpga_board_power_template_v0.json",
                MODULE.DEFAULT_BOARD_FILES["compare"]: "qe_fpga_board_compare_template_v0.json",
            }
            for out_name, repo_name in template_map.items():
                src = MODULE.BENCHMARKS_DIR / repo_name
                (bundle_dir / out_name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            MODULE.validate_board_artifact_bundle(bundle_dir, self.runner)

    def test_board_bundle_passes_when_join_keys_and_ids_match(self) -> None:
        join_key = {
            "workload_id": "si4_pbe_uspp_small",
            "workload_group_id": self.runner.PHASE1_WORKLOAD_GROUP_ID,
            "architecture_family": "F2",
            "assumption_set_id": "phase1_calibrated_v0",
            "diag_policy": "device_first_fallback",
            "offload_scope": "balanced",
            "resident_policy": "fit_first",
            "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
            "accounting_boundary_id": "scf_shell_convergence_scope_v1",
            "fairness_policy_id": self.runner.PHASE1_FAIRNESS_POLICY_ID,
            "power_boundary_id": self.runner.PHASE1_POWER_BOUNDARY_ID,
            "observability_contract_id": self.runner.PHASE1_OBSERVABILITY_CONTRACT_ID,
            "algorithm_rewrite_manifest_id": self.runner.PHASE1_REWRITE_MANIFEST_ID,
            "algorithm_contract_deviation": False,
            "request_id": "REQ-001",
            "scf_iteration": 6,
            "episode_id": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = Path(tmpdir)
            self.write_bundle(bundle_dir, join_key)
            MODULE.validate_board_artifact_bundle(bundle_dir, self.runner)

    def test_board_bundle_rejects_join_key_drift(self) -> None:
        join_key = {
            "workload_id": "graphene_pbe_uspp",
            "workload_group_id": self.runner.PHASE1_WORKLOAD_GROUP_ID,
            "architecture_family": "F1",
            "assumption_set_id": "phase1_calibrated_v0",
            "diag_policy": "cpu_only",
            "offload_scope": "single_hotpath",
            "resident_policy": "fit_first",
            "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
            "accounting_boundary_id": "scf_shell_convergence_scope_v1",
            "fairness_policy_id": self.runner.PHASE1_FAIRNESS_POLICY_ID,
            "power_boundary_id": self.runner.PHASE1_POWER_BOUNDARY_ID,
            "observability_contract_id": self.runner.PHASE1_OBSERVABILITY_CONTRACT_ID,
            "algorithm_rewrite_manifest_id": self.runner.PHASE1_REWRITE_MANIFEST_ID,
            "algorithm_contract_deviation": False,
            "request_id": "REQ-001",
            "scf_iteration": None,
            "episode_id": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = Path(tmpdir)
            self.write_bundle(bundle_dir, join_key)
            metrics = MODULE.load_json(bundle_dir / MODULE.DEFAULT_BOARD_FILES["metrics"])
            metrics["join_key"]["architecture_family"] = "F2"
            (bundle_dir / MODULE.DEFAULT_BOARD_FILES["metrics"]).write_text(
                json.dumps(metrics, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MODULE.ValidationError, "board_metrics join_key must match"):
                MODULE.validate_board_artifact_bundle(bundle_dir, self.runner)

    def write_bundle(self, bundle_dir: Path, join_key: dict[str, object]) -> None:
        payloads = {
            MODULE.DEFAULT_BOARD_FILES["manifest"]: {
                "schema_version": "qe_fpga_board_manifest_template_v0",
                "artifact_kind": "board_manifest",
                "board_manifest_id": "qe_fpga_board_manifest_v0",
                "board_run_id": "BOARD-RUN-001",
                "generated_at_utc": "2026-04-14T00:00:00Z",
                **join_key,
                "claim_ids_supported": ["CL1", "CL2", "CL3"],
                "board_system": {
                    "host_id": "host-a",
                    "fpga_board_id": "u55c-lab-a",
                    "fpga_image_id": "image-001",
                    "driver_rev": "drv-1",
                    "runtime_rev": "rt-1",
                    "qe_rev": "qe-1",
                },
                "ref_cycle_contract": {
                    "ref_clock_hz": 250000000,
                    "ref_cycle_unit": "cycles_at_ref_clock",
                    "normalization_note": "250mhz_ref_cycle_v0",
                },
                "measurement_boundary": {
                    "start_event": "qe_wrapper_launch",
                    "stop_event": "qe_wrapper_exit",
                    "boundary_note": "whole_qe_run_wrapper_v0",
                },
                "artifact_paths": {
                    "stdout_path": "stdout.txt",
                    "metrics_path": "board_metrics.json",
                    "power_path": "board_power.json",
                    "compare_report_path": "board_compare.json",
                    "command_log_path": "cmd.log",
                    "env_snapshot_path": "env.json",
                },
            },
            MODULE.DEFAULT_BOARD_FILES["metrics"]: {
                "schema_version": "qe_fpga_board_metrics_template_v0",
                "artifact_kind": "board_metrics",
                "board_run_id": "BOARD-RUN-001",
                "join_key": join_key,
                "obs_rows_present": ["OBS-01", "OBS-02"],
                "timing": {
                    "wall_time_s": 12.5,
                    "scf_iterations_to_convergence": 6,
                    "iteration_wall_times_s": [2.0, 2.1],
                    "qe_stdout_total_time_s": 12.5,
                    "electrons_total_time_s": 11.9,
                },
                "data_movement": {
                    "total_data_movement_kib": 1024.0,
                    "dma_read_kib": 512.0,
                    "dma_write_kib": 512.0,
                    "dma_ledger_closure_abs_kib": 0.0,
                },
                "cycles": {
                    "device_busy_ref_cycles": 1000000,
                    "dma_ref_cycles": 120000,
                    "host_assist_ref_cycles": 42000,
                    "accounted_ref_cycles": 1162000,
                    "accounted_backpressure_ref_cycles": 20000,
                    "backpressure_ratio": 0.02,
                },
                "policy_counters": {
                    "cpu_fallbacks": 0,
                    "fallback_ratio": 0.0,
                    "resident_reuse_hits": 18,
                    "resident_reuse_ratio": 0.9,
                    "spill_events": 0,
                    "spill_ratio": 0.0,
                },
                "counter_sources": {
                    "dma_bytes_source": "dma",
                    "device_busy_source": "device",
                    "host_assist_source": "host",
                    "fallback_source": "runtime",
                    "resident_source": "runtime",
                    "spill_source": "runtime",
                    "timeline_source": "timeline",
                },
                "raw_trace_paths": [],
                "notes": [],
            },
            MODULE.DEFAULT_BOARD_FILES["power"]: {
                "schema_version": "qe_fpga_board_power_template_v0",
                "artifact_kind": "board_power",
                "board_run_id": "BOARD-RUN-001",
                "join_key": {k: v for k, v in join_key.items() if k not in {"qe_tolerance_schema_id", "scf_iteration", "episode_id"}},
                "obs_rows_present": ["OBS-12", "OBS-13"],
                "power_window": {
                    "start_event": "qe_wrapper_launch",
                    "stop_event": "qe_wrapper_exit",
                    "warmup_policy": "symmetric_warmup_once",
                    "sampling_period_ms": None,
                },
                "total_energy": {
                    "energy_to_convergence_j": 140.0,
                    "avg_power_w": 70.0,
                    "peak_power_w": 95.0,
                },
                "energy_ledger": {
                    "E_host_j": 65.0,
                    "E_device_runtime_j": 45.0,
                    "E_dma_j": 10.0,
                    "E_hardware_datapath_j": 15.0,
                    "E_idle_static_j": 5.0,
                    "ledger_total_j": 140.0,
                    "ledger_closure_rel_err": 0.0,
                },
                "measurement_sources": {
                    "host_energy_source": "host_meter",
                    "fpga_board_energy_source": "board_meter",
                    "idle_static_accounting_note": "whole-node steady-state",
                    "rail_split_note": "estimated",
                },
                "confidence": {
                    "power_claim_ready": True,
                    "confidence_grade": "measured",
                    "downgrade_reasons": [],
                },
                "notes": [],
            },
            MODULE.DEFAULT_BOARD_FILES["compare"]: {
                "schema_version": "qe_fpga_board_compare_template_v0",
                "artifact_kind": "board_compare",
                "board_run_id": "BOARD-RUN-001",
                "join_key": {k: v for k, v in join_key.items() if k not in {"scf_iteration", "episode_id"}},
                "obs_rows_present": ["OBS-03", "OBS-14"],
                "correctness": {
                    "status": "pass",
                    "gold_pass": True,
                    "convergence_comparable_pass": True,
                    "final_total_energy_match": True,
                    "residual_threshold_state_match": True,
                    "converged_state_match": True,
                    "required_field_failures": [],
                    "baseline_scf_iterations": 6,
                    "candidate_scf_iterations": 6,
                    "final_total_energy_abs_err_ev": 0.0,
                    "final_total_energy_rel_err": 0.0,
                    "notes": [],
                },
                "projection_cross_check": {
                    "speedup_to_convergence_range": {"lower": 1.9, "upper": 2.1, "units": "x"},
                    "energy_to_convergence_range_j": {"lower": 120.0, "upper": 150.0, "units": "J"},
                    "realized_speedup_to_convergence": 2.0,
                    "realized_energy_to_convergence_j": 140.0,
                    "projection_confidence": "high",
                    "ranking_grade_ready": True,
                    "projection_grade_ready": True,
                    "range_margin_rel": 0.0,
                    "projection_consistency_status": "pass",
                },
                "claim_dependency_ids": ["CL3", "CL4", "CL6"],
                "compare_inputs": {
                    "gold_baseline_path": "gold.json",
                    "candidate_report_path": "candidate.json",
                    "simulator_projection_source": "projection.json",
                },
                "notes": [],
            },
        }
        for name, payload in payloads.items():
            (bundle_dir / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
