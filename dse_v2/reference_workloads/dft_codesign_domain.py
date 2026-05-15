#!/usr/bin/env python3
"""DFT plugin proposal for the seven-axis co-design release domain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from dse_v2.codesign.release_domain import (
    AxisDomain,
    AxisValue,
    axis_value_ids,
    build_candidate_universe,
    build_domain_freeze,
    stable_json_hash,
)


DFT_CODESIGN_RELEASE_ID = "dft_first_seven_axis_release_v1"
DFT_SEVEN_AXIS_IDS = (
    "dft_phase_hotspot_selection",
    "algorithm_variants",
    "schedule_runtime_policy",
    "mapping_data_layout",
    "hardware_microarchitecture",
    "interface_descriptor_protocol",
    "evidence_fidelity_promotion_policy",
)

DFT_LEGALITY_CONSTRAINTS = (
    {
        "constraint_id": "hybrid_exx_requires_batched_gemm",
        "when": {"dft_phase_hotspot_selection": "hybrid_exx_fft"},
        "requires": {"algorithm_variants": "batched_gemm_exx"},
        "reason": "hybrid_exx_fft requires batched_gemm_exx algorithm template",
    },
    {
        "constraint_id": "batched_gemm_requires_band_block_layout",
        "when": {"algorithm_variants": "batched_gemm_exx"},
        "requires": {"mapping_data_layout": "band_block_systolic"},
        "reason": "batched_gemm_exx requires band_block_systolic layout",
    },
    {
        "constraint_id": "fft_grid_layout_bound_to_host_fpga",
        "when": {"mapping_data_layout": "fft_grid_hbm_tiled"},
        "requires": {"hardware_microarchitecture": "host_fpga_minimal_v0"},
        "reason": "fft_grid_hbm_tiled release value is bound to host_fpga_minimal_v0 in this frozen domain",
    },
    {
        "constraint_id": "batched_descriptor_requires_batched_gemm",
        "when": {"interface_descriptor_protocol": "batched_kernel_descriptor_v1"},
        "requires": {"algorithm_variants": "batched_gemm_exx"},
        "reason": "batched descriptor requires batched_gemm_exx algorithm",
    },
    {
        "constraint_id": "eda_formal_ladder_requires_genericaccel_descriptor",
        "when": {"evidence_fidelity_promotion_policy": "systemc_gem5_eda_formal_ladder"},
        "requires": {"interface_descriptor_protocol": "genericaccel_descriptor_v1"},
        "reason": "EDA/formal ladder currently requires genericaccel_descriptor_v1",
    },
)

_SOURCE_LEDGER = (
    {
        "id": "S01",
        "kind": "official_docs",
        "source": "Quantum ESPRESSO pw.x input description v7.5",
        "url": "https://www.quantum-espresso.org/Doc/INPUT_PW.html",
        "supports": ["dft_phase_hotspot_selection", "algorithm_variants"],
    },
    {
        "id": "S03",
        "kind": "paper",
        "source": "Giannozzi et al., Quantum ESPRESSO toward the exascale, JCP 2020",
        "doi": "10.1063/5.0005082",
        "supports": ["algorithm_variants", "schedule_runtime_policy"],
    },
    {
        "id": "S15",
        "kind": "vendor_official",
        "source": "AMD Alveo U280 product brief",
        "supports": ["hardware_microarchitecture", "mapping_data_layout"],
    },
    {
        "id": "S19",
        "kind": "vendor_app_note",
        "source": "Alpha Data HBM FPGA memory-bandwidth app note",
        "supports": ["mapping_data_layout", "hardware_microarchitecture"],
    },
    {
        "id": "S21",
        "kind": "research_software_docs",
        "source": "AutoSA matrix multiplication with HBM example",
        "supports": ["algorithm_variants", "hardware_microarchitecture"],
    },
    {
        "id": "S22",
        "kind": "vendor_benchmark",
        "source": "Xilinx Vitis BLAS benchmark",
        "supports": ["algorithm_variants", "evidence_fidelity_promotion_policy"],
    },
    {
        "id": "GENERIC_DSE_V2",
        "kind": "repo_architecture_doc",
        "source": "docs/architecture/generic_dse_framework_design_spec_v2.md",
        "supports": [
            "schedule_runtime_policy",
            "interface_descriptor_protocol",
            "evidence_fidelity_promotion_policy",
        ],
    },
)


def dft_seven_axis_source_ledger() -> list[Dict[str, Any]]:
    return [dict(item) for item in _SOURCE_LEDGER]


def dft_legality_constraints() -> list[Dict[str, Any]]:
    """Return DFT legality constraints as data consumed by the generic universe builder."""
    return [
        {
            "schema_version": "dse.dft.legality_constraint.v1",
            **dict(item),
            "axis_ids": sorted({*item["when"], *item["requires"]}),
            "claim_boundary": "DFT plugin data for generic legality evaluation; not core coupling.",
        }
        for item in DFT_LEGALITY_CONSTRAINTS
    ]


def dft_seven_axis_domains() -> tuple[AxisDomain, ...]:
    return (
        AxisDomain(
            axis_id="dft_phase_hotspot_selection",
            label="DFT phase / hotspot selection",
            description="First-stage DFT workflow focus used to seed candidate generation and feedback grouping.",
            source_refs=("S01", "S03"),
            values=(
                AxisValue(
                    "scf_hpsi_density",
                    "SCF h_psi / density / mixing",
                    "SCF-dominant plane-wave phase bundle with h_psi, diagonalization, density, and mixing.",
                    ("S01", "S03"),
                    {"phase_groups": ["dense_linear_algebra", "fft_grid_density", "mixing_reduction"]},
                ),
                AxisValue(
                    "hybrid_exx_fft",
                    "Hybrid exact exchange / FFT",
                    "Hybrid-functional path with exact exchange, FFT/grid movement, and diagonalization pressure.",
                    ("S01", "S22"),
                    {"phase_groups": ["hybrid_exchange", "fft_grid_density", "dense_linear_algebra"]},
                ),
            ),
        ),
        AxisDomain(
            axis_id="algorithm_variants",
            label="Algorithm variants",
            description="Algorithmic kernel template used before any hardware binding.",
            source_refs=("S01", "S03", "S21", "S22"),
            values=(
                AxisValue(
                    "iterative_diag_fft",
                    "Iterative diagonalization + FFT",
                    "QE-like iterative eigensolver plus FFT/grid kernels.",
                    ("S01", "S03"),
                    {"phase_groups": ["diagonalization", "fft_grid_density"]},
                ),
                AxisValue(
                    "batched_gemm_exx",
                    "Batched GEMM exact-exchange",
                    "Exact-exchange/hybrid block expressed as batched dense kernels.",
                    ("S21", "S22"),
                    {"phase_groups": ["hybrid_exchange", "dense_linear_algebra"]},
                ),
            ),
        ),
        AxisDomain(
            axis_id="schedule_runtime_policy",
            label="Schedule / runtime policy",
            description="Runtime orchestration policy used by screening and feedback.",
            source_refs=("S03", "GENERIC_DSE_V2"),
            values=(
                AxisValue(
                    "host_orchestrated_sync",
                    "Host-orchestrated synchronous kernels",
                    "Conservative host-submitted accelerator kernels with explicit completion boundaries.",
                    ("S03", "GENERIC_DSE_V2"),
                    {"overlap": False, "feedback_feature": "host_submission_latency"},
                ),
                AxisValue(
                    "overlap_dma_compute",
                    "Overlap DMA and compute",
                    "Pipelined transfer/compute overlap candidate for streaming/HBM candidates.",
                    ("S15", "S19", "GENERIC_DSE_V2"),
                    {"overlap": True, "feedback_feature": "dma_compute_overlap"},
                ),
            ),
        ),
        AxisDomain(
            axis_id="mapping_data_layout",
            label="Mapping / data layout",
            description="Generic layout/mapping template used by legality and screening.",
            source_refs=("S15", "S19", "S21"),
            values=(
                AxisValue(
                    "fft_grid_hbm_tiled",
                    "FFT/grid HBM tiling",
                    "Grid/FFT/data-density path using HBM-friendly tiles.",
                    ("S15", "S19"),
                    {"layout_group": "fft_grid_density"},
                ),
                AxisValue(
                    "band_block_systolic",
                    "Band-block systolic layout",
                    "Band/block layout for dense GEMM/eigensolver/exact-exchange candidates.",
                    ("S21", "S22"),
                    {"layout_group": "dense_linear_algebra"},
                ),
            ),
        ),
        AxisDomain(
            axis_id="hardware_microarchitecture",
            label="Hardware / microarchitecture",
            description="Searchable hardware family binding; values map to repo architecture IDs when available.",
            source_refs=("S15", "S19", "S21", "GENERIC_DSE_V2"),
            values=(
                AxisValue(
                    "balanced_generic_systemc_v0",
                    "Balanced GenericAccel/SystemC candidate",
                    "Existing balanced-generic-systemc-v0 path with GenericAccel non-smoke evidence hooks.",
                    ("GENERIC_DSE_V2",),
                    {"architecture_id": "balanced-generic-systemc-v0", "family": "balanced_generic"},
                ),
                AxisValue(
                    "host_fpga_minimal_v0",
                    "Host + minimal FPGA candidate",
                    "Existing host-fpga-minimal-v0 path used as a small host/FPGA comparison point.",
                    ("GENERIC_DSE_V2", "S15"),
                    {"architecture_id": "host-fpga-minimal-v0", "family": "host_fpga_minimal"},
                ),
            ),
        ),
        AxisDomain(
            axis_id="interface_descriptor_protocol",
            label="Interface / descriptor protocol",
            description="Host/accelerator interface contract used by promotion and L4 evidence checks.",
            source_refs=("GENERIC_DSE_V2",),
            values=(
                AxisValue(
                    "genericaccel_descriptor_v1",
                    "GenericAccel descriptor v1",
                    "Repo GenericAccel descriptor/request/completion path.",
                    ("GENERIC_DSE_V2",),
                    {"descriptor_schema": "generic_accel_descriptor.v1"},
                ),
                AxisValue(
                    "batched_kernel_descriptor_v1",
                    "Batched kernel descriptor v1",
                    "Descriptor variant for batched dense/hybrid-exchange kernels; still GenericAccel-compatible.",
                    ("GENERIC_DSE_V2", "S22"),
                    {"descriptor_schema": "generic_accel_batched_kernel_descriptor.v1"},
                ),
            ),
        ),
        AxisDomain(
            axis_id="evidence_fidelity_promotion_policy",
            label="Evidence fidelity / promotion policy",
            description="Promotion ladder defining what evidence is required before stronger claims.",
            source_refs=("GENERIC_DSE_V2", "S22"),
            values=(
                AxisValue(
                    "systemc_then_gem5_non_smoke",
                    "SystemC then non-smoke gem5",
                    "Step3 generic_sim timing followed by non-smoke gem5 GenericAccel proof for promoted candidates.",
                    ("GENERIC_DSE_V2",),
                    {"requires_systemc": True, "requires_gem5_non_smoke": True, "requires_eda": False},
                ),
                AxisValue(
                    "systemc_gem5_eda_formal_ladder",
                    "SystemC + gem5 + EDA/formal ladder",
                    "Stronger release ladder that also schedules EDA/formal evidence rows.",
                    ("GENERIC_DSE_V2", "S22"),
                    {"requires_systemc": True, "requires_gem5_non_smoke": True, "requires_eda": True},
                ),
            ),
        ),
    )


def dft_domain_freeze() -> Dict[str, Any]:
    freeze = build_domain_freeze(
        dft_seven_axis_domains(),
        release_id=DFT_CODESIGN_RELEASE_ID,
        source_ledger=dft_seven_axis_source_ledger(),
        claim_boundary=(
            "frozen finite DFT-first release domain; candidate/evidence execution "
            "and closure are audited by downstream artifacts"
        ),
    )
    freeze["small_release_domain_policy"] = {
        "finite": True,
        "cited": True,
        "explicit_scope": "DFT-first seven-axis release v1, two values per axis",
        "complete_for_frozen_scope": True,
        "represents_infinite_dft_space": False,
        "claim_boundary": (
            "This small release domain is complete only for the frozen cited scope; "
            "it is not represented as the infinite DFT design space."
        ),
    }
    freeze["legality_constraints"] = dft_legality_constraints()
    freeze["domain_hash"] = stable_json_hash({
        key: value for key, value in freeze.items() if key != "domain_hash"
    })
    return freeze


def _legality(assignments: Mapping[str, str]) -> tuple[bool, Sequence[str]]:
    reasons: list[str] = []
    for constraint in DFT_LEGALITY_CONSTRAINTS:
        when = constraint["when"]
        requires = constraint["requires"]
        if all(assignments.get(axis_id) == value_id for axis_id, value_id in when.items()) and any(
            assignments.get(axis_id) != value_id for axis_id, value_id in requires.items()
        ):
            reasons.append(str(constraint["reason"]))
    return not reasons, reasons


def _screen(assignments: Mapping[str, str]) -> Dict[str, Any]:
    axis_terms = {axis_id: 1.0 for axis_id in DFT_SEVEN_AXIS_IDS}
    if assignments["schedule_runtime_policy"] == "overlap_dma_compute":
        axis_terms["schedule_runtime_policy"] = 0.85
    if assignments["hardware_microarchitecture"] == "balanced_generic_systemc_v0":
        axis_terms["hardware_microarchitecture"] = 0.95
    if assignments["evidence_fidelity_promotion_policy"] == "systemc_gem5_eda_formal_ladder":
        axis_terms["evidence_fidelity_promotion_policy"] = 1.15
    return {
        "score_model": "deterministic_axis_weighted_screen_v1",
        "axis_terms": axis_terms,
        "score": round(sum(axis_terms.values()), 6),
        "all_axes_used": sorted(axis_terms) == sorted(DFT_SEVEN_AXIS_IDS),
        "trusted_final_claim": False,
    }


def dft_candidate_universe() -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    freeze = dft_domain_freeze()
    manifest, legality = build_candidate_universe(freeze, legality_fn=_legality, score_fn=_screen)
    return freeze, manifest, legality


def build_search_space_report(
    freeze: Mapping[str, Any],
    manifest: Mapping[str, Any],
    legality: Mapping[str, Any],
    *,
    timing_evidence_summary: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    axes = axis_value_ids(freeze)
    legal_candidates = [
        candidate for candidate in manifest.get("candidates", []) or []
        if isinstance(candidate, Mapping) and candidate.get("legal") is True
    ]
    timing_summary = dict(timing_evidence_summary or {})
    feedback_axis_updates = {
        axis_id: {
            "status": "updated_from_non_smoke_timing_evidence" if timing_summary else "ready_for_timing_feedback",
            "value_count": len(values),
            "values": values,
        }
        for axis_id, values in axes.items()
    }
    promoted = [
        {
            "candidate_id": candidate["candidate_id"],
            "assignments": candidate["assignments"],
            "promotion_target": "non_smoke_systemc_gem5_timing",
            "promotion_reason": "legal candidate in frozen seven-axis release domain",
            "all_axes_used": sorted(candidate["assignments"]) == sorted(DFT_SEVEN_AXIS_IDS),
            "timing_evidence_status": "pending_or_external_sample",
        }
        for candidate in legal_candidates
    ]
    promoted_candidate_ids = [item["candidate_id"] for item in promoted]
    report = {
        "schema_version": "dse.dft.seven_axis_search_space_report.v1",
        "status": "passed" if legal_candidates else "failed",
        "release_id": freeze.get("release_id"),
        "domain_hash": freeze.get("domain_hash"),
        "universe_hash": manifest.get("universe_hash"),
        "legality_hash": legality.get("legality_hash"),
        "axis_ids": list(DFT_SEVEN_AXIS_IDS),
        "axis_usage": {
            axis_id: {
                "candidate_generation": True,
                "screening": True,
                "non_smoke_timing_promotion": True,
                "feedback": True,
                "values": values,
            }
            for axis_id, values in axes.items()
        },
        "candidate_generation": {
            "cartesian_count": manifest.get("cartesian_count"),
            "legal_candidate_count": manifest.get("legal_candidate_count"),
            "all_candidates_have_all_axes": all(
                sorted(candidate.get("assignments", {})) == sorted(DFT_SEVEN_AXIS_IDS)
                for candidate in manifest.get("candidates", []) or []
                if isinstance(candidate, Mapping)
            ),
        },
        "cardinality_cost_estimator": {
            "stage": "before_full_evidence_execution",
            "cartesian_candidate_count": manifest.get("cartesian_count"),
            "legal_candidate_count": manifest.get("legal_candidate_count"),
            "illegal_candidate_count": manifest.get("illegal_candidate_count"),
            "required_hard_evidence_classes": 9,
            "estimated_candidate_evidence_rows": int(manifest.get("legal_candidate_count") or 0),
            "estimated_hard_evidence_slots": int(manifest.get("legal_candidate_count") or 0) * 9,
            "claim_boundary": (
                "Cardinality/cost estimates may size and order the run before "
                "full evidence execution; they are not completion evidence."
            ),
        },
        "screening": {
            "all_legal_candidates_have_axis_terms": all(
                sorted((candidate.get("screening", {}).get("axis_terms") or {}).keys()) == sorted(DFT_SEVEN_AXIS_IDS)
                for candidate in legal_candidates
            ),
            "priority_queue_policy": {
                "top_k_or_representative_subset_allowed_for_execution_order": True,
                "completion_requires_all_legal_candidates": True,
                "subset_satisfies_release_completion": False,
                "claim_boundary": (
                    "Screening scores may prioritize expensive evidence execution, "
                    "but top-K or representative-only evidence cannot replace "
                    "all-candidate evidence closure for the frozen release domain."
                ),
            },
        },
        "promotion_queue": promoted,
        "universe_backed_queue": {
            "queue_mode": "all_legal_candidates",
            "source": "candidate_universe_manifest.legal_candidate_ids",
            "entry_count": len(promoted_candidate_ids),
            "candidate_ids": promoted_candidate_ids,
            "all_legal_candidates_once": promoted_candidate_ids == list(manifest.get("legal_candidate_ids", []) or [])
            and len(promoted_candidate_ids) == len(set(promoted_candidate_ids)),
            "claim_boundary": (
                "Queue covers each legal frozen-domain candidate exactly once; "
                "downstream evidence status still controls completion claims."
            ),
        },
        "feedback_trace": {
            "schema_version": "dse.dft.closed_loop_feedback_trace.v1",
            "status": "passed" if timing_summary else "ready",
            "source": "existing_non_smoke_timing_sample" if timing_summary else "domain_ready_no_timing_sample",
            "timing_evidence_summary": timing_summary,
            "axis_updates": feedback_axis_updates,
            "all_axes_updated_or_ready": sorted(feedback_axis_updates) == sorted(DFT_SEVEN_AXIS_IDS),
        },
        "claim_boundary": (
            "Seven-axis release-domain/search-space contract. This is not a claim "
            "that every legal candidate already has all downstream evidence rows closed."
        ),
    }
    report["search_space_hash"] = stable_json_hash({
        key: value for key, value in report.items() if key != "search_space_hash"
    })
    return report


def timing_summary_from_dft_run(run_dir: Path) -> Dict[str, Any]:
    summary_path = run_dir / "dft_end_to_end_summary.json"
    if not summary_path.exists():
        return {}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    step4 = summary.get("step4_gem5") if isinstance(summary, Mapping) else {}
    if not isinstance(step4, Mapping):
        step4 = {}
    best = summary.get("best_architecture") if isinstance(summary, Mapping) else {}
    if not isinstance(best, Mapping):
        best = {}
    return {
        "run_dir": str(run_dir),
        "summary": str(summary_path),
        "status": summary.get("status"),
        "best_architecture": best,
        "step4_architecture_id": step4.get("architecture_id"),
        "step4_trusted_timing": step4.get("trusted_step4_timing"),
        "step4_activity_artifact": step4.get("activity_artifact"),
        "step4_attempted": step4.get("attempted"),
    }


def write_dft_seven_axis_artifacts(out_dir: Path, *, timing_run_dir: Path | None = None) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    freeze, manifest, legality = dft_candidate_universe()
    timing = timing_summary_from_dft_run(timing_run_dir) if timing_run_dir else {}
    report = build_search_space_report(freeze, manifest, legality, timing_evidence_summary=timing)
    artifacts = {
        "seven_axis_domain_freeze": out_dir / "seven_axis_domain_freeze.json",
        "candidate_universe_manifest": out_dir / "candidate_universe_manifest.json",
        "candidate_legality_report": out_dir / "candidate_legality_report.json",
        "seven_axis_search_space_report": out_dir / "seven_axis_search_space_report.json",
        "closed_loop_feedback_trace": out_dir / "closed_loop_feedback_trace.json",
    }
    # Preserve insertion order in artifact JSON so human review sees every
    # candidate assignment in the frozen axis order.  Hashes remain stable
    # because stable_json_hash() canonicalizes separately for digesting.
    artifacts["seven_axis_domain_freeze"].write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    artifacts["candidate_universe_manifest"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    artifacts["candidate_legality_report"].write_text(json.dumps(legality, indent=2) + "\n", encoding="utf-8")
    artifacts["seven_axis_search_space_report"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    artifacts["closed_loop_feedback_trace"].write_text(json.dumps(report["feedback_trace"], indent=2) + "\n", encoding="utf-8")
    status = {
        "schema_version": "dse.dft.seven_axis_artifact_status.v1",
        "status": "passed" if report["status"] == "passed" else "failed",
        "artifacts": {key: str(path) for key, path in artifacts.items()},
        "domain_hash": freeze["domain_hash"],
        "universe_hash": manifest["universe_hash"],
        "legality_hash": legality["legality_hash"],
        "search_space_hash": report["search_space_hash"],
        "axis_ids": list(DFT_SEVEN_AXIS_IDS),
        "legal_candidate_count": manifest["legal_candidate_count"],
        "claim_boundary": report["claim_boundary"],
    }
    (out_dir / "status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status
