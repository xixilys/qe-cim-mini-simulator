#!/usr/bin/env python3
"""QE-IC case setup for real opportunity campaigns."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROGRAM_BY_FAMILY = {
    "ground_state_band_structure": "pw.x",
    "electron_phonon_mobility": "epw.x",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _case_id(workload_family_id: str) -> str:
    if workload_family_id == "ground_state_band_structure":
        return "ground_state_band_structure_initial_real_case"
    if workload_family_id == "electron_phonon_mobility":
        return "electron_phonon_mobility_initial_real_case"
    return f"{workload_family_id}_initial_real_case"


def prepare_qe_ic_cases(config: Mapping[str, Any], *, out_dir: Path | None = None) -> list[dict[str, Any]]:
    """Prepare case descriptors or templates without inventing physical inputs."""

    case_selection = config.get("case_selection") if isinstance(config.get("case_selection"), Mapping) else {}
    families = case_selection.get("required_workload_families")
    if not isinstance(families, list):
        families = ["ground_state_band_structure", "electron_phonon_mobility"]
    input_decks = config.get("input_decks") if isinstance(config.get("input_decks"), Mapping) else {}
    base_output = out_dir or Path("runs/qe_ic_real_opportunity_campaign")
    cases: list[dict[str, Any]] = []
    for family_id in families:
        program = PROGRAM_BY_FAMILY.get(str(family_id), "pw.x")
        deck_value = input_decks.get(str(family_id))
        deck_path = Path(str(deck_value)) if isinstance(deck_value, str) and deck_value else None
        deck_exists = deck_path is not None and deck_path.exists()
        case_status = "ready" if deck_exists else "input_deck_missing"
        template_path = base_output / "case_templates" / f"{family_id}.in"
        if not deck_exists:
            template_path.parent.mkdir(parents=True, exist_ok=True)
            if not template_path.exists():
                template_path.write_text(
                    "\n".join(
                        [
                            f"# Placeholder QE input deck template for {family_id}.",
                            "# This file is intentionally not physical input data.",
                            "# Replace with a validated QE input deck before running measurements.",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
        cases.append(
            {
                "workload_family_id": family_id,
                "case_id": _case_id(str(family_id)),
                "program": program,
                "input_deck_path": str(deck_path) if deck_path is not None else str(template_path),
                "input_deck_hash": _sha256(deck_path) if deck_exists and deck_path is not None else None,
                "precision": "fp64_mixed",
                "run_command": f"{program} -in {deck_path}" if deck_exists else None,
                "profile_command": f"nsys profile {program} -in {deck_path}" if deck_exists else None,
                "output_directory": str(base_output / str(family_id)),
                "case_status": case_status,
                "evidence_status": "ready_for_run" if deck_exists else "evidence_missing",
                "template_created": not deck_exists,
                "template_note": "Template descriptor only; no physical QE input data is invented.",
            }
        )
    return cases
