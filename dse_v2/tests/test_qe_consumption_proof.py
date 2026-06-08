#!/usr/bin/env python3
"""Tests for fail-closed QE post-bridge consumption proof merging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _domain_fft_artifacts(tmp_path: Path) -> dict[str, Path | str]:
    output_data = tmp_path / "accelerated_fft_output.bin"
    output_data.write_bytes(b"domain-correct-qe-fft-output-buffer")
    output_hash = hashlib.sha256(output_data.read_bytes()).hexdigest()
    output_json = tmp_path / "accelerated_output.json"
    _write_json(
        output_json,
        {
            "schema_version": "dse.qe_offload_runtime_bridge.v1",
            "status": "domain_correct_fft_payload_materialized",
            "candidate_id": "candidate-a",
            "workload_case_id": "case-a",
            "target_kernel": "fft",
            "domain_correct_fft_payload_available": True,
            "domain_correct_fft_recomputed": True,
            "proxy_runtime_only": False,
            "proxy_runtime_smoke_only": False,
            "qe_callsite_gated_proxy_only": False,
            "output_buffer_sha256": output_hash,
            "output_buffer_path": str(output_data),
            "software_payload_after_l4_transport": True,
            "not_fpga_or_asic_evidence": True,
        },
    )
    kernel_evidence = tmp_path / "kernel_evidence.json"
    _write_json(
        kernel_evidence,
        [
            {
                "major_kernel_id": "fft_ifft_ffft",
                "kernel_id": "fft_ifft_ffft",
                "target_kernel": "fft",
                "kernel_scope": "full_fft",
                "full_kernel_recomputed": True,
                "domain_correct_fft_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": False,
                "accelerated_result_materialized_for_qe": True,
                "accelerated_output_data_path": str(output_data),
                "absolute_error": 0.0,
                "relative_error": 0.0,
                "source": "qe_offload_runtime_numpy_fft_payload_after_l4_bridge",
                "software_payload_after_l4_transport": True,
                "not_fpga_or_asic_evidence": True,
                "timing_only": False,
            }
        ],
    )
    provenance = tmp_path / "offload_provenance.json"
    _write_json(
        provenance,
        {
            "schema_version": "dse.qe_offload_runtime_bridge_provenance.v1",
            "producer": "dse_v2/scripts/dse/run_qe_offload_runtime_bridge.py",
            "accelerated_runtime": "qe_offload_runtime",
            "offload_target": "repo_native_offload_runtime_proxy_bridge",
            "target_kernel": "fft",
            "qe_mainflow_integrated": True,
            "accelerated_results_consumed_by_qe": False,
            "full_kernel_recomputed": True,
            "domain_correct_fft_recomputed": True,
            "proxy_runtime_smoke_only": False,
            "proxy_runtime_only": False,
            "qe_callsite_gated_proxy_only": False,
            "baseline_copy": False,
            "fixture": False,
            "timing_only": False,
            "software_payload_after_l4_transport": True,
            "not_fpga_or_asic_evidence": True,
            "l4_execution_proof": {"passed": True, "transport_harness": "repo_native_offload_runtime_proxy_bridge"},
        },
    )
    proof = tmp_path / "qe_consumption_proof.json"
    _write_json(
        proof,
        {
            "schema_version": "dse.qe_offload_consumption_proof.v1",
            "passed": True,
            "candidate_id": "candidate-a",
            "workload_case_id": "case-a",
            "target_kernel": "fft",
            "major_kernel_id": "fft_ifft_ffft",
            "full_kernel_recomputed": True,
            "qe_mainflow_integrated": True,
            "accelerated_results_consumed_by_qe": True,
            "software_fallback_on_critical_path": False,
            "qe_software_kernel_execution_skipped": True,
            "qe_kernel_work_replaced_on_critical_path": True,
            "accelerated_result_materialized_in_qe_memory": True,
            "accelerated_output_written_to_qe_buffer": True,
            "qe_consumed_accelerator_output_buffer": True,
            "consumed_output_buffer_sha256": output_hash,
            "duration_s": 2.5e-6,
            "absolute_error": 0.0,
            "relative_error": 0.0,
        },
    )
    return {
        "output_data": output_data,
        "output_json": output_json,
        "output_hash": output_hash,
        "kernel_evidence": kernel_evidence,
        "provenance": provenance,
        "proof": proof,
    }


def test_qe_consumption_proof_merge_upgrades_domain_fft_payload_to_consumed_replacement(tmp_path: Path):
    from dse_v2.reference_workloads.qe_consumption_proof import merge_qe_consumption_proof_artifacts

    paths = _domain_fft_artifacts(tmp_path)
    runtime_events = tmp_path / "full_scf_runtime_events.jsonl"

    result = merge_qe_consumption_proof_artifacts(
        consumption_proof_path=paths["proof"],
        kernel_evidence_path=paths["kernel_evidence"],
        offload_provenance_path=paths["provenance"],
        accelerated_output_json_path=paths["output_json"],
        accelerated_output_data_path=paths["output_data"],
        runtime_events_path=runtime_events,
        candidate_id="candidate-a",
        workload_case_id="case-a",
        target_kernel="fft",
    )

    assert result["status"] == "passed"
    assert result["merged_major_kernel_id"] == "fft_ifft_ffft"
    kernel_rows = json.loads(Path(paths["kernel_evidence"]).read_text(encoding="utf-8"))
    trusted_row = next(row for row in kernel_rows if row["kernel_id"] == "fft_ifft_ffft")
    assert trusted_row["accelerated_results_consumed_by_qe"] is True
    assert trusted_row["accelerated_output_written_to_qe_buffer"] is True
    assert trusted_row["qe_consumed_accelerator_output_buffer"] is True
    assert trusted_row["consumed_output_buffer_sha256"] == paths["output_hash"]
    assert trusted_row["proxy_runtime_only"] is False
    provenance = json.loads(Path(paths["provenance"]).read_text(encoding="utf-8"))
    assert provenance["accelerated_results_consumed_by_qe"] is True
    assert provenance["qe_consumed_accelerator_output_buffer"] is True
    event = json.loads(runtime_events.read_text(encoding="utf-8").strip())
    assert event["category"] == "accelerated_kernel"
    assert event["kernel_id"] == "fft_ifft_ffft"
    assert event["measurement_source"] == "qe_offload_runtime_trace"
    assert event["duration_s"] == 2.5e-6
    assert "proxy_runtime_only" not in event


def test_qe_consumption_proof_merge_fail_closes_on_output_hash_mismatch(tmp_path: Path):
    from dse_v2.reference_workloads.qe_consumption_proof import merge_qe_consumption_proof_artifacts

    paths = _domain_fft_artifacts(tmp_path)
    proof_payload = json.loads(Path(paths["proof"]).read_text(encoding="utf-8"))
    proof_payload["consumed_output_buffer_sha256"] = "0" * 64
    _write_json(Path(paths["proof"]), proof_payload)

    result = merge_qe_consumption_proof_artifacts(
        consumption_proof_path=paths["proof"],
        kernel_evidence_path=paths["kernel_evidence"],
        offload_provenance_path=paths["provenance"],
        accelerated_output_json_path=paths["output_json"],
        accelerated_output_data_path=paths["output_data"],
        runtime_events_path=tmp_path / "full_scf_runtime_events.jsonl",
        candidate_id="candidate-a",
        workload_case_id="case-a",
        target_kernel="fft",
    )

    assert result["status"] == "blocked"
    assert "consumed_output_buffer_sha256_mismatch" in result["blockers"]
    kernel_rows = json.loads(Path(paths["kernel_evidence"]).read_text(encoding="utf-8"))
    assert kernel_rows[0]["accelerated_results_consumed_by_qe"] is False


def test_full_l4_matrix_requirements_include_consumption_proof_merge_contract(tmp_path: Path):
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_complete_dse_full_l4_matrix.py"
    spec = importlib.util.spec_from_file_location("run_complete_dse_full_l4_matrix_req_contract", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    requirements = module._build_accelerated_evidence_requirements(
        out_dir=tmp_path / "out",
        candidate_ids=["candidate-a"],
        workload_case_ids=["case-a"],
    )
    row = requirements["rows"][0]

    assert row["required_outputs"]["consumption_proof_json"].endswith("qe_consumption_proof.json")
    assert row["required_outputs"]["full_scf_runtime_events_jsonl"].endswith("full_scf_runtime_events.jsonl")
    merge_command = row["consumption_proof_merge_command_template"]
    joined = " ".join(str(part) for part in merge_command)
    assert "dse_v2/scripts/dse/merge_qe_consumption_proof.py" in joined
    assert "--consumption-proof" in merge_command
    assert str(row["required_outputs"]["consumption_proof_json"]) in merge_command
    assert "--runtime-events" in merge_command
    assert str(row["required_outputs"]["full_scf_runtime_events_jsonl"]) in merge_command
    assert row["target_kernel_evidence_requirements"]["requires_qe_post_bridge_consumption_proof"] is True


def test_accelerated_numeric_producer_merges_runtime_consumption_proof_before_building_evidence(tmp_path: Path, monkeypatch):
    import importlib.util
    import sys

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_accelerated_numeric_producer.py"
    spec = importlib.util.spec_from_file_location("run_qe_accelerated_numeric_producer_consumption", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    row_dir = tmp_path / "row"
    row_dir.mkdir()
    baseline = tmp_path / "baseline_comparison.json"
    _write_json(
        baseline,
        {
            "baseline_sequence": [{"step_id": "stage_00", "command": ["pw.x", "-in", "case.in"], "input_path": "case.in"}],
            "performance_metrics": {"terminal_step_metrics": {"total_energy_ry": -1.0, "highest_occupied_ev": 1.0, "lowest_unoccupied_ev": 2.0}},
        },
    )
    (tmp_path / "case.in").write_text("&control\n/\n", encoding="utf-8")
    paths = _domain_fft_artifacts(row_dir)
    kernel_payload = json.loads(Path(paths["kernel_evidence"]).read_text(encoding="utf-8"))
    provenance_payload = json.loads(Path(paths["provenance"]).read_text(encoding="utf-8"))
    proof_payload = json.loads(Path(paths["proof"]).read_text(encoding="utf-8"))
    output_json_payload = json.loads(Path(paths["output_json"]).read_text(encoding="utf-8"))
    output_data_bytes = Path(paths["output_data"]).read_bytes()
    stdout = row_dir / "accelerated_qe.stdout.log"
    kernel = Path(paths["kernel_evidence"])
    provenance = Path(paths["provenance"])
    proof = Path(paths["proof"])
    runtime_events = row_dir / "full_scf_runtime_events.jsonl"
    evidence_out = row_dir / "qe_accelerated_numeric_evidence.json"
    row = {
        "candidate_id": "candidate-a",
        "workload_case_id": "case-a",
        "baseline_comparison": str(baseline),
        "required_outputs": {
            "accelerated_stdout": str(stdout),
            "kernel_evidence_json": str(kernel),
            "offload_provenance_json": str(provenance),
            "accelerated_output_json": str(paths["output_json"]),
            "accelerated_output_data": str(paths["output_data"]),
            "consumption_proof_json": str(proof),
            "full_scf_runtime_events_jsonl": str(runtime_events),
        },
        "target_kernel_evidence_requirements": {"target_kernel": "fft"},
        "evidence_output": str(evidence_out),
    }

    def fake_materialize_run_inputs(*, baseline_dir, run_dir, sequence):
        run_dir.mkdir(parents=True, exist_ok=True)
        return []

    writer_script = row_dir / "fake_accelerated_qe_runtime.py"
    writer_script.write_text(
        "import json, pathlib\n"
        f"pathlib.Path({str(kernel)!r}).write_text({(json.dumps(kernel_payload, indent=2, sort_keys=True) + chr(10))!r})\n"
        f"pathlib.Path({str(provenance)!r}).write_text({(json.dumps(provenance_payload, indent=2, sort_keys=True) + chr(10))!r})\n"
        f"pathlib.Path({str(proof)!r}).write_text({(json.dumps(proof_payload, indent=2, sort_keys=True) + chr(10))!r})\n"
        f"pathlib.Path({str(paths['output_json'])!r}).write_text({(json.dumps(output_json_payload, indent=2, sort_keys=True) + chr(10))!r})\n"
        f"pathlib.Path({str(paths['output_data'])!r}).write_bytes({output_data_bytes!r})\n"
        "print('!    total energy              =      -1.000000 Ry')\n"
        "print(' highest occupied, lowest unoccupied level (ev): 1.0 2.0')\n",
        encoding="utf-8",
    )

    def fake_normalize(step, *, accelerated_qe_bin_dir):
        return [sys.executable, str(writer_script)] , {
            "program": "pw.x",
            "resolved_executable": sys.executable,
            "resolution_provenance": "test",
        }

    monkeypatch.setattr(module, "_materialize_run_inputs", fake_materialize_run_inputs)
    monkeypatch.setattr(module, "_normalize_qe_command", fake_normalize)

    status = module._run_row(
        row,
        accelerated_qe_bin_dir=None,
        timeout=5,
        source_kind="qe_offload_runtime",
        enable_hpsi_component_sidecar=False,
        hpsi_sidecar_max_calls=1,
        hpsi_sidecar_command_template=None,
    )

    assert status["outputs"]["consumption_proof_json"] == str(proof)
    assert status["consumption_proof_merge"]["status"] == "passed"
    kernel_rows = json.loads(kernel.read_text(encoding="utf-8"))
    assert kernel_rows[0]["accelerated_results_consumed_by_qe"] is True
    assert runtime_events.exists()
    evidence = json.loads(evidence_out.read_text(encoding="utf-8"))
    assert evidence["offload_provenance"]["qe_consumed_accelerator_output_buffer"] is True
