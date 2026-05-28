#!/usr/bin/env python3
"""Evidence-bounded FPGA/ASIC deployment-target feasibility for DFT winners.

This artifact is deliberately narrower than a board bitstream or tapeout claim.
It consumes the scoped FPGA/ASIC deployment summary and answers two questions:

* Is there a cited AMD/Xilinx raw FPGA package whose published resources can
  accommodate the current FPGA winner metrics?
* Is the ASIC target library already bound by all-major-kernel DC evidence?

It never reranks candidates, never treats a published device table as Vivado
implementation closure, and never marks the DFT full-SCF deliverable complete.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json


DFT_DEPLOYMENT_TARGET_FEASIBILITY_SCHEMA = "dse.dft.deployment_target_feasibility.v1"
DFT_DEPLOYMENT_TARGET_FEASIBILITY_VALIDATION_SCHEMA = (
    "dse.dft.deployment_target_feasibility_validation.v1"
)
DFT_DEPLOYMENT_TARGET_FEASIBILITY_STATUS_SCHEMA = (
    "dse.dft.deployment_target_feasibility_status.v1"
)

_CLAIM_BOUNDARY = (
    "Deployment target feasibility may recommend a raw FPGA package from cited "
    "published resource tables and may report ASIC target-library binding from "
    "kernel-row DC evidence.  It is not a Vivado platform/bitstream closure, "
    "not a board deployment claim, not a tapeout signoff claim, and never marks "
    "full-SCF deliverable completion."
)

_FPGA_RAW_TARGET_SELECTION_CLASS = "raw_package_capacity_screen"
_FPGA_CLAIM_AWARE_NEXT_GATE = "per_kernel_vivado_part_or_platform_consensus"

_PUBLISHED_FPGA_TARGETS: tuple[Dict[str, Any], ...] = (
    {
        "target_id": "amd_virtex_ultrascale_plus_vu19p_a3824_raw_package",
        "vendor": "AMD/Xilinx",
        "family": "Virtex UltraScale+",
        "device": "VU19P",
        "part": "XCVU19P",
        "package": "A3824-class raw package",
        "recommended_for": "raw_fpga_package_when_bonded_iob_is_literal_package_io",
        "published_capacity": {
            "clb_luts": 4_086_000,
            "dsp_slices": 3_840,
            "block_ram_mb": 75.9,
            "ultraram_mb": 90.0,
            "total_single_ended_io": 2_072,
            "hp_single_ended_io": 1_976,
            "hd_single_ended_io": 96,
            "system_logic_cells": 8_938_000,
        },
        "source_refs": [
            {
                "source_id": "amd_vu19p_product_page",
                "kind": "official_product_page",
                "url": "https://www.amd.com/en/products/adaptive-socs-and-fpgas/fpga/virtex-ultrascale-plus-vu19p.html",
                "fields": ["XCVU19P", "system logic cells", "DSP slices", "I/O"],
            },
            {
                "source_id": "amd_xmp103_ultrascale_plus_selection_guide",
                "kind": "official_selection_guide_pdf",
                "url": "https://www.amd.com/content/dam/xilinx/support/documents/selection-guides/ultrascale-plus-fpga-product-selection-guide.pdf",
                "fields": [
                    "VU19P CLB LUTs",
                    "Total Block RAM",
                    "UltraRAM",
                    "DSP Slices",
                    "Max Single-Ended HP I/Os",
                    "Max Single-Ended HD I/Os",
                    "A3824 footprint",
                ],
            },
        ],
    },
)

_IO_INTERPRETATION_REFS = (
    {
        "source_id": "amd_ug906_report_utilization",
        "kind": "official_vivado_doc",
        "url": "https://docs.amd.com/r/en-US/ug906-vivado-design-analysis/Report-Utilization",
        "fields": ["report_utilization", "I/O Resources", "LUT", "block RAM", "DSP"],
    },
    {
        "source_id": "amd_ug912_port_property",
        "kind": "official_vivado_doc",
        "url": "https://docs.amd.com/r/2023.2-English/ug912-vivado-properties/PORT",
        "fields": ["PORT", "PACKAGE_PIN", "I/O standards", "I/O banks"],
    },
    {
        "source_id": "amd_ug899_placing_io_ports",
        "kind": "official_vivado_doc",
        "url": "https://docs.amd.com/r/en-US/ug899-vivado-io-clock-planning/Placing-I/O-Ports",
        "fields": ["I/O port placement", "package pins"],
    },
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path, *, required: bool = True) -> Dict[str, Any]:
    path = Path(path)
    exists = path.exists() and path.is_file()
    return {
        "path": str(path),
        "required": required,
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
        "hash_algorithm": "sha256",
    }


def _source_freshness_errors(
    source_artifacts: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> list[str]:
    errors: list[str] = []
    for key in keys:
        ref = source_artifacts.get(key)
        if not isinstance(ref, Mapping):
            errors.append(f"missing_required_source_artifact:{key}")
            continue
        path_text = str(ref.get("path") or "")
        if ref.get("exists") is not True or not path_text:
            errors.append(f"missing_required_source_artifact:{key}")
            continue
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            errors.append(f"source_artifact_current_path_missing:{key}")
            continue
        expected_sha = str(ref.get("sha256") or "")
        actual_sha = sha256_file(path)
        if not expected_sha:
            errors.append(f"source_artifact_missing_recorded_sha256:{key}")
        elif actual_sha != expected_sha:
            errors.append(f"stale_source_artifact:{key}")
    return errors


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _resource_check(metric_id: str, required: int | None, capacity: int | None) -> Dict[str, Any]:
    comparable = required is not None and capacity is not None
    return {
        "metric_id": metric_id,
        "required": required,
        "capacity": capacity,
        "comparable": comparable,
        "fits": bool(comparable and required <= capacity),
        "utilization_fraction": (float(required) / float(capacity)) if comparable and capacity else None,
    }


def _fpga_target_fit(metrics: Mapping[str, Any], target: Mapping[str, Any]) -> Dict[str, Any]:
    capacity = target.get("published_capacity", {})
    capacity = capacity if isinstance(capacity, Mapping) else {}
    checks = [
        _resource_check(
            "fpga_total_slice_luts",
            _as_int(metrics.get("fpga_total_slice_luts")),
            _as_int(capacity.get("clb_luts")),
        ),
        _resource_check(
            "fpga_total_dsps",
            _as_int(metrics.get("fpga_total_dsps")),
            _as_int(capacity.get("dsp_slices")),
        ),
        _resource_check(
            "fpga_total_bonded_iob",
            _as_int(metrics.get("fpga_total_bonded_iob")),
            _as_int(capacity.get("total_single_ended_io")),
        ),
    ]
    bram_tiles = _as_int(metrics.get("fpga_total_block_ram_tiles"))
    bram_check = {
        "metric_id": "fpga_total_block_ram_tiles",
        "required": bram_tiles,
        "capacity": capacity.get("block_ram_mb"),
        "comparable": bram_tiles in (None, 0),
        "fits": bool(bram_tiles in (None, 0)),
        "note": (
            "Current candidate uses no BRAM tiles, so published Block RAM Mb is "
            "sufficient for this check.  Nonzero tile counts require a separate "
            "unit conversion before claiming capacity fit."
        ),
    }
    checks.append(bram_check)
    return {
        "target_id": target.get("target_id"),
        "part": target.get("part"),
        "package": target.get("package"),
        "resource_checks": checks,
        "resource_fit": all(bool(check.get("fits")) for check in checks),
    }


def _select_fpga_target(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = [_fpga_target_fit(metrics, target) for target in _PUBLISHED_FPGA_TARGETS]
    selected_fit = next((candidate for candidate in candidates if candidate.get("resource_fit") is True), None)
    selected_target = None
    if selected_fit:
        selected_target = next(
            target for target in _PUBLISHED_FPGA_TARGETS if target["target_id"] == selected_fit["target_id"]
        )
    status = (
        "raw_package_feasible_target_selected"
        if selected_target
        else "blocked_no_published_fpga_target_resource_fit"
    )
    return {
        "status": status,
        "target_selection_class": _FPGA_RAW_TARGET_SELECTION_CLASS,
        "selected_target_id": selected_target.get("target_id") if selected_target else None,
        "selected_vendor": selected_target.get("vendor") if selected_target else None,
        "selected_family": selected_target.get("family") if selected_target else None,
        "selected_device": selected_target.get("device") if selected_target else None,
        "selected_part": selected_target.get("part") if selected_target else None,
        "selected_package": selected_target.get("package") if selected_target else None,
        "published_capacity": selected_target.get("published_capacity", {}) if selected_target else {},
        "source_refs": list(selected_target.get("source_refs", []) if selected_target else []),
        "io_interpretation_refs": list(_IO_INTERPRETATION_REFS),
        "candidate_fits": candidates,
        "resource_fit": bool(selected_target),
        "bitstream_implementation_claim_eligible": False,
        "board_deployment_claim_eligible": False,
        "deployment_target_claim_eligible": False,
        "can_clear_physical_target_blocker": False,
        "claim_aware_next_gate": _FPGA_CLAIM_AWARE_NEXT_GATE,
        "iob_interpretation": {
            "status": "raw_package_io_count_fit_not_board_shell_proof" if selected_target else "not_evaluated",
            "winner_bonded_iob": _as_int(metrics.get("fpga_total_bonded_iob")),
            "selected_total_single_ended_io": (
                selected_target.get("published_capacity", {}).get("total_single_ended_io")
                if selected_target
                else None
            ),
            "claim_boundary": (
                "The bonded_iob metric may represent literal package I/O only when "
                "the synthesized top module is the final FPGA top with LOC/IOSTANDARD "
                "constraints.  For Alveo/Vitis-style accelerator deployment, wide "
                "kernel buses should be wrapped behind platform interfaces; raw I/O "
                "counts are not board exposed pins and require a platform build."
            ),
        },
        "required_next_evidence": [
            "Vivado synthesis/implementation rerun with the selected part or board/platform target",
            "I/O constraints or platform wrapper proving whether bonded_iob maps to package pins or internal AXI/platform interfaces",
            "Timing/resource reports from the selected part before any FPGA deployment claim",
        ],
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _asic_target_binding(summary: Mapping[str, Any]) -> Dict[str, Any]:
    asic = summary.get("asic", {}) if isinstance(summary.get("asic", {}), Mapping) else {}
    device_summary = (
        asic.get("device_summary", {})
        if isinstance(asic.get("device_summary", {}), Mapping)
        else {}
    )
    target_evidence = (
        device_summary.get("kernel_row_target_evidence", {})
        if isinstance(device_summary.get("kernel_row_target_evidence", {}), Mapping)
        else {}
    )
    selected_target = device_summary.get("selected_asic_target") or device_summary.get("selected_device")
    bound = bool(
        asic.get("resolved") is True
        and device_summary.get("device_selection_status") == "resolved_from_kernel_row_evidence"
        and target_evidence.get("all_major_kernel_consistency") is True
        and selected_target
    )
    return {
        "status": "bound_from_dc_kernel_row_consensus" if bound else "blocked_no_real_target_library_consensus",
        "selected_target_library": selected_target if bound else None,
        "candidate_id": asic.get("best_candidate_id"),
        "design_candidate_id": asic.get("best_design_candidate_id"),
        "all_major_kernel_consistency": bool(target_evidence.get("all_major_kernel_consistency", False)),
        "target_evidence": target_evidence,
        "target_binding_claim_eligible": bound,
        "tapeout_signoff_claim_eligible": False,
        "claim_boundary": (
            "ASIC target binding means the current winner's DC kernel rows agree "
            "on a real target library.  It is not tapeout signoff and does not "
            "replace final timing/area/physical verification."
        ),
    }


def build_dft_deployment_target_feasibility(run_dir: Path) -> Dict[str, Any]:
    """Build a fail-closed target feasibility artifact from deployment summary."""

    run_dir = Path(run_dir)
    summary_path = run_dir / "dft_fpga_asic_deployment_summary.json"
    validation_path = run_dir / "dft_fpga_asic_deployment_summary_validation.json"
    summary = _load_json(summary_path)
    validation = _load_json(validation_path)
    fpga = summary.get("fpga", {}) if isinstance(summary.get("fpga", {}), Mapping) else {}
    fpga_metrics = fpga.get("metrics", {}) if isinstance(fpga.get("metrics", {}), Mapping) else {}
    fpga_target = _select_fpga_target(fpga_metrics) if fpga.get("resolved") is True else {
        "status": "blocked_no_resolved_fpga_deployment_winner",
        "target_selection_class": _FPGA_RAW_TARGET_SELECTION_CLASS,
        "resource_fit": False,
        "bitstream_implementation_claim_eligible": False,
        "board_deployment_claim_eligible": False,
        "deployment_target_claim_eligible": False,
        "can_clear_physical_target_blocker": False,
        "claim_aware_next_gate": _FPGA_CLAIM_AWARE_NEXT_GATE,
        "required_next_evidence": ["Resolve FPGA deployment winner before target feasibility"],
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    asic_target = _asic_target_binding(summary)
    feasibility_ready = bool(
        summary.get("best_deployment_claim_eligible") is True
        and validation.get("valid") is True
        and fpga_target.get("resource_fit") is True
        and asic_target.get("target_binding_claim_eligible") is True
    )
    return {
        "schema_version": DFT_DEPLOYMENT_TARGET_FEASIBILITY_SCHEMA,
        "generated_at": _now_iso(),
        "status": "target_feasibility_ready" if feasibility_ready else "target_feasibility_partial",
        "source_artifacts": {
            "dft_fpga_asic_deployment_summary": _source_ref(summary_path),
            "dft_fpga_asic_deployment_summary_validation": _source_ref(validation_path),
        },
        "deployment_summary_validation_valid": validation.get("valid"),
        "best_deployment_claim_eligible": bool(
            summary.get("best_deployment_claim_eligible", False)
            and validation.get("valid") is True
        ),
        "fpga_target_feasibility": fpga_target,
        "asic_target_binding": asic_target,
        "target_feasibility_ready": feasibility_ready,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def validate_dft_deployment_target_feasibility(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate fail-closed target-feasibility semantics."""

    errors: list[str] = []
    if payload.get("schema_version") != DFT_DEPLOYMENT_TARGET_FEASIBILITY_SCHEMA:
        errors.append("invalid_schema_version")
    if payload.get("deliverable_complete") is True:
        errors.append("target_feasibility_must_not_mark_deliverable_complete")
    errors.extend(
        _source_freshness_errors(
            payload.get("source_artifacts", {})
            if isinstance(payload.get("source_artifacts", {}), Mapping)
            else {},
            keys=(
                "dft_fpga_asic_deployment_summary",
                "dft_fpga_asic_deployment_summary_validation",
            ),
        )
    )
    fpga = payload.get("fpga_target_feasibility", {})
    fpga = fpga if isinstance(fpga, Mapping) else {}
    asic = payload.get("asic_target_binding", {})
    asic = asic if isinstance(asic, Mapping) else {}
    if fpga.get("bitstream_implementation_claim_eligible") is True:
        errors.append("fpga_target_feasibility_must_not_claim_bitstream_implementation")
    if fpga.get("board_deployment_claim_eligible") is True:
        errors.append("fpga_target_feasibility_must_not_claim_board_deployment")
    if fpga.get("deployment_target_claim_eligible") is True:
        errors.append("fpga_raw_target_feasibility_must_not_claim_deployment_target")
    if fpga.get("can_clear_physical_target_blocker") is True:
        errors.append("fpga_raw_target_feasibility_must_not_clear_physical_target_blocker")
    if fpga.get("resource_fit") is True:
        if fpga.get("target_selection_class") != _FPGA_RAW_TARGET_SELECTION_CLASS:
            errors.append("fpga_resource_fit_without_raw_package_capacity_screen_class")
        if fpga.get("claim_aware_next_gate") != _FPGA_CLAIM_AWARE_NEXT_GATE:
            errors.append("fpga_resource_fit_without_vivado_part_or_platform_next_gate")
    if fpga.get("selected_part") and fpga.get("resource_fit") is not True:
        errors.append("selected_fpga_part_without_resource_fit")
    if fpga.get("resource_fit") is True and not fpga.get("source_refs"):
        errors.append("fpga_resource_fit_without_official_source_refs")
    if asic.get("tapeout_signoff_claim_eligible") is True:
        errors.append("asic_target_binding_must_not_claim_tapeout_signoff")
    if asic.get("target_binding_claim_eligible") is True:
        if asic.get("all_major_kernel_consistency") is not True:
            errors.append("asic_binding_without_kernel_consistency")
        if not asic.get("selected_target_library"):
            errors.append("asic_binding_without_selected_target_library")
    if payload.get("target_feasibility_ready") is True:
        if fpga.get("resource_fit") is not True:
            errors.append("ready_without_fpga_resource_fit")
        if asic.get("target_binding_claim_eligible") is not True:
            errors.append("ready_without_asic_target_binding")
    return {
        "schema_version": DFT_DEPLOYMENT_TARGET_FEASIBILITY_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_deployment_target_feasibility(run_dir: Path) -> Dict[str, Any]:
    """Write feasibility, validation, and status artifacts."""

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    feasibility = build_dft_deployment_target_feasibility(run_dir)
    validation = validate_dft_deployment_target_feasibility(feasibility)
    write_json(run_dir / "dft_deployment_target_feasibility.json", feasibility)
    write_json(run_dir / "dft_deployment_target_feasibility_validation.json", validation)
    status = {
        "schema_version": DFT_DEPLOYMENT_TARGET_FEASIBILITY_STATUS_SCHEMA,
        "generated_at": _now_iso(),
        "status": "passed" if validation["valid"] else "failed",
        "target_feasibility_ready": feasibility.get("target_feasibility_ready"),
        "fpga_status": feasibility.get("fpga_target_feasibility", {}).get("status"),
        "fpga_target_selection_class": feasibility.get("fpga_target_feasibility", {}).get(
            "target_selection_class"
        ),
        "asic_status": feasibility.get("asic_target_binding", {}).get("status"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(run_dir / "dft_deployment_target_feasibility_status.json", status)
    return {
        "schema_version": "dse.dft.deployment_target_feasibility_artifact_status.v1",
        "status": status["status"],
        "deployment_target_feasibility": str(run_dir / "dft_deployment_target_feasibility.json"),
        "deployment_target_feasibility_validation": str(
            run_dir / "dft_deployment_target_feasibility_validation.json"
        ),
        "deployment_target_feasibility_status": str(
            run_dir / "dft_deployment_target_feasibility_status.json"
        ),
        "target_feasibility_ready": feasibility.get("target_feasibility_ready"),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


__all__ = [
    "DFT_DEPLOYMENT_TARGET_FEASIBILITY_SCHEMA",
    "DFT_DEPLOYMENT_TARGET_FEASIBILITY_STATUS_SCHEMA",
    "DFT_DEPLOYMENT_TARGET_FEASIBILITY_VALIDATION_SCHEMA",
    "build_dft_deployment_target_feasibility",
    "validate_dft_deployment_target_feasibility",
    "write_dft_deployment_target_feasibility",
]
