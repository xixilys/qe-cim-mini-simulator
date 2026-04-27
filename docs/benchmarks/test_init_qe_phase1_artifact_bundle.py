from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("init_qe_phase1_artifact_bundle.py")
SPEC = importlib.util.spec_from_file_location("init_qe_phase1_artifact_bundle", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

VALIDATOR_PATH = Path(__file__).with_name("check_qe_phase1_artifact_contracts.py")
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "check_qe_phase1_artifact_contracts", VALIDATOR_PATH
)
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC is not None
assert VALIDATOR_SPEC.loader is not None
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)


class InitPhase1ArtifactBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = MODULE.load_runner_module()

    def test_cpu_gpu_scaffold_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = type(
                "Args",
                (),
                {
                    "output_dir": tmpdir,
                    "case_id": "si4_pbe_uspp_small",
                    "gpu_mode": "strict_fp64",
                    "run_tag": "20260414-120000",
                    "host_id": "host-a",
                    "gpu_id": "gpu-a",
                    "qe_rev": "qe-rev",
                    "workload_group_id": self.runner.PHASE1_WORKLOAD_GROUP_ID,
                    "fairness_policy_id": self.runner.PHASE1_FAIRNESS_POLICY_ID,
                    "algorithm_rewrite_manifest_id": self.runner.PHASE1_REWRITE_MANIFEST_ID,
                    "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                    "accounting_boundary_id": "scf_shell_convergence_scope_v1",
                    "power_boundary_id": self.runner.PHASE1_POWER_BOUNDARY_ID,
                    "algorithm_contract_deviation": "none",
                    "command": "run-qe-gpu",
                    "cuda_visible_devices": "0",
                },
            )()
            paths = MODULE.scaffold_cpu_gpu(args)
            self.assertEqual(len(paths), 1)
            manifest_path = paths[0]
            self.assertTrue(manifest_path.exists())
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            VALIDATOR.validate_baseline_manifest_template(payload, self.runner, manifest_path)

    def test_fpga_board_scaffold_writes_validator_compatible_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = type(
                "Args",
                (),
                {
                    "output_dir": tmpdir,
                    "case_id": "si4_pbe_uspp_small",
                    "run_tag": "20260414-120000",
                    "host_id": "host-a",
                    "qe_rev": "qe-rev",
                    "workload_group_id": self.runner.PHASE1_WORKLOAD_GROUP_ID,
                    "fairness_policy_id": self.runner.PHASE1_FAIRNESS_POLICY_ID,
                    "power_boundary_id": self.runner.PHASE1_POWER_BOUNDARY_ID,
                    "observability_contract_id": self.runner.PHASE1_OBSERVABILITY_CONTRACT_ID,
                    "algorithm_rewrite_manifest_id": self.runner.PHASE1_REWRITE_MANIFEST_ID,
                    "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                    "accounting_boundary_id": "scf_shell_convergence_scope_v1",
                    "algorithm_contract_deviation": "none",
                    "family": "F2",
                    "assumption_set_id": "phase1_calibrated_v0",
                    "diag_policy": "device_first_fallback",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "request_id": "REQ-001",
                    "scf_iteration": 6,
                    "episode_id": 2,
                    "board_id": "u55c-a",
                    "fpga_image_id": "img-1",
                    "driver_rev": "drv-1",
                    "runtime_rev": "rt-1",
                    "board_run_id": "board-run-1",
                },
            )()
            paths = MODULE.scaffold_fpga_board(args)
            self.assertEqual(len(paths), 4)
            for path in paths:
                self.assertTrue(path.exists())
            VALIDATOR.validate_board_artifact_bundle(Path(tmpdir), self.runner)


if __name__ == "__main__":
    unittest.main()
