#!/usr/bin/env python3
"""QE-IC real GPU-vs-FPGA/hybrid opportunity campaign regressions."""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dse_v2.experiments import qe_ic_real_opportunity as campaign
from dse_v2.experiments.qe_ic_real_opportunity import gpu_baseline as baseline_module
from dse_v2.experiments.qe_ic_real_opportunity.candidate_evidence import (
    build_candidate_high_fidelity_evidence,
    candidate_evidence_from_csv,
    candidate_evidence_from_ingest_payload,
)
from dse_v2.experiments.qe_ic_real_opportunity.case_setup import generate_qe_ic_benchmark_cases
from dse_v2.experiments.qe_ic_real_opportunity.case_setup import prepare_qe_ic_cases
from dse_v2.experiments.qe_ic_real_opportunity.candidate_selection import (
    select_layer4_candidates_for_campaign,
)
from dse_v2.experiments.qe_ic_real_opportunity.eda_stub_evidence import (
    build_generated_eda_stub_evidence,
)
from dse_v2.experiments.qe_ic_real_opportunity.environment_probe import (
    discover_qe_executables,
    merge_local_and_remote_eda_tools,
    normalized_qe_probe_output_hash,
    parse_nvidia_smi_query_output,
    parse_ssh_config_hosts,
    probe_qe_ic_real_opportunity_environment,
    probe_remote_eda_aliases,
)
from dse_v2.experiments.qe_ic_real_opportunity.gpu_baseline import (
    build_gpu_baseline_measurements,
    run_gpu_baseline_commands_if_available,
)
from dse_v2.experiments.qe_ic_real_opportunity.implementation_audit import (
    audit_candidate_implementation_quality,
)


CONFIG_PATH = Path(
    "dse_v2/testdata/qe_ic_real_opportunity/"
    "qe_ic_real_opportunity_campaign_config_template.json"
)
CHECKED_IN_RESULTS_DIR = Path("artifacts/qe_ic_real_opportunity_campaign")
CLI_PATH = Path("dse_v2/scripts/dse/run_qe_ic_real_opportunity_campaign.py")
LAYER4_PLAN_PATH = Path("artifacts/qe_ic_candidate_plan/qe_ic_candidate_plan.json")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _tracked_layer4_candidate(target_type: str = "fpga_only") -> dict:
    plan = _load_json(LAYER4_PLAN_PATH)
    l1 = _load_json(Path("artifacts/qe_ic_l1_cost_model/qe_ic_l1_cost_model_results.json"))
    closed = _load_json(Path("artifacts/qe_ic_closed_loop_dse/qe_ic_closed_loop_dse_results.json"))
    tracked = {row["candidate_id"] for row in l1["results"]} & {
        row["candidate_id"] for row in closed["candidate_trajectory"]
    }
    preferred_templates = {
        "fpga_only": {"fpga_fft_transpose_engine", "fpga_streaming_pipeline"},
        "gpu_fpga_hybrid": {"hybrid_reduction_sidecar", "hybrid_dma_overlap_sidecar"},
    }
    preferred = next(
        (
            candidate
            for candidate in plan["candidates"]
            if candidate["candidate_id"] in tracked
            and candidate["target_type"] == target_type
            and candidate["template_id"] in preferred_templates.get(target_type, set())
        ),
        None,
    )
    if preferred is not None:
        return preferred
    return next(
        candidate
        for candidate in plan["candidates"]
        if candidate["candidate_id"] in tracked and candidate["target_type"] == target_type
    )


def _measured_baseline_runs(candidate: dict, *, runtime_seconds: list[float] | None = None) -> list[dict]:
    return [
        {
            "workload_family_id": candidate["workload_family_id"],
            "case_id": "controlled_case",
            "program": "pw.x",
            "input_deck_hash": "sha256:" + "1" * 64,
            "precision": "fp64_mixed",
            "runtime_seconds": value,
            "gpu_utilization": 0.55,
            "gpu_memory_bandwidth_utilization": 0.61,
            "host_device_transfer_seconds": 2.0,
            "communication_seconds": 1.0,
            "profile_artifact_hash": "sha256:" + "2" * 64,
        }
        for value in (runtime_seconds or [99.0, 100.0, 101.0])
    ]


def _candidate_evidence_record(candidate: dict, *, workflow_runtime: float = 80.0) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "workload_family_id": candidate["workload_family_id"],
        "motif_id": candidate["motif_id"],
        "target_type": candidate["target_type"],
        "case_id": "controlled_case",
        "program": "pw.x",
        "input_deck_hash": "sha256:" + "1" * 64,
        "precision": "fp64_mixed",
        "evidence_level": "trace_replay",
        "evidence_status": "high_fidelity_estimate",
        "architecture_summary": {
            "architecture_id": "controlled_arch",
            "architecture_family": candidate["candidate_parameters"]["template_family"],
            "gpu_role": "primary_compute" if candidate["target_type"] == "gpu_fpga_hybrid" else "none",
            "fpga_role": "controlled_workflow_sidecar",
            "host_role": "scf_control_retained",
            "dataflow_summary": "controlled workflow replay",
            "memory_interface": "pcie_hbm",
            "synchronization_model": "batched_barrier",
        },
        "runtime_seconds_runs": [workflow_runtime - 1.0, workflow_runtime, workflow_runtime + 1.0],
        "runtime_seconds_mean": workflow_runtime,
        "runtime_seconds_std": 1.0,
        "confidence_interval_95": {"low": workflow_runtime - 2.0, "high": workflow_runtime + 2.0},
        "workflow_runtime_seconds_mean": workflow_runtime,
        "kernel_runtime_seconds_mean": workflow_runtime - 20.0,
        "transfer_overhead_seconds": 4.0,
        "workflow_overhead_seconds": 3.0,
        "resource": {
            "resource_feasible": True,
            "timing_feasible": True,
            "lut_utilization": 0.55,
            "ff_utilization": 0.51,
            "bram_utilization": 0.46,
            "dsp_utilization": 0.50,
            "hbm_port_utilization": 0.44,
            "fmax_mhz": 280.0,
        },
        "evidence_artifact_hash": "sha256:" + "3" * 64,
        "tool_provenance": {
            "tool": "controlled_trace_replay",
            "version": "test",
            "run_id": "controlled_trace",
            "config_hash": "sha256:" + "4" * 64,
            "output_artifact_hash": "sha256:" + "5" * 64,
        },
    }


def test_public_api_exports_expected_functions():
    assert campaign.run_qe_ic_real_opportunity_campaign
    assert campaign.validate_qe_ic_real_opportunity_campaign_report
    assert campaign.write_qe_ic_real_opportunity_campaign_artifacts
    assert campaign.load_qe_ic_real_opportunity_campaign_report


def test_config_template_matches_required_policy():
    config = _load_json(CONFIG_PATH)

    assert config["schema_version"] == "dse.qe_ic.real_opportunity_campaign_config.v1"
    assert config["mode"] == "run_if_available_or_ingest_only"
    assert config["candidate_selection"]["select_from_layer4_only"] is True
    assert config["evidence_policy"]["forbid_fabricated_measurements"] is True
    assert config["claim_policy"]["must_use_existing_opportunity_claim_gate"] is True
    assert config["claim_policy"]["allow_kernel_only_claim"] is False


