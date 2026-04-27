from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check_qe_next_stage_dse_simulator_contracts.py")
SPEC = importlib.util.spec_from_file_location("check_qe_next_stage_dse_simulator_contracts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class NextStageDseSimulatorContractsTests(unittest.TestCase):
    def test_repo_artifacts_pass(self) -> None:
        MODULE.check_phase_config(MODULE.DEFAULT_PHASE_CONFIG_PATH)
        MODULE.check_checklist(MODULE.DEFAULT_CHECKLIST_PATH)
        MODULE.check_plan(MODULE.DEFAULT_PLAN_PATH)
        MODULE.check_result_schema(MODULE.DEFAULT_RESULT_SCHEMA_PATH)
        MODULE.check_phase_runner(MODULE.DEFAULT_PHASE_RUNNER_PATH)

    def test_missing_metric_fails_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "plan.md"
            text = Path(MODULE.DEFAULT_PLAN_PATH).read_text(encoding="utf-8")
            text = text.replace("energy_to_convergence_j", "energy_to_conv_removed")
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ContractError, "energy_to_convergence_j"):
                MODULE.check_plan(path)

    def test_phase_config_tie_band_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase_config.json"
            payload = json.loads(Path(MODULE.DEFAULT_PHASE_CONFIG_PATH).read_text(encoding="utf-8"))
            payload["promotion_policy"]["tie_band_rule"]["max_relative_margin"] = 0.07
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ContractError, "tie-band margin"):
                MODULE.check_phase_config(path)

    def test_phase_runner_missing_artifact_bundle_surface_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase_runner.py"
            text = Path(MODULE.DEFAULT_PHASE_RUNNER_PATH).read_text(encoding="utf-8")
            text = text.replace("stage_artifact_bundle_manifest", "stage_bundle_removed")
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ContractError, "stage_artifact_bundle_manifest"):
                MODULE.check_phase_runner(path)

    def test_checklist_missing_release_bundle_wording_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "checklist.md"
            text = Path(MODULE.DEFAULT_CHECKLIST_PATH).read_text(encoding="utf-8")
            text = text.replace("stage artifact bundle manifest", "removed release manifest wording")
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ContractError, "stage artifact bundle manifest"):
                MODULE.check_checklist(path)


if __name__ == "__main__":
    unittest.main()
