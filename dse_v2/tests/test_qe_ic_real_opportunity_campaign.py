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
from dse_v2.experiments.qe_ic_real_opportunity.candidate_evidence import (
    build_candidate_high_fidelity_evidence,
    candidate_evidence_from_csv,
)
from dse_v2.experiments.qe_ic_real_opportunity.candidate_selection import (
    select_layer4_candidates_for_campaign,
)
from dse_v2.experiments.qe_ic_real_opportunity.environment_probe import (
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
            stdout = "vivado\n" if command and command[0] == "ssh" else ""
            stderr = ""

        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    env = probe_qe_ic_real_opportunity_environment()

    eda = env["tools"]["eda"]
    assert any(call and call[0] == "ssh" and "eda-vivado" in call for call in calls)
    assert eda["remote_probe_status"] == "checked_redacted"
    assert eda["remote_available_tool_count"] == "redacted"
    assert eda["remote_ssh_aliases_checked"] == "redacted"
    assert "eda-vivado" not in json.dumps(env)


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


def test_case_setup_creates_template_files_without_physical_data(tmp_path: Path):
    config = _load_json(CONFIG_PATH)
    report = campaign.run_qe_ic_real_opportunity_campaign(CONFIG_PATH, out_dir=tmp_path)

    for case in report["case_summary"]:
        template = Path(case["input_deck_path"])
        assert case["case_status"] == "input_deck_missing"
        assert template.exists()
        assert "placeholder" in template.read_text().lower()
    assert config["case_selection"]["allow_proxy_case_if_full_workload_unavailable"] is True


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
