from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "backend/runners/run_backend_execution_v0.py"
SPEC = importlib.util.spec_from_file_location("run_backend_execution_v0", RUNNER_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
RUNNER = cast(Any, MODULE)


class BackendExecutionRunnerTests(unittest.TestCase):
    def make_request(self, mode: str, *, input_refs: dict[str, Any] | None = None) -> dict[str, Any]:
        fidelity = {
            "systemc_standalone": "B1",
            "systemc_timed_functional": "B2",
            "gem5_systemc_smoke": "B3",
            "gem5_systemc_timed_proxy": "B4",
        }[mode]
        return {
            "schema_version": "backend_execution_request_v0",
            "candidate_id": f"candidate_{mode}",
            "requested_fidelity": fidelity,
            "execution_mode": mode,
            "workload_identity": {
                "workload_id": "si8_proxy",
                "domain": "dft",
                "adapter": "qe",
            },
            "candidate_identity": {
                "architecture_template_id": "F2",
                "target_class": "fpga",
                "design_axes": {"diag_policy": "device_first_fallback"},
            },
            "input_refs": input_refs or {},
            "software_runtime": {
                "mode": "proxy_runtime",
                "control_policy": "sync",
            },
            "domain_extension": {"qe": {"case_id": "si8_proxy"}},
            "expected_report_schema": "backend_execution_report_v0",
        }

    def write_request(self, directory: Path, payload: dict[str, Any]) -> Path:
        path = directory / "request.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def read_report(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def assert_refused_report(self, report: dict[str, Any], mode: str) -> None:
        self.assertEqual(report["schema_version"], "backend_execution_report_v0")
        self.assertEqual(report["execution_status"], "refused")
        self.assertEqual(report["fidelity"], mode)
        self.assertIn("refusal_reason", report)
        self.assertFalse(report["correctness_gate"]["workload_equivalent_claim"])
        self.assertFalse(report["correctness_gate"]["domain_equivalence_claim"])
        self.assertIn("no_rtl_hls_board_or_asic_implementation_claim", report["non_claims"])

    def test_dry_run_writes_refused_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            request = self.write_request(tmp, self.make_request("systemc_standalone"))
            output = tmp / "report.json"

            rc = RUNNER.main(["--request", str(request), "--output", str(output), "--mode", "systemc_standalone", "--dry-run"])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_standalone")
            self.assertIn("dry-run", report["refusal_reason"])

    def test_missing_systemc_executable_writes_refused_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            missing_exe = tmp / "missing-qe-band-solver"
            request = self.write_request(
                tmp,
                self.make_request("systemc_standalone", input_refs={"systemc_executable": str(missing_exe)}),
            )
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_standalone",
                "--allow-execute",
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_standalone")
            self.assertIn("SystemC executable is missing", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["systemc_executable"], str(missing_exe))

    def test_missing_gem5_executable_writes_refused_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            missing_exe = tmp / "missing-gem5.opt"
            request = self.write_request(
                tmp,
                self.make_request("gem5_systemc_smoke", input_refs={"gem5_executable": str(missing_exe)}),
            )
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "gem5_systemc_smoke",
                "--allow-execute",
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assert_refused_report(report, "gem5_systemc_smoke")
            self.assertIn("gem5 executable is missing", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["gem5_executable"], str(missing_exe))

    def test_legacy_b3_conversion_writes_backend_report_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            request = self.write_request(tmp, self.make_request("gem5_systemc_smoke"))
            output = tmp / "report.json"
            legacy = ROOT / "docs/benchmarks/results/qe_dse_gem5_systemc_smoke_report_v0.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "gem5_systemc_smoke",
                "--legacy-b3-report",
                str(legacy),
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assertEqual(report["schema_version"], "backend_execution_report_v0")
            self.assertEqual(report["execution_status"], "executed")
            self.assertEqual(report["claim_ceiling"], "gem5_systemc_smoke_only")
            self.assertEqual(report["artifact_refs"]["legacy_b3_smoke_report"], str(legacy))
            self.assertEqual(report["control_path"]["completion_source"], "smoke_immediate_complete")
            self.assertFalse(report["correctness_gate"]["workload_equivalent_claim"])
            self.assertIn("runtime_smoke_status", report["metrics"])

    def test_legacy_b3_conversion_refuses_hidden_qe_equivalence_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            request = self.write_request(tmp, self.make_request("gem5_systemc_smoke"))
            output = tmp / "report.json"
            legacy_src = ROOT / "docs/benchmarks/results/qe_dse_gem5_systemc_smoke_report_v0.json"
            legacy_payload = json.loads(legacy_src.read_text(encoding="utf-8"))
            for hidden_text in ("QE-equivalence passed", "domain-equivalence passed"):
                with self.subTest(hidden_text=hidden_text):
                    legacy_payload["notes"] = list(legacy_payload.get("notes", [])) + [hidden_text]
                    legacy = tmp / "bad_legacy_b3.json"
                    legacy.write_text(
                        json.dumps(legacy_payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                    rc = RUNNER.main([
                        "--request",
                        str(request),
                        "--output",
                        str(output),
                        "--mode",
                        "gem5_systemc_smoke",
                        "--legacy-b3-report",
                        str(legacy),
                    ])

                    self.assertEqual(rc, 0)
                    report = self.read_report(output)
                    self.assert_refused_report(report, "gem5_systemc_smoke")
                    self.assertIn("conversion failed", report["refusal_reason"])
                    self.assertIn("QE-equivalent", report["refusal_reason"])

    def test_bad_expected_report_schema_writes_refused_report_and_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = self.make_request("systemc_standalone")
            payload["expected_report_schema"] = "wrong_schema_v0"
            request = self.write_request(tmp, payload)
            output = tmp / "report.json"

            rc = RUNNER.main(["--request", str(request), "--output", str(output), "--mode", "systemc_standalone"])

            self.assertEqual(rc, 2)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_standalone")
            self.assertIn("expected_report_schema", report["refusal_reason"])

    def test_runner_uses_canonical_request_validation_for_qe_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = self.make_request("systemc_standalone")
            payload["qe_case_id"] = "top_level_not_allowed"
            request = self.write_request(tmp, payload)
            output = tmp / "report.json"

            rc = RUNNER.main(["--request", str(request), "--output", str(output), "--mode", "systemc_standalone"])

            self.assertEqual(rc, 2)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_standalone")
            self.assertIn("domain_extension.qe", report["refusal_reason"])

    def test_runner_uses_canonical_request_validation_for_missing_qe_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = self.make_request("systemc_standalone")
            payload["domain_extension"] = {}
            request = self.write_request(tmp, payload)
            output = tmp / "report.json"

            rc = RUNNER.main(["--request", str(request), "--output", str(output), "--mode", "systemc_standalone"])

            self.assertEqual(rc, 2)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_standalone")
            self.assertIn("domain_extension.qe", report["refusal_reason"])

    def test_deterministic_json_output_for_identical_dry_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            request = self.write_request(tmp, self.make_request("systemc_timed_functional"))
            output_a = tmp / "report_a.json"
            output_b = tmp / "report_b.json"
            args = ["--request", str(request), "--mode", "systemc_timed_functional", "--dry-run"]

            self.assertEqual(RUNNER.main(args + ["--output", str(output_a)]), 0)
            self.assertEqual(RUNNER.main(args + ["--output", str(output_b)]), 0)

            self.assertEqual(output_a.read_text(encoding="utf-8"), output_b.read_text(encoding="utf-8"))

    def test_systemc_candidate_result_conversion_when_artifact_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            candidate = tmp / "systemc_candidate.json"
            candidate.write_text(
                json.dumps(
                    {
                        "schema_version": "systemc_architecture_candidate_result_v0",
                        "generated_at_utc": "2026-04-28T00:00:00Z",
                        "case_id": "si8_proxy",
                        "architecture_family": "F2",
                        "assumption_set_id": "unit_test",
                        "run_summary": {"total_episodes": 2, "total_ref_cycles": 12345},
                        "final": {"converged": True, "scf_iterations": 2},
                        "iteration_diagnostics": [
                            {"spill_active": False},
                            {"spill_active": True},
                        ],
                        "metrics": {
                            "cpu_fallbacks": 1,
                            "resident_reuse_hits": 1,
                            "total_data_movement_kib": 4.0,
                            "dma_read_kib": 1.5,
                            "dma_write_kib": 2.5,
                        },
                        "cluster_metrics": {"cluster_a": {"invocations": 2}},
                        "timing": {"wall_time_s": 0.25},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            request = self.write_request(
                tmp,
                self.make_request("systemc_standalone", input_refs={"systemc_candidate_result": str(candidate)}),
            )
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_standalone",
                "--allow-execute",
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assertEqual(report["execution_status"], "executed")
            self.assertEqual(report["metrics"]["cycle_proxy"], 12345)
            self.assertEqual(report["metrics"]["dma_read_bytes"], 1536)
            self.assertEqual(report["metrics"]["dma_write_bytes"], 2560)
            self.assertEqual(report["metrics"]["bytes_moved_to_convergence"], 4096)
            self.assertEqual(report["metrics"]["fallback_ratio"], 0.5)
            self.assertEqual(report["metrics"]["resident_reuse_ratio"], 0.5)
            self.assertEqual(report["metrics"]["spill_ratio"], 0.5)
            self.assertEqual(report["artifact_refs"]["systemc_candidate_result"], str(candidate))
            self.assertEqual(report["control_path"]["completion_source"], "systemc_candidate_result")

    def test_relative_input_refs_resolve_from_request_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            candidate = tmp / "bundle" / "artifacts" / "systemc_candidate.json"
            candidate.parent.mkdir(parents=True)
            candidate.write_text(
                json.dumps(
                    {
                        "schema_version": "systemc_architecture_candidate_result_v0",
                        "generated_at_utc": "2026-04-28T00:00:00Z",
                        "case_id": "bundle_case",
                        "architecture_family": "F2",
                        "assumption_set_id": "bundle_relative",
                        "run_summary": {"total_episodes": 1, "total_ref_cycles": 99},
                        "final": {"converged": True, "scf_iterations": 1},
                        "iteration_diagnostics": [],
                        "metrics": {},
                        "cluster_metrics": {},
                        "timing": {"wall_time_s": 0.01},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            request = self.write_request(
                tmp / "bundle",
                self.make_request(
                    "systemc_standalone",
                    input_refs={"systemc_candidate_result": "artifacts/systemc_candidate.json"},
                ),
            )
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_standalone",
                "--allow-execute",
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assertEqual(report["execution_status"], "executed")
            self.assertEqual(report["artifact_refs"]["systemc_candidate_result"], str(candidate))

    def test_systemc_execution_maps_request_to_qebs_env_and_keeps_raw_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            exe = tmp / "bin" / "fake_systemc.py"
            exe.parent.mkdir(parents=True)
            exe.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "env = {k: v for k, v in os.environ.items() if k.startswith('QEBS_')}\n"
                "out = Path(os.environ['QEBS_RESULT_JSON'])\n"
                "out.parent.mkdir(parents=True, exist_ok=True)\n"
                "out.write_text(json.dumps({\n"
                "  'schema_version': 'systemc_architecture_candidate_result_v0',\n"
                "  'generated_at_utc': '2026-04-28T00:00:00Z',\n"
                "  'case_id': env.get('QEBS_QE_CASE_ID'),\n"
                "  'architecture_family': env.get('QEBS_DESIGN_AXIS_FAMILY'),\n"
                "  'assumption_set_id': env.get('QEBS_BACKEND_PROFILE_ID'),\n"
                "  'run_summary': {'total_episodes': 1, 'total_ref_cycles': 77},\n"
                "  'final': {'converged': True, 'scf_iterations': 1},\n"
                "  'iteration_diagnostics': [],\n"
                "  'metrics': {'dma_read_kib': 1.0, 'dma_write_kib': 2.0},\n"
                "  'cluster_metrics': {'qebs_env': env},\n"
                "  'timing': {'wall_time_s': 0.02}\n"
                "}, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            exe.chmod(exe.stat().st_mode | 0o111)

            cfg = tmp / "cfg" / "systemc.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("{}\n", encoding="utf-8")
            request_payload = self.make_request(
                "systemc_timed_functional",
                input_refs={
                    "systemc_executable": "bin/fake_systemc.py",
                    "systemc_config": "cfg/systemc.json",
                },
            )
            request_payload["candidate_identity"]["backend_profile_id"] = "unit_profile"
            request_payload["candidate_identity"]["design_axes"].update(
                {
                    "family": "F2",
                    "offload_scope": "balanced",
                    "resident_policy": "fit_first",
                    "partition_strategy": "operator__build__diag__refresh",
                }
            )
            request_payload["domain_extension"]["qe"].update(
                {
                    "pseudopotential_family": "NC",
                    "solver_path_class": "standard_band",
                    "qe_tolerance_schema_id": "qe_gold_numerical_tolerance_schema_v0",
                }
            )
            request = self.write_request(tmp, request_payload)
            output = tmp / "report.json"
            raw_result = tmp / "report.systemc_candidate_result.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_timed_functional",
                "--allow-execute",
            ])

            self.assertEqual(rc, 0)
            self.assertTrue(raw_result.exists())
            report = self.read_report(output)
            self.assertEqual(report["execution_status"], "executed")
            self.assertEqual(report["artifact_refs"]["systemc_candidate_result"], str(raw_result))
            env = report["artifact_refs"]["source_cluster_metrics"]["qebs_env"]
            self.assertEqual(env["QEBS_CANDIDATE_ID"], request_payload["candidate_id"])
            self.assertEqual(env["QEBS_EXECUTION_MODE"], "systemc_timed_functional")
            self.assertEqual(env["QEBS_QE_CASE_ID"], "si8_proxy")
            self.assertEqual(env["QEBS_CASE_ID"], "si8_proxy")
            self.assertEqual(env["QEBS_BACKEND_PROFILE_ID"], "unit_profile")
            self.assertEqual(env["QEBS_ASSUMPTION_SET_ID"], "unit_profile")
            self.assertEqual(env["QEBS_DESIGN_AXIS_FAMILY"], "F2")
            self.assertEqual(env["QEBS_ARCH_FAMILY"], "F2")
            self.assertEqual(env["QEBS_DESIGN_AXIS_DIAG_POLICY"], "device_first_fallback")
            self.assertEqual(env["QEBS_INPUT_REF_SYSTEMC_CONFIG"], str(cfg))
            self.assertEqual(env["QEBS_ARCH_CONFIG"], str(cfg))
            self.assertEqual(env["QEBS_RESULT_JSON"], str(raw_result))

    def test_b4_direct_gem5_path_refuses_without_smoke_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_gem5 = tmp / "bin" / "gem5.opt"
            fake_gem5.parent.mkdir(parents=True)
            fake_gem5.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            fake_gem5.chmod(fake_gem5.stat().st_mode | 0o111)
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_timed_proxy",
                    input_refs={"gem5_executable": "bin/gem5.opt"},
                ),
            )
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "gem5_systemc_timed_proxy",
                "--allow-execute",
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assert_refused_report(report, "gem5_systemc_timed_proxy")
            self.assertEqual(report["claim_ceiling"], "gem5_systemc_timed_proxy_only")
            self.assertEqual(report["control_path"]["completion_source"], "not_executed")
            self.assertNotEqual(report["control_path"]["completion_source"], "smoke_immediate_complete")
            self.assertIn("direct gem5 execution is not implemented", report["refusal_reason"])

    def test_failed_systemc_execution_marks_missing_raw_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            exe = tmp / "bin" / "failing_systemc.py"
            exe.parent.mkdir(parents=True)
            exe.write_text("#!/usr/bin/env python3\nraise SystemExit(7)\n", encoding="utf-8")
            exe.chmod(exe.stat().st_mode | 0o111)
            request = self.write_request(
                tmp,
                self.make_request(
                    "systemc_timed_functional",
                    input_refs={"systemc_executable": "bin/failing_systemc.py"},
                ),
            )
            output = tmp / "report.json"
            raw_result = tmp / "report.systemc_candidate_result.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_timed_functional",
                "--allow-execute",
            ])

            self.assertEqual(rc, 1)
            self.assertFalse(raw_result.exists())
            report = self.read_report(output)
            self.assertEqual(report["execution_status"], "failed")
            self.assertEqual(report["artifact_refs"]["systemc_candidate_result_status"], "missing")
            self.assertEqual(report["artifact_refs"]["systemc_candidate_result"], str(raw_result))

    def test_missing_request_provided_systemc_result_marks_artifact_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            missing = tmp / "missing_candidate.json"
            request = self.write_request(
                tmp,
                self.make_request(
                    "systemc_standalone",
                    input_refs={"systemc_candidate_result": "missing_candidate.json"},
                ),
            )
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_standalone",
                "--allow-execute",
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assertEqual(report["execution_status"], "refused")
            self.assertEqual(report["artifact_refs"]["systemc_candidate_result"], str(missing))
            self.assertEqual(report["artifact_refs"]["systemc_candidate_result_status"], "missing")


if __name__ == "__main__":
    unittest.main()
