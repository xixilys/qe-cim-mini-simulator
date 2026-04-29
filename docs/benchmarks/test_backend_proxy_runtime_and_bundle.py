from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[2]
BUNDLE_PATH = ROOT / "backend/runners/build_backend_release_bundle_v0.py"
SPEC = importlib.util.spec_from_file_location("build_backend_release_bundle_v0", BUNDLE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
BUNDLE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUNDLE_MODULE)
BUNDLE = cast(Any, BUNDLE_MODULE)


class BackendProxyRuntimeAndBundleTests(unittest.TestCase):
    def test_generic_proxy_runtime_builds_and_emits_claim_safe_json(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc is not available for proxy runtime compile smoke")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            exe = tmp / "generic_scf_proxy"
            compile_cmd = [
                "gcc",
                "-std=c11",
                "-Wall",
                "-Werror",
                "-I",
                str(ROOT / "runtime_api"),
                str(ROOT / "proxy_programs/generic_scf_proxy.c"),
                str(ROOT / "runtime_api/offload_runtime.c"),
                "-o",
                str(exe),
            ]
            subprocess.run(compile_cmd, check=True, capture_output=True, text=True)
            completed = subprocess.run(
                [str(exe)],
                check=True,
                capture_output=True,
                text=True,
                env={"QEBS_PROXY_ITERATIONS": "2", "QEBS_PROXY_NBANDS": "4"},
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["schema_version"], "qebs_proxy_runtime_report_v0")
            self.assertEqual(payload["claim_ceiling"], "proxy_runtime_smoke_only")
            self.assertEqual(payload["metrics"]["command_count"], 1)
            self.assertEqual(payload["metrics"]["completion_count"], 1)
            self.assertGreater(payload["metrics"]["mmio_write_count"], 0)
            self.assertIn("no_qe_equivalent_scf_claim", payload["non_claims"])
            self.assertIn("no_rtl_hls_board_or_asic_implementation_claim", payload["non_claims"])

    def test_runtime_api_exposes_domain_neutral_aliases(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc is not available for runtime alias compile smoke")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "alias_smoke.c"
            exe = tmp / "alias_smoke"
            source.write_text(
                "#include \"offload_runtime.h\"\n"
                "int main(void) {\n"
                "    volatile unsigned int regs[256] = {0};\n"
                "    offload_runtime runtime;\n"
                "    offload_command_descriptor desc = offload_command_descriptor_default();\n"
                "    desc.opcode = OFFLOAD_OPCODE_GENERIC_WORKLOAD;\n"
                "    desc.control_policy = OFFLOAD_CONTROL_POLLING;\n"
                "    offload_runtime_init(&runtime, regs, sizeof(regs));\n"
                "    return offload_runtime_submit_sync(&runtime, &desc);\n"
                "}\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "gcc",
                    "-std=c11",
                    "-Wall",
                    "-Werror",
                    "-I",
                    str(ROOT / "runtime_api"),
                    str(source),
                    str(ROOT / "runtime_api/offload_runtime.c"),
                    "-o",
                    str(exe),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run([str(exe)], check=True, capture_output=True, text=True)

    def test_release_bundle_manifest_preserves_backend_claim_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            report = tmp / "backend_report.json"
            correctness = tmp / "correctness_report.json"
            correctness.write_text(
                json.dumps(
                    {
                        "schema_version": "correctness_report_v0",
                        "execution_status": "executed",
                        "claim_ceiling": "correctness_report_reference_only",
                        "report_id": "correctness_unit",
                        "candidate_id": "candidate_bundle",
                        "workload_identity": {
                            "workload_id": "generic_proxy",
                            "domain": "synthetic",
                            "adapter": "generic",
                        },
                        "tolerance_schema_id": "generic_proxy_tolerance_v0",
                        "correctness_status": "baseline_missing",
                        "workload_equivalent_claim": False,
                        "compare_report": {"overall_pass": False},
                        "evidence_refs": {"baseline": "missing"},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            calibration = tmp / "calibration_feedback.json"
            calibration.write_text(
                json.dumps(
                    {
                        "schema_version": "calibration_feedback_v0",
                        "feedback_id": "calibration_unit",
                        "candidate_id": "candidate_bundle",
                        "calibration_status": "not_measured",
                        "claim_ceiling": "calibration_feedback_only",
                        "source_report_refs": {"backend": str(report)},
                        "updated_parameters": {"host_wait_scale": 1.0},
                        "residual_summary": {"status": "not_measured", "sample_count": 0},
                        "evidence_refs": {},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "backend_execution_report_v0",
                        "candidate_id": "candidate_bundle",
                        "execution_status": "refused",
                        "fidelity": "gem5_systemc_timed_proxy",
                        "claim_ceiling": "gem5_systemc_timed_proxy_only",
                        "backend_class": "gem5_systemc_timed_proxy",
                        "source_kind": "backend_runner_gem5_systemc",
                        "environment": {},
                        "control_path": {
                            "host_launch_count": 0,
                            "completion_count": 0,
                            "fallback_count": 0,
                            "deadlock": False,
                            "completion_source": "not_executed",
                        },
                        "metrics": {
                            "time_to_completion_s": None,
                            "cycle_proxy": None,
                            "host_wait_s": None,
                            "device_busy_s": None,
                            "dma_read_bytes": None,
                            "dma_write_bytes": None,
                            "bytes_moved_to_convergence": None,
                            "resident_reuse_ratio": None,
                            "spill_ratio": None,
                            "fallback_ratio": None,
                        },
                        "correctness_gate": {
                            "workload_equivalent_claim": False,
                            "domain": "dft",
                            "domain_equivalence_claim": False,
                        },
                        "artifact_refs": {"blocker": "gem5.opt missing"},
                        "non_claims": [
                            "no_qe_equivalent_scf_claim",
                            "no_cycle_accuracy_claim",
                            "no_rtl_hls_board_or_asic_implementation_claim",
                        ],
                        "refusal_reason": "gem5 executable is missing",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            rc = BUNDLE.main([
                "--output-dir",
                str(tmp / "bundle"),
                "--backend-report",
                str(report),
                "--correctness-report",
                str(correctness),
                "--calibration-feedback",
                str(calibration),
                "--reproduction-command",
                "python3 backend/runners/run_backend_execution_v0.py ...",
            ])

            self.assertEqual(rc, 0)
            manifest = json.loads(
                (tmp / "bundle/backend_release_bundle_manifest_v0.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["backend_reports"][0]["claim_ceiling"], "gem5_systemc_timed_proxy_only")
            self.assertEqual(manifest["correctness"]["correctness_status"], "baseline_missing")
            self.assertFalse(manifest["correctness"]["workload_equivalent_claim"])
            self.assertEqual(manifest["calibration_feedback"]["claim_ceiling"], "calibration_feedback_only")
            self.assertEqual(manifest["calibration_feedback"]["calibration_status"], "not_measured")
            self.assertEqual(
                manifest["reproduction_commands"],
                ["python3 backend/runners/run_backend_execution_v0.py ..."],
            )
            matrix = json.loads((tmp / "bundle/claim_ceiling_matrix_v0.json").read_text(encoding="utf-8"))
            self.assertEqual(matrix["rows"][0]["execution_status"], "refused")
            self.assertIn("no_final_architecture_recommendation", matrix["global_non_claims"])

    def test_release_bundle_generates_default_reproduction_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            request = tmp / "request.json"
            request.write_text("{}\n", encoding="utf-8")
            report = tmp / "backend_report.json"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "backend_execution_report_v0",
                        "candidate_id": "candidate_bundle",
                        "execution_status": "refused",
                        "fidelity": "systemc_standalone",
                        "claim_ceiling": "systemc_standalone_proxy_only",
                        "backend_class": "systemc_standalone_proxy",
                        "source_kind": "backend_runner_systemc",
                        "environment": {},
                        "control_path": {
                            "host_launch_count": 0,
                            "completion_count": 0,
                            "fallback_count": 0,
                            "deadlock": False,
                            "completion_source": "not_executed",
                        },
                        "metrics": {},
                        "correctness_gate": {
                            "workload_equivalent_claim": False,
                            "domain": "synthetic",
                            "domain_equivalence_claim": False,
                        },
                        "artifact_refs": {},
                        "non_claims": [
                            "no_qe_equivalent_scf_claim",
                            "no_cycle_accuracy_claim",
                            "no_rtl_hls_board_or_asic_implementation_claim",
                        ],
                        "refusal_reason": "unit",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            rc = BUNDLE.main([
                "--output-dir",
                str(tmp / "bundle"),
                "--request",
                str(request),
                "--backend-report",
                str(report),
            ])

            self.assertEqual(rc, 0)
            manifest = json.loads(
                (tmp / "bundle/backend_release_bundle_manifest_v0.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["reproduction_commands"]), 1)
            self.assertIn("--request", manifest["reproduction_commands"][0])
            self.assertIn("--mode systemc_standalone", manifest["reproduction_commands"][0])

    def test_release_bundle_rejects_calibration_identity_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            report = tmp / "backend_report.json"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "backend_execution_report_v0",
                        "candidate_id": "candidate_bundle",
                        "execution_status": "refused",
                        "fidelity": "systemc_standalone",
                        "claim_ceiling": "systemc_standalone_proxy_only",
                        "backend_class": "systemc_standalone_proxy",
                        "source_kind": "backend_runner_systemc",
                        "environment": {},
                        "control_path": {
                            "host_launch_count": 0,
                            "completion_count": 0,
                            "fallback_count": 0,
                            "deadlock": False,
                            "completion_source": "not_executed",
                        },
                        "metrics": {},
                        "correctness_gate": {
                            "workload_equivalent_claim": False,
                            "domain": "synthetic",
                            "domain_equivalence_claim": False,
                        },
                        "artifact_refs": {},
                        "non_claims": [
                            "no_qe_equivalent_scf_claim",
                            "no_cycle_accuracy_claim",
                            "no_rtl_hls_board_or_asic_implementation_claim",
                        ],
                        "refusal_reason": "unit",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            calibration = tmp / "bad_calibration_feedback.json"
            calibration.write_text(
                json.dumps(
                    {
                        "schema_version": "calibration_feedback_v0",
                        "feedback_id": "bad_calibration_unit",
                        "candidate_id": "candidate_bundle",
                        "calibration_status": "partial",
                        "claim_ceiling": "calibration_feedback_only",
                        "source_report_refs": {"backend": str(report)},
                        "updated_parameters": {"workload_id": "illegal_identity_update"},
                        "residual_summary": {"status": "partial"},
                        "evidence_refs": {},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "identity key"):
                BUNDLE.main([
                    "--output-dir",
                    str(tmp / "bundle"),
                    "--backend-report",
                    str(report),
                    "--calibration-feedback",
                    str(calibration),
                ])


if __name__ == "__main__":
    unittest.main()
