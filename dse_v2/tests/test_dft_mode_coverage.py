#!/usr/bin/env python3
"""First-stage DFT common-mode coverage contract tests."""

from __future__ import annotations

import json
import subprocess
import sys

from dse_v2.reference_workloads.dft_modes import (
    FIRST_STAGE_DFT_MODE_IDS,
    DftWorkflowSpec,
    assert_first_stage_modes_covered,
    build_first_stage_dft_mode_coverage_report,
    first_stage_dft_configs,
    first_stage_dft_mode_templates,
    workflow_spec_for_mode,
)


def _all_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_keys(item)


def test_all_six_first_stage_dft_modes_have_configs_templates_and_workflows():
    templates = first_stage_dft_mode_templates()
    configs = first_stage_dft_configs()
    report = build_first_stage_dft_mode_coverage_report()

    assert tuple(templates) == FIRST_STAGE_DFT_MODE_IDS
    assert tuple(configs) == FIRST_STAGE_DFT_MODE_IDS
    assert report["status"] == "passed"
    assert report["covered_mode_ids"] == list(FIRST_STAGE_DFT_MODE_IDS)
    assert report["missing_mode_ids"] == []
    assert report["incomplete_mode_ids"] == []
    assert report["claim_boundary"] == "workflow-template coverage only; not release-complete evidence"
    assert_first_stage_modes_covered()

    for mode_id in FIRST_STAGE_DFT_MODE_IDS:
        template = templates[mode_id]
        config = configs[mode_id]
        workflow = workflow_spec_for_mode(mode_id)
        assert config.mode_id == mode_id
        assert config.claim_boundary == "workflow_template"
        assert template.phase_ids
        assert workflow.stages
        assert workflow.coverage_level == "first_stage_common_mode_template"
        assert workflow.workflow_id == f"{mode_id}_workflow_template"


def test_mode_workflow_specs_round_trip_and_remain_non_decision_artifacts():
    forbidden_decision_fields = {
        "selected_mapping",
        "selected_placement",
        "selected_schedule",
        "selected_runtime_policy",
        "descriptor_protocol_selection",
        "simulator_verdict",
        "accelerator_config",
        "promotion_decision",
        "l2_evidence",
        "l3_evidence",
        "l4_evidence",
    }

    for mode_id in FIRST_STAGE_DFT_MODE_IDS:
        workflow = workflow_spec_for_mode(mode_id)
        payload = workflow.to_dict()
        restored = DftWorkflowSpec.from_dict(payload)
        keys = set(_all_keys(payload))

        assert restored.workflow_id == workflow.workflow_id
        assert restored.stages
        assert payload["non_decision_contract"]["analysis_scope"] == "architecture_independent"
        assert forbidden_decision_fields.isdisjoint(keys)
        assert "template_requires_profile_or_fixture_for_strong_claim" in payload["review_flags"]
        assert payload["review_gates"]
        assert payload["hotspot_claims"]
        assert all(claim["evidence_label"] == "predicted" for claim in payload["hotspot_claims"])
        assert all(claim["review_status"] == "needs_review" for claim in payload["hotspot_claims"])


def test_individual_required_modes_expose_expected_stage_and_phase_coverage():
    expected = {
        "scf_ground_state": {"stage_types": {"scf"}, "phases": {"h_psi", "diagonalization", "charge_density", "mixing"}},
        "nscf_bands_dos": {"stage_types": {"nscf", "bands", "dos"}, "phases": {"kpoint_sampling", "band_path_interpolation", "dos_histogram"}},
        "relax_vc_relax": {"stage_types": {"relax", "vc_relax"}, "phases": {"forces", "stress", "cell_update"}},
        "aimd_md": {"stage_types": {"md"}, "phases": {"md_step", "forces", "velocity_update", "thermostat"}},
        "hybrid_exact_exchange": {"stage_types": {"hybrid_scf"}, "phases": {"exact_exchange", "fft", "h_psi"}},
        "postprocess_charge_density": {"stage_types": {"postprocess_charge_density", "projwfc"}, "phases": {"charge_density_read", "grid_interpolation", "wavefunction_projection"}},
    }

    for mode_id, requirements in expected.items():
        workflow = workflow_spec_for_mode(mode_id)
        stage_types = {stage.stage_type for stage in workflow.stages}
        phases = {
            phase["phase_id"]
            for stage in workflow.stages
            for phase in stage.phase_skeleton
        }
        assert requirements["stage_types"].issubset(stage_types)
        assert requirements["phases"].issubset(phases)


def test_dft_mode_coverage_report_script_emits_replayable_artifacts(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "dse_v2/scripts/dse/build_dft_mode_coverage_report.py",
            "--out",
            str(tmp_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    stdout = json.loads(result.stdout)
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    report = json.loads((tmp_path / "dft_mode_coverage_report.json").read_text(encoding="utf-8"))
    workflows = json.loads((tmp_path / "dft_mode_workflows.json").read_text(encoding="utf-8"))

    assert stdout["status"] == "passed"
    assert status["status"] == "passed"
    assert report["covered_mode_ids"] == list(FIRST_STAGE_DFT_MODE_IDS)
    assert set(workflows["workflows"]) == set(FIRST_STAGE_DFT_MODE_IDS)
