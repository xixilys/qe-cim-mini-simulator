#!/usr/bin/env python3
"""Per-shard DFT/QE hardware closure packets and runbooks.

This helper expands ``dft_hardware_closure_shards.json`` into one JSON closure
packet plus one human/agent runbook per shard.  The packets are execution
instructions only: they enumerate candidate-specific RTL/HLS bundle inputs,
expected raw evidence filenames, and tool command templates, but they never
attach or fabricate closure evidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from dse_v2.codesign.evidence_ledger import sha256_file, write_json

DFT_HARDWARE_CLOSURE_PACKETS_SCHEMA = "dse.dft.hardware_closure_packets.v1"
DFT_HARDWARE_CLOSURE_PACKET_SCHEMA = "dse.dft.hardware_closure_packet.v1"
DFT_HARDWARE_CLOSURE_PACKETS_VALIDATION_SCHEMA = "dse.dft.hardware_closure_packets_validation.v1"

_PACKET_DIR = "dft_hardware_closure_packets"
_BLOCKED_STATUS = "blocked_until_candidate_specific_bundle_and_real_tool_execution"
_CANDIDATE_METADATA_FIELDS = (
    "design_candidate_id",
    "assignments",
    "identity_assignments",
    "non_identity_assignments",
    "applicability_assignments",
    "evaluation_policy_assignments",
)
_CLAIM_BOUNDARY = (
    "dft_hardware_closure_packet_index.json and per-shard closure packets are "
    "runbooks for candidate-specific RTL/HLS/Vivado/DC execution. They do not "
    "contain candidate-specific evidence and cannot upgrade numerical "
    "correctness, FPGA/ASIC PPA, trusted Pareto, or deliverable completion."
)

_STAGE_FILE_TEMPLATES: Dict[str, tuple[str, ...]] = {
    "golden_correctness": (
        "{unit_dir}/golden_correctness_report.json",
        "{unit_dir}/golden_reference_trace.json",
        "{unit_dir}/candidate_input_manifest.json",
    ),
    "hls_or_rtl_sim": (
        "{unit_dir}/hls_csim_or_rtl_sim_transcript.log",
        "{unit_dir}/rtl_or_hls_sim_result.json",
        "{unit_dir}/sim_waveform_manifest.json",
    ),
    "hls_or_rtl_synth": (
        "{unit_dir}/hls_or_rtl_synth_report.json",
        "{unit_dir}/hls_or_rtl_synth_utilization.json",
        "{unit_dir}/hls_or_rtl_synth_transcript.log",
    ),
    "vivado_fpga_synth_or_impl": (
        "{unit_dir}/vivado_synth_or_impl.log",
        "{unit_dir}/vivado_timing_summary.rpt",
        "{unit_dir}/vivado_utilization.rpt",
        "{unit_dir}/vivado_route_status.json",
    ),
    "dc_asic_synth_timing_area": (
        "{unit_dir}/dc_shell.log",
        "{unit_dir}/dc_timing.rpt",
        "{unit_dir}/dc_area.rpt",
        "{unit_dir}/dc_qor.rpt",
        "{unit_dir}/dc_synth.ddc",
    ),
}

_STAGE_COMMAND_IDS: Dict[str, tuple[str, ...]] = {
    "golden_correctness": ("golden_correctness_host_reference",),
    "hls_or_rtl_sim": ("vcs_or_hls_csim",),
    "hls_or_rtl_synth": ("vivado_hls_or_rtl_synth",),
    "vivado_fpga_synth_or_impl": ("vivado_fpga_synth_impl",),
    "dc_asic_synth_timing_area": ("dc_asic_synth_timing_area",),
}

_COMMAND_TEMPLATES: tuple[Dict[str, Any], ...] = (
    {
        "template_id": "golden_correctness_host_reference",
        "stage_ids": ["golden_correctness"],
        "tool": "python3",
        "command": (
            "python3 dse_v2/scripts/dse/run_dft_candidate_golden_correctness.py "
            "--candidate-bundle {candidate_bundle_json} --kernel {kernel_id} "
            "--out {unit_evidence_dir}"
        ),
        "required_outputs": list(_STAGE_FILE_TEMPLATES["golden_correctness"]),
        "notes": "Domain golden reference must use the frozen descriptor+runnable bundle for this candidate/kernel.",
    },
    {
        "template_id": "vcs_or_hls_csim",
        "stage_ids": ["hls_or_rtl_sim"],
        "tool": "vcs_or_hls",
        "command": (
            "vcs -full64 -sverilog {rtl_sources} {testbench_sources} "
            "-l {unit_evidence_dir}/hls_csim_or_rtl_sim_transcript.log && "
            "{sim_binary} +KERNEL={kernel_id} +CANDIDATE_BUNDLE={candidate_bundle_json}"
        ),
        "alternate_command": (
            "vivado_hls -f scripts/run_hls_csim.tcl -tclargs "
            "{candidate_bundle_json} {kernel_id} {unit_evidence_dir}"
        ),
        "required_outputs": list(_STAGE_FILE_TEMPLATES["hls_or_rtl_sim"]),
        "notes": "Either RTL simulation or HLS C-sim may satisfy the sim gate, but logs must be raw and candidate-specific.",
    },
    {
        "template_id": "vivado_hls_or_rtl_synth",
        "stage_ids": ["hls_or_rtl_synth"],
        "tool": "vivado_or_hls",
        "command": (
            "vivado -mode batch -source scripts/run_vivado_or_hls_synth.tcl "
            "-tclargs {candidate_bundle_json} {kernel_id} {unit_evidence_dir}"
        ),
        "alternate_command": (
            "vivado_hls -f scripts/run_hls_synth.tcl -tclargs "
            "{candidate_bundle_json} {kernel_id} {unit_evidence_dir}"
        ),
        "required_outputs": list(_STAGE_FILE_TEMPLATES["hls_or_rtl_synth"]),
        "notes": "HLS/RTL synthesis is not an FPGA implementation claim until the Vivado FPGA gate also closes.",
    },
    {
        "template_id": "vivado_fpga_synth_impl",
        "stage_ids": ["vivado_fpga_synth_or_impl"],
        "tool": "vivado",
        "command": (
            "LC_ALL=C LANG=C vivado -mode batch -source scripts/run_vivado_fpga_impl.tcl "
            "-tclargs {candidate_bundle_json} {kernel_id} {unit_evidence_dir}"
        ),
        "required_outputs": list(_STAGE_FILE_TEMPLATES["vivado_fpga_synth_or_impl"]),
        "notes": "This is the FPGA claim gate; DC-only evidence must not be accepted for this stage.",
    },
    {
        "template_id": "dc_asic_synth_timing_area",
        "stage_ids": ["dc_asic_synth_timing_area"],
        "tool": "dc_shell",
        "command": (
            "dc_shell -f scripts/run_dc_asic_synth.tcl -x "
            "\"set candidate_bundle {candidate_bundle_json}; set kernel_id {kernel_id}; "
            "set evidence_dir {unit_evidence_dir}\" | tee {unit_evidence_dir}/dc_shell.log"
        ),
        "required_outputs": list(_STAGE_FILE_TEMPLATES["dc_asic_synth_timing_area"]),
        "notes": "This is the ASIC claim gate; Vivado-only evidence must not be accepted for this stage.",
    },
)


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _source_ref(path: Path) -> Dict[str, Any]:
    candidate = Path(path)
    return {
        "path": str(candidate),
        "exists": candidate.exists() and candidate.is_file(),
        "sha256": sha256_file(candidate) if candidate.exists() and candidate.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _artifact_ref(root_dir: Path, relative_path: str) -> Dict[str, Any]:
    path = Path(root_dir) / relative_path
    return {
        "path": relative_path,
        "exists": path.exists() and path.is_file(),
        "sha256": sha256_file(path) if path.exists() and path.is_file() else None,
        "hash_algorithm": "sha256",
    }


def _safe_slug(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    slug = re.sub(r"[^a-z0-9_.-]+", "_", text)
    return slug.strip("_") or "unknown"


def _unit_evidence_dir(candidate_id: str, kernel_id: str) -> str:
    return f"candidate_specific_evidence/{_safe_slug(candidate_id)}/{_safe_slug(kernel_id)}"


def _expected_evidence_files(unit: Mapping[str, Any]) -> list[Dict[str, Any]]:
    candidate_id = str(unit.get("candidate_id", "unknown_candidate"))
    kernel_id = str(unit.get("kernel_id", "unknown_kernel"))
    unit_dir = _unit_evidence_dir(candidate_id, kernel_id)
    rows: list[Dict[str, Any]] = []
    for stage_id in unit.get("stage_ids", []) or []:
        for template in _STAGE_FILE_TEMPLATES.get(str(stage_id), ("{unit_dir}/stage_evidence.json",)):
            rows.append(
                {
                    "stage_id": str(stage_id),
                    "path": template.format(unit_dir=unit_dir),
                    "required": True,
                    "present": False,
                    "claim_role": "candidate_specific_required_evidence_placeholder",
                }
            )
    rows.extend(
        [
            {
                "stage_id": "all",
                "path": f"{unit_dir}/tool_versions.json",
                "required": True,
                "present": False,
                "claim_role": "tool_version_provenance_placeholder",
            },
            {
                "stage_id": "all",
                "path": f"{unit_dir}/command_manifest.json",
                "required": True,
                "present": False,
                "claim_role": "replay_command_provenance_placeholder",
            },
            {
                "stage_id": "all",
                "path": f"{unit_dir}/raw_transcript_index.json",
                "required": True,
                "present": False,
                "claim_role": "raw_transcript_provenance_placeholder",
            },
            {
                "stage_id": "all",
                "path": f"{unit_dir}/source_bundle_manifest.json",
                "required": True,
                "present": False,
                "claim_role": "rtl_hls_source_bundle_placeholder",
            },
        ]
    )
    return rows


def _required_command_template_ids(stage_ids: Iterable[Any]) -> list[str]:
    ids: list[str] = []
    for stage_id in stage_ids:
        ids.extend(_STAGE_COMMAND_IDS.get(str(stage_id), ()))
    return sorted(dict.fromkeys(ids))


def _packet_path(shard_id: str) -> str:
    return f"{_PACKET_DIR}/{_safe_slug(shard_id)}_packet.json"


def _runbook_path(shard_id: str) -> str:
    return f"{_PACKET_DIR}/{_safe_slug(shard_id)}_runbook.md"


def _packet_payload(shard: Mapping[str, Any], *, release_id: Any, source_path: Path) -> Dict[str, Any]:
    shard_id = str(shard.get("shard_id", "unknown_shard"))
    units: list[Dict[str, Any]] = []
    for unit in shard.get("units", []) or []:
        if not isinstance(unit, Mapping):
            continue
        stage_ids = [str(stage_id) for stage_id in unit.get("stage_ids", []) or []]
        expected_files = _expected_evidence_files(unit)
        units.append(
            {
                "unit_id": str(unit.get("unit_id", "")),
                "candidate_id": str(unit.get("candidate_id", "")),
                **{
                    field: (
                        dict(unit.get(field, {}))
                        if isinstance(unit.get(field), Mapping)
                        else unit.get(field)
                    )
                    for field in _CANDIDATE_METADATA_FIELDS
                    if unit.get(field) not in (None, {}, [])
                },
                "kernel_id": str(unit.get("kernel_id", "")),
                "kernel_name": str(unit.get("kernel_name", unit.get("kernel_id", ""))),
                "kernel_family": str(unit.get("kernel_family", "")),
                "stage_ids": stage_ids,
                "work_item_ids": [str(item) for item in unit.get("work_item_ids", []) or []],
                "required_tools": [str(tool) for tool in unit.get("required_tools", []) or []],
                "unit_evidence_dir": _unit_evidence_dir(unit.get("candidate_id", ""), unit.get("kernel_id", "")),
                "candidate_bundle_json": (
                    "candidate_specific_bundles/"
                    f"{_safe_slug(unit.get('candidate_id', 'unknown_candidate'))}/"
                    f"{_safe_slug(unit.get('kernel_id', 'unknown_kernel'))}/candidate_bundle.json"
                ),
                "expected_evidence_files": expected_files,
                "expected_evidence_file_count": len(expected_files),
                "required_command_template_ids": _required_command_template_ids(stage_ids),
                "candidate_specific_bundle_required": True,
                "candidate_specific_bundle_present": False,
                "candidate_specific_evidence_present": False,
                "execution_status": _BLOCKED_STATUS,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )
    command_ids = sorted({command_id for unit in units for command_id in unit["required_command_template_ids"]})
    command_templates = [dict(template) for template in _COMMAND_TEMPLATES if template["template_id"] in command_ids]
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_PACKET_SCHEMA,
        "packet_id": f"{shard_id}_closure_packet",
        "shard_id": shard_id,
        "release_id": release_id,
        "status": _BLOCKED_STATUS,
        "blocking_condition": _BLOCKED_STATUS,
        "source_artifacts": {"hardware_closure_shards": _source_ref(source_path)},
        "candidate_ids": [str(item) for item in shard.get("candidate_ids", []) or []],
        "kernel_ids": [str(item) for item in shard.get("kernel_ids", []) or []],
        "required_tools": [str(item) for item in shard.get("required_tools", []) or []],
        "unit_count": len(units),
        "work_item_count": int(shard.get("work_item_count", 0) or 0),
        "blocked_work_item_count": int(shard.get("blocked_work_item_count", 0) or 0),
        "expected_evidence_file_count": sum(int(unit["expected_evidence_file_count"]) for unit in units),
        "command_template_ids": command_ids,
        "candidate_specific_bundle_count": 0,
        "candidate_specific_evidence_present_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "units": units,
        "command_templates": command_templates,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def _render_runbook(packet: Mapping[str, Any]) -> str:
    lines = [
        f"# DFT hardware closure runbook: {packet.get('shard_id')}",
        "",
        f"- Packet: `{packet.get('packet_id')}`",
        f"- Status: `{packet.get('status')}`",
        f"- Release: `{packet.get('release_id')}`",
        f"- Candidates: `{', '.join(str(item) for item in packet.get('candidate_ids', []) or [])}`",
        f"- Kernels: `{', '.join(str(item) for item in packet.get('kernel_ids', []) or [])}`",
        f"- Required tools: `{', '.join(str(item) for item in packet.get('required_tools', []) or [])}`",
        f"- Units/work-items: `{packet.get('unit_count')}` / `{packet.get('work_item_count')}`",
        "",
        "## Non-upgrade boundary",
        "",
        str(packet.get("claim_boundary", _CLAIM_BOUNDARY)),
        "",
        "Do not mark any row as passed until a candidate-specific bundle and raw tool outputs are attached for that exact candidate/kernel/stage.",
        "",
        "## Command templates",
        "",
    ]
    for template in packet.get("command_templates", []) or []:
        if not isinstance(template, Mapping):
            continue
        lines.extend(
            [
                f"### `{template.get('template_id')}`",
                "",
                f"- Tool: `{template.get('tool')}`",
                f"- Stages: `{', '.join(str(item) for item in template.get('stage_ids', []) or [])}`",
                "",
                "```bash",
                str(template.get("command", "")),
                "```",
            ]
        )
        if template.get("alternate_command"):
            lines.extend(["", "Alternate:", "", "```bash", str(template["alternate_command"]), "```"])
        lines.extend(["", f"Notes: {template.get('notes', '')}", ""])
    lines.extend(["## Unit evidence checklist", ""])
    for unit in packet.get("units", []) or []:
        if not isinstance(unit, Mapping):
            continue
        lines.extend(
            [
                f"### `{unit.get('unit_id')}`",
                "",
                f"- Candidate bundle: `{unit.get('candidate_bundle_json')}`",
                f"- Evidence dir: `{unit.get('unit_evidence_dir')}`",
                f"- Stage IDs: `{', '.join(str(item) for item in unit.get('stage_ids', []) or [])}`",
                f"- Command templates: `{', '.join(str(item) for item in unit.get('required_command_template_ids', []) or [])}`",
                "",
                "Expected files:",
            ]
        )
        for item in unit.get("expected_evidence_files", []) or []:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('stage_id')}`: `{item.get('path')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _packet_summaries(
    *,
    root_dir: Path,
    packets: Iterable[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for packet in packets:
        shard_id = str(packet.get("shard_id", "unknown_shard"))
        rows.append(
            {
                "packet_id": packet.get("packet_id"),
                "shard_id": shard_id,
                "status": packet.get("status"),
                "packet_json": _artifact_ref(root_dir, _packet_path(shard_id)),
                "runbook_md": _artifact_ref(root_dir, _runbook_path(shard_id)),
                "candidate_ids": list(packet.get("candidate_ids", []) or []),
                "kernel_ids": list(packet.get("kernel_ids", []) or []),
                "required_tools": list(packet.get("required_tools", []) or []),
                "unit_count": packet.get("unit_count"),
                "work_item_count": packet.get("work_item_count"),
                "expected_evidence_file_count": packet.get("expected_evidence_file_count"),
                "command_template_ids": list(packet.get("command_template_ids", []) or []),
                "candidate_specific_bundle_required": True,
                "candidate_specific_bundle_present": False,
                "candidate_specific_evidence_present": False,
                "hardware_completion_eligible": False,
                "deliverable_complete": False,
                "claim_boundary": _CLAIM_BOUNDARY,
            }
        )
    return rows


def build_dft_hardware_closure_packet_payloads(*, hardware_closure_shards_path: Path) -> list[Dict[str, Any]]:
    """Return per-shard closure packet payloads without writing files."""

    shards_payload = _load_json(hardware_closure_shards_path)
    packets: list[Dict[str, Any]] = []
    for shard in shards_payload.get("shards", []) or []:
        if isinstance(shard, Mapping):
            packets.append(
                _packet_payload(
                    shard,
                    release_id=shards_payload.get("release_id"),
                    source_path=Path(hardware_closure_shards_path),
                )
            )
    return packets


def validate_dft_hardware_closure_packet_index(
    payload_or_path: Mapping[str, Any] | Path,
    *,
    root_dir: Path | None = None,
) -> Dict[str, Any]:
    if isinstance(payload_or_path, Path):
        payload = _load_json(payload_or_path)
        root = root_dir or Path(payload_or_path).parent
    else:
        payload = dict(payload_or_path)
        root = root_dir
    errors: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_HARDWARE_CLOSURE_PACKETS_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected hardware closure packet-index schema"})
    packets = payload.get("packets", [])
    if not isinstance(packets, list) or not packets:
        errors.append({"field": "packets", "message": "non-empty packets required"})
        packets = []
    seen_packet_ids: set[str] = set()
    seen_shard_ids: set[str] = set()
    for packet_index, packet in enumerate(packets):
        if not isinstance(packet, Mapping):
            errors.append({"field": f"packets[{packet_index}]", "message": "packet summary must be an object"})
            continue
        packet_id = str(packet.get("packet_id", ""))
        shard_id = str(packet.get("shard_id", ""))
        if not packet_id:
            errors.append({"field": f"packets[{packet_index}].packet_id", "message": "packet_id required"})
        if packet_id in seen_packet_ids:
            errors.append({"field": f"packets[{packet_index}].packet_id", "message": "duplicate packet_id"})
        seen_packet_ids.add(packet_id)
        if not shard_id:
            errors.append({"field": f"packets[{packet_index}].shard_id", "message": "shard_id required"})
        if shard_id in seen_shard_ids:
            errors.append({"field": f"packets[{packet_index}].shard_id", "message": "duplicate shard_id"})
        seen_shard_ids.add(shard_id)
        if packet.get("status") != _BLOCKED_STATUS:
            errors.append({"field": f"packets[{packet_index}].status", "message": "packet must remain blocked"})
        for field in ("candidate_specific_bundle_present", "candidate_specific_evidence_present", "hardware_completion_eligible", "deliverable_complete"):
            if packet.get(field) is True:
                errors.append({"field": f"packets[{packet_index}].{field}", "message": "packet index cannot contain claim-upgrading evidence"})
        if not packet.get("command_template_ids"):
            errors.append({"field": f"packets[{packet_index}].command_template_ids", "message": "command template IDs required"})
        if not packet.get("expected_evidence_file_count"):
            errors.append({"field": f"packets[{packet_index}].expected_evidence_file_count", "message": "expected evidence file count required"})
        packet_payload: Dict[str, Any] = {}
        for ref_field in ("packet_json", "runbook_md"):
            ref = packet.get(ref_field, {})
            if not isinstance(ref, Mapping) or not ref.get("path"):
                errors.append({"field": f"packets[{packet_index}].{ref_field}", "message": "artifact ref with path required"})
                continue
            if root is not None:
                ref_path = root / str(ref.get("path"))
                if not ref_path.exists() or not ref_path.is_file():
                    errors.append({"field": f"packets[{packet_index}].{ref_field}", "message": "referenced packet artifact is missing"})
                elif ref.get("sha256") and sha256_file(ref_path) != ref.get("sha256"):
                    errors.append({"field": f"packets[{packet_index}].{ref_field}.sha256", "message": "referenced artifact hash mismatch"})
                elif ref_field == "packet_json":
                    packet_payload = _load_json(ref_path)
        if packet_payload:
            if packet_payload.get("schema_version") != DFT_HARDWARE_CLOSURE_PACKET_SCHEMA:
                errors.append({"field": f"packets[{packet_index}].packet_json.schema_version", "message": "unexpected packet schema"})
            for field in ("hardware_completion_eligible", "deliverable_complete"):
                if packet_payload.get(field) is True:
                    errors.append({"field": f"packets[{packet_index}].packet_json.{field}", "message": "referenced packet cannot upgrade claims"})
            if packet_payload.get("candidate_specific_bundle_count") not in (0, None):
                errors.append({"field": f"packets[{packet_index}].packet_json.candidate_specific_bundle_count", "message": "referenced packet cannot fabricate bundles"})
            if packet_payload.get("candidate_specific_evidence_present_count") not in (0, None):
                errors.append({"field": f"packets[{packet_index}].packet_json.candidate_specific_evidence_present_count", "message": "referenced packet cannot fabricate evidence"})
            units = packet_payload.get("units", [])
            if not isinstance(units, list) or not units:
                errors.append({"field": f"packets[{packet_index}].packet_json.units", "message": "referenced packet units required"})
                units = []
            for unit_index, unit in enumerate(units):
                if not isinstance(unit, Mapping):
                    errors.append({"field": f"packets[{packet_index}].packet_json.units[{unit_index}]", "message": "referenced packet unit must be an object"})
                    continue
                for field in ("candidate_specific_bundle_present", "candidate_specific_evidence_present", "hardware_completion_eligible", "deliverable_complete"):
                    if unit.get(field) is True:
                        errors.append({"field": f"packets[{packet_index}].packet_json.units[{unit_index}].{field}", "message": "referenced packet unit cannot upgrade claims"})
                for file_index, expected_file in enumerate(unit.get("expected_evidence_files", []) or []):
                    if isinstance(expected_file, Mapping) and expected_file.get("present") is True:
                        errors.append({"field": f"packets[{packet_index}].packet_json.units[{unit_index}].expected_evidence_files[{file_index}].present", "message": "packet expected-file rows must remain placeholders"})
    for field in ("hardware_completion_eligible", "deliverable_complete"):
        if payload.get(field) is True:
            errors.append({"field": field, "message": "packet index cannot be completion evidence"})
    if payload.get("candidate_specific_bundle_count") not in (0, None):
        errors.append({"field": "candidate_specific_bundle_count", "message": "packet index cannot fabricate candidate-specific bundles"})
    if payload.get("candidate_specific_evidence_present_count") not in (0, None):
        errors.append({"field": "candidate_specific_evidence_present_count", "message": "packet index cannot fabricate candidate-specific evidence"})
    return {
        "schema_version": DFT_HARDWARE_CLOSURE_PACKETS_VALIDATION_SCHEMA,
        "valid": not errors,
        "packet_count": len(packets),
        "errors": errors,
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def write_dft_hardware_closure_packets(
    out_dir: Path,
    *,
    hardware_closure_shards_path: Path,
) -> Dict[str, Any]:
    """Write packet JSON, runbook Markdown, index, validation, and status."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    packets = build_dft_hardware_closure_packet_payloads(
        hardware_closure_shards_path=hardware_closure_shards_path,
    )
    for packet in packets:
        shard_id = str(packet.get("shard_id", "unknown_shard"))
        write_json(out_dir / _packet_path(shard_id), packet)
        (out_dir / _runbook_path(shard_id)).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / _runbook_path(shard_id)).write_text(_render_runbook(packet), encoding="utf-8")

    shard_payload = _load_json(hardware_closure_shards_path)
    packet_summaries = _packet_summaries(root_dir=out_dir, packets=packets)
    index_payload = {
        "schema_version": DFT_HARDWARE_CLOSURE_PACKETS_SCHEMA,
        "status": "blocked_packetized_fail_closed" if packets else "failed_empty_shard_queue",
        "blocking_condition": _BLOCKED_STATUS,
        "source_artifacts": {"hardware_closure_shards": _source_ref(hardware_closure_shards_path)},
        "release_id": shard_payload.get("release_id"),
        "candidate_count": shard_payload.get("candidate_count"),
        "major_kernel_count": shard_payload.get("major_kernel_count"),
        "shard_count": shard_payload.get("shard_count"),
        "packet_count": len(packets),
        "unit_count": sum(int(packet.get("unit_count", 0) or 0) for packet in packets),
        "work_item_count": sum(int(packet.get("work_item_count", 0) or 0) for packet in packets),
        "blocked_work_item_count": sum(int(packet.get("blocked_work_item_count", 0) or 0) for packet in packets),
        "expected_evidence_file_count": sum(int(packet.get("expected_evidence_file_count", 0) or 0) for packet in packets),
        "candidate_specific_bundle_count": 0,
        "candidate_specific_evidence_present_count": 0,
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "packets": packet_summaries,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_packet_index.json", index_payload)
    validation = validate_dft_hardware_closure_packet_index(index_payload, root_dir=out_dir)
    write_json(out_dir / "dft_hardware_closure_packet_index_validation.json", validation)
    status = {
        "schema_version": "dse.dft.hardware_closure_packets_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "packet_index": "dft_hardware_closure_packet_index.json",
        "validation": "dft_hardware_closure_packet_index_validation.json",
        "packet_count": index_payload["packet_count"],
        "unit_count": index_payload["unit_count"],
        "work_item_count": index_payload["work_item_count"],
        "expected_evidence_file_count": index_payload["expected_evidence_file_count"],
        "hardware_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_hardware_closure_packet_index_status.json", status)
    return status


__all__ = [
    "DFT_HARDWARE_CLOSURE_PACKETS_SCHEMA",
    "DFT_HARDWARE_CLOSURE_PACKET_SCHEMA",
    "DFT_HARDWARE_CLOSURE_PACKETS_VALIDATION_SCHEMA",
    "build_dft_hardware_closure_packet_payloads",
    "validate_dft_hardware_closure_packet_index",
    "write_dft_hardware_closure_packets",
]
