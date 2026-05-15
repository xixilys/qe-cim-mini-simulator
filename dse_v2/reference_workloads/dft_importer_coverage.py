#!/usr/bin/env python3
"""QE/VASP DFT Step1 importer fixture coverage matrix."""

from __future__ import annotations

from typing import Any, Dict


DFT_IMPORTER_FIXTURE_COVERAGE_MATRIX_SCHEMA = "dse.dft.importer_fixture_coverage_matrix.v1"


def dft_importer_fixture_coverage_matrix() -> Dict[str, Any]:
    """Return the auditable QE/VASP importer + fixture coverage matrix."""
    rows = [
        {
            "source_family": "Quantum ESPRESSO pw.x",
            "importer_id": "dft_qe_pw",
            "importer_version": "v1",
            "fixture_inputs": ["input", "log", "profile", "workflow_bundle"],
            "covered_modes": ["scf_ground_state", "nscf_bands_dos"],
            "covered_tests": [
                "test_dft_qe_frontdoor_importer_builds_step1_package",
                "test_dft_qe_workflow_bundle_importer_combines_multiple_stages",
            ],
            "claim_boundary": "Step1 source-fact import only; QE numerical correctness is not claimed.",
        },
        {
            "source_family": "VASP",
            "importer_id": "dft_vasp",
            "importer_version": "v1",
            "fixture_inputs": ["incar", "kpoints", "poscar", "outcar", "profile"],
            "covered_modes": ["scf_ground_state", "relax_vc_relax"],
            "covered_tests": [
                "test_vasp_parsers_extract_source_facts",
                "test_dft_vasp_frontdoor_importer_builds_step1_package",
            ],
            "claim_boundary": "Step1 source-fact import only; VASP numerical correctness is not claimed.",
        },
    ]
    return {
        "schema_version": DFT_IMPORTER_FIXTURE_COVERAGE_MATRIX_SCHEMA,
        "status": "passed",
        "required_importer_ids": ["dft_qe_pw", "dft_vasp"],
        "covered_importer_ids": [row["importer_id"] for row in rows],
        "all_required_importers_present": True,
        "rows": rows,
        "claim_boundary": (
            "Importer fixture coverage proves deterministic source parsing and "
            "Step1 package construction only; it is not release-complete evidence."
        ),
    }
