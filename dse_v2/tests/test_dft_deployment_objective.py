#!/usr/bin/env python3
"""DFT deployment-objective producer tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dse_v2.reference_workloads.dft_deployment_objective import (
    DFT_DEPLOYMENT_OBJECTIVE_PRODUCER_STATUS_SCHEMA,
    DFT_DEPLOYMENT_OBJECTIVE_VALIDATION_SCHEMA,
    build_conservative_dft_deployment_objective,
    validate_dft_deployment_objective,
    write_conservative_dft_deployment_objective,
)
from dse_v2.reference_workloads.dft_deployment_selector import DFT_DEPLOYMENT_OBJECTIVE_SCHEMA


def test_conservative_deployment_objective_preserves_cross_target_tie() -> None:
    objective = build_conservative_dft_deployment_objective()
    validation = validate_dft_deployment_objective(objective)

    assert objective["schema_version"] == DFT_DEPLOYMENT_OBJECTIVE_SCHEMA
    assert objective["objective_id"] == "evidence-first-neutral-cross-target-v1"
    assert objective["deployment_target"] == "cross_target"
    assert objective["target_score_direction"] == "min"
    assert objective["target_scores"] == {"fpga": 1.0, "asic": 1.0}
    assert objective["tie_policy"] == "preserve_physical_ties"
    assert objective["allow_non_physical_tie_breakers"] is False
    assert objective["trusted_final_claim"] is False
    assert objective["deliverable_complete"] is False
    assert validation["schema_version"] == DFT_DEPLOYMENT_OBJECTIVE_VALIDATION_SCHEMA
    assert validation["valid"] is True


def test_write_conservative_deployment_objective_artifacts(tmp_path: Path) -> None:
    status = write_conservative_dft_deployment_objective(tmp_path)

    objective_path = tmp_path / "dft_deployment_objective.json"
    validation_path = tmp_path / "dft_deployment_objective_validation.json"
    status_path = tmp_path / "dft_deployment_objective_status.json"
    objective = json.loads(objective_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))

    assert status["status"] == "passed"
    assert status_payload["schema_version"] == DFT_DEPLOYMENT_OBJECTIVE_PRODUCER_STATUS_SCHEMA
    assert status_payload["objective_present"] is True
    assert status_payload["selection_upgrade_allowed"] is False
    assert objective["target_scores"]["fpga"] == objective["target_scores"]["asic"]
    assert validation["valid"] is True


def test_deployment_objective_cli_writes_expected_files(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_deployment_objective.py",
            "--out",
            str(tmp_path),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert (tmp_path / "dft_deployment_objective.json").is_file()
