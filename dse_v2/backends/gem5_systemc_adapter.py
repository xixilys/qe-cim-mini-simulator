#!/usr/bin/env python3
"""gem5+SystemC closure adapter for the generic DSE backend.

This module is intentionally conservative: it records the descriptor/request /
completion contract that an L4 gem5+SystemC run must satisfy, and it emits a
machine-checkable blocked/prototype verdict when that evidence is unavailable.
It does not claim L4 completion from MMIO smoke tests, fixed timing, or a
standalone SystemC run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from dse_v2.backends.generic_systemc_bridge import GenericSystemCBackend
from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.dse.orchestrator import DesignPoint

GSIM_MAGIC = 0x4753494D  # 'GSIM'
GSIM_DESCRIPTOR_VERSION = 1
GSIM_COMMAND_TYPE_GRAPH = 1
GSIM_COMPLETION_STATUS_BLOCKED = 2
GSIM_ERROR_DESCRIPTOR_UNVERIFIED = 0x1001
GSIM_ERROR_COMPLETION_UNVERIFIED = 0x1002
GSIM_ERROR_SYSTEMC_BINDING_UNVERIFIED = 0x1003


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


@dataclass(frozen=True)
class Gem5SystemCBlocker:
    """One missing evidence item that prevents L4 completion claims."""

    blocker_id: str
    detail: str
    required_evidence: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.blocker_id,
            "status": "blocked",
            "detail": self.detail,
            "required_evidence": self.required_evidence,
        }


DEFAULT_BLOCKERS = [
    Gem5SystemCBlocker(
        "gem5_descriptor_ingestion",
        "No verified read of a GSIM command descriptor and request payload from gem5 guest memory into GenericAccel/SystemC.",
        ["gem5.log descriptor_read", "descriptor address/size", "request payload checksum"],
    ),
    Gem5SystemCBlocker(
        "systemc_invocation_from_gem5",
        "No verified GenericAccel-to-SystemC timing invocation carrying the QE SCF shell request.",
        ["gem5.log systemc_submit", "simulation_request.json", "SystemC backend command/result path"],
    ),
    Gem5SystemCBlocker(
        "gem5_completion_result_writeback",
        "No verified completion descriptor and result JSON writeback visible to gem5 software side.",
        ["completion descriptor", "result address", "guest-visible status", "gem5.log completion_writeback"],
    ),
]


@dataclass
class Gem5SystemCClosureAdapter:
    """Build descriptor artifacts and blocked/prototype verdicts for L4 closure."""

    bridge: GenericSystemCBackend = field(default_factory=lambda: GenericSystemCBackend(mode="gem5_systemc_blocked"))

    def build_request(
        self,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
        output_dir: Path,
    ) -> Dict[str, Any]:
        request = self.bridge._build_request(design_point, compute_graph, output_dir=output_dir)
        request["mode"] = "gem5_systemc_blocked"
        request.setdefault("backend_contract", {})
        request["backend_contract"].update({
            "backend": "gem5_systemc",
            "required_descriptor_magic": "GSIM",
            "required_completion_visible_to_guest": True,
            "claim_boundary": "blocked/prototype until gem5 descriptor ingestion and completion/result writeback evidence exists",
        })
        return request

    def build_command_descriptor(
        self,
        *,
        request_path: Path,
        result_path: Path,
        workspace_size: int = 0,
    ) -> Dict[str, Any]:
        return {
            "schema_version": "gsim.gem5_command_descriptor.v1",
            "magic": GSIM_MAGIC,
            "magic_ascii": "GSIM",
            "version": GSIM_DESCRIPTOR_VERSION,
            "type": GSIM_COMMAND_TYPE_GRAPH,
            "type_name": "graph_request",
            "flags": {
                "requires_descriptor_dma": True,
                "requires_result_writeback": True,
                "requires_completion_mailbox": True,
            },
            "request": {
                "path": str(request_path),
                "guest_addr": None,
                "verified_in_gem5_log": False,
            },
            "result": {
                "path": str(result_path),
                "guest_addr": None,
                "verified_in_gem5_log": False,
            },
            "workspace": {
                "guest_addr": None,
                "size_bytes": workspace_size,
                "verified_in_gem5_log": False,
            },
        }

    def build_blocked_completion_descriptor(self, result_path: Path) -> Dict[str, Any]:
        return {
            "schema_version": "gsim.gem5_completion_descriptor.v1",
            "magic": GSIM_MAGIC,
            "magic_ascii": "GSIM",
            "status": GSIM_COMPLETION_STATUS_BLOCKED,
            "status_name": "blocked_unverified",
            "result": {
                "path": str(result_path),
                "guest_addr": None,
                "verified_in_gem5_log": False,
            },
            "cycles": 0,
            "error_code": GSIM_ERROR_COMPLETION_UNVERIFIED,
            "error_name": "completion_writeback_not_verified",
        }

    def emit_blocked_verdict(
        self,
        *,
        design_point: DesignPoint,
        compute_graph: ComputeGraph,
        output_dir: Path,
        blockers: Optional[Iterable[Gem5SystemCBlocker]] = None,
        cli_command: Optional[List[str]] = None,
        gem5_log_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Write blocked/prototype L4 artifacts and return the verdict payload."""
        output_dir.mkdir(parents=True, exist_ok=True)
        request_path = output_dir / "simulation_request.json"
        result_path = output_dir / "simulation_result.json"
        descriptor_path = output_dir / "gem5_command_descriptor.json"
        completion_path = output_dir / "gem5_completion_descriptor.json"
        gem5_log_path = output_dir / "gem5.log"

        request = self.build_request(design_point, compute_graph, output_dir)
        descriptor = self.build_command_descriptor(request_path=request_path, result_path=result_path)
        completion = self.build_blocked_completion_descriptor(result_path=result_path)
        blocker_payload = [blocker.to_dict() for blocker in (list(blockers) if blockers is not None else DEFAULT_BLOCKERS)]

        result = {
            "schema_version": "gsim.result.v1",
            "run_id": design_point.design_point_id,
            "status": "blocked",
            "error_message": "gem5+SystemC descriptor/request/completion path is not verified; L4 completion is not claimed.",
            "metrics": {
                "latency_ms": 0.0,
                "host_time_ms": 0.0,
                "device_time_ms": 0.0,
                "dma_time_ms": 0.0,
                "throughput_gops": 0.0,
                "power_w": 0.0,
                "energy_j": 0.0,
                "area_mm2": 0.0,
                "total_data_movement_mb": 0.0,
            },
            "resource_utilization": {},
            "events": [],
            "uncertainty": {"fidelity_level": "L4", "confidence_level": 0.0, "mape_percent": 100.0},
            "gem5_systemc_blockers": blocker_payload,
        }

        if gem5_log_text is None:
            gem5_log_text = "\n".join([
                "GSIM_L4_STATUS blocked_prototype",
                "descriptor_read verified=false",
                "systemc_submit verified=false",
                "completion_writeback verified=false",
                "claim_boundary no_l4_complete_claim_without_descriptor_and_completion_evidence",
                "",
            ])

        verdict = {
            "schema_version": "dse.gem5_systemc_closure_verdict.v1",
            "run_id": design_point.design_point_id,
            "created_at": _now_iso(),
            "backend": "gem5_systemc",
            "closure_status": "blocked_prototype",
            "trusted_for_final_ranking": False,
            "l4_complete": False,
            "prototype_only": True,
            "descriptor_evidence_present": False,
            "completion_evidence_present": False,
            "gem5_log": "gem5.log",
            "artifacts": {
                "simulation_request": "simulation_request.json",
                "simulation_result": "simulation_result.json",
                "gem5_command_descriptor": "gem5_command_descriptor.json",
                "gem5_completion_descriptor": "gem5_completion_descriptor.json",
                "gem5_log": "gem5.log",
            },
            "blockers": blocker_payload,
            "forbidden_claims": [
                "L4 gem5+SystemC complete",
                "guest-visible completion verified",
                "descriptor DMA path implemented",
                "SystemC invoked from gem5 GenericAccel",
            ],
            "next_step_checklist": [
                "Implement GenericAccel descriptor DMA read from guest memory.",
                "Bind descriptor request payload to the generic SystemC backend invocation.",
                "Write result JSON and completion descriptor back to guest-visible memory.",
                "Emit gem5.log lines proving descriptor_read/systemc_submit/completion_writeback before allowing L4 claims.",
            ],
            "cli_command": cli_command or [],
        }

        _write_json(request_path, request)
        _write_json(descriptor_path, descriptor)
        _write_json(completion_path, completion)
        _write_json(result_path, result)
        _write_json(output_dir / "verdict.json", verdict)
        _write_text(gem5_log_path, gem5_log_text)
        _write_json(output_dir / "artifact_manifest.json", {
            "schema_version": "dse.gem5_systemc_artifact_manifest.v1",
            "run_id": design_point.design_point_id,
            "artifacts": [
                {"path": rel, "exists": (output_dir / rel).exists()}
                for rel in verdict["artifacts"].values()
            ] + [{"path": "verdict.json", "exists": True}],
        })
        return verdict


__all__ = [
    "DEFAULT_BLOCKERS",
    "GSIM_COMMAND_TYPE_GRAPH",
    "GSIM_COMPLETION_STATUS_BLOCKED",
    "GSIM_DESCRIPTOR_VERSION",
    "GSIM_MAGIC",
    "Gem5SystemCBlocker",
    "Gem5SystemCClosureAdapter",
]