def test_default_campaign_does_not_fabricate_measurements(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(CONFIG_PATH, out_dir=tmp_path)

    assert report["schema_version"] == "dse.qe_ic.real_opportunity_campaign_report.v1"
    assert report["campaign_status"] in {"blocked", "evidence_missing", "partially_ready"}
    assert report["gpu_baseline_summary"]["measurements_are_real"] is False
    assert report["candidate_evidence_summary"]["results_are_real"] is False
    assert report["final_answer"]["overall_answer"] == "evidence_missing"
    assert report["final_answer"]["best_candidate_id"] is None
    assert report["opportunity_summary"]["claim_gate_invoked"] is False
    assert len(report["opportunity_summary"]["opportunity_records"]) == len(report["candidate_selection"])
    assert all(not row["claim_allowed"] for row in report["opportunity_summary"]["opportunity_records"])
    assert all(row["verdict"] == "evidence_missing" for row in report["opportunity_summary"]["opportunity_records"])
    assert all("implementation_quality_classification" in row for row in report["opportunity_summary"]["opportunity_records"])
    assert all("final_interpretation" in row for row in report["opportunity_summary"]["opportunity_records"])
    assert "blocked_by_missing_candidate_design" in report["environment_summary"]["blockers"]
    assert "No FPGA/GPU+FPGA superiority claim is made" in report["claim_boundary"]


def test_missing_qe_or_input_deck_produces_valid_campaign_report(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(CONFIG_PATH, out_dir=tmp_path)
    validation = campaign.validate_qe_ic_real_opportunity_campaign_report(report)

    statuses = {case["case_status"] for case in report["case_summary"]}
    assert "input_deck_missing" in statuses
    assert report["campaign_status"] != "failed"
    assert validation["status"] == "passed"
    assert not validation["errors"]


def test_local_gpu_probe_parser_accepts_nvidia_smi_like_output():
    parsed = parse_nvidia_smi_query_output(
        "NVIDIA A100-SXM4-80GB, 81251 MiB, 535.129.03, 12.2\n"
    )

    assert parsed == {
        "gpu_present": True,
        "gpu_model": "NVIDIA A100-SXM4-80GB",
        "gpu_memory_total_mib": 81251,
        "driver_version": "535.129.03",
        "cuda_version": "12.2",
    }


def test_local_gpu_probe_parser_accepts_rtx_3070_output():
    parsed = parse_nvidia_smi_query_output(
        "NVIDIA GeForce RTX 3070, 8192 MiB, 596.36, 13.2\n"
    )

    assert parsed == {
        "gpu_present": True,
        "gpu_model": "NVIDIA GeForce RTX 3070",
        "gpu_memory_total_mib": 8192,
        "driver_version": "596.36",
        "cuda_version": "13.2",
    }


def test_environment_probe_uses_wsl_compatible_nvidia_smi_query(
    monkeypatch: pytest.MonkeyPatch,
):
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)

        class Result:
            returncode = 0
            stdout = "NVIDIA GeForce RTX 3070, 8192, 596.36\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "dse_v2.experiments.qe_ic_real_opportunity.environment_probe._which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr("subprocess.run", fake_run)

    env = probe_qe_ic_real_opportunity_environment()

    assert env["gpu"]["gpu_present"] is True
    assert env["gpu"]["gpu_model"] == "NVIDIA GeForce RTX 3070"
    assert env["gpu"]["gpu_memory_total_mib"] == 8192
    assert env["gpu"]["driver_version"] == "596.36"
    assert env["gpu"]["cuda_version"] is None
    assert "--query-gpu=name,memory.total,driver_version" in commands[0]


def test_qe_discovery_uses_env_qe_bin_and_requires_dynamic_gpu_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bin_dir = tmp_path / "qe-bin"
    bin_dir.mkdir()
    pw = bin_dir / "pw.x"
    pw.write_text("#!/bin/sh\necho 'Program PWSCF v.7.5 GPU CUDA enabled'\n", encoding="utf-8")
    pw.chmod(0o755)
    monkeypatch.setenv("QE_BIN", str(bin_dir))
    monkeypatch.delenv("QE_ROOT", raising=False)
    monkeypatch.delenv("ESPRESSO_ROOT", raising=False)

    discovered = discover_qe_executables(config={}, programs=["pw.x"], repo_root=tmp_path)

    pw_record = discovered["programs"]["pw.x"]
    assert pw_record["path"] == str(pw)
    assert pw_record["runs"] is True
    assert pw_record["help_gpu_support"] == "detected"
    assert pw_record["dynamic_gpu_library_support"] == "not_detected"
    assert pw_record["gpu_support"] == "not_detected"
    assert pw_record["dynamic_gpu_libraries"] == []
    assert pw_record["probe_command_output_hash"].startswith("sha256:")
    assert "7.5" in pw_record["version"]


def test_qe_discovery_marks_gpu_support_when_help_and_ldd_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bin_dir = tmp_path / "qe-bin"
    bin_dir.mkdir()
    pw = bin_dir / "pw.x"
    pw.write_text("#!/bin/sh\necho 'Program PWSCF v.7.5 GPU CUDA enabled'\n", encoding="utf-8")
    pw.chmod(0o755)
    monkeypatch.setenv("QE_BIN", str(bin_dir))
    monkeypatch.delenv("QE_ROOT", raising=False)
    monkeypatch.delenv("ESPRESSO_ROOT", raising=False)
    original_run = subprocess.run

    def fake_run(command, **kwargs):
        if command[0] == "ldd":
            class LddResult:
                returncode = 0
                stdout = "\tlibcudart.so.12 => /usr/local/cuda/lib64/libcudart.so.12\n"
                stderr = ""

            return LddResult()
        return original_run(command, **kwargs)

    monkeypatch.setattr(
        "dse_v2.experiments.qe_ic_real_opportunity.environment_probe.subprocess.run",
        fake_run,
    )

    discovered = discover_qe_executables(config={}, programs=["pw.x"], repo_root=tmp_path)
    pw_record = discovered["programs"]["pw.x"]

    assert pw_record["help_gpu_support"] == "detected"
    assert pw_record["dynamic_gpu_library_support"] == "detected"
    assert pw_record["dynamic_gpu_libraries"] == ["libcudart.so.12"]
    assert pw_record["gpu_support"] == "detected"


def test_environment_probe_records_gpu_qe_build_probe(tmp_path: Path):
    probe_path = tmp_path / "artifacts" / "qe_gpu_build" / "qe_gpu_build_probe.json"
    probe_path.parent.mkdir(parents=True)
    _write_json(
        probe_path,
        {
            "status": "gpu_qe_build_failed",
            "failure_reason": "built GPU-linked QE segfaulted during -h probe",
            "programs": [
                {
                    "program": "pw.x",
                    "path": "/tmp/qe-gpu/bin/pw.x",
                    "ldd": {"gpu_lib_lines": ["libcudart.so.13 => /opt/cuda/libcudart.so.13"]},
                    "help": {"returncode": -11},
                }
            ],
        },
    )

    env = probe_qe_ic_real_opportunity_environment(
        config={},
        repo_root=tmp_path,
        include_qe_discovery=True,
    )

    build_probe = env["tools"]["qe_gpu_build_probe"]
    assert build_probe["status"] == "gpu_qe_build_failed"
    assert build_probe["failure_reason"] == "built GPU-linked QE segfaulted during -h probe"
    assert build_probe["program_count"] == 1
    assert build_probe["path"] == str(probe_path)


def test_execute_real_prefers_gpu_qe_build_failed_when_build_probe_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_probe(*_args, **_kwargs):
        return {
            "environment_status": "partially_ready",
            "blockers": [],
            "gpu": {"gpu_present": True, "gpu_model": "controlled-gpu"},
            "tools": {
                "qe": {"pw.x": "/bin/true", "ph.x": None, "epw.x": None},
                "qe_discovery": {
                    "discovery_status": "available",
                    "programs": {
                        "pw.x": {
                            "path": "/bin/true",
                            "runs": True,
                            "version": "controlled",
                            "gpu_support": "not_detected",
                            "help_gpu_support": "not_detected",
                            "dynamic_gpu_library_support": "not_detected",
                            "dynamic_gpu_libraries": [],
                        }
                    },
                },
                "qe_gpu_build_probe": {
                    "status": "gpu_qe_build_failed",
                    "failure_reason": "controlled GPU-linked QE segfault",
                },
                "profilers": {"nsys": "/bin/true", "ncu": None},
                "systemc": {"generic_sim": None, "systemc_runner": None},
                "eda": {"available_tools": {}, "missing_tools": ["vivado", "dc_shell", "vcs", "yosys"]},
            },
        }

    monkeypatch.setattr(
        "dse_v2.experiments.qe_ic_real_opportunity.opportunity_campaign.probe_qe_ic_real_opportunity_environment",
        fake_probe,
    )

    report = campaign.run_qe_ic_real_opportunity_campaign(
        CONFIG_PATH,
        out_dir=tmp_path,
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )

    assert report["final_answer"]["overall_answer"] == "gpu_qe_build_failed"
    assert "gpu_qe_build_failed" in report["gpu_baseline_summary"]["blocker_reasons"]
    assert "gpu_qe_build_failed" in report["final_answer"]["missing_evidence"]
    assert report["final_answer"]["best_speedup_vs_gpu"] is None


def test_qe_probe_hash_ignores_qe_start_timestamp():
    first = "Program PWSCF v.6.7MaX starts on  7Jun2026 at 20:43:55\nWaiting for input"
    second = "Program PWSCF v.6.7MaX starts on  7Jun2026 at 20:44:16\nWaiting for input"

    assert normalized_qe_probe_output_hash(first, returncode=1) == normalized_qe_probe_output_hash(second, returncode=1)


def test_qe_probe_hash_ignores_single_digit_second_timestamp():
    first = "Program PWSCF v.6.7MaX starts on  8Jun2026 at  0:20: 2\nWaiting for input"
    second = "Program PWSCF v.6.7MaX starts on  8Jun2026 at  0:20: 9\nWaiting for input"

    assert normalized_qe_probe_output_hash(first, returncode=1) == normalized_qe_probe_output_hash(second, returncode=1)


def test_qe_discovery_report_omits_volatile_raw_probe_hash(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(
        CONFIG_PATH,
        out_dir=tmp_path,
        execute_real=True,
    )

    discovery = report["environment_summary"]["tools"]["qe_discovery"]["programs"]
    assert all("probe_command_output_hash" in row for row in discovery.values())
    assert all("probe_command_raw_output_hash" not in row for row in discovery.values())


def test_eda_probe_records_available_tools_but_does_not_imply_speedup(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(CONFIG_PATH, out_dir=tmp_path)

    assert "eda" in report["environment_summary"]["tools"]
    assert report["environment_summary"]["tools"]["eda"]["speedup_claim_implication"] == "none"
    assert report["final_answer"]["best_speedup_vs_gpu"] is None


def test_remote_eda_probe_discovers_ssh_aliases_without_claiming_speedup():
    aliases = parse_ssh_config_hosts(
        """
        Host login-node
          HostName login.example
        Host eda-vivado dc-farm
          User eda
        Host *
          ForwardAgent no
        """
    )

    assert aliases == ["eda-vivado", "dc-farm"]


def test_remote_eda_probe_attempts_discovered_aliases(monkeypatch: pytest.MonkeyPatch):
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)

        class Result:
            returncode = 0
            stdout = "vivado\n"
            stderr = ""

        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    result = probe_remote_eda_aliases(["eda-vivado"], timeout_seconds=1)

    assert calls
    assert calls[0][0] == "ssh"
    assert "eda-vivado" in calls[0]
    assert result["remote_probe_status"] == "probed"
    assert result["aliases"][0]["available_tools"] == ["vivado"]
    assert result["speedup_claim_implication"] == "none"


def test_remote_eda_probe_keeps_partial_tools_when_optional_tool_missing(monkeypatch: pytest.MonkeyPatch):
    def fake_run(_command, **_kwargs):
        class Result:
            returncode = 1
            stdout = "\n".join(
                [
                    "/home/Xilinx/Vivado/2019.1/bin/vivado",
                    "/home/synopsys/syn/O-2018.06-SP1/bin/dc_shell",
                    "/home/synopsys/vcs-mx/O-2018.09-1/bin/vcs",
                    "",
                ]
            )
            stderr = "setlocale: LC_ALL: cannot change locale (C.UTF-8)\n"

        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    result = probe_remote_eda_aliases(["ic-eda"], timeout_seconds=1)

    row = result["aliases"][0]
    assert row["probe_status"] == "available"
    assert row["available_tools"] == ["vivado", "dc_shell", "vcs"]


def test_remote_eda_tools_are_merged_into_environment_availability():
    merged = merge_local_and_remote_eda_tools(
        local_tools={"vivado": None, "dc_shell": None, "vcs": None, "yosys": None},
        remote_probe={
            "remote_probe_status": "probed",
            "aliases": [
                {
                    "alias": "ic-eda",
                    "probe_status": "available",
                    "available_tool_paths": {
                        "vivado": "/home/Xilinx/Vivado/2019.1/bin/vivado",
                        "dc_shell": "/home/synopsys/syn/O-2018.06-SP1/bin/dc_shell",
                        "vcs": "/home/synopsys/vcs-mx/O-2018.09-1/bin/vcs",
                    },
                    "available_tools": ["vivado", "dc_shell", "vcs"],
                }
            ],
            "speedup_claim_implication": "none",
        },
    )

    assert merged["available_tools"] == {
        "vivado": "ssh://ic-eda/home/Xilinx/Vivado/2019.1/bin/vivado",
        "dc_shell": "ssh://ic-eda/home/synopsys/syn/O-2018.06-SP1/bin/dc_shell",
        "vcs": "ssh://ic-eda/home/synopsys/vcs-mx/O-2018.09-1/bin/vcs",
    }
    assert merged["missing_tools"] == ["yosys"]
    assert merged["remote_probe_status"] == "probed"


def test_remote_eda_probe_tolerates_lc_all_warning(monkeypatch: pytest.MonkeyPatch):
    def fake_run(_command, **_kwargs):
        class Result:
            returncode = 0
            stdout = "/home/Xilinx/Vivado/2019.1/bin/vivado\n"
            stderr = "setlocale: LC_ALL: cannot change locale (C.UTF-8)\n"

        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    result = probe_remote_eda_aliases(["ic-eda"], timeout_seconds=1)

    assert result["aliases"][0]["probe_status"] == "available"
    assert result["aliases"][0]["available_tools"] == ["vivado"]


def test_default_environment_probe_attempts_remote_aliases_without_exposing_names(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "dse_v2.experiments.qe_ic_real_opportunity.environment_probe._ssh_config_aliases",
        lambda: ["eda-vivado"],
    )

    def fake_run(command, **_kwargs):
        calls.append(command)

        class Result:
            returncode = 0
            stdout = "/home/Xilinx/Vivado/2019.1/bin/vivado\n" if command and command[0] == "ssh" else ""
            stderr = ""

        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    env = probe_qe_ic_real_opportunity_environment()

    eda = env["tools"]["eda"]
    assert any(call and call[0] == "ssh" and "eda-vivado" in call for call in calls)
    assert eda["remote_probe_status"] == "probed"
    assert eda["remote_available_tool_count"] == 1
    assert eda["remote_ssh_aliases_checked"] == 1
    assert eda["available_tools"] == {"vivado": "ssh://eda-vivado/home/Xilinx/Vivado/2019.1/bin/vivado"}


def test_candidate_selection_uses_only_layer4_candidates():
    config = _load_json(CONFIG_PATH)
    plan = _load_json(LAYER4_PLAN_PATH)

    selection = select_layer4_candidates_for_campaign(
        candidate_plan=plan,
        candidate_selection_config=config["candidate_selection"],
    )

    layer4_ids = {candidate["candidate_id"] for candidate in plan["candidates"]}
    selected_ids = {candidate["candidate_id"] for candidate in selection["selected_candidates"]}
    assert selected_ids
    assert selected_ids <= layer4_ids
    assert all(candidate["selection_source"] == "layer4_candidate_plan" for candidate in selection["selected_candidates"])


def test_candidate_selection_does_not_invent_candidate_ids():
    config = _load_json(CONFIG_PATH)
    plan = copy.deepcopy(_load_json(LAYER4_PLAN_PATH))
    plan["candidates"] = [
        candidate
        for candidate in plan["candidates"]
        if candidate["target_type"] in {"gpu_only", "fpga_only"}
    ]

    selection = select_layer4_candidates_for_campaign(
        candidate_plan=plan,
        candidate_selection_config=config["candidate_selection"],
    )

    assert selection["selection_status"] == "candidate_selection_blocked"
    assert "missing_target_candidate_kinds" in selection["blocker_reasons"]
    assert "synthetic" not in json.dumps(selection).lower()


def test_baseline_builder_computes_mean_std_ci_from_real_supplied_runs():
    candidate = _tracked_layer4_candidate()
    baseline = build_gpu_baseline_measurements(
        run_records=_measured_baseline_runs(candidate),
        platform={
            "gpu_name": "controlled-a100",
            "cpu_name": "controlled-host",
            "memory": "80GB",
            "qe_version": "7.5",
            "cuda_version": "12.4",
            "driver_version": "controlled",
            "precision": "fp64_mixed",
        },
    )

    record = baseline["artifact"]["baseline_records"][0]
    assert baseline["evidence_status"] == "measured"
    assert baseline["artifact"]["measurements_are_real"] is True
    assert record["runtime_seconds_mean"] == pytest.approx(100.0)
    assert record["runtime_seconds_std"] == pytest.approx(1.0)
    assert record["confidence_interval_95"]["low"] == pytest.approx(97.515862)
    assert record["confidence_interval_95"]["high"] == pytest.approx(102.484138)
    assert record["metric_availability"]["gpu_utilization_mean"] == "measured"


def test_baseline_builder_marks_missing_optional_metrics_unavailable():
    candidate = _tracked_layer4_candidate()
    runs = [
        {
            "workload_family_id": candidate["workload_family_id"],
            "case_id": "controlled_case",
            "program": "pw.x",
            "input_deck_hash": "sha256:" + "1" * 64,
            "precision": "fp64_mixed",
            "runtime_seconds": value,
            "profile_artifact_hash": "sha256:" + "2" * 64,
        }
        for value in [99.0, 100.0, 101.0]
    ]

    baseline = build_gpu_baseline_measurements(run_records=runs, platform={"gpu_name": "controlled"})

    record = baseline["artifact"]["baseline_records"][0]
    assert record["metric_availability"]["gpu_utilization_mean"] == "unavailable"
    assert record["metric_availability"]["host_device_transfer_seconds"] == "unavailable"
    assert record["gpu_utilization_mean"] is None
    assert record["gpu_memory_bandwidth_utilization_mean"] is None
    assert record["host_device_transfer_seconds"] is None
    assert record["communication_seconds"] is None
    assert baseline["validation"]["status"] == "passed"


def test_measured_baseline_cannot_be_emitted_from_template_only_inputs():
    baseline = build_gpu_baseline_measurements(run_records=[], platform={})

    assert baseline["evidence_status"] == "evidence_missing"
    assert baseline["artifact"] is None
    assert baseline["measurements_are_real"] is False


def test_run_if_available_baseline_runner_executes_ready_case_repeatedly(tmp_path: Path):
    deck = tmp_path / "case.in"
    deck.write_text("&control\n/\n")
    case = {
        "workload_family_id": "ground_state_band_structure",
        "case_id": "controlled_ready_case",
        "program": "pw.x",
        "input_deck_hash": "sha256:" + "1" * 64,
        "precision": "fp64_mixed",
        "run_command": f"{sys.executable} -c pass",
        "case_status": "ready",
    }
    environment = {
        "gpu": {
            "gpu_model": "controlled-gpu",
            "cuda_version": "12.4",
            "driver_version": "controlled",
        },
        "tools": {"qe": {"pw.x": sys.executable}},
    }

    result = run_gpu_baseline_commands_if_available(
        cases=[case],
        environment_summary=environment,
        repeat_count=3,
        timeout_seconds=10,
    )

    assert result["evidence_status"] == "measured"
    assert result["artifact"]["measurements_are_real"] is True
    assert len(result["artifact"]["baseline_records"][0]["runtime_seconds_runs"]) == 3


def test_run_if_available_baseline_runner_records_logs_without_fake_telemetry(tmp_path: Path):
    case = {
        "workload_family_id": "ground_state_band_structure",
        "case_id": "controlled_ready_case",
        "program": "pw.x",
        "input_deck_hash": "sha256:" + "1" * 64,
        "precision": "fp64_mixed",
        "run_command": f"{sys.executable} -c \"print('qe ok')\"",
        "case_status": "ready",
    }
    environment = {
        "gpu": {
            "gpu_model": "controlled-gpu",
            "cuda_version": "12.4",
            "driver_version": "controlled",
        },
        "tools": {"qe": {"pw.x": sys.executable}, "profilers": {}},
    }

    result = run_gpu_baseline_commands_if_available(
        cases=[case],
        environment_summary=environment,
        repeat_count=3,
        timeout_seconds=10,
        run_root=tmp_path / "runs",
    )

    record = result["artifact"]["baseline_records"][0]
    assert result["artifact"]["measurements_are_real"] is True
    assert record["gpu_utilization_mean"] is None
    assert record["metric_availability"]["gpu_utilization_mean"] == "unavailable"
    run_records = result["run_records"]
    assert len(run_records) == 3
    assert all(Path(row["stdout_log_path"]).exists() for row in run_records)
    assert all(Path(row["stderr_log_path"]).exists() for row in run_records)
    assert all(row["output_hash"].startswith("sha256:") for row in run_records)


def test_case_setup_creates_template_files_without_physical_data(tmp_path: Path):
    config = _load_json(CONFIG_PATH)
    report = campaign.run_qe_ic_real_opportunity_campaign(CONFIG_PATH, out_dir=tmp_path)

    for case in report["case_summary"]:
        template = Path(case["input_deck_path"])
        assert case["case_status"] == "input_deck_missing"
        assert template.exists()
        assert "placeholder" in template.read_text().lower()
    assert config["case_selection"]["allow_proxy_case_if_full_workload_unavailable"] is True


def test_case_setup_discovers_input_decks_from_search_paths(tmp_path: Path):
    deck_root = tmp_path / "qe_inputs"
    deck_root.mkdir()
    deck = deck_root / "ground_state_band_structure.in"
    deck.write_text("&control\n calculation='scf'\n/\n", encoding="utf-8")
    config = _load_json(CONFIG_PATH)
    config.pop("input_decks", None)
    config["input_deck_search_paths"] = [str(deck_root)]

    cases = prepare_qe_ic_cases(config, out_dir=tmp_path / "out")

    ground_state = next(case for case in cases if case["workload_family_id"] == "ground_state_band_structure")
    mobility = next(case for case in cases if case["workload_family_id"] == "electron_phonon_mobility")
    assert ground_state["case_status"] == "ready"
    assert ground_state["input_deck_path"] == str(deck)
    assert ground_state["input_deck_hash"].startswith("sha256:")
    assert ground_state["run_command"].endswith(f"-in {deck}")
    assert mobility["case_status"] == "input_deck_missing"


def test_candidate_evidence_requires_provenance():
    candidate = _tracked_layer4_candidate()
    record = _candidate_evidence_record(candidate)
    record.pop("tool_provenance")

    evidence = build_candidate_high_fidelity_evidence(
        candidate_records=[record],
        selected_candidates=[candidate],
    )

    assert evidence["evidence_status"] == "evidence_missing"
    assert evidence["artifact"] is None
    assert "high_fidelity_provenance_missing" in evidence["blocker_reasons"]


def test_l1_synthetic_data_cannot_be_used_as_high_fidelity_evidence():
    candidate = _tracked_layer4_candidate()
    record = _candidate_evidence_record(candidate)
    record["evidence_level"] = "l1_estimate_only"
    record["source_label_kind"] = "synthetic_feedback"

    evidence = build_candidate_high_fidelity_evidence(
        candidate_records=[record],
        selected_candidates=[candidate],
    )

    assert evidence["artifact"] is None
    assert "l1_or_synthetic_not_high_fidelity" in evidence["blocker_reasons"]


def test_candidate_evidence_missing_uses_campaign_blocker():
    candidate = _tracked_layer4_candidate()

    evidence = candidate_evidence_from_ingest_payload(None, selected_candidates=[candidate])

    assert evidence["evidence_status"] == "evidence_missing"
    assert evidence["artifact"] is None
    assert "blocked_by_missing_candidate_evidence" in evidence["blocker_reasons"]


def test_execute_real_reports_candidate_evidence_attempt_ladder(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(
        CONFIG_PATH,
        out_dir=tmp_path,
        execute_real=True,
    )

    attempts = report["candidate_evidence_attempts"]
    assert [row["attempt"] for row in attempts] == [
        "ingest_existing_candidate_evidence",
        "trace_replay",
        "systemc_timing",
        "eda_resource_timing",
    ]
    assert all(row["status"] in {"not_configured", "blocked"} for row in attempts)
    assert report["candidate_evidence_summary"]["attempt_count"] == len(attempts)


def test_execute_real_runs_configured_trace_replay_candidate_evidence(tmp_path: Path):
    candidate = _tracked_layer4_candidate()
    baseline_path = tmp_path / "baseline_runs.json"
    profile_path = tmp_path / "profile_logs.json"
    candidate_source = tmp_path / "candidate_source.json"
    candidate_output = tmp_path / "candidate_output.json"
    writer = tmp_path / "write_candidate_evidence.py"
    _write_json(
        baseline_path,
        {
            "platform": {
                "gpu_name": "controlled-a100",
                "cpu_name": "controlled-host",
                "memory": "80GB",
                "qe_version": "7.5",
                "cuda_version": "12.4",
                "driver_version": "controlled",
                "precision": "fp64_mixed",
            },
            "run_records": _measured_baseline_runs(candidate),
        },
    )
    _write_json(profile_path, {"profiles": [{"case_id": "controlled_case", "trace_hash": "sha256:" + "6" * 64}]})
    _write_json(candidate_source, {"candidate_results": [_candidate_evidence_record(candidate)]})
    writer.write_text(
        "import pathlib, shutil, sys\n"
        "shutil.copyfile(sys.argv[1], sys.argv[2])\n"
        "pathlib.Path(sys.argv[2]).touch()\n",
        encoding="utf-8",
    )
    config = _load_json(CONFIG_PATH)
    config["input_artifacts"]["gpu_baseline_runs"] = str(baseline_path)
    config["input_artifacts"]["profile_logs"] = str(profile_path)
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(tmp_path / "missing_candidate.json")
    config["candidate_evidence_execution"] = {
        "trace_replay": {
            "command": [sys.executable, str(writer), str(candidate_source), str(candidate_output)],
            "profile_artifact": str(profile_path),
            "output_json": str(candidate_output),
            "tool": "controlled_trace_replay",
            "version": "test",
        }
    }
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(
        config_path,
        out_dir=tmp_path / "out",
        execute_real=True,
    )

    trace_attempt = next(row for row in report["candidate_evidence_attempts"] if row["attempt"] == "trace_replay")
    assert trace_attempt["status"] == "executed"
    assert Path(trace_attempt["stdout_log_path"]).exists()
    assert trace_attempt["output_artifact_hash"].startswith("sha256:")
    assert report["candidate_evidence_summary"]["results_are_real"] is True
    assert report["opportunity_summary"]["claim_gate_invoked"] is True
    assert report["final_answer"]["overall_answer"] == "opportunity_found"


def test_execute_real_failed_candidate_evidence_command_remains_missing(tmp_path: Path):
    config = _load_json(CONFIG_PATH)
    config["candidate_evidence_execution"] = {
        "systemc_timing": {
            "command": [sys.executable, "-c", "import sys; sys.exit(7)"],
            "output_json": str(tmp_path / "missing_systemc_output.json"),
            "tool": "controlled_systemc",
            "version": "test",
        }
    }
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(
        config_path,
        out_dir=tmp_path / "out",
        execute_real=True,
    )

    systemc_attempt = next(row for row in report["candidate_evidence_attempts"] if row["attempt"] == "systemc_timing")
    assert systemc_attempt["status"] == "failed"
    assert systemc_attempt["returncode"] == 7
    assert report["candidate_evidence_summary"]["results_are_real"] is False
    assert report["opportunity_summary"]["claim_gate_invoked"] is False
    assert report["final_answer"]["overall_answer"] == "evidence_missing"


def test_candidate_evidence_can_ingest_external_csv(tmp_path: Path):
    candidate = _tracked_layer4_candidate()
    csv_path = tmp_path / "candidate.csv"
    csv_path.write_text(
        "\n".join(
            [
                "candidate_id,workload_family_id,motif_id,target_type,case_id,program,input_deck_hash,precision,evidence_level,evidence_status,architecture_id,architecture_family,gpu_role,fpga_role,host_role,dataflow_summary,memory_interface,synchronization_model,runtime_seconds_runs,workflow_runtime_seconds_mean,kernel_runtime_seconds_mean,transfer_overhead_seconds,workflow_overhead_seconds,resource_feasible,timing_feasible,lut_utilization,ff_utilization,bram_utilization,dsp_utilization,hbm_port_utilization,fmax_mhz,evidence_artifact_hash,tool,version,run_id,config_hash,output_artifact_hash",
                f"{candidate['candidate_id']},{candidate['workload_family_id']},{candidate['motif_id']},{candidate['target_type']},controlled_case,pw.x,sha256:{'1'*64},fp64_mixed,trace_replay,high_fidelity_estimate,controlled_arch,{candidate['candidate_parameters']['template_family']},none,fpga,host,workflow,pcie,barrier,79|80|81,80,60,4,3,true,true,0.5,0.5,0.4,0.4,0.3,280,sha256:{'3'*64},trace_tool,1,run,sha256:{'4'*64},sha256:{'5'*64}",
            ]
        )
        + "\n"
    )

    evidence = candidate_evidence_from_csv(csv_path, selected_candidates=[candidate])

    assert evidence["evidence_status"] == "measured_or_high_fidelity"
    assert evidence["artifact"]["candidate_results"][0]["runtime_seconds_runs"] == [79.0, 80.0, 81.0]


def test_campaign_runner_ingests_candidate_evidence_csv(tmp_path: Path):
    candidate = _tracked_layer4_candidate()
    baseline_path = tmp_path / "baseline_runs.json"
    csv_path = tmp_path / "candidate.csv"
    _write_json(
        baseline_path,
        {
            "platform": {
                "gpu_name": "controlled-a100",
                "cpu_name": "controlled-host",
                "memory": "80GB",
                "qe_version": "7.5",
                "cuda_version": "12.4",
                "driver_version": "controlled",
                "precision": "fp64_mixed",
            },
            "run_records": _measured_baseline_runs(candidate),
        },
    )
    csv_path.write_text(
        "\n".join(
            [
                "candidate_id,workload_family_id,motif_id,target_type,case_id,program,input_deck_hash,precision,evidence_level,evidence_status,architecture_id,architecture_family,gpu_role,fpga_role,host_role,dataflow_summary,memory_interface,synchronization_model,runtime_seconds_runs,workflow_runtime_seconds_mean,kernel_runtime_seconds_mean,transfer_overhead_seconds,workflow_overhead_seconds,resource_feasible,timing_feasible,lut_utilization,ff_utilization,bram_utilization,dsp_utilization,hbm_port_utilization,fmax_mhz,evidence_artifact_hash,tool,version,run_id,config_hash,output_artifact_hash",
                f"{candidate['candidate_id']},{candidate['workload_family_id']},{candidate['motif_id']},{candidate['target_type']},controlled_case,pw.x,sha256:{'1'*64},fp64_mixed,trace_replay,high_fidelity_estimate,controlled_arch,{candidate['candidate_parameters']['template_family']},none,fpga,host,workflow,pcie,barrier,79|80|81,80,60,4,3,true,true,0.5,0.5,0.4,0.4,0.3,280,sha256:{'3'*64},trace_tool,1,run,sha256:{'4'*64},sha256:{'5'*64}",
            ]
        )
        + "\n"
    )
    config = _load_json(CONFIG_PATH)
    config["input_artifacts"]["gpu_baseline_runs"] = str(baseline_path)
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(csv_path)
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(config_path, out_dir=tmp_path)

    assert report["candidate_evidence_summary"]["results_are_real"] is True
    assert report["opportunity_summary"]["claim_gate_invoked"] is True


def test_implementation_limited_when_actual_loses_but_upper_bound_suggests_opportunity():
    audit = audit_candidate_implementation_quality(
        candidate_selection=[_tracked_layer4_candidate()],
        opportunity_records=[
            {
                "candidate_id": _tracked_layer4_candidate()["candidate_id"],
                "claim_allowed": False,
                "speedup_vs_gpu_mean": 0.90,
                "verdict": "fpga_or_hybrid_inconclusive",
                "resource_summary": {"resource_feasible": True, "timing_feasible": True, "fmax_mhz": 180.0},
                "failure_reasons": ["no_speedup_vs_gpu"],
                "overhead_summary": {
                    "transfer_overhead_ratio": 0.05,
                    "workflow_overhead_ratio": 0.05,
                },
            }
        ],
        candidate_evidence_by_id={
            _tracked_layer4_candidate()["candidate_id"]: {
                "implementation_quality": {
                    "pipeline_utilization": 0.30,
                    "memory_bandwidth_utilization": 0.35,
                    "transfer_overlap": 0.20,
                    "calibrated": False,
                },
                "idealized_upper_bound_speedup_vs_gpu": 1.35,
            }
        },
    )

    assert audit[0]["implementation_quality_classification"] == "implementation_limited"
    assert "low pipeline utilization" in audit[0]["implementation_limited_reasons"]
    assert audit[0]["idealized_upper_bound"]["speedup_vs_gpu"] == pytest.approx(1.35)


def test_fundamental_no_opportunity_requires_quality_pass_and_upper_bound_fails():
    candidate = _tracked_layer4_candidate()
    audit = audit_candidate_implementation_quality(
        candidate_selection=[candidate],
        opportunity_records=[
            {
                "candidate_id": candidate["candidate_id"],
                "claim_allowed": False,
                "speedup_vs_gpu_mean": 0.85,
                "verdict": "gpu_dominant_no_fpga_opportunity",
                "claim_blockers": ["no_speedup_vs_gpu"],
                "failure_reasons": ["no_speedup_vs_gpu", "gpu_utilization_high"],
                "resource_summary": {"resource_feasible": True, "timing_feasible": True, "fmax_mhz": 300.0},
                "overhead_summary": {"transfer_overhead_ratio": 0.02, "workflow_overhead_ratio": 0.02},
            }
        ],
        candidate_evidence_by_id={
            candidate["candidate_id"]: {
                "implementation_quality": {
                    "pipeline_utilization": 0.82,
                    "memory_bandwidth_utilization": 0.75,
                    "transfer_overlap": 0.85,
                    "calibrated": True,
                    "mature_implementation": True,
                },
                "idealized_upper_bound_speedup_vs_gpu": 0.96,
            }
        },
    )

    assert audit[0]["implementation_quality_classification"] == "fundamental_no_opportunity"


def test_opportunity_found_only_when_existing_claim_gate_passes(tmp_path: Path):
    candidate = _tracked_layer4_candidate()
    baseline_path = tmp_path / "baseline_runs.json"
    candidate_path = tmp_path / "candidate_evidence.json"
    _write_json(
        baseline_path,
        {
            "platform": {
                "gpu_name": "controlled-a100",
                "cpu_name": "controlled-host",
                "memory": "80GB",
                "qe_version": "7.5",
                "cuda_version": "12.4",
                "driver_version": "controlled",
                "precision": "fp64_mixed",
            },
            "run_records": _measured_baseline_runs(candidate),
        },
    )
    _write_json(candidate_path, {"candidate_results": [_candidate_evidence_record(candidate)]})
    config = _load_json(CONFIG_PATH)
    config["input_artifacts"]["gpu_baseline_runs"] = str(baseline_path)
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(candidate_path)
    config_path = tmp_path / "campaign_config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(config_path, out_dir=tmp_path)

    assert report["opportunity_summary"]["claim_gate_invoked"] is True
    assert report["final_answer"]["overall_answer"] == "opportunity_found"
    assert report["final_answer"]["best_candidate_id"] == candidate["candidate_id"]
    assert report["final_answer"]["best_speedup_vs_gpu"] == pytest.approx(1.25)
    assert report["opportunity_summary"]["opportunity_records"][0]["claim_allowed"] is True
    preliminary = report["opportunity_summary"]["preliminary_classification"]
    assert preliminary["preliminary_label"] == "fpga_hybrid_stronger"
    assert preliminary["best_candidate_id"] == candidate["candidate_id"]
    assert preliminary["final_claim_allowed"] is False


def test_final_answer_says_evidence_missing_when_no_real_baseline_exists(tmp_path: Path):
    candidate = _tracked_layer4_candidate()
    candidate_path = tmp_path / "candidate_evidence.json"
    _write_json(candidate_path, {"candidate_results": [_candidate_evidence_record(candidate)]})
    config = _load_json(CONFIG_PATH)
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(candidate_path)
    config_path = tmp_path / "campaign_config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(config_path, out_dir=tmp_path)

    assert report["final_answer"]["overall_answer"] == "evidence_missing"
    assert "baseline" in report["final_answer"]["what_we_cannot_say"].lower()
    assert report["opportunity_summary"]["preliminary_classification"]["preliminary_label"] == "insufficient_evidence"


def test_proxy_real_run_reports_preliminary_insufficient_evidence(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(
        CONFIG_PATH,
        out_dir=tmp_path,
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )

    preliminary = report["opportunity_summary"]["preliminary_classification"]
    assert preliminary["preliminary_label"] == "insufficient_evidence"
    assert preliminary["advisor_labels_supported"] is False
    assert "real_or_high_fidelity_candidate_evidence_missing" in preliminary["blockers"]
    assert report["final_answer"]["preliminary_label"] == "insufficient_evidence"


def test_validator_rejects_stale_or_inconsistent_final_answer(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(CONFIG_PATH, out_dir=tmp_path)
    report["final_answer"]["overall_answer"] = "fundamental_no_opportunity"

    validation = campaign.validate_qe_ic_real_opportunity_campaign_report(report)

    assert validation["status"] == "failed"
    assert any("fundamental_no_opportunity" in error["message"] for error in validation["errors"])


def test_validator_rejects_non_layer4_selection_marker(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(CONFIG_PATH, out_dir=tmp_path)
    report["candidate_selection"][0]["selection_source"] = "invented_candidate"

    validation = campaign.validate_qe_ic_real_opportunity_campaign_report(report)

    assert validation["status"] == "failed"
    assert any("Layer-4" in error["message"] for error in validation["errors"])


def test_validator_rejects_hardware_proven_fields(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(CONFIG_PATH, out_dir=tmp_path)
    report["hardware_proven"] = True

    validation = campaign.validate_qe_ic_real_opportunity_campaign_report(report)

    assert validation["status"] == "failed"
    assert any("hardware_proven" in error["message"] for error in validation["errors"])


def test_writer_fail_closed_removes_stale_artifacts(tmp_path: Path):
    good = campaign.write_qe_ic_real_opportunity_campaign_artifacts(tmp_path, CONFIG_PATH)
    assert good["status"] == "passed"
    bad_config = _load_json(CONFIG_PATH)
    bad_config["schema_version"] = "wrong"
    bad_path = tmp_path / "bad_config.json"
    _write_json(bad_path, bad_config)

    failed = campaign.write_qe_ic_real_opportunity_campaign_artifacts(tmp_path, bad_path)

    assert failed["status"] == "failed"
    assert (tmp_path / "qe_ic_real_opportunity_campaign_validation.json").exists()
    assert not (tmp_path / "qe_ic_real_opportunity_campaign_report.json").exists()
    assert not (tmp_path / "qe_ic_real_opportunity_campaign_manifest.json").exists()
    assert not (tmp_path / "qe_ic_real_opportunity_campaign_readme.md").exists()


def test_checked_in_campaign_artifacts_match_builder_output(tmp_path: Path):
    campaign.write_qe_ic_real_opportunity_campaign_artifacts(tmp_path, CONFIG_PATH)

    for artifact in [
        "qe_ic_real_opportunity_campaign_report.json",
        "qe_ic_real_opportunity_campaign_validation.json",
        "qe_ic_real_opportunity_campaign_manifest.json",
        "qe_ic_real_opportunity_campaign_readme.md",
    ]:
        assert (CHECKED_IN_RESULTS_DIR / artifact).read_text() == (tmp_path / artifact).read_text()


def test_cli_is_thin_wrapper_and_missing_environment_returns_zero(tmp_path: Path):
    tree = ast.parse(CLI_PATH.read_text())
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert function_names == {"parse_args", "main"}
    assert "speedup_vs_gpu" not in CLI_PATH.read_text()
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "--config",
            str(CONFIG_PATH),
            "--out",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "passed"


def test_execute_real_without_qe_or_input_deck_returns_blocked_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.delenv("QE_BIN", raising=False)
    monkeypatch.delenv("QE_ROOT", raising=False)
    monkeypatch.delenv("ESPRESSO_ROOT", raising=False)
    config = _load_json(CONFIG_PATH)
    config.pop("input_decks", None)
    config["input_deck_search_paths"] = [str(tmp_path / "missing-inputs")]
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(
        config_path,
        out_dir=tmp_path / "out",
        execute_real=True,
    )

    assert report["execution_mode"] == "execute_real"
    assert report["campaign_status"] in {"blocked_by_missing_qe", "blocked_by_missing_input_deck"}
    assert report["final_answer"]["overall_answer"] == "evidence_missing"
    assert "blocked_by_missing_qe" in report["environment_summary"]["blockers"]
    assert "blocked_by_missing_input_deck" in report["final_answer"]["missing_evidence"]
    assert campaign.validate_qe_ic_real_opportunity_campaign_report(report)["status"] == "passed"


def test_nonblocking_generates_benchmark_input_when_deck_missing(tmp_path: Path):
    config = _load_json(CONFIG_PATH)
    config.pop("input_decks", None)
    config["input_deck_search_paths"] = [str(tmp_path / "missing-inputs")]
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(
        config_path,
        out_dir=tmp_path / "out",
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )

    generated_cases = [case for case in report["case_summary"] if case.get("case_origin") == "generated_benchmark"]
    assert generated_cases
    assert all(case["scientific_claim_scope"] == "performance_benchmark_only" for case in generated_cases)
    assert all(Path(case["input_deck_path"]).exists() for case in generated_cases)
    assert report["campaign_status"] != "blocked_by_missing_input_deck"
    assert report["final_answer"]["overall_answer"] in {
        "proxy_only_inconclusive",
        "implementation_limited",
        "gpu_or_eda_failure",
        "gpu_qe_binary_cpu_only",
        "gpu_qe_build_failed",
    }
    assert campaign.validate_qe_ic_real_opportunity_campaign_report(report)["status"] == "passed"


def test_generated_silicon_benchmark_searches_local_pseudopotential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    pseudo_dir = tmp_path / "pseudo"
    pseudo_dir.mkdir()
    pseudo = pseudo_dir / "Si.pbe-n-kjpaw_psl.1.0.0.UPF"
    pseudo.write_text("controlled pseudo\n", encoding="utf-8")
    monkeypatch.setenv("QE_PSEUDO_DIR", str(pseudo_dir))
    cases = [
        {
            "workload_family_id": "ground_state_band_structure",
            "case_id": "missing_silicon_case",
            "program": "pw.x",
            "case_status": "input_deck_missing",
        }
    ]

    generated = generate_qe_ic_benchmark_cases(cases, out_dir=tmp_path / "out")

    case = generated[0]
    deck_text = Path(case["input_deck_path"]).read_text(encoding="utf-8")
    assert case["pseudo_status"] == "pseudo_available"
    assert case["pseudo_file_path"] == str(pseudo)
    assert case["pseudo_hash"].startswith("sha256:")
    assert f"pseudo_dir = '{pseudo_dir}'" in deck_text


def test_nonblocking_report_includes_cpu_baseline_attempt_summary(tmp_path: Path):
    config = _load_json(CONFIG_PATH)
    config.pop("input_decks", None)
    config["input_deck_search_paths"] = [str(tmp_path / "missing-inputs")]
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(
        config_path,
        out_dir=tmp_path / "out",
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )

    assert "cpu_baseline_summary" in report
    assert report["cpu_baseline_summary"]["target_type"] == "cpu_only"
    assert report["cpu_baseline_summary"]["measurements_are_real"] is False
    assert report["gpu_baseline_summary"]["target_type"] == "gpu_only"
    assert report["gpu_baseline_summary"]["measurements_are_real"] is False
    assert campaign.validate_qe_ic_real_opportunity_campaign_report(report)["status"] == "passed"


def test_cpu_baseline_does_not_make_gpu_baseline_real_when_qe_is_cpu_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bin_dir = tmp_path / "qe-bin"
    bin_dir.mkdir()
    pw = bin_dir / "pw.x"
    pw.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-h\" ]; then echo 'Program PWSCF v.7.5'; exit 0; fi\n"
        "echo \"cpu-only QE run $@\"\n",
        encoding="utf-8",
    )
    pw.chmod(0o755)
    deck = tmp_path / "ground_state_band_structure.in"
    deck.write_text("&control\n calculation='scf'\n/\n", encoding="utf-8")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setenv("QE_BIN", str(bin_dir))
    monkeypatch.delenv("QE_ROOT", raising=False)
    monkeypatch.delenv("ESPRESSO_ROOT", raising=False)
    cases = [
        {
            "workload_family_id": "ground_state_band_structure",
            "case_id": "controlled_cpu_only_case",
            "program": "pw.x",
            "input_deck_path": str(deck),
            "input_deck_hash": "sha256:" + "1" * 64,
            "precision": "fp64_mixed",
            "case_status": "ready",
            "run_command": f"{pw} -in {deck}",
        }
    ]
    environment = probe_qe_ic_real_opportunity_environment(
        {"qe_bin": str(bin_dir)},
        repo_root=tmp_path,
        include_qe_discovery=True,
    )

    assert hasattr(baseline_module, "run_cpu_baseline_commands_if_available")
    cpu = baseline_module.run_cpu_baseline_commands_if_available(
        cases=cases,
        environment_summary=environment,
        repeat_count=3,
        run_root=tmp_path / "cpu-runs",
    )
    gpu = run_gpu_baseline_commands_if_available(
        cases=cases,
        environment_summary=environment,
        repeat_count=3,
        run_root=tmp_path / "gpu-runs",
    )

    assert cpu["measurements_are_real"] is True
    assert gpu["measurements_are_real"] is False
    assert "gpu_qe_binary_cpu_only" in gpu["blocker_reasons"]


def test_generated_pseudo_missing_classifies_gpu_qe_unavailable(tmp_path: Path):
    missing_deck = tmp_path / "generated_missing_pseudo.in"
    missing_deck.write_text(
        "\n".join(
            [
                "&control",
                "  calculation = 'scf'",
                "  pseudo_dir = './pseudo'",
                "/",
                "ATOMIC_SPECIES",
                "  Si 28.0855 Si.pbe-n-kjpaw_psl.1.0.0.UPF",
                "",
            ]
        ),
        encoding="utf-8",
    )
    cases = [
        {
            "workload_family_id": "ground_state_band_structure",
            "case_id": "generated_missing_pseudo",
            "program": "pw.x",
            "input_deck_path": str(missing_deck),
            "input_deck_hash": "sha256:" + "1" * 64,
            "precision": "fp64_mixed",
            "case_status": "ready",
            "case_origin": "generated_benchmark",
            "scientific_claim_scope": "performance_benchmark_only",
            "pseudo_status": "pseudo_missing",
            "run_command": f"{tmp_path / 'missing-pw.x'} -in {missing_deck}",
        }
    ]
    environment = {
        "gpu": {"gpu_present": True, "gpu_model": "controlled-gpu"},
        "tools": {
            "qe": {"pw.x": str(tmp_path / "missing-pw.x")},
            "qe_discovery": {
                "programs": {
                    "pw.x": {
                        "path": str(tmp_path / "missing-pw.x"),
                        "gpu_support": "detected",
                    }
                }
            },
        },
    }

    gpu = run_gpu_baseline_commands_if_available(
        cases=cases,
        environment_summary=environment,
        repeat_count=3,
        run_root=tmp_path / "gpu-runs",
    )

    assert gpu["measurements_are_real"] is False
    assert "gpu_qe_execution_unavailable_due_to_pseudopotential" in gpu["blocker_reasons"]


def test_generated_pseudo_missing_is_retained_when_qe_binary_is_cpu_only(tmp_path: Path):
    deck = tmp_path / "generated_missing_pseudo.in"
    deck.write_text("&control\n pseudo_dir='./pseudo'\n/\n", encoding="utf-8")
    cases = [
        {
            "workload_family_id": "ground_state_band_structure",
            "case_id": "generated_missing_pseudo",
            "program": "pw.x",
            "input_deck_path": str(deck),
            "input_deck_hash": "sha256:" + "1" * 64,
            "precision": "fp64_mixed",
            "case_status": "ready",
            "case_origin": "generated_benchmark",
            "scientific_claim_scope": "performance_benchmark_only",
            "pseudo_status": "pseudo_missing",
            "run_command": f"{tmp_path / 'pw.x'} -in {deck}",
        }
    ]
    environment = {
        "gpu": {"gpu_present": False},
        "tools": {
            "qe": {"pw.x": str(tmp_path / "pw.x")},
            "qe_discovery": {
                "programs": {
                    "pw.x": {
                        "path": str(tmp_path / "pw.x"),
                        "gpu_support": "not_detected",
                    }
                }
            },
        },
    }

    gpu = run_gpu_baseline_commands_if_available(
        cases=cases,
        environment_summary=environment,
        repeat_count=3,
        run_root=tmp_path / "gpu-runs",
    )

    assert gpu["measurements_are_real"] is False
    assert "gpu_qe_binary_cpu_only" in gpu["blocker_reasons"]
    assert "gpu_qe_execution_unavailable_due_to_pseudopotential" in gpu["blocker_reasons"]


def test_execute_real_cpu_only_qe_uses_precise_final_answer(tmp_path: Path):
    config = _load_json(CONFIG_PATH)
    config["qe_gpu_build_probe"] = str(tmp_path / "missing_qe_gpu_build_probe.json")
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(
        config_path,
        out_dir=tmp_path,
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )

    assert report["final_answer"]["overall_answer"] == "gpu_qe_binary_cpu_only"
    assert "gpu_qe_binary_cpu_only" in report["final_answer"]["missing_evidence"]
    assert report["final_answer"]["best_speedup_vs_gpu"] is None
    assert report["opportunity_summary"]["claim_gate_invoked"] is False


def test_execute_real_generates_eda_stub_evidence_without_gpu_qe(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(
        CONFIG_PATH,
        out_dir=tmp_path,
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )

    artifact_path = Path(report["real_run_artifacts"]["candidate_eda_stub_evidence_real_run"])
    artifact = _load_json(artifact_path)

    assert artifact["schema_version"] == "dse.qe_ic.eda_stub_evidence.v1"
    assert artifact["claim_strength"] == "none"
    assert artifact["results_are_real"] is False
    assert artifact["resource_timing_scope"] == "syntax_only"
    assert artifact["resource_metrics_available"] is False
    assert artifact["timing_metrics_available"] is False
    assert artifact["selected_candidate_count"] == 3
    assert len(artifact["candidate_stub_results"]) == 3
    assert all(row["resource_timing_scope"] == "syntax_only" for row in artifact["candidate_stub_results"])
    assert {row["candidate_id"] for row in artifact["candidate_stub_results"]} == {
        row["candidate_id"] for row in report["candidate_selection"]
    }
    assert any(
        attempt["attempt"] == "generated_eda_stub_resource_timing" and attempt["status"] in {"executed", "failed"}
        for attempt in report["candidate_evidence_attempts"]
    )
    assert "blocked_by_missing_candidate_design" not in report["environment_summary"]["blockers"]


def test_generated_eda_stub_evidence_falls_back_when_no_tool_available(tmp_path: Path):
    candidates = [
        _tracked_layer4_candidate("fpga_only"),
        _tracked_layer4_candidate("gpu_fpga_hybrid"),
    ]

    evidence = build_generated_eda_stub_evidence(
        selected_candidates=candidates,
        environment={"tools": {"eda": {"available_tools": {}}}},
        out_dir=tmp_path,
    )
    artifact = evidence["artifact"]

    assert evidence["results_are_real"] is False
    assert evidence["tool_execution_is_real"] is False
    assert evidence["blocker_reasons"] == []
    assert artifact["claim_strength"] == "none"
    assert len(artifact["candidate_stub_results"]) == 2
    assert artifact["tool_attempts"][0]["status"] == "blocked"
    assert Path(artifact["combined_rtl_stub_path"]).exists()
    assert all(Path(row["rtl_stub_path"]).exists() for row in artifact["candidate_stub_results"])


def test_generated_eda_stub_remote_vcs_sets_portable_locale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    commands: list[tuple[list[str], str | None]] = []

    def fake_run(command, **kwargs):
        commands.append((list(command), kwargs.get("input")))

        class Result:
            returncode = 0
            stdout = "ok\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "dse_v2.experiments.qe_ic_real_opportunity.eda_stub_evidence.subprocess.run",
        fake_run,
    )

    evidence = build_generated_eda_stub_evidence(
        selected_candidates=[_tracked_layer4_candidate("fpga_only")],
        environment={
            "tools": {
                "eda": {
                    "available_tools": {
                        "vcs": "ssh://ic-eda/home/synopsys/vcs-mx/O-2018.09-1/bin/vcs",
                    }
                }
            }
        },
        out_dir=tmp_path,
    )

    assert evidence["tool_execution_is_real"] is True
    assert len(commands) == 2
    assert commands[0][0][:2] == ["ssh", "ic-eda"]
    assert commands[1][0][:2] == ["ssh", "ic-eda"]
    assert "export LC_ALL=C LANG=C" in commands[0][0][2]
    assert "export LC_ALL=C LANG=C" in commands[1][0][2]
    assert "rm -rf /tmp/dse_qe_ic_eda_stub_" in commands[0][0][2]
    assert "/home/synopsys/vcs-mx/O-2018.09-1/bin/vcs" in commands[1][0][2]
    assert "-full64" in commands[1][0][2]


def test_nonblocking_generates_proxy_candidate_evidence_without_strong_claim(tmp_path: Path):
    candidate = _tracked_layer4_candidate()
    baseline_path = tmp_path / "baseline_runs.json"
    _write_json(
        baseline_path,
        {
            "platform": {
                "gpu_name": "controlled-a100",
                "cpu_name": "controlled-host",
                "memory": "80GB",
                "qe_version": "7.5",
                "cuda_version": "12.4",
                "driver_version": "controlled",
                "precision": "fp64_mixed",
            },
            "run_records": _measured_baseline_runs(candidate),
        },
    )
    config = _load_json(CONFIG_PATH)
    config["input_artifacts"]["gpu_baseline_runs"] = str(baseline_path)
    config["input_artifacts"]["candidate_high_fidelity_results"] = str(tmp_path / "missing_candidate.json")
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(
        config_path,
        out_dir=tmp_path / "out",
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )

    assert report["campaign_status"] == "completed_proxy_only"
    assert report["final_answer"]["overall_answer"] == "proxy_only_inconclusive"
    assert report["candidate_evidence_summary"]["results_are_real"] is False
    assert report["candidate_evidence_summary"]["proxy_evidence_generated"] is True
    assert all(row["claim_allowed"] is False for row in report["opportunity_summary"]["opportunity_records"])
    assert report["final_answer"]["best_candidate_id"] is None
    assert campaign.validate_qe_ic_real_opportunity_campaign_report(report)["status"] == "passed"


def test_validator_rejects_nonblocking_missing_input_terminal_status(tmp_path: Path):
    report = campaign.run_qe_ic_real_opportunity_campaign(
        CONFIG_PATH,
        out_dir=tmp_path,
        execute_real=True,
        allow_generated_inputs=True,
        nonblocking=True,
    )
    report["campaign_status"] = "blocked_by_missing_input_deck"

    validation = campaign.validate_qe_ic_real_opportunity_campaign_report(report)

    assert validation["status"] == "failed"
    assert any("nonblocking" in error["message"] for error in validation["errors"])


def test_execute_real_uses_discovered_qe_path_for_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bin_dir = tmp_path / "qe-bin"
    bin_dir.mkdir()
    pw = bin_dir / "pw.x"
    pw.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-h\" ]; then echo 'Program PWSCF v.7.5 CUDA'; exit 0; fi\n"
        "echo \"fake QE run $@\"\n",
        encoding="utf-8",
    )
    pw.chmod(0o755)
    deck = tmp_path / "ground_state_band_structure.in"
    deck.write_text("&control\n calculation='scf'\n/\n", encoding="utf-8")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setenv("QE_BIN", str(bin_dir))
    monkeypatch.delenv("QE_ROOT", raising=False)
    monkeypatch.delenv("ESPRESSO_ROOT", raising=False)
    monkeypatch.setattr(
        "dse_v2.experiments.qe_ic_real_opportunity.environment_probe._probe_dynamic_gpu_libraries",
        lambda _path: {
            "dynamic_gpu_library_support": "detected",
            "dynamic_gpu_libraries": ["libcudart.so.12"],
            "ldd_command": ["ldd", str(pw)],
            "ldd_returncode": 0,
            "ldd_output_hash": "sha256:" + "6" * 64,
        },
    )
    config = _load_json(CONFIG_PATH)
    config["qe_gpu_build_probe"] = str(tmp_path / "missing_qe_gpu_build_probe.json")
    config["case_selection"]["required_workload_families"] = ["ground_state_band_structure"]
    config["input_decks"] = {"ground_state_band_structure": str(deck)}
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    report = campaign.run_qe_ic_real_opportunity_campaign(
        config_path,
        out_dir=tmp_path / "out",
        execute_real=True,
    )

    case = report["case_summary"][0]
    assert case["run_command"].startswith(str(pw))
    assert report["gpu_baseline_summary"]["measurements_are_real"] is True
    assert report["gpu_baseline_summary"]["baseline_record_count"] == 1
    assert report["final_answer"]["overall_answer"] == "evidence_missing"
    assert "blocked_by_missing_candidate_evidence" in report["final_answer"]["missing_evidence"]


def test_execute_real_baseline_artifact_keeps_per_run_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bin_dir = tmp_path / "qe-bin"
    bin_dir.mkdir()
    pw = bin_dir / "pw.x"
    pw.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-h\" ]; then echo 'Program PWSCF v.7.5 CUDA'; exit 0; fi\n"
        "echo \"fake QE run $@\"\n",
        encoding="utf-8",
    )
    pw.chmod(0o755)
    deck = tmp_path / "ground_state_band_structure.in"
    deck.write_text("&control\n calculation='scf'\n/\n", encoding="utf-8")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setenv("QE_BIN", str(bin_dir))
    monkeypatch.setattr(
        "dse_v2.experiments.qe_ic_real_opportunity.environment_probe._probe_dynamic_gpu_libraries",
        lambda _path: {
            "dynamic_gpu_library_support": "detected",
            "dynamic_gpu_libraries": ["libcudart.so.12"],
            "ldd_command": ["ldd", str(pw)],
            "ldd_returncode": 0,
            "ldd_output_hash": "sha256:" + "6" * 64,
        },
    )
    config = _load_json(CONFIG_PATH)
    config["qe_gpu_build_probe"] = str(tmp_path / "missing_qe_gpu_build_probe.json")
    config["case_selection"]["required_workload_families"] = ["ground_state_band_structure"]
    config["input_decks"] = {"ground_state_band_structure": str(deck)}
    config_path = tmp_path / "config.json"
    _write_json(config_path, config)

    result = campaign.write_qe_ic_real_opportunity_campaign_artifacts(
        tmp_path / "out",
        config_path,
        execute_real=True,
    )

    assert result["status"] == "passed"
    baseline_real_run = _load_json(tmp_path / "out" / "qe_ic_gpu_baseline_measurements_real_run.json")
    assert baseline_real_run["schema_version"] == "dse.qe_ic.gpu_baseline_measurements.v1"
    assert baseline_real_run["measurements_are_real"] is True
    assert len(baseline_real_run["run_records"]) == 3
    assert all(row["command"].startswith(str(pw)) for row in baseline_real_run["run_records"])
    assert all(Path(row["stdout_log_path"]).exists() for row in baseline_real_run["run_records"])
    assert all(row["output_hash"].startswith("sha256:") for row in baseline_real_run["run_records"])


def test_cli_accepts_execute_real_as_thin_wrapper(tmp_path: Path):
    tree = ast.parse(CLI_PATH.read_text())
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert function_names == {"parse_args", "main"}
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "--config",
            str(CONFIG_PATH),
            "--out",
            str(tmp_path),
            "--execute-real",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "passed"
    assert (tmp_path / "qe_ic_real_opportunity_campaign_report.json").exists()


def test_cli_accepts_nonblocking_and_allow_generated_inputs(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "--config",
            str(CONFIG_PATH),
            "--out",
            str(tmp_path),
            "--execute-real",
            "--allow-generated-inputs",
            "--nonblocking",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "passed"
    report = _load_json(tmp_path / "qe_ic_real_opportunity_campaign_report.json")
    assert report["execution_mode"] == "execute_real"
    assert report["nonblocking_mode"] is True


def test_readme_explains_real_campaign_interpretation():
    readme = (CHECKED_IN_RESULTS_DIR / "qe_ic_real_opportunity_campaign_readme.md").read_text().lower()

    for required in [
        "run_if_available",
        "ingest_only",
        "real gpu baseline",
        "candidate high-fidelity evidence",
        "implementation_limited",
        "fundamental_no_opportunity",
        "claim gate",
        "forbidden conclusions",
        "replace templates",
    ]:
        assert required in readme
