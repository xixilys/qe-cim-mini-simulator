#!/usr/bin/env python3
"""Tests for fail-closed Wave36 next source-flow batch planner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _packet_index(path: Path, candidate_ids: list[str]) -> Path:
    packets = []
    for index, candidate_id in enumerate(candidate_ids):
        packets.append(
            {
                "packet_id": f"packet-{index}",
                "shard_id": f"shard-{index}",
                "status": "blocked_until_candidate_specific_bundle_and_real_tool_execution",
                "candidate_ids": [candidate_id],
                "packet_json": {"path": f"packets/shard-{index}.json", "exists": True},
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            }
        )
        _write_json(
            path.parent / "packets" / f"shard-{index}.json",
            {
                "schema_version": "dse.dft.hardware_closure_packet.v1",
                "candidate_ids": [candidate_id],
                "units": [
                    {
                        "candidate_id": candidate_id,
                        "kernel_id": "fft_ifft_ffft",
                        "hardware_completion_eligible": False,
                        "deliverable_complete": False,
                    }
                ],
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
            },
        )
    return _write_json(
        path,
        {
            "schema_version": "dse.dft.hardware_closure_packets.v1",
            "status": "blocked_packetized_fail_closed",
            "packet_count": len(packets),
            "candidate_count": len(candidate_ids),
            "packets": packets,
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def _ready_all8_run(run_root: Path, candidate_id: str) -> Path:
    run_dir = run_root / f"wave36_real_source_flow_run_{candidate_id}_all8_fixture"
    (run_dir / "source_flows").mkdir(parents=True, exist_ok=True)
    return _write_json(
        run_dir / "dft_hardware_closure_real_source_flow_run.json",
        {
            "schema_version": "dse.dft.hardware_closure_real_source_flow_run.v1",
            "status": "source_flows_ready_pending_step5",
            "source_flow_ready_count": 8,
            "blocked_unit_count": 0,
            "units": [{"candidate_id": candidate_id}],
            "flows": [],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_planner(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/plan_dft_hardware_closure_next_source_flow_batch.py",
            *args,
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_next_source_flow_batch_excludes_ready_and_running_candidates(
    tmp_path: Path,
) -> None:
    packet_index = _packet_index(
        tmp_path / "packets-out" / "dft_hardware_closure_packet_index.json",
        ["cand-ready", "cand-running", "cand-new", "cand-extra"],
    )
    run_root = tmp_path / "runs" / "dse"
    _ready_all8_run(run_root, "cand-ready")
    (run_root / "wave36_real_source_flow_run_cand-running_all8_live").mkdir(
        parents=True
    )
    out = tmp_path / "plan" / "next_source_flow_batch.json"

    result = _run_planner(
        "--closure-packet-index",
        str(packet_index),
        "--run-root",
        str(run_root),
        "--max-new-candidates",
        "1",
        "--out",
        str(out),
        "--quiet",
    )

    assert result.returncode == 0, result.stderr
    payload = _load(out)
    assert payload["status"] == "planned_next_source_flow_batch"
    assert payload["candidate_order"] == [
        "cand-ready",
        "cand-running",
        "cand-new",
        "cand-extra",
    ]
    assert payload["ready_candidate_ids"] == ["cand-ready"]
    assert payload["running_candidate_ids"] == ["cand-running"]
    assert payload["recommended_candidate_ids"] == ["cand-new"]
    assert payload["blocked_or_pending_candidate_ids"] == [
        "cand-running",
        "cand-extra",
    ]
    assert payload["deliverable_complete"] is False
    assert payload["hardware_completion_eligible"] is False
    assert "does not execute EDA tools" in payload["claim_boundary"]


def test_next_source_flow_batch_generates_runner_argv_and_shell_only(
    tmp_path: Path,
) -> None:
    packet_index = _packet_index(
        tmp_path / "packets-out" / "dft_hardware_closure_packet_index.json",
        ["cand-a", "cand-b"],
    )
    run_root = tmp_path / "runs" / "dse"
    out = tmp_path / "plan" / "next_source_flow_batch.json"

    result = _run_planner(
        "--closure-packet-index",
        str(packet_index),
        "--run-root",
        str(run_root),
        "--max-new-candidates",
        "2",
        "--ssh-target",
        "ic-eda-test",
        "--timeout-s",
        "123",
        "--run-tag",
        "20260520T000000Z",
        "--out",
        str(out),
        "--emit-shell",
        "--quiet",
    )

    assert result.returncode == 0, result.stderr
    payload = _load(out)
    assert payload["recommended_candidate_ids"] == ["cand-a", "cand-b"]
    assert len(payload["commands"]) == 2
    first_command = payload["commands"][0]
    assert first_command[:2] == [
        sys.executable,
        "dse_v2/scripts/dse/run_dft_hardware_closure_real_source_flows.py",
    ]
    assert first_command[first_command.index("--candidate-id") + 1] == "cand-a"
    assert first_command[first_command.index("--jobs") + 1] == "1"
    assert first_command[first_command.index("--ssh-target") + 1] == "ic-eda-test"
    assert first_command[first_command.index("--timeout-s") + 1] == "123"
    assert first_command[first_command.index("--out") + 1].endswith(
        "wave36_real_source_flow_run_cand-a_all8_20260520T000000Z"
    )
    assert "--skip-remote" not in first_command

    shell_path = out.parent / "next_source_flow_batch.sh"
    shell_text = shell_path.read_text(encoding="utf-8")
    assert payload["shell_script"] == str(shell_path)
    assert "nohup" in shell_text
    assert "run_dft_hardware_closure_real_source_flows.py" in shell_text
    assert "cand-a" in shell_text
    assert "&" in shell_text


def test_next_source_flow_batch_fails_closed_for_empty_packet_index(
    tmp_path: Path,
) -> None:
    packet_index = _write_json(
        tmp_path / "empty" / "dft_hardware_closure_packet_index.json",
        {
            "schema_version": "dse.dft.hardware_closure_packets.v1",
            "packets": [],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    out = tmp_path / "plan" / "next_source_flow_batch.json"

    result = _run_planner(
        "--closure-packet-index",
        str(packet_index),
        "--out",
        str(out),
        "--quiet",
    )

    assert result.returncode == 1
    payload = _load(out)
    assert payload["status"] == "blocked_invalid_or_empty_closure_packet_index"
    assert payload["recommended_candidate_ids"] == []
    assert payload["commands"] == []
    assert payload["error_count"] == 1
    assert "closure_packet_index_candidate_order_empty" in payload["errors"]
    assert payload["deliverable_complete"] is False
    assert payload["hardware_completion_eligible"] is False


def test_next_source_flow_batch_invalid_packet_index_emits_no_commands(
    tmp_path: Path,
) -> None:
    packet_index = _write_json(
        tmp_path / "invalid" / "dft_hardware_closure_packet_index.json",
        {
            "schema_version": "dse.dft.hardware_closure_packets.v1",
            "candidate_ids": ["cand-would-run"],
            "packets": "not-a-list",
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    out = tmp_path / "plan" / "next_source_flow_batch.json"

    result = _run_planner(
        "--closure-packet-index",
        str(packet_index),
        "--out",
        str(out),
        "--emit-shell",
        "--quiet",
    )

    assert result.returncode == 1
    payload = _load(out)
    assert payload["status"] == "blocked_invalid_or_empty_closure_packet_index"
    assert payload["candidate_order"] == ["cand-would-run"]
    assert payload["recommended_candidate_ids"] == []
    assert payload["commands"] == []
    assert payload["blocked_or_pending_candidate_ids"] == ["cand-would-run"]
    assert "closure_packet_index_packets_not_list" in payload["errors"]
    shell_text = (out.parent / "next_source_flow_batch.sh").read_text(
        encoding="utf-8"
    )
    assert "No recommended candidates to launch." in shell_text
    assert "nohup" not in shell_text


def test_next_source_flow_batch_running_detection_uses_exact_candidate(
    tmp_path: Path,
) -> None:
    packet_index = _packet_index(
        tmp_path / "packets-out" / "dft_hardware_closure_packet_index.json",
        ["cand", "cand-extra"],
    )
    run_root = tmp_path / "runs" / "dse"
    (run_root / "wave36_real_source_flow_run_cand-extra_all8_live").mkdir(
        parents=True
    )
    out = tmp_path / "plan" / "next_source_flow_batch.json"

    result = _run_planner(
        "--closure-packet-index",
        str(packet_index),
        "--run-root",
        str(run_root),
        "--max-new-candidates",
        "1",
        "--out",
        str(out),
        "--quiet",
    )

    assert result.returncode == 0, result.stderr
    payload = _load(out)
    assert payload["running_candidate_ids"] == ["cand-extra"]
    assert payload["recommended_candidate_ids"] == ["cand"]


def test_next_source_flow_batch_malformed_manifest_fails_closed_without_crash(
    tmp_path: Path,
) -> None:
    packet_index = _packet_index(
        tmp_path / "packets-out" / "dft_hardware_closure_packet_index.json",
        ["cand-bad", "cand-next"],
    )
    run_root = tmp_path / "runs" / "dse"
    run_dir = run_root / "wave36_real_source_flow_run_cand-bad_all8_live"
    (run_dir / "source_flows").mkdir(parents=True)
    _write_json(
        run_dir / "dft_hardware_closure_real_source_flow_run.json",
        {
            "schema_version": "dse.dft.hardware_closure_real_source_flow_run.v1",
            "status": "source_flows_ready_pending_step5",
            "source_flow_ready_count": "not-int",
            "blocked_unit_count": 0,
            "units": [{"candidate_id": "cand-bad"}],
            "hardware_completion_eligible": False,
            "deliverable_complete": False,
        },
    )
    out = tmp_path / "plan" / "next_source_flow_batch.json"

    result = _run_planner(
        "--closure-packet-index",
        str(packet_index),
        "--run-root",
        str(run_root),
        "--max-new-candidates",
        "1",
        "--out",
        str(out),
        "--quiet",
    )

    assert result.returncode == 0, result.stderr
    payload = _load(out)
    assert payload["ready_candidate_ids"] == []
    assert payload["running_candidate_ids"] == ["cand-bad"]
    assert payload["recommended_candidate_ids"] == ["cand-next"]
