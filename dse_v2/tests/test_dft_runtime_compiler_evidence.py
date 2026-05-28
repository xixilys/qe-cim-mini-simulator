"""Tests for repo-native runtime/compiler evidence event/proof emission."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dse_v2.scripts.dse.build_dft_runtime_compiler_evidence import build_runtime_compiler_evidence


def test_runtime_compiler_evidence_emits_runtime_events_and_execution_proof(tmp_path: Path) -> None:
    cc = shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        pytest.skip("C compiler unavailable for runtime compiler evidence test")

    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "candidate_universe_manifest.json").write_text(
        json.dumps(
            {
                "legal_candidate_ids": ["cand_runtime_a"],
                "candidates": [
                    {
                        "candidate_id": "cand_runtime_a",
                        "legal": True,
                        "architecture_parameters": {"fft_engine_count": 1},
                        "mapping_layout_parameters": {"layout": "streaming"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_runtime_compiler_evidence(
        tmp_path / "runtime_compiler",
        release_artifact_dir=release_dir,
        cc=cc,
    )

    assert payload["status"] == "passed"
    assert payload["execution_summary"]["passed_candidate_count"] == 1
    record = payload["candidate_records"][0]
    assert record["status"] == "passed"
    execution = record["execution"]
    assert execution["runtime_events"]["exists"] is True
    assert execution["runtime_execution_proof"]["exists"] is True

    events_path = Path(execution["runtime_events"]["path"])
    proof_path = Path(execution["runtime_execution_proof"]["path"])
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    proof = json.loads(proof_path.read_text(encoding="utf-8"))

    assert {event["category"] for event in events} == {"host_proxy_submit", "host_proxy_complete"}
    assert all(event["measurement_source"] == "qe_offload_runtime_trace" for event in events)
    assert all(event["candidate_id"] == "cand_runtime_a" for event in events)
    assert proof["passed"] is True
    assert proof["measurement_source"] == "qe_offload_runtime_trace"
    assert proof["transport_harness"] == "host_proxy_repo_native_runtime"
    assert proof["metrics"]["command_count"] == 1
    assert proof["metrics"]["completion_count"] == 1
