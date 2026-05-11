from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("assess_qe_cpu_gpu_baseline_readiness.py")
SPEC = importlib.util.spec_from_file_location("assess_qe_cpu_gpu_baseline_readiness", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AssessCpuGpuBaselineReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = MODULE.load_validator_module()
        cls.runner = cls.validator.load_runner_module()

    def make_manifest(self, baseline_dir: Path, gpu_mode: str) -> Path:
        payload = {
            "schema_version": "qe_cpu_gpu_baseline_manifest_template_v0",
            "baseline_class": "CPU+GPU",
            "case_id": "si4_pbe_uspp_small",
            "gpu_mode": gpu_mode,
            "run_tag": "20260414-120000",
            "host_id": "host-a",
            "gpu_id": "gpu-a",
            "qe_rev": "rev-a",
            "correctness_contract_id": "qe_gold_correctness_contract_v0",
            "workload_group_id": self.runner.PHASE1_WORKLOAD_GROUP_ID,
            "fairness_policy_id": self.runner.PHASE1_FAIRNESS_POLICY_ID,
            "algorithm_rewrite_manifest_id": self.runner.PHASE1_REWRITE_MANIFEST_ID,
            "gpu_mode_attempts": [gpu_mode],
            "mode_attempt_exemption_note": "",
            "shared_rewrite_closed": False,
            "host_platform_comparable": False,
            "rewrite_mode": "none",
            "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
            "accounting_boundary_id": "scf_shell_convergence_scope_v1",
            "power_boundary_id": self.runner.PHASE1_POWER_BOUNDARY_ID,
            "warmup_policy": "symmetric_warmup_once",
            "host_normalization_note": "same host",
            "command": "run",
            "env": {"CUDA_VISIBLE_DEVICES": "0"},
            "artifact_paths": {
                "stdout": "run.stdout.txt",
                "stderr": "run.stderr.txt",
                "timing": "run.timing.json",
                "correctness": "run.correctness.json",
                "convergence": "run.convergence.json",
                "power": "run.power.json",
                "summary": "run.summary.md",
            },
            "baseline_state": "pending",
        }
        path = baseline_dir / "cpu_gpu_baseline_manifest.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        rewrite_manifest = {
            "schema_version": "qe_algorithm_rewrite_manifest_template_v0",
            "manifest_id": self.runner.PHASE1_REWRITE_MANIFEST_ID,
            "fairness_policy_id": self.runner.PHASE1_FAIRNESS_POLICY_ID,
            "workload_group_id": self.runner.PHASE1_WORKLOAD_GROUP_ID,
            "entries": [
                {
                    "rewrite_id": "RW-QE-001",
                    "title": "example rewrite",
                    "rewrite_class": "shared_semantic",
                    "scope": ["h_psi"],
                    "description": "desc",
                    "motivation": "motivation",
                    "changes_algorithm_semantics": "qualified",
                    "correctness_contract_impact": "bounded",
                    "tolerance_contract_note": "none",
                    "gpu_applicable": "yes",
                    "gpu_applicability_basis": "applicable",
                    "gpu_enabled_in_baseline": "deferred",
                    "gpu_enablement_note": "pending",
                    "fpga_required_arch_feature": "none",
                    "expected_benefit_axis": "time",
                    "expected_benefit_note": "time",
                    "ablation_required": "yes",
                    "admission_risk": "medium",
                    "evidence_note": "spec-only",
                    "review_status": "draft",
                    "owner_note": "owner",
                    "affected_workload_ids": ["si4_pbe_uspp_small"],
                    "affected_family_ids": ["F1", "F2"],
                    "simulator_hook_ids": ["algorithm_rewrite_manifest_id"],
                    "board_observability_rows": ["OBS-01"],
                    "fallback_behavior": "none",
                    "shared_rewrite_dependency_ids": [],
                    "claim_dependency_ids": ["CL1"],
                }
            ],
        }
        (baseline_dir / "algorithm_rewrite_manifest.json").write_text(
            json.dumps(rewrite_manifest, indent=2) + "\n", encoding="utf-8"
        )
        return path

    def write_required_files(self, baseline_dir: Path, *, gold_pass: bool, convergence_pass: bool, time_s: float | None, power_w: float | None, energy_j: float | None) -> None:
        (baseline_dir / "run.stdout.txt").write_text("stdout", encoding="utf-8")
        (baseline_dir / "run.stderr.txt").write_text("", encoding="utf-8")
        (baseline_dir / "run.summary.md").write_text("summary", encoding="utf-8")
        (baseline_dir / "run.correctness.json").write_text(
            json.dumps(
                {
                    "gold_pass": gold_pass,
                    "convergence_comparable_pass": convergence_pass,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (baseline_dir / "run.convergence.json").write_text(
            json.dumps({"convergence_comparable_pass": convergence_pass}, indent=2) + "\n",
            encoding="utf-8",
        )
        (baseline_dir / "run.timing.json").write_text(
            json.dumps({"time_to_convergence_s": time_s}, indent=2) + "\n",
            encoding="utf-8",
        )
        (baseline_dir / "run.power.json").write_text(
            json.dumps({"avg_whole_node_power_w": power_w, "energy_to_solution_j": energy_j}, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_missing_artifacts_is_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_dir = Path(tmpdir)
            self.make_manifest(baseline_dir, "strict_fp64")
            row = MODULE.classify_row(baseline_dir, self.validator, self.runner)
            self.assertEqual(row["status"], "deferred")

    def test_failed_correctness_is_reference_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_dir = Path(tmpdir)
            self.make_manifest(baseline_dir, "strict_fp64")
            self.write_required_files(
                baseline_dir,
                gold_pass=False,
                convergence_pass=False,
                time_s=10.0,
                power_w=150.0,
                energy_j=1500.0,
            )
            row = MODULE.classify_row(baseline_dir, self.validator, self.runner)
            self.assertEqual(row["status"], "reference_only")

    def test_missing_fairness_closure_is_reference_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_dir = Path(tmpdir)
            manifest_path = self.make_manifest(baseline_dir, "strict_fp64")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["gpu_mode_attempts"] = ["strict_fp64", "practical"]
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            self.write_required_files(
                baseline_dir,
                gold_pass=True,
                convergence_pass=True,
                time_s=10.0,
                power_w=150.0,
                energy_j=1500.0,
            )
            row = MODULE.classify_row(baseline_dir, self.validator, self.runner)
            self.assertEqual(row["status"], "reference_only")
            self.assertEqual(row["reason"], "shared_rewrite_not_closed")

    def test_unresolved_rewrite_manifest_is_reference_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_dir = Path(tmpdir)
            manifest_path = self.make_manifest(baseline_dir, "strict_fp64")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["gpu_mode_attempts"] = ["strict_fp64", "practical"]
            manifest["shared_rewrite_closed"] = True
            manifest["host_platform_comparable"] = True
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            self.write_required_files(
                baseline_dir,
                gold_pass=True,
                convergence_pass=True,
                time_s=10.0,
                power_w=150.0,
                energy_j=1500.0,
            )
            row = MODULE.classify_row(baseline_dir, self.validator, self.runner)
            self.assertEqual(row["status"], "reference_only")
            self.assertEqual(row["reason"], "rewrite_manifest_not_closed")

    def test_eligible_rows_choose_fastest_decisive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            strict_dir = root / "strict"
            practical_dir = root / "practical"
            strict_dir.mkdir()
            practical_dir.mkdir()
            strict_manifest_path = self.make_manifest(strict_dir, "strict_fp64")
            practical_manifest_path = self.make_manifest(practical_dir, "practical")
            for path in [strict_manifest_path, practical_manifest_path]:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["gpu_mode_attempts"] = ["strict_fp64", "practical"]
                manifest["shared_rewrite_closed"] = True
                manifest["host_platform_comparable"] = True
                path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            for base in [strict_dir, practical_dir]:
                rewrite_path = base / "algorithm_rewrite_manifest.json"
                rewrite = json.loads(rewrite_path.read_text(encoding="utf-8"))
                rewrite["entries"][0]["review_status"] = "accepted"
                rewrite["entries"][0]["gpu_enabled_in_baseline"] = "yes"
                rewrite_path.write_text(json.dumps(rewrite, indent=2) + "\n", encoding="utf-8")
            self.write_required_files(
                strict_dir,
                gold_pass=True,
                convergence_pass=True,
                time_s=12.0,
                power_w=150.0,
                energy_j=1500.0,
            )
            self.write_required_files(
                practical_dir,
                gold_pass=True,
                convergence_pass=True,
                time_s=9.0,
                power_w=170.0,
                energy_j=1530.0,
            )
            rows = [
                MODULE.classify_row(strict_dir, self.validator, self.runner),
                MODULE.classify_row(practical_dir, self.validator, self.runner),
            ]
            rows = MODULE.choose_decisive(rows)
            decisive = [row for row in rows if row.get("decisive_for_case")]
            self.assertEqual(len(decisive), 1)
            self.assertEqual(decisive[0]["gpu_mode"], "practical")


if __name__ == "__main__":
    unittest.main()
