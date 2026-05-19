#!/usr/bin/env python3
"""DFT Step1 evidence-label and static-dominance contract tests."""

from __future__ import annotations

from pathlib import Path

from dse_v2.reference_workloads.dft import (
    SourceFact,
    domain_claim_summary_from_case,
    normalize_dft_case_from_facts,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _dimension_facts(*, source_type="input"):
    return [
        SourceFact("input.calculation", "scf", source_type="input", evidence_level="declared_input"),
        SourceFact("dimension.npw", 1024, unit="count", source_type=source_type, evidence_level="declared_input"),
        SourceFact("dimension.nfft", 4096, unit="count", source_type=source_type, evidence_level="declared_input"),
        SourceFact("dimension.nbnd", 512, unit="count", source_type=source_type, evidence_level="declared_input"),
        SourceFact("dimension.kpoint_count", 1, unit="count", source_type=source_type, evidence_level="declared_input"),
    ]


def test_static_dominance_is_predicted_and_review_gated_until_user_confirmation():
    case = normalize_dft_case_from_facts(
        _dimension_facts(),
        case_id="static_dominance",
        source_program="qe_pw",
        parameters={"static_dominance_margin": 2.0},
    )

    claims = domain_claim_summary_from_case(case)

    assert claims["observed_dominance"] == []
    assert claims["predicted_dominance"]
    predicted = claims["predicted_dominance"][0]
    assert predicted["phase_id"] == "diagonalization"
    assert predicted["review_status"] == "needs_review"
    assert claims["needs_review"]


def test_user_confirmation_promotes_static_dominance_without_relabeling_observed():
    case = normalize_dft_case_from_facts(
        _dimension_facts(),
        case_id="confirmed_dominance",
        source_program="qe_pw",
        parameters={"static_dominance_margin": 2.0, "user_confirmed_dominance": ["diagonalization"]},
    )

    claims = domain_claim_summary_from_case(case)

    assert claims["observed_dominance"] == []
    assert claims["predicted_dominance"]
    assert claims["user_confirmed_dominance"]
    assert claims["user_confirmed_dominance"][0]["phase_id"] == "diagonalization"


def test_conflicting_source_facts_create_review_gate_in_claim_summary():
    facts = _dimension_facts()
    facts.append(SourceFact("dimension.npw", 2048, unit="count", source_type="log", evidence_level="observed_preprocessed"))
    case = normalize_dft_case_from_facts(
        facts,
        case_id="conflict_case",
        source_program="qe_pw",
        parameters={"static_dominance_margin": 2.0},
    )

    claims = domain_claim_summary_from_case(case)

    assert any(gate["severity"] == "conflict" for gate in claims["review_gates"])
    assert "project_critical_conflict" in case.review_flags


def test_dft_reference_logic_does_not_leak_into_core_or_mapping_layers():
    """DFT/QE-specific logic must stay behind the reference-workload adapter."""

    forbidden_markers = ("dft", "qe_", "qe-", "quantum espresso", "vasp", "ozaki", "pw.x")
    offenders = []
    for root in (REPO_ROOT / "dse_v2" / "core", REPO_ROOT / "dse_v2" / "mapping"):
        for path in root.rglob("*.py"):
            lowered = path.read_text(encoding="utf-8").lower()
            allowed_boundary_mentions = (
                "dft-specific intent must be translated by a profile",
            )
            scrubbed = lowered
            for allowed in allowed_boundary_mentions:
                scrubbed = scrubbed.replace(allowed, "")
            for marker in forbidden_markers:
                if marker in scrubbed:
                    offenders.append(f"{path.relative_to(REPO_ROOT)} contains {marker!r}")

    assert offenders == []
