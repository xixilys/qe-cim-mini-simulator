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
                "validity_class": "valid_executable",
                "design_axes": {"diag_policy": "device_first_fallback"},
            },
            "backend_capability_profile": {
                "profile_id": "unit_profile",
                "supports_systemc_standalone": True,
                "supports_systemc_timed_functional": True,
                "supports_gem5_smoke": True,
                "supports_gem5_timed_proxy": True,
                "supports_real_bridge": True,
            },
            "input_refs": input_refs or {},
            "software_runtime": {
                "mode": "proxy_runtime",
                "control_policy": "sync",
            },
            "domain_extension": {"qe": {"case_id": "si8_proxy"}},
            "expected_report_schema": "backend_execution_report_v0",
            "metrics_contract": {
                "taxonomy": "backend_metric_groups_v0",
                "required_groups": ["summary", "host", "device", "dma", "systemc", "gem5", "runner"],
            },
        }

    def write_request(self, directory: Path, payload: dict[str, Any]) -> Path:
        path = directory / "request.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def read_report(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_timing_sidecar(self, directory: Path, name: str = "timing_sidecar.json") -> Path:
        sidecar = directory / "timing" / name
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(
            json.dumps(
                {
                    "schema_version": "qe_gem5_systemc_b4_timing_sidecar_v0",
                    "candidate_id": "candidate_gem5_systemc_timed_proxy",
                    "control_path": {
                        "mmio_read_count": 5,
                        "mmio_write_count": 8,
                        "polling_read_count": 3,
                        "interrupt_count": 0,
                        "command_issue_tick": 100,
                        "device_accept_tick": 110,
                        "systemc_start_tick": 120,
                        "systemc_end_tick": 520,
                        "completion_tick": 560,
                        "dma_start_tick": 130,
                        "dma_end_tick": 300,
                    },
                    "metrics": {
                        "cycle_proxy": 560,
                        "cycle_source": "timing_sidecar_projection",
                        "cycle_proxy_source": "timing_sidecar_projection",
                        "event_timed_device_activity_observed": False,
                        "candidate_device_event_delta_ticks": None,
                        "logical_dma_payload_bytes": 6144,
                    },
                    "claim_ceiling": "gem5_systemc_timed_proxy_only",
                    "non_claims": ["no_cycle_accuracy_claim"],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return sidecar

    def write_candidate_timing_profile(self, directory: Path, name: str = "candidate_timing_profile_v0.json") -> Path:
        profile = directory / "timing" / name
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(
            json.dumps(
                {
                    "schema_version": "qe_gem5_systemc_b4_candidate_timing_profile_v0",
                    "candidate_id": "candidate_gem5_systemc_timed_proxy",
                    "runtime_timing_role": "strict_b4_runtime_profile_input",
                    "event_schedule": {
                        "command_issue_tick": 100,
                        "device_accept_tick": 110,
                        "systemc_start_tick": 120,
                        "systemc_end_tick": 520,
                        "completion_tick": 560,
                        "candidate_event_delta_ticks": 460,
                        "device_busy_ticks": 400,
                    },
                    "claim_ceiling": "gem5_event_scheduled_tick_observed_proxy_input_only",
                    "non_claims": ["no_cycle_accuracy_claim"],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return profile

    def b4_input_refs(
        self,
        *,
        gem5_executable: str = "bin/gem5.opt",
        gem5_config: str = "configs/fake_gem5_config.py",
        systemc_bridge_library: str = "lib/libgem5_systemc_bridge.a",
        timing_sidecar: str = "timing/timing_sidecar.json",
        candidate_timing_profile: str | None = None,
    ) -> dict[str, str]:
        refs = {
            "gem5_executable": gem5_executable,
            "gem5_config": gem5_config,
            "systemc_bridge_library": systemc_bridge_library,
            "timing_sidecar": timing_sidecar,
        }
        if candidate_timing_profile is not None:
            refs["candidate_timing_profile"] = candidate_timing_profile
            refs["strict_b4_runtime_timing_input"] = candidate_timing_profile
        return refs

    def write_direct_backend_report_executable(
        self,
        directory: Path,
        name: str,
        *,
        candidate_id_expr: str = "os.environ['QEBS_CANDIDATE_ID']",
        completion_source: str = "direct_backend_execution_report",
    ) -> Path:
        exe = directory / "bin" / name
        exe.parent.mkdir(parents=True)
        source = Path(name).stem
        exe.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "out = Path(os.environ['QEBS_BACKEND_EXECUTION_REPORT_JSON'])\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            f"candidate_id = {candidate_id_expr}\n"
            f"completion_source = {completion_source!r}\n"
            f"source = {source!r}\n"
            "mode = os.environ['QEBS_EXECUTION_MODE']\n"
            "claim = {\n"
            "  'systemc_standalone': 'systemc_standalone_proxy_only',\n"
            "  'systemc_timed_functional': 'systemc_timed_functional_proxy_only',\n"
            "  'gem5_systemc_smoke': 'gem5_systemc_smoke_only',\n"
            "  'gem5_systemc_timed_proxy': 'gem5_systemc_timed_proxy_only',\n"
            "}[mode]\n"
            "backend_class = {\n"
            "  'systemc_standalone': 'systemc_standalone_proxy',\n"
            "  'systemc_timed_functional': 'systemc_timed_functional_proxy',\n"
            "  'gem5_systemc_smoke': 'gem5_systemc_smoke',\n"
            "  'gem5_systemc_timed_proxy': 'gem5_systemc_timed_proxy',\n"
            "}[mode]\n"
            "source_kind = {\n"
            "  'systemc_standalone': 'backend_runner_systemc',\n"
            "  'systemc_timed_functional': 'backend_runner_systemc',\n"
            "  'gem5_systemc_smoke': 'backend_runner_gem5_systemc',\n"
            "  'gem5_systemc_timed_proxy': 'backend_runner_gem5_systemc',\n"
            "}[mode]\n"
            "out.write_text(json.dumps({\n"
            "  'schema_version': 'backend_execution_report_v0',\n"
            "  'candidate_id': candidate_id,\n"
            "  'execution_status': 'executed',\n"
            "  'fidelity': mode,\n"
            "  'claim_ceiling': claim,\n"
            "  'backend_class': backend_class,\n"
            "  'source_kind': source_kind,\n"
            "  'environment': {'source': source},\n"
            "  'control_path': {\n"
            "    'host_launch_count': 1,\n"
            "    'completion_count': 1,\n"
            "    'fallback_count': 0,\n"
            "    'deadlock': False,\n"
            "    'completion_source': completion_source\n"
            "  },\n"
            "  'metrics': {\n"
            "    'time_to_completion_s': 0.001,\n"
            "    'cycle_proxy': 10,\n"
            "    'host_wait_s': None,\n"
            "    'device_busy_s': 0.000001,\n"
            "    'dma_read_bytes': 64,\n"
            "    'dma_write_bytes': 32,\n"
            "    'bytes_moved_to_convergence': 96,\n"
            "    'resident_reuse_ratio': 0.0,\n"
            "    'spill_ratio': 0.0,\n"
            "    'fallback_ratio': 0.0\n"
            "  },\n"
            "  'correctness_gate': {\n"
            "    'workload_equivalent_claim': False,\n"
            "    'domain': os.environ.get('QEBS_WORKLOAD_DOMAIN', 'dft'),\n"
            "    'domain_equivalence_claim': False\n"
            "  },\n"
            "  'artifact_refs': {'source': source},\n"
            "  'non_claims': [\n"
            "    'no_qe_equivalent_scf_claim',\n"
            "    'no_cycle_accuracy_claim',\n"
            "    'no_rtl_hls_board_or_asic_implementation_claim'\n"
            "  ]\n"
            "}, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        exe.chmod(exe.stat().st_mode | 0o111)
        return exe

    def write_fake_gem5_report_executable(self, directory: Path, name: str = "gem5.opt") -> Path:
        exe = directory / "bin" / name
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "mode = os.environ['QEBS_EXECUTION_MODE']\n"
            "claim = {\n"
            "  'gem5_systemc_smoke': 'gem5_systemc_smoke_only',\n"
            "  'gem5_systemc_timed_proxy': 'gem5_systemc_timed_proxy_only',\n"
            "}[mode]\n"
            "backend_class = {\n"
            "  'gem5_systemc_smoke': 'gem5_systemc_smoke',\n"
            "  'gem5_systemc_timed_proxy': 'gem5_systemc_timed_proxy',\n"
            "}[mode]\n"
            "source_kind = 'backend_runner_gem5_systemc'\n"
            "out = Path(os.environ['QEBS_BACKEND_EXECUTION_REPORT_JSON'])\n"
            "out.write_text(json.dumps({\n"
            "  'schema_version': 'backend_execution_report_v0',\n"
            "  'candidate_id': os.environ['QEBS_CANDIDATE_ID'],\n"
            "  'execution_status': 'executed',\n"
            "  'fidelity': mode,\n"
            "  'claim_ceiling': claim,\n"
            "  'backend_class': backend_class,\n"
            "  'source_kind': source_kind,\n"
            "  'environment': {\n"
            "    'gem5_mode': os.environ.get('QEBS_GEM5_MODE'),\n"
            "    'fpga_execution_mode': os.environ.get('QEBS_FPGA_EXECUTION_MODE'),\n"
            "    'real_systemc_target': os.environ.get('QEBS_REAL_SYSTEMC_TARGET'),\n"
            "    'systemc_bridge': os.environ.get('QEBS_SYSTEMC_BRIDGE'),\n"
            "    'timing_sidecar': os.environ.get('QEBS_TIMING_SIDECAR_JSON'),\n"
            "    'candidate_timing_profile': os.environ.get('QEBS_CANDIDATE_TIMING_PROFILE_JSON'),\n"
            "    'strict_b4_event_timing': os.environ.get('QEBS_STRICT_B4_EVENT_TIMING'),\n"
            "    'device_event_report': os.environ.get('QEBS_STRICT_B4_DEVICE_EVENT_REPORT_JSON')\n"
            "  },\n"
            "  'control_path': {\n"
            "    'host_launch_count': 1,\n"
            "    'completion_count': 1,\n"
            "    'fallback_count': 0,\n"
            "    'deadlock': False,\n"
            "    'completion_source': 'timed_proxy_scheduled_event',\n"
            "    'mmio_read_count': 5,\n"
            "    'mmio_write_count': 8,\n"
            "    'polling_read_count': 3,\n"
            "    'interrupt_count': 0,\n"
            "    'command_issue_tick': 100,\n"
            "    'device_accept_tick': 110,\n"
            "    'systemc_start_tick': 120,\n"
            "    'systemc_end_tick': 520,\n"
            "    'completion_tick': 560,\n"
            "    'dma_start_tick': 130,\n"
            "    'dma_end_tick': 300\n"
            "  },\n"
            "  'metrics': {\n"
            "    'time_to_completion_s': 0.01,\n"
            "    'cycle_proxy': 1000,\n"
            "    'cycle_source': 'timing_sidecar_projection',\n"
            "    'cycle_proxy_source': 'timing_sidecar_projection',\n"
            "    'event_timed_device_activity_observed': False,\n"
            "    'candidate_device_event_delta_ticks': None,\n"
            "    'host_wait_s': 0.001,\n"
            "    'device_busy_s': 0.004,\n"
            "    'dma_read_bytes': 4096,\n"
            "    'dma_write_bytes': 2048,\n"
            "    'bytes_moved_to_convergence': 6144,\n"
            "    'resident_reuse_ratio': 0.5,\n"
            "    'spill_ratio': 0.0,\n"
            "    'fallback_ratio': 0.0,\n"
            "    'host_control_mmio_read_count': 5,\n"
            "    'host_control_mmio_write_count': 8,\n"
            "    'host_control_polling_read_count': 3,\n"
            "    'host_control_interrupt_count': 0,\n"
            "    'host_control_queue_wait_ns': 10,\n"
            "    'systemc_datapath_device_busy_ns': 4000000,\n"
            "    'systemc_datapath_compute_ns': 3000000,\n"
            "    'systemc_datapath_dma_read_ns': 1000,\n"
            "    'systemc_datapath_dma_write_ns': 500,\n"
            "    'systemc_datapath_queue_depth': 1,\n"
            "    'systemc_datapath_backpressure_count': 0,\n"
            "    'logical_dma_payload_bytes': 6144,\n"
            "    'observed_gem5_dma_stat_bytes': 6144,\n"
            "    'successful_dma_transfer_bytes': 6144,\n"
            "    'dma_warning_count': 0\n"
            "  },\n"
            "  'correctness_gate': {\n"
            "    'workload_equivalent_claim': False,\n"
            "    'domain': os.environ.get('QEBS_WORKLOAD_DOMAIN', 'dft'),\n"
            "    'domain_equivalence_claim': False\n"
            "  },\n"
            "  'artifact_refs': {\n"
            "    'fake_gem5_config': os.environ.get('QEBS_GEM5_CONFIG'),\n"
            "    'gem5_config': os.environ.get('QEBS_GEM5_CONFIG'),\n"
            "    'systemc_bridge': os.environ.get('QEBS_SYSTEMC_BRIDGE'),\n"
            "    'timing_sidecar': os.environ.get('QEBS_TIMING_SIDECAR_JSON'),\n"
            "    'candidate_timing_profile': os.environ.get('QEBS_CANDIDATE_TIMING_PROFILE_JSON'),\n"
            "    'strict_b4_runtime_timing_input': os.environ.get('QEBS_STRICT_B4_RUNTIME_TIMING_INPUT'),\n"
            "    'device_event_report': os.environ.get('QEBS_STRICT_B4_DEVICE_EVENT_REPORT_JSON')\n"
            "  },\n"
            "  'non_claims': [\n"
            "    'no_qe_equivalent_scf_claim',\n"
            "    'no_cycle_accuracy_claim',\n"
            "    'no_rtl_hls_board_or_asic_implementation_claim',\n"
            "    'no_final_architecture_recommendation'\n"
            "  ]\n"
            "}, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        exe.chmod(exe.stat().st_mode | 0o111)
        return exe

    def write_fake_qe_pw_executable(
        self,
        directory: Path,
        name: str = "pw.x",
        *,
        converged: bool = True,
    ) -> Path:
        exe = directory / "bin" / name
        exe.parent.mkdir(parents=True, exist_ok=True)
        qe_stdout = (
            "     Program PWSCF starts on fake host\\n"
            "     convergence has been achieved in   4 iterations\\n"
            "!    total energy              =      -2.1234567890 Ry\\n"
            "     estimated scf accuracy    <       1.0E-10 Ry\\n"
            "     JOB DONE.\\n"
            if converged
            else "     Program PWSCF starts on fake host\\n     iteration # 1\\n"
        )
        exe.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"sys.stdout.write({qe_stdout!r})\n",
            encoding="utf-8",
        )
        exe.chmod(exe.stat().st_mode | 0o111)
        return exe

    def write_fake_real_qe_gem5_executable(
        self,
        directory: Path,
        name: str = "gem5.opt",
        *,
        converged: bool = True,
        hit_tick_limit: bool = False,
    ) -> Path:
        exe = directory / "bin" / name
        exe.parent.mkdir(parents=True, exist_ok=True)
        if converged:
            qe_stdout = (
                "Beginning simulation!\\n"
                "     Program PWSCF starts on gem5 fake host\\n"
                "     convergence has been achieved in   4 iterations\\n"
                "!    total energy              =      -2.1234567890 Ry\\n"
                "     estimated scf accuracy    <       1.0E-10 Ry\\n"
                "     JOB DONE.\\n"
            )
        else:
            qe_stdout = "Beginning simulation!\\n     Program PWSCF starts on gem5 fake host\\n"
        exit_cause = "simulate() limit reached" if hit_tick_limit else "exiting with last active thread context"
        exe.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n"
            "from pathlib import Path\n"
            "argv_path = Path.cwd() / 'fake_gem5_argv.json'\n"
            "argv_path.write_text(json.dumps(sys.argv, indent=2) + '\\n', encoding='utf-8')\n"
            f"sys.stdout.write({qe_stdout!r})\n"
            f"sys.stdout.write('Exiting @ tick 12345 because {exit_cause}\\n')\n",
            encoding="utf-8",
        )
        exe.chmod(exe.stat().st_mode | 0o111)
        return exe

    def write_real_qe_smoke_inputs(
        self,
        directory: Path,
        *,
        missing_pseudo_dir: bool = False,
    ) -> dict[str, Path]:
        config = directory / "configs" / "fake_qe_fpga_system.py"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("# fake config consumed by fake gem5 wrapper\n", encoding="utf-8")
        qe_input = directory / "inputs" / "h2_tiny_gamma.in"
        qe_input.parent.mkdir(parents=True, exist_ok=True)
        qe_input.write_text(
            "&CONTROL\n"
            "  calculation = 'scf',\n"
            "  prefix = 'h2_tiny',\n"
            "  pseudo_dir = './pseudo',\n"
            "  outdir = './out',\n"
            "/\n"
            "&SYSTEM\n"
            "  ibrav = 1,\n"
            "  nat = 2,\n"
            "  ntyp = 1,\n"
            "/\n"
            "&ELECTRONS\n"
            "/\n"
            "ATOMIC_SPECIES\n"
            "  H  1.00794  H.pbe-rrkjus.UPF\n"
            "ATOMIC_POSITIONS {bohr}\n"
            "  H  0.0  0.0  -0.7\n"
            "  H  0.0  0.0   0.7\n"
            "K_POINTS gamma\n",
            encoding="utf-8",
        )
        pseudo_dir = directory / "pseudo"
        if not missing_pseudo_dir:
            pseudo_dir.mkdir(parents=True, exist_ok=True)
            (pseudo_dir / "H.pbe-rrkjus.UPF").write_text("fake pseudo\n", encoding="utf-8")
        run_dir = directory / "run"
        return {
            "config": config,
            "qe_input": qe_input,
            "pseudo_dir": pseudo_dir,
            "run_dir": run_dir,
        }

    def assert_refused_report(self, report: dict[str, Any], mode: str) -> None:
        expected_backend_class = {
            "systemc_standalone": "systemc_standalone_proxy",
            "systemc_timed_functional": "systemc_timed_functional_proxy",
            "gem5_systemc_smoke": "gem5_systemc_smoke",
            "gem5_systemc_timed_proxy": "gem5_systemc_timed_proxy",
        }[mode]
        expected_source_kind = (
            "backend_runner_systemc"
            if mode in {"systemc_standalone", "systemc_timed_functional"}
            else "backend_runner_gem5_systemc"
        )
        self.assertEqual(report["schema_version"], "backend_execution_report_v0")
        self.assertEqual(report["execution_status"], "refused")
        self.assertEqual(report["fidelity"], mode)
        self.assertEqual(report["backend_class"], expected_backend_class)
        self.assertEqual(report["source_kind"], expected_source_kind)
        self.assertIn("refusal_reason", report)
        self.assertFalse(report["correctness_gate"]["workload_equivalent_claim"])
        self.assertFalse(report["correctness_gate"]["domain_equivalence_claim"])
        self.assertIn("no_rtl_hls_board_or_asic_implementation_claim", report["non_claims"])
        self.assertIn("metric_groups", report["metrics"])
        self.assertIn("summary", report["metrics"]["metric_groups"])
        self.assertIn("runner", report["metrics"]["metric_groups"])

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

    def test_invalid_request_forbidden_claim_refusal_report_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload = self.make_request("systemc_standalone")
            payload["domain_extension"]["qe"]["implementation_claim"] = "board evidence passed"
            request = self.write_request(tmp, payload)
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

            self.assertEqual(rc, 2)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_standalone")
            RUNNER.validate_report(report)
            self.assertIn("invalid backend execution request", report["refusal_reason"])

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
            legacy = ROOT / "docs/benchmarks/archive/results/qe_dse_gem5_systemc_smoke_report_v0.json"

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
            legacy_src = ROOT / "docs/benchmarks/archive/results/qe_dse_gem5_systemc_smoke_report_v0.json"
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
            self.assertEqual(report["backend_class"], "systemc_standalone_proxy")
            self.assertEqual(report["source_kind"], "backend_runner_systemc")
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
            arch_cfg = tmp / "cfg" / "architecture.json"
            arch_cfg.write_text("{}\n", encoding="utf-8")
            request_payload = self.make_request(
                "systemc_timed_functional",
                input_refs={
                    "systemc_executable": "bin/fake_systemc.py",
                    "architecture_config": "cfg/architecture.json",
                    "systemc_config": "cfg/systemc.json",
                    "architecture_config": "cfg/architecture.json",
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
            self.assertEqual(env["QEBS_INPUT_REF_ARCHITECTURE_CONFIG"], str(arch_cfg))
            self.assertEqual(env["QEBS_INPUT_REF_SYSTEMC_CONFIG"], str(cfg))
            self.assertEqual(env["QEBS_ARCH_CONFIG"], str(arch_cfg))
            self.assertEqual(env["QEBS_ARCHITECTURE_CONFIG"], str(arch_cfg))
            self.assertEqual(env["QEBS_SYSTEMC_CONFIG_REF"], str(cfg))
            self.assertEqual(env["QEBS_RESULT_JSON"], str(raw_result))
            self.assertEqual(env["QEBS_BACKEND_EXECUTION_REPORT_JSON"], str(output))
            self.assertEqual(env["QEBS_BACKEND_REPORT_JSON"], str(output))

    def test_systemc_request_under_backend_execution_requests_resolves_sibling_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            frontend_root = tmp / "frontend_dse"
            request_dir = frontend_root / "backend_execution_requests"
            request_dir.mkdir(parents=True)
            exe = frontend_root / "bin" / "fake_systemc.py"
            exe.parent.mkdir(parents=True)
            exe.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os\n"
                "from pathlib import Path\n"
                "env = {k: v for k, v in os.environ.items() if k.startswith('QEBS_')}\n"
                "Path(os.environ['QEBS_RESULT_JSON']).write_text(json.dumps({\n"
                "  'schema_version': 'systemc_architecture_candidate_result_v0',\n"
                "  'generated_at_utc': '2026-04-28T00:00:00Z',\n"
                "  'case_id': 'si8_proxy',\n"
                "  'architecture_family': 'F2',\n"
                "  'assumption_set_id': 'unit_profile',\n"
                "  'run_summary': {'total_episodes': 1, 'total_ref_cycles': 77},\n"
                "  'final': {'converged': True, 'scf_iterations': 1},\n"
                "  'iteration_diagnostics': [],\n"
                "  'metrics': {},\n"
                "  'cluster_metrics': {'qebs_env': env},\n"
                "  'timing': {'wall_time_s': 0.001}\n"
                "}, sort_keys=True), encoding='utf-8')\n",
                encoding="utf-8",
            )
            exe.chmod(exe.stat().st_mode | 0o111)
            arch_cfg = frontend_root / "architecture_configs" / "candidate.json"
            arch_cfg.parent.mkdir(parents=True)
            arch_cfg.write_text("{}\n", encoding="utf-8")
            systemc_cfg = frontend_root / "systemc_configs" / "candidate.json"
            systemc_cfg.parent.mkdir(parents=True)
            systemc_cfg.write_text("{}\n", encoding="utf-8")
            request_payload = self.make_request(
                "systemc_timed_functional",
                input_refs={
                    "systemc_executable": "bin/fake_systemc.py",
                    "architecture_config": "architecture_configs/candidate.json",
                    "systemc_config": "systemc_configs/candidate.json",
                },
            )
            request = request_dir / "candidate.json"
            request.write_text(json.dumps(request_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            output = tmp / "report.json"

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
            env = self.read_report(output)["artifact_refs"]["source_cluster_metrics"]["qebs_env"]
            self.assertEqual(env["QEBS_ARCH_CONFIG"], str(arch_cfg))
            self.assertEqual(env["QEBS_ARCHITECTURE_CONFIG"], str(arch_cfg))
            self.assertEqual(env["QEBS_SYSTEMC_CONFIG_REF"], str(systemc_cfg))
            self.assertEqual(env["QEBS_INPUT_REF_ARCHITECTURE_CONFIG"], str(arch_cfg))
            self.assertNotIn("backend_execution_requests/architecture_configs", env["QEBS_ARCH_CONFIG"])

    def test_systemc_config_ref_does_not_fallback_to_arch_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            exe = tmp / "bin" / "fake_systemc.py"
            exe.parent.mkdir(parents=True)
            exe.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os\n"
                "from pathlib import Path\n"
                "env = {k: v for k, v in os.environ.items() if k.startswith('QEBS_')}\n"
                "Path(os.environ['QEBS_RESULT_JSON']).write_text(json.dumps({\n"
                "  'schema_version': 'systemc_architecture_candidate_result_v0',\n"
                "  'generated_at_utc': '2026-04-28T00:00:00Z',\n"
                "  'case_id': 'si8_proxy',\n"
                "  'architecture_family': 'F2',\n"
                "  'assumption_set_id': 'unit_profile',\n"
                "  'run_summary': {'total_episodes': 1, 'total_ref_cycles': 1},\n"
                "  'final': {'converged': True, 'scf_iterations': 1},\n"
                "  'iteration_diagnostics': [],\n"
                "  'metrics': {},\n"
                "  'cluster_metrics': {'qebs_env': env},\n"
                "  'timing': {'wall_time_s': 0.001}\n"
                "}, sort_keys=True), encoding='utf-8')\n",
                encoding="utf-8",
            )
            exe.chmod(exe.stat().st_mode | 0o111)
            cfg = tmp / "cfg" / "systemc.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("{}\n", encoding="utf-8")
            request = self.write_request(
                tmp,
                self.make_request(
                    "systemc_timed_functional",
                    input_refs={"systemc_executable": "bin/fake_systemc.py", "systemc_config": "cfg/systemc.json"},
                ),
            )
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request", str(request), "--output", str(output),
                "--mode", "systemc_timed_functional", "--allow-execute",
            ])

            self.assertEqual(rc, 0)
            env = self.read_report(output)["artifact_refs"]["source_cluster_metrics"]["qebs_env"]
            self.assertEqual(env["QEBS_SYSTEMC_CONFIG_FILE"], str(cfg))
            self.assertNotIn("QEBS_ARCH_CONFIG", env)

    def test_systemc_execution_can_accept_direct_backend_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_direct_backend_report_executable(tmp, "direct_backend_report.py")
            request = self.write_request(
                tmp,
                self.make_request(
                    "systemc_timed_functional",
                    input_refs={"systemc_executable": "bin/direct_backend_report.py"},
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

            self.assertEqual(rc, 0)
            self.assertFalse(raw_result.exists())
            report = self.read_report(output)
            self.assertEqual(report["execution_status"], "executed")
            self.assertEqual(report["control_path"]["completion_source"], "direct_backend_execution_report")
            self.assertEqual(report["claim_ceiling"], "systemc_timed_functional_proxy_only")

    def test_systemc_direct_backend_report_rejects_candidate_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_direct_backend_report_executable(
                tmp,
                "bad_direct_backend_report.py",
                candidate_id_expr="'wrong_candidate'",
                completion_source="bad_direct_backend_execution_report",
            )
            request = self.write_request(
                tmp,
                self.make_request(
                    "systemc_timed_functional",
                    input_refs={"systemc_executable": "bin/bad_direct_backend_report.py"},
                ),
            )
            output = tmp / "report.json"

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
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_timed_functional")
            self.assertIn("candidate_id does not match request", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["direct_backend_execution_report_status"], "invalid")
            self.assertTrue(Path(report["artifact_refs"]["direct_backend_execution_report"]).exists())

    def test_strict_direct_backend_report_validation_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_direct_backend_report_executable(
                tmp,
                "bad_direct_backend_report.py",
                candidate_id_expr="'wrong_candidate'",
                completion_source="bad_direct_backend_execution_report",
            )
            request = self.write_request(
                tmp,
                self.make_request(
                    "systemc_timed_functional",
                    input_refs={"systemc_executable": "bin/bad_direct_backend_report.py"},
                ),
            )
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_timed_functional",
                "--allow-execute",
                "--strict-report-validation",
            ])

            self.assertEqual(rc, 1)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_timed_functional")
            self.assertIn("direct BackendExecutionReport validation failed", report["refusal_reason"])

    def test_allow_execute_refuses_projection_only_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_direct_backend_report_executable(tmp, "direct_backend_report.py")
            payload = self.make_request(
                "systemc_timed_functional",
                input_refs={"systemc_executable": "bin/direct_backend_report.py"},
            )
            payload["candidate_identity"]["validity_class"] = "projection_only"
            request = self.write_request(tmp, payload)
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_timed_functional",
                "--allow-execute",
            ])

            self.assertEqual(rc, 2)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_timed_functional")
            self.assertIn("valid_executable", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["candidate_validity_class"], "projection_only")

    def test_debug_non_executable_candidate_refuses_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            exe = self.write_direct_backend_report_executable(tmp, "direct_backend_report.py")
            payload = self.make_request(
                "systemc_timed_functional",
                input_refs={"systemc_executable": "bin/direct_backend_report.py"},
            )
            payload["candidate_identity"]["validity_class"] = "debug_only"
            request = self.write_request(tmp, payload)
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "systemc_timed_functional",
                "--allow-execute",
                "--allow-non-executable-debug",
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assert_refused_report(report, "systemc_timed_functional")
            self.assertEqual(report["artifact_refs"]["candidate_execution_status"], "not_attempted")
            self.assertNotEqual(report["artifact_refs"].get("source"), exe.stem)

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

    def test_b4_with_config_refuses_without_explicit_systemc_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_fake_gem5_report_executable(tmp)
            config = tmp / "configs" / "fake_gem5_config.py"
            config.parent.mkdir(parents=True)
            config.write_text("# fake config\n", encoding="utf-8")
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_timed_proxy",
                    input_refs={
                        "gem5_executable": "bin/gem5.opt",
                        "gem5_config": "configs/fake_gem5_config.py",
                    },
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
            self.assertIn("requires an explicit systemc_bridge", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["systemc_bridge_status"], "missing_input_ref")

    def test_b4_refuses_when_real_bridge_capability_is_not_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_fake_gem5_report_executable(tmp)
            config = tmp / "configs" / "fake_gem5_config.py"
            config.parent.mkdir(parents=True)
            config.write_text("# fake config\n", encoding="utf-8")
            bridge = tmp / "lib" / "libgem5_systemc_bridge.a"
            bridge.parent.mkdir(parents=True)
            bridge.write_text("fake bridge artifact for unit test\n", encoding="utf-8")
            payload = self.make_request(
                "gem5_systemc_timed_proxy",
                input_refs={
                    "gem5_executable": "bin/gem5.opt",
                    "gem5_config": "configs/fake_gem5_config.py",
                    "systemc_bridge_library": "lib/libgem5_systemc_bridge.a",
                },
            )
            payload["backend_capability_profile"]["supports_real_bridge"] = False
            request = self.write_request(tmp, payload)
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
            self.assertIn("supports_real_bridge=true", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["real_bridge_capability_status"], "missing_or_false")

    def test_b4_gem5_direct_report_executes_with_explicit_config_and_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_fake_gem5_report_executable(tmp)
            config = tmp / "configs" / "fake_gem5_config.py"
            config.parent.mkdir(parents=True)
            config.write_text("# fake config consumed by unit-test gem5 wrapper\n", encoding="utf-8")
            bridge = tmp / "lib" / "libgem5_systemc_bridge.a"
            bridge.parent.mkdir(parents=True)
            bridge.write_text("fake bridge artifact for unit test\n", encoding="utf-8")
            sidecar = self.write_timing_sidecar(tmp)
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_timed_proxy",
                    input_refs=self.b4_input_refs(),
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
            self.assertEqual(report["execution_status"], "executed")
            self.assertEqual(report["claim_ceiling"], "gem5_systemc_timed_proxy_only")
            self.assertEqual(report["environment"]["fpga_execution_mode"], "real_bridge")
            self.assertEqual(report["environment"]["real_systemc_target"], "1")
            self.assertEqual(report["environment"]["systemc_bridge"], str(bridge))
            self.assertEqual(report["environment"]["timing_sidecar"], str(sidecar))
            self.assertEqual(report["control_path"]["completion_source"], "timed_proxy_scheduled_event")
            self.assertNotEqual(report["control_path"]["completion_source"], "smoke_immediate_complete")
            self.assertEqual(report["control_path"]["systemc_start_tick"], 120)
            self.assertEqual(report["control_path"]["completion_tick"], 560)
            self.assertEqual(report["metrics"]["cycle_source"], "timing_sidecar_projection")
            self.assertFalse(report["metrics"]["event_timed_device_activity_observed"])
            self.assertEqual(report["metrics"]["successful_dma_transfer_bytes"], 6144)
            self.assertEqual(report["metrics"]["dma_warning_count"], 0)
            self.assertEqual(report["artifact_refs"]["gem5_config"], str(config))
            self.assertEqual(report["artifact_refs"]["systemc_bridge"], str(bridge))
            self.assertEqual(report["artifact_refs"]["timing_sidecar"], str(sidecar))
            self.assertIn("gem5_stdout_log", report["artifact_refs"])

    def test_b4_candidate_profile_enables_strict_event_env_for_gem5_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_fake_gem5_report_executable(tmp)
            config = tmp / "configs" / "fake_gem5_config.py"
            config.parent.mkdir(parents=True)
            config.write_text("# fake config consumed by unit-test gem5 wrapper\n", encoding="utf-8")
            bridge = tmp / "lib" / "libgem5_systemc_bridge.a"
            bridge.parent.mkdir(parents=True)
            bridge.write_text("fake bridge artifact for unit test\n", encoding="utf-8")
            sidecar = self.write_timing_sidecar(tmp)
            profile = self.write_candidate_timing_profile(tmp)
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_timed_proxy",
                    input_refs=self.b4_input_refs(
                        candidate_timing_profile="timing/candidate_timing_profile_v0.json",
                    ),
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
            self.assertEqual(report["execution_status"], "executed")
            self.assertEqual(report["environment"]["candidate_timing_profile"], str(profile))
            self.assertEqual(report["environment"]["strict_b4_event_timing"], "1")
            self.assertTrue(report["environment"]["device_event_report"].endswith(".device_event_report.json"))
            self.assertEqual(report["artifact_refs"]["candidate_timing_profile"], str(profile))
            self.assertEqual(report["artifact_refs"]["strict_b4_runtime_timing_input"], str(profile))
            self.assertTrue(report["artifact_refs"]["device_event_report"].endswith(".device_event_report.json"))
            self.assertEqual(report["artifact_refs"]["timing_sidecar"], str(sidecar))

    def test_b4_direct_report_rejects_missing_timed_proxy_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_direct_backend_report_executable(tmp, "bad_b4_report.py")
            config = tmp / "configs" / "fake_gem5_config.py"
            config.parent.mkdir(parents=True)
            config.write_text("# fake config\n", encoding="utf-8")
            bridge = tmp / "lib" / "libgem5_systemc_bridge.a"
            bridge.parent.mkdir(parents=True)
            bridge.write_text("fake bridge artifact for unit test\n", encoding="utf-8")
            self.write_timing_sidecar(tmp)
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_timed_proxy",
                    input_refs=self.b4_input_refs(gem5_executable="bin/bad_b4_report.py"),
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
            self.assertIn("B4 timed proxy report requires", report["refusal_reason"])

    def test_b4_direct_report_rejects_bridge_provenance_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_fake_gem5_report_executable(tmp)
            config = tmp / "configs" / "fake_gem5_config.py"
            config.parent.mkdir(parents=True)
            config.write_text("# fake config\n", encoding="utf-8")
            expected_bridge = tmp / "lib" / "expected_bridge.so"
            actual_bridge = tmp / "lib" / "actual_bridge.so"
            expected_bridge.parent.mkdir(parents=True)
            expected_bridge.write_text("expected bridge artifact\n", encoding="utf-8")
            actual_bridge.write_text("actual bridge artifact\n", encoding="utf-8")
            self.write_timing_sidecar(tmp)
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_timed_proxy",
                    input_refs=self.b4_input_refs(systemc_bridge_library="lib/expected_bridge.so"),
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
            self.assertEqual(report["execution_status"], "executed")
            with self.assertRaisesRegex(ValueError, "systemc_bridge does not match expected bridge"):
                RUNNER._validate_b4_timed_proxy_report_shape(
                    report,
                    expected_systemc_bridge=actual_bridge,
                )

    def test_b4_direct_report_accepts_normalized_bridge_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bridge = tmp / "lib" / "expected_bridge.so"
            sidecar = tmp / "timing" / "timing_sidecar.json"
            bridge.parent.mkdir(parents=True)
            sidecar.parent.mkdir(parents=True)
            bridge.write_text("expected bridge artifact\n", encoding="utf-8")
            sidecar.write_text("{}\n", encoding="utf-8")
            equivalent_bridge = bridge.parent / ".." / "lib" / bridge.name
            equivalent_sidecar = sidecar.parent / ".." / "timing" / sidecar.name

            RUNNER._validate_b4_timed_proxy_report_shape(
                {
                    "environment": {
                        "fpga_execution_mode": "real_bridge",
                        "real_systemc_target": "1",
                        "systemc_bridge": str(equivalent_bridge),
                        "timing_sidecar": str(equivalent_sidecar),
                    },
                    "control_path": {
                        "mmio_read_count": 5,
                        "mmio_write_count": 8,
                        "polling_read_count": 3,
                        "interrupt_count": 0,
                        "command_issue_tick": 100,
                        "device_accept_tick": 110,
                        "systemc_start_tick": 120,
                        "systemc_end_tick": 520,
                        "completion_tick": 560,
                        "dma_start_tick": 130,
                        "dma_end_tick": 300,
                    },
                    "metrics": {
                        "host_control_mmio_read_count": 5,
                        "host_control_mmio_write_count": 8,
                        "host_control_polling_read_count": 3,
                        "host_control_interrupt_count": 0,
                        "host_control_queue_wait_ns": 10,
                        "systemc_datapath_device_busy_ns": 4000000,
                        "systemc_datapath_compute_ns": 3000000,
                        "systemc_datapath_dma_read_ns": 1000,
                        "systemc_datapath_dma_write_ns": 500,
                        "systemc_datapath_queue_depth": 1,
                        "systemc_datapath_backpressure_count": 0,
                        "logical_dma_payload_bytes": 6144,
                        "observed_gem5_dma_stat_bytes": 6144,
                        "successful_dma_transfer_bytes": 6144,
                        "dma_warning_count": 0,
                        "cycle_source": "timing_sidecar_projection",
                        "cycle_proxy_source": "timing_sidecar_projection",
                        "event_timed_device_activity_observed": False,
                        "candidate_device_event_delta_ticks": None,
                    },
                    "artifact_refs": {"timing_sidecar": str(equivalent_sidecar)},
                },
                expected_systemc_bridge=bridge,
                expected_timing_sidecar=sidecar,
            )

    def test_b4_direct_report_rejects_event_timed_source_without_mmio_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bridge = tmp / "lib" / "expected_bridge.so"
            sidecar = tmp / "timing" / "timing_sidecar.json"
            bridge.parent.mkdir(parents=True)
            sidecar.parent.mkdir(parents=True)
            bridge.write_text("expected bridge artifact\n", encoding="utf-8")
            sidecar.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "nonzero MMIO activity"):
                RUNNER._validate_b4_timed_proxy_report_shape(
                    {
                        "environment": {
                            "fpga_execution_mode": "real_bridge",
                            "real_systemc_target": "1",
                            "systemc_bridge": str(bridge),
                            "timing_sidecar": str(sidecar),
                        },
                        "control_path": {
                            "mmio_read_count": 0,
                            "mmio_write_count": 0,
                            "polling_read_count": 0,
                            "interrupt_count": 0,
                            "command_issue_tick": 100,
                            "device_accept_tick": 110,
                            "systemc_start_tick": 120,
                            "systemc_end_tick": 520,
                            "completion_tick": 560,
                            "dma_start_tick": 130,
                            "dma_end_tick": 300,
                        },
                        "metrics": {
                            "host_control_mmio_read_count": 0,
                            "host_control_mmio_write_count": 0,
                            "host_control_polling_read_count": 0,
                            "host_control_interrupt_count": 0,
                            "host_control_queue_wait_ns": 10,
                            "systemc_datapath_device_busy_ns": 4000000,
                            "systemc_datapath_compute_ns": 3000000,
                            "systemc_datapath_dma_read_ns": 1000,
                            "systemc_datapath_dma_write_ns": 500,
                            "systemc_datapath_queue_depth": 1,
                            "systemc_datapath_backpressure_count": 0,
                            "logical_dma_payload_bytes": 6144,
                            "observed_gem5_dma_stat_bytes": 6144,
                            "successful_dma_transfer_bytes": 6144,
                            "dma_warning_count": 0,
                            "cycle_source": "gem5_event_timed_device_observed",
                            "event_timed_device_activity_observed": True,
                            "candidate_device_event_delta_ticks": 460,
                        },
                        "artifact_refs": {"timing_sidecar": str(sidecar)},
                    },
                    expected_systemc_bridge=bridge,
                    expected_timing_sidecar=sidecar,
                )

    def test_b4_direct_report_rejects_event_timed_source_without_candidate_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bridge = tmp / "lib" / "expected_bridge.so"
            sidecar = tmp / "timing" / "timing_sidecar.json"
            bridge.parent.mkdir(parents=True)
            sidecar.parent.mkdir(parents=True)
            bridge.write_text("expected bridge artifact\n", encoding="utf-8")
            sidecar.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "candidate timing profile provenance"):
                RUNNER._validate_b4_timed_proxy_report_shape(
                    {
                        "environment": {
                            "fpga_execution_mode": "real_bridge",
                            "real_systemc_target": "1",
                            "systemc_bridge": str(bridge),
                            "timing_sidecar": str(sidecar),
                        },
                        "control_path": {
                            "mmio_read_count": 2,
                            "mmio_write_count": 3,
                            "polling_read_count": 1,
                            "interrupt_count": 0,
                            "command_issue_tick": 100,
                            "device_accept_tick": 110,
                            "systemc_start_tick": 120,
                            "systemc_end_tick": 520,
                            "completion_tick": 560,
                            "dma_start_tick": 130,
                            "dma_end_tick": 300,
                            "mmio_activity_source": "gem5_simobject_counters",
                        },
                        "metrics": {
                            "host_control_mmio_read_count": 2,
                            "host_control_mmio_write_count": 3,
                            "host_control_polling_read_count": 1,
                            "host_control_interrupt_count": 0,
                            "host_control_queue_wait_ns": 10,
                            "systemc_datapath_device_busy_ns": 4000000,
                            "systemc_datapath_compute_ns": 3000000,
                            "systemc_datapath_dma_read_ns": 1000,
                            "systemc_datapath_dma_write_ns": 500,
                            "systemc_datapath_queue_depth": 1,
                            "systemc_datapath_backpressure_count": 0,
                            "logical_dma_payload_bytes": 6144,
                            "observed_gem5_dma_stat_bytes": 6144,
                            "successful_dma_transfer_bytes": 6144,
                            "dma_warning_count": 0,
                            "cycle_source": "gem5_event_timed_device_observed",
                            "event_timed_device_activity_observed": True,
                            "candidate_device_event_delta_ticks": 460,
                            "observed_device_activity_source": "gem5_simobject_counters",
                        },
                        "artifact_refs": {"timing_sidecar": str(sidecar)},
                    },
                    expected_systemc_bridge=bridge,
                    expected_timing_sidecar=sidecar,
                )

    def test_b4_direct_report_accepts_event_timed_source_with_profile_and_simobject_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bridge = tmp / "lib" / "expected_bridge.so"
            sidecar = tmp / "timing" / "timing_sidecar.json"
            profile = tmp / "timing" / "candidate_timing_profile_v0.json"
            bridge.parent.mkdir(parents=True)
            sidecar.parent.mkdir(parents=True)
            bridge.write_text("expected bridge artifact\n", encoding="utf-8")
            sidecar.write_text("{}\n", encoding="utf-8")
            profile.write_text("{}\n", encoding="utf-8")

            RUNNER._validate_b4_timed_proxy_report_shape(
                {
                    "environment": {
                        "fpga_execution_mode": "real_bridge",
                        "real_systemc_target": "1",
                        "systemc_bridge": str(bridge),
                        "timing_sidecar": str(sidecar),
                        "candidate_timing_profile": str(profile),
                    },
                    "control_path": {
                        "mmio_read_count": 2,
                        "mmio_write_count": 3,
                        "polling_read_count": 1,
                        "interrupt_count": 0,
                        "command_issue_tick": 100,
                        "device_accept_tick": 110,
                        "systemc_start_tick": 120,
                        "systemc_end_tick": 520,
                        "completion_tick": 560,
                        "dma_start_tick": 130,
                        "dma_end_tick": 300,
                        "mmio_activity_source": "gem5_simobject_counters",
                    },
                    "metrics": {
                        "host_control_mmio_read_count": 2,
                        "host_control_mmio_write_count": 3,
                        "host_control_polling_read_count": 1,
                        "host_control_interrupt_count": 0,
                        "host_control_queue_wait_ns": 10,
                        "systemc_datapath_device_busy_ns": 4000000,
                        "systemc_datapath_compute_ns": 3000000,
                        "systemc_datapath_dma_read_ns": 1000,
                        "systemc_datapath_dma_write_ns": 500,
                        "systemc_datapath_queue_depth": 1,
                        "systemc_datapath_backpressure_count": 0,
                        "logical_dma_payload_bytes": 6144,
                        "observed_gem5_dma_stat_bytes": 6144,
                        "successful_dma_transfer_bytes": 6144,
                        "dma_warning_count": 0,
                        "cycle_source": "gem5_event_timed_device_observed",
                        "event_timed_device_activity_observed": True,
                        "candidate_device_event_delta_ticks": 460,
                        "observed_device_activity_source": "gem5_simobject_counters",
                    },
                    "artifact_refs": {
                        "timing_sidecar": str(sidecar),
                        "candidate_timing_profile": str(profile),
                    },
                },
                expected_systemc_bridge=bridge,
                expected_timing_sidecar=sidecar,
            )

    def test_b4_refuses_missing_explicit_systemc_bridge_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            self.write_fake_gem5_report_executable(tmp)
            config = tmp / "configs" / "fake_gem5_config.py"
            config.parent.mkdir(parents=True)
            config.write_text("# fake config\n", encoding="utf-8")
            missing_bridge = tmp / "lib" / "missing_bridge.so"
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_timed_proxy",
                    input_refs={
                        "gem5_executable": "bin/gem5.opt",
                        "gem5_config": "configs/fake_gem5_config.py",
                        "systemc_bridge_library": str(missing_bridge),
                    },
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
            self.assertIn("SystemC bridge artifact is missing", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["systemc_bridge_status"], "missing")

    def test_real_qe_gem5_smoke_synthesizes_report_without_direct_backend_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_gem5 = self.write_fake_real_qe_gem5_executable(tmp)
            fake_qe = self.write_fake_qe_pw_executable(tmp)
            inputs = self.write_real_qe_smoke_inputs(tmp)
            stale_gem5_out = inputs["run_dir"] / "gem5_qe_outdir" / "stale.restart"
            stale_native_out = inputs["run_dir"] / "native_qe_outdir" / "stale.restart"
            stale_m5out = inputs["run_dir"] / "m5out" / "stale.stats"
            stale_gem5_out.parent.mkdir(parents=True, exist_ok=True)
            stale_native_out.parent.mkdir(parents=True, exist_ok=True)
            stale_m5out.parent.mkdir(parents=True, exist_ok=True)
            stale_gem5_out.write_text("old gem5 outdir state\n", encoding="utf-8")
            stale_native_out.write_text("old native outdir state\n", encoding="utf-8")
            stale_m5out.write_text("old m5out state\n", encoding="utf-8")
            request_payload = self.make_request(
                "gem5_systemc_smoke",
                input_refs={
                    "gem5_executable": str(fake_gem5),
                    "gem5_config": str(inputs["config"]),
                    "qe_binary": str(fake_qe),
                    "qe_input_template": str(inputs["qe_input"]),
                    "qe_pseudo_dir": str(inputs["pseudo_dir"]),
                    "qe_run_dir": str(inputs["run_dir"]),
                    "gem5_max_ticks": "99999",
                },
            )
            request_payload["software_runtime"]["mode"] = "real_qe_gem5_se_smoke"
            request = self.write_request(tmp, request_payload)
            output = tmp / "report.json"

            rc = RUNNER.main([
                "--request",
                str(request),
                "--output",
                str(output),
                "--mode",
                "gem5_systemc_smoke",
                "--allow-execute",
                "--timeout-s",
                "30",
            ])

            self.assertEqual(rc, 0)
            report = self.read_report(output)
            self.assertEqual(report["schema_version"], "backend_execution_report_v0")
            self.assertEqual(report["execution_status"], "executed")
            self.assertEqual(report["claim_ceiling"], "gem5_systemc_smoke_only")
            self.assertEqual(report["backend_class"], "gem5_systemc_smoke")
            self.assertEqual(report["source_kind"], "backend_runner_gem5_systemc")
            self.assertEqual(report["artifact_refs"]["artifact_subtype"], "real_qe_gem5_se_scf_smoke_v0")
            self.assertEqual(report["control_path"]["completion_source"], "gem5_se_real_pw_stdout_parser")
            self.assertEqual(report["control_path"]["completion_count"], 1)
            self.assertEqual(report["metrics"]["runtime_smoke_ticks"], 12345)
            self.assertEqual(report["metrics"]["cycle_proxy"], 12345)
            self.assertFalse(report["correctness_gate"]["workload_equivalent_claim"])
            self.assertIn("no_fpga_systemc_offload_claim", report["non_claims"])
            command = report["artifact_refs"]["gem5_command"]
            self.assertEqual(command[0], str(fake_gem5))
            self.assertEqual(command[1], "-d")
            self.assertTrue(Path(command[2]).is_absolute())
            self.assertEqual(command[3], str(inputs["config"]))
            self.assertEqual(command[command.index("--binary") + 1], str(fake_qe))
            options = command[command.index("--options") + 1]
            self.assertTrue(options.startswith("-in "))
            self.assertTrue(Path(options.split(" ", 1)[1]).is_absolute())
            self.assertEqual(command[command.index("--max-ticks") + 1], "99999")
            manifest = Path(report["artifact_refs"]["run_manifest"])
            self.assertTrue(manifest.exists())
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            native_input = Path(manifest_payload["native_qe_input"])
            gem5_input = Path(manifest_payload["gem5_qe_input"])
            native_outdir = Path(manifest_payload["native_qe_outdir"])
            gem5_outdir = Path(manifest_payload["gem5_qe_outdir"])
            self.assertNotEqual(native_input, gem5_input)
            self.assertNotEqual(native_outdir, gem5_outdir)
            self.assertEqual(Path(report["artifact_refs"]["qe_input"]), gem5_input)
            self.assertEqual(Path(report["artifact_refs"]["qe_outdir"]), gem5_outdir)
            self.assertIn(str(native_outdir), native_input.read_text(encoding="utf-8"))
            self.assertIn(str(gem5_outdir), gem5_input.read_text(encoding="utf-8"))
            self.assertFalse(manifest_payload["outdir_isolation"]["native_and_gem5_outdirs_shared"])
            self.assertFalse(stale_gem5_out.exists())
            self.assertFalse(stale_native_out.exists())
            self.assertFalse(stale_m5out.exists())
            self.assertTrue(manifest_payload["native_parse"]["scf_converged"])
            self.assertTrue(manifest_payload["gem5_parse"]["scf_converged"])
            self.assertEqual(manifest_payload["gem5_parse"]["gem5_exit_tick"], 12345)
            argv_payload = json.loads((inputs["run_dir"] / "fake_gem5_argv.json").read_text(encoding="utf-8"))
            self.assertEqual(argv_payload[1:4], ["-d", str(inputs["run_dir"] / "m5out"), str(inputs["config"])])

    def test_real_qe_gem5_smoke_fails_when_gem5_stdout_lacks_convergence_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_gem5 = self.write_fake_real_qe_gem5_executable(tmp, converged=False)
            fake_qe = self.write_fake_qe_pw_executable(tmp)
            inputs = self.write_real_qe_smoke_inputs(tmp)
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_smoke",
                    input_refs={
                        "gem5_executable": str(fake_gem5),
                        "gem5_config": str(inputs["config"]),
                        "qe_binary": str(fake_qe),
                        "qe_input_template": str(inputs["qe_input"]),
                        "qe_pseudo_dir": str(inputs["pseudo_dir"]),
                        "qe_run_dir": str(inputs["run_dir"]),
                        "gem5_max_ticks": "99999",
                    },
                ),
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

            self.assertEqual(rc, 1)
            report = self.read_report(output)
            self.assertEqual(report["execution_status"], "failed")
            self.assertEqual(report["fidelity"], "gem5_systemc_smoke")
            self.assertIn("did not expose required convergence", report["status_reason"])
            self.assertEqual(report["control_path"]["completion_count"], 0)
            self.assertEqual(report["artifact_refs"]["artifact_subtype"], "real_qe_gem5_se_scf_smoke_v0")

    def test_real_qe_gem5_smoke_refuses_missing_pseudo_dir_before_gem5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_gem5 = self.write_fake_real_qe_gem5_executable(tmp)
            fake_qe = self.write_fake_qe_pw_executable(tmp)
            inputs = self.write_real_qe_smoke_inputs(tmp, missing_pseudo_dir=True)
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_smoke",
                    input_refs={
                        "gem5_executable": str(fake_gem5),
                        "gem5_config": str(inputs["config"]),
                        "qe_binary": str(fake_qe),
                        "qe_input_template": str(inputs["qe_input"]),
                        "qe_pseudo_dir": str(inputs["pseudo_dir"]),
                        "qe_run_dir": str(inputs["run_dir"]),
                    },
                ),
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
            self.assertIn("QE pseudo_dir is missing", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["qe_pseudo_dir_status"], "missing")

    def test_real_qe_gem5_smoke_refuses_non_executable_pw_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_gem5 = self.write_fake_real_qe_gem5_executable(tmp)
            inputs = self.write_real_qe_smoke_inputs(tmp)
            qe_binary = tmp / "bin" / "pw.x"
            qe_binary.parent.mkdir(parents=True, exist_ok=True)
            qe_binary.write_text("#!/usr/bin/env sh\necho should-not-run\n", encoding="utf-8")
            request = self.write_request(
                tmp,
                self.make_request(
                    "gem5_systemc_smoke",
                    input_refs={
                        "gem5_executable": str(fake_gem5),
                        "gem5_config": str(inputs["config"]),
                        "qe_binary": str(qe_binary),
                        "qe_input_template": str(inputs["qe_input"]),
                        "qe_pseudo_dir": str(inputs["pseudo_dir"]),
                        "qe_run_dir": str(inputs["run_dir"]),
                    },
                ),
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
            self.assertIn("not executable", report["refusal_reason"])
            self.assertEqual(report["artifact_refs"]["qe_binary_status"], "not_executable")

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
