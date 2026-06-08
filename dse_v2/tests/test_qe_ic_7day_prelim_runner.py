#!/usr/bin/env python3
"""Tests for the QE-IC seven-day preliminary campaign runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dse" / "run_qe_ic_7day_prelim.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_qe_ic_7day_prelim", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_ic_cases_include_stable_four_atom_al_interconnect_proxy(tmp_path, monkeypatch):
    runner = _load_runner()

    def fake_pseudo_map(_elements):
        return {
            "Si": {
                "element": "Si",
                "path": "/tmp/pseudo/Si.pz-vbc.UPF",
                "hash": "sha256:" + "1" * 64,
                "status": "pseudo_available",
            },
            "O": {
                "element": "O",
                "path": "/tmp/pseudo/O.pz-rrkjus.UPF",
                "hash": "sha256:" + "2" * 64,
                "status": "pseudo_available",
            },
            "Al": {
                "element": "Al",
                "path": "/tmp/pseudo/Al.pz-vbc.UPF",
                "hash": "sha256:" + "3" * 64,
                "status": "pseudo_available",
            },
        }

    monkeypatch.setattr(runner, "_pseudo_map", fake_pseudo_map)

    cases = runner.generate_ic_qe_cases(tmp_path, {})

    assert len(cases) == 3
    assert all(case["case_origin"] == "generated_benchmark" for case in cases)
    assert all(case["scientific_claim_scope"] == "performance_benchmark_only" for case in cases)
    al_case = next(case for case in cases if case["workload_family_id"] == "ic_metal_interconnect_scf")
    deck = Path(al_case["input_deck_path"]).read_text()
    assert al_case["case_id"] == "ic_al_interconnect_4atom_scf_v0"
    assert "nat = 4" in deck
    assert deck.count("  Al ") >= 5  # species row plus four atomic positions
    assert "  2 2 2 0 0 0" in deck
    assert "generated ic/eda-relevant full-scf benchmark" in al_case["template_note"].lower()
