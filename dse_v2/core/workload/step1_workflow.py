#!/usr/bin/env python3
"""Persisted Step1 workload-ingestion workflow boundary.

Step1 is the first replayable handoff in the Generic DSE flow.  It resolves a
profile/importer pair, imports a domain-neutral :class:`WorkloadPackage`, lowers
the package graph into an executable view, and writes all handoff artifacts to
disk before Step2 is allowed to consume the workload.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from dse_v2.core.ir.compute_graph import ComputeGraph
from dse_v2.core.workload.characterization import (
    WORKLOAD_CHARACTERIZATION_SCHEMA,
    characterize_workload,
)
from dse_v2.core.workload.importers import ImporterRegistry, default_importer_registry
from dse_v2.core.workload.lowering import GraphLoweringResult, lower_compute_graph
from dse_v2.core.workload.package import WorkloadPackage
from dse_v2.core.workload.profiles import ProfileRegistry, WorkloadProfile, default_profile_registry


STEP1_INGESTION_REQUEST_SCHEMA = "dse.step1.ingestion_request.v1"
STEP1_STATUS_SCHEMA = "dse.step1.status.v1"
STEP1_WORKLOAD_PACKAGE_SCHEMA = "dse.step1.workload_package.v1"
STEP1_PROFILE_MANIFEST_SCHEMA = "dse.step1.profile_manifest.v1"
STEP1_IMPORTER_MANIFEST_SCHEMA = "dse.step1.importer_manifest.v1"
STEP1_ARTIFACT_VALIDATION_SCHEMA = "dse.step1.artifact_validation.v1"
STEP1_ARTIFACT_VERIFICATION_SCHEMA = "dse.step1.artifact_verification.v1"

SUPPORTED_PROFILE_SCHEMA = "dse.workload_profile.v1"
SUPPORTED_IMPORTER_VERSION = "v1"

STEP1_ARTIFACT_FILES = {
    "ingestion_request": "ingestion_request.json",
    "step1_status": "step1_status.json",
    "workload_package": "workload_package.json",
    "workload_graph": "workload_graph.json",
    "workload_characterization": "workload_characterization.json",
    "graph_lowering_report": "graph_lowering_report.json",
    "executable_graph": "executable_graph.json",
    "profile_manifest": "profile_manifest.json",
    "importer_manifest": "importer_manifest.json",
    "step1_artifact_validation": "step1_artifact_validation.json",
}

STEP1_EXPECTED_SCHEMAS = {
    "ingestion_request": STEP1_INGESTION_REQUEST_SCHEMA,
    "step1_status": STEP1_STATUS_SCHEMA,
    "workload_package": STEP1_WORKLOAD_PACKAGE_SCHEMA,
    "workload_graph": "dse.compute_graph.v1",
    "workload_characterization": WORKLOAD_CHARACTERIZATION_SCHEMA,
    "graph_lowering_report": "dse.graph_lowering_report.v1",
    "executable_graph": "dse.compute_graph.v1",
    "profile_manifest": STEP1_PROFILE_MANIFEST_SCHEMA,
    "importer_manifest": STEP1_IMPORTER_MANIFEST_SCHEMA,
    "step1_artifact_validation": STEP1_ARTIFACT_VALIDATION_SCHEMA,
}


class Step1HandoffError(RuntimeError):
    """Raised when a persisted Step1 directory is not a valid Step2 handoff."""


@dataclass
class Step1WorkflowResult:
    """In-memory summary for a complete or blocked Step1 workflow."""

    status: str
    output_dir: Path
    workload_package: Optional[WorkloadPackage] = None
    source_graph: Optional[ComputeGraph] = None
    lowering: Optional[GraphLoweringResult] = None
    executable_graph: Optional[ComputeGraph] = None
    ingestion_request: Dict[str, Any] = field(default_factory=dict)
    workload_characterization: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    artifact_paths: Dict[str, str] = field(default_factory=dict)
    reasons: list[Dict[str, Any]] = field(default_factory=list)

    @property
    def full_workload_eligible(self) -> bool:
        if self.lowering is None or self.workload_package is None:
            return False
        return bool(self.lowering.report.get("full_workload_eligible", False)) and self.workload_package.is_full_workload()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "output_dir": str(self.output_dir),
            "workload_id": self.workload_package.workload_id if self.workload_package else None,
            "workload_family": self.workload_package.workload_family if self.workload_package else None,
            "source_graph_id": self.source_graph.graph_id if self.source_graph else None,
            "executable_graph_id": self.executable_graph.graph_id if self.executable_graph else None,
            "full_workload_eligible": self.full_workload_eligible,
            "artifact_paths": dict(self.artifact_paths),
            "reasons": list(self.reasons),
        }


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(payload)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _environment_summary() -> Dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def _source_kind(source: Any, parameters: Mapping[str, Any]) -> str:
    if parameters.get("source_kind"):
        return str(parameters["source_kind"])
    if isinstance(source, WorkloadPackage):
        return str(source.source.get("kind", "hand_authored"))
    if isinstance(source, Mapping):
        return str(source.get("source_kind", source.get("source", {}).get("kind", "generic_json")) if isinstance(source.get("source", {}), Mapping) else source.get("source_kind", "generic_json"))
    if isinstance(source, ComputeGraph):
        return "hand_authored"
    return "unknown"


def _source_payload_kind(source: Any) -> str:
    if isinstance(source, WorkloadPackage):
        return "workload_package"
    if isinstance(source, ComputeGraph):
        return "compute_graph"
    if isinstance(source, Mapping):
        if source.get("schema_version") == STEP1_INGESTION_REQUEST_SCHEMA:
            return "step1_ingestion_request"
        if "graph" in source:
            return "dict_with_graph"
        return "dict"
    if source is None:
        return "none"
    return type(source).__name__


def _status_reason(reason_id: str, detail: str, **extra: Any) -> Dict[str, Any]:
    payload = {"reason_id": reason_id, "detail": detail}
    payload.update(extra)
    return payload


def _ingestion_request_payload(
    *,
    source: Any,
    profile_id: str,
    importer_id: str,
    source_kind: str,
    parameters: Mapping[str, Any],
    source_path: Optional[str],
    profile_version: str = "unknown",
    importer_version: str = "unknown",
    timestamp: Optional[str] = None,
    framework_version: str = "generic-dse-prototype",
    environment_summary: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the normalized Step1 request artifact without embedding source IR."""
    return {
        "schema_version": STEP1_INGESTION_REQUEST_SCHEMA,
        "source": {
            "source_kind": source_kind,
            "source_path": source_path,
            "payload_kind": _source_payload_kind(source),
        },
        "profile": {
            "profile_id": profile_id,
            "profile_version": profile_version,
        },
        "importer": {
            "importer_id": importer_id,
            "importer_version": importer_version,
        },
        "parameters": dict(parameters),
        "provenance": {
            "timestamp": timestamp or _utc_timestamp(),
            "framework_version": framework_version,
            "environment_summary": dict(environment_summary or _environment_summary()),
        },
    }


def _profile_manifest(registry: ProfileRegistry, selected_profile_id: Optional[str]) -> Dict[str, Any]:
    registry_payload = registry.to_dict()
    return {
        "schema_version": STEP1_PROFILE_MANIFEST_SCHEMA,
        "requested_profile_id": selected_profile_id,
        "profiles": registry_payload.get("profiles", []),
        "aliases": registry_payload.get("aliases", {}),
        "registry": registry_payload,
    }


def _importer_manifest(registry: ImporterRegistry, selected_importer_id: Optional[str]) -> Dict[str, Any]:
    registry_payload = registry.to_dict()
    return {
        "schema_version": STEP1_IMPORTER_MANIFEST_SCHEMA,
        "requested_importer_id": selected_importer_id,
        "importers": registry_payload.get("importers", []),
        "registry": registry_payload,
    }


def _workload_package_payload(package: WorkloadPackage) -> Dict[str, Any]:
    payload = package.to_dict()
    payload["schema_version"] = STEP1_WORKLOAD_PACKAGE_SCHEMA
    return payload


def _version_errors(profile: WorkloadProfile, importer_version: str) -> list[Dict[str, Any]]:
    errors: list[Dict[str, Any]] = []
    profile_payload = profile.to_dict()
    if profile_payload.get("schema_version") != SUPPORTED_PROFILE_SCHEMA:
        errors.append(_status_reason(
            "importer_or_profile_version_incompatible",
            "profile schema version is not supported",
            expected=SUPPORTED_PROFILE_SCHEMA,
            actual=profile_payload.get("schema_version"),
        ))
    if profile.profile_version != "v1":
        errors.append(_status_reason(
            "importer_or_profile_version_incompatible",
            "profile version is not supported",
            expected="v1",
            actual=profile.profile_version,
        ))
    if importer_version != SUPPORTED_IMPORTER_VERSION:
        errors.append(_status_reason(
            "importer_or_profile_version_incompatible",
            "importer version is not supported",
            expected=SUPPORTED_IMPORTER_VERSION,
            actual=importer_version,
        ))
    return errors


def _artifact_entry(path: Path, key: str) -> Dict[str, Any]:
    expected_schema = STEP1_EXPECTED_SCHEMAS.get(key)
    entry: Dict[str, Any] = {
        "artifact": key,
        "file": path.name,
        "present": path.exists(),
        "expected_schema_version": expected_schema,
    }
    if key == "step1_artifact_validation":
        if path.exists():
            entry["bytes"] = path.stat().st_size
            try:
                payload = _read_json(path)
                entry["json_valid"] = True
                entry["schema_version"] = payload.get("schema_version")
                entry["schema_valid"] = expected_schema is None or payload.get("schema_version") == expected_schema
            except Exception as exc:
                entry["json_valid"] = False
                entry["error"] = str(exc)
        else:
            entry["pending_write"] = True
        entry["checksum_policy"] = "self_checksum_omitted"
        return entry
    if not path.exists():
        return entry
    entry["bytes"] = path.stat().st_size
    entry["sha256"] = _sha256(path)
    try:
        payload = _read_json(path)
    except Exception as exc:
        entry["json_valid"] = False
        entry["error"] = str(exc)
        return entry
    actual_schema = payload.get("schema_version")
    entry["json_valid"] = True
    entry["schema_version"] = actual_schema
    entry["schema_valid"] = expected_schema is None or actual_schema == expected_schema
    return entry


def _validate_artifact_payload(output_dir: Path, artifact_paths: Mapping[str, str]) -> Dict[str, Any]:
    errors: list[Dict[str, Any]] = []
    warnings: list[Dict[str, Any]] = []
    entries: Dict[str, Dict[str, Any]] = {}
    for key, filename in sorted(artifact_paths.items()):
        path = Path(output_dir) / filename
        entry = _artifact_entry(path, key)
        entries[key] = entry
        if not entry.get("present", False):
            if key == "step1_artifact_validation" and entry.get("pending_write"):
                continue
            errors.append({"artifact": key, "message": f"missing artifact {filename}"})
            continue
        if entry.get("json_valid") is False:
            errors.append({"artifact": key, "message": f"artifact is not valid JSON: {entry.get('error')}"})
        if entry.get("schema_valid") is False:
            errors.append({
                "artifact": key,
                "message": "schema_version mismatch",
                "expected": entry.get("expected_schema_version"),
                "actual": entry.get("schema_version"),
            })
    if "step1_artifact_validation" in entries:
        warnings.append({
            "artifact": "step1_artifact_validation",
            "message": "self checksum is intentionally omitted to avoid recursive checksum mutation",
        })
    return {
        "schema_version": STEP1_ARTIFACT_VALIDATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_artifacts": sorted(artifact_paths),
        "artifacts": entries,
    }


def _build_status_payload(
    *,
    status: str,
    profile_id: str,
    profile_version: str = "unknown",
    importer_id: str,
    importer_version: str = "unknown",
    source_kind: str,
    artifact_paths: Mapping[str, str],
    reasons: list[Dict[str, Any]],
    package: Optional[WorkloadPackage] = None,
    lowering: Optional[GraphLoweringResult] = None,
    validation: Optional[Mapping[str, Any]] = None,
    source_path: Optional[str] = None,
    timestamp: Optional[str] = None,
    framework_version: str = "generic-dse-prototype",
    environment_summary: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    full_workload_eligible = bool(lowering and lowering.report.get("full_workload_eligible", False) and package and package.is_full_workload())
    return {
        "schema_version": STEP1_STATUS_SCHEMA,
        "status": status,
        "workload_id": package.workload_id if package else None,
        "workload_family": package.workload_family if package else None,
        "profile_id": package.profile_id if package else profile_id,
        "profile_version": package.profile_version if package else profile_version,
        "importer_id": package.importer_id if package else importer_id,
        "importer_version": package.importer_version if package else importer_version,
        "source_kind": source_kind,
        "claim_boundary": package.claim_boundary if package else None,
        "full_workload_eligible": full_workload_eligible,
        "provenance": {
            "profile_id": package.profile_id if package else profile_id,
            "profile_version": package.profile_version if package else profile_version,
            "importer_id": package.importer_id if package else importer_id,
            "importer_version": package.importer_version if package else importer_version,
            "source_path": source_path,
            "timestamp": timestamp or _utc_timestamp(),
            "framework_version": framework_version,
            "environment_summary": dict(environment_summary or _environment_summary()),
        },
        "artifacts": dict(artifact_paths),
        "validation": dict(validation or {"valid": not reasons, "errors": reasons, "warnings": []}),
        "reasons": list(reasons),
    }


def _finalize_step1(
    *,
    output_dir: Path,
    status: str,
    profile_id: str,
    profile_version: str = "unknown",
    importer_id: str,
    importer_version: str = "unknown",
    source_kind: str,
    artifact_payloads: Mapping[str, Mapping[str, Any]],
    reasons: list[Dict[str, Any]],
    package: Optional[WorkloadPackage],
    lowering: Optional[GraphLoweringResult],
    validation: Optional[Mapping[str, Any]],
    source_path: Optional[str],
    timestamp: Optional[str],
    framework_version: str,
    environment_summary: Optional[Mapping[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    output_dir = Path(output_dir)
    artifact_paths: Dict[str, str] = {}
    for key, payload in artifact_payloads.items():
        filename = STEP1_ARTIFACT_FILES[key]
        _atomic_write_json(output_dir / filename, payload)
        artifact_paths[key] = filename

    artifact_paths["step1_status"] = STEP1_ARTIFACT_FILES["step1_status"]
    artifact_paths["step1_artifact_validation"] = STEP1_ARTIFACT_FILES["step1_artifact_validation"]
    status_payload = _build_status_payload(
        status=status,
        profile_id=profile_id,
        profile_version=profile_version,
        importer_id=importer_id,
        importer_version=importer_version,
        source_kind=source_kind,
        artifact_paths=artifact_paths,
        reasons=reasons,
        package=package,
        lowering=lowering,
        validation=validation,
        source_path=source_path,
        timestamp=timestamp,
        framework_version=framework_version,
        environment_summary=environment_summary,
    )
    _atomic_write_json(output_dir / STEP1_ARTIFACT_FILES["step1_status"], status_payload)

    artifact_validation = _validate_artifact_payload(output_dir, artifact_paths)
    _atomic_write_json(output_dir / STEP1_ARTIFACT_FILES["step1_artifact_validation"], artifact_validation)
    artifact_validation = _validate_artifact_payload(output_dir, artifact_paths)
    _atomic_write_json(output_dir / STEP1_ARTIFACT_FILES["step1_artifact_validation"], artifact_validation)
    return status_payload, artifact_paths, artifact_validation


def run_step1_workload_ingestion_workflow(
    source: Any,
    *,
    profile_id: str,
    importer_id: str = "generic_json",
    output_dir: Path,
    parameters: Optional[Mapping[str, Any]] = None,
    source_kind: Optional[str] = None,
    profile_registry: Optional[ProfileRegistry] = None,
    importer_registry: Optional[ImporterRegistry] = None,
    source_path: Optional[str] = None,
    timestamp: Optional[str] = None,
    framework_version: str = "generic-dse-prototype",
    environment_summary: Optional[Mapping[str, Any]] = None,
) -> Step1WorkflowResult:
    """Run Step1 ingestion and persist the complete handoff directory.

    The function never hands Step2 a live importer object.  Success is represented
    by `status == "complete"` plus a valid `step1_artifact_validation.json`.
    Blocked outcomes still write status and registry manifests so callers can
    diagnose the failed profile/importer boundary.
    """

    output_dir = Path(output_dir)
    parameters_payload = dict(parameters or {})
    if source_kind is not None:
        parameters_payload["source_kind"] = source_kind
    resolved_source_kind = _source_kind(source, parameters_payload)
    profiles = profile_registry or default_profile_registry()
    importers = importer_registry or default_importer_registry()

    ingestion_request = _ingestion_request_payload(
        source=source,
        profile_id=profile_id,
        importer_id=importer_id,
        source_kind=resolved_source_kind,
        parameters=parameters_payload,
        source_path=source_path,
        timestamp=timestamp,
        framework_version=framework_version,
        environment_summary=environment_summary,
    )
    base_artifacts: Dict[str, Mapping[str, Any]] = {
        "ingestion_request": ingestion_request,
        "profile_manifest": _profile_manifest(profiles, profile_id),
        "importer_manifest": _importer_manifest(importers, importer_id),
    }

    reasons: list[Dict[str, Any]] = []
    try:
        profile = profiles.get(profile_id)
        importer = importers.get(importer_id)
    except KeyError as exc:
        reasons.append(_status_reason(
            "unknown_importer_or_profile",
            str(exc),
            available_profiles=sorted(profiles.profiles),
            available_importers=sorted(importers.importers),
        ))
        status_payload, artifact_paths, artifact_validation = _finalize_step1(
            output_dir=output_dir,
            status="blocked_unknown_importer_or_profile",
            profile_id=profile_id,
            importer_id=importer_id,
            source_kind=resolved_source_kind,
            artifact_payloads=base_artifacts,
            reasons=reasons,
            package=None,
            lowering=None,
            validation={"valid": False, "errors": reasons, "warnings": []},
            source_path=source_path,
            timestamp=timestamp,
            framework_version=framework_version,
            environment_summary=environment_summary,
        )
        return Step1WorkflowResult(
            status="blocked_unknown_importer_or_profile",
            output_dir=output_dir,
            ingestion_request=ingestion_request,
            artifacts={
                "step1_status": status_payload,
                "ingestion_request": base_artifacts["ingestion_request"],
                "profile_manifest": base_artifacts["profile_manifest"],
                "importer_manifest": base_artifacts["importer_manifest"],
                "step1_artifact_validation": artifact_validation,
            },
            artifact_paths=artifact_paths,
            reasons=reasons,
        )

    ingestion_request = _ingestion_request_payload(
        source=source,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        importer_id=importer.importer_id,
        importer_version=importer.importer_version,
        source_kind=resolved_source_kind,
        parameters=parameters_payload,
        source_path=source_path,
        timestamp=timestamp,
        framework_version=framework_version,
        environment_summary=environment_summary,
    )
    base_artifacts["ingestion_request"] = ingestion_request

    reasons.extend(_version_errors(profile, importer.importer_version))
    if resolved_source_kind not in importer.supported_source_kinds:
        reasons.append(_status_reason(
            "unsupported_source_kind",
            "importer does not support source_kind",
            source_kind=resolved_source_kind,
            supported_source_kinds=list(importer.supported_source_kinds),
        ))
    if profile.profile_id not in importer.compatible_profiles and profile.workload_family not in importer.compatible_profiles:
        reasons.append(_status_reason(
            "incompatible_profile_importer",
            "importer is not declared compatible with profile",
            profile_id=profile.profile_id,
            importer_id=importer.importer_id,
            compatible_profiles=list(importer.compatible_profiles),
        ))
    if reasons:
        status_payload, artifact_paths, artifact_validation = _finalize_step1(
            output_dir=output_dir,
            status="blocked_invalid_importer_input",
            profile_id=profile_id,
            profile_version=profile.profile_version,
            importer_id=importer_id,
            importer_version=importer.importer_version,
            source_kind=resolved_source_kind,
            artifact_payloads=base_artifacts,
            reasons=reasons,
            package=None,
            lowering=None,
            validation={"valid": False, "errors": reasons, "warnings": []},
            source_path=source_path,
            timestamp=timestamp,
            framework_version=framework_version,
            environment_summary=environment_summary,
        )
        return Step1WorkflowResult(
            status="blocked_invalid_importer_input",
            output_dir=output_dir,
            ingestion_request=ingestion_request,
            artifacts={
                "step1_status": status_payload,
                "ingestion_request": base_artifacts["ingestion_request"],
                "profile_manifest": base_artifacts["profile_manifest"],
                "importer_manifest": base_artifacts["importer_manifest"],
                "step1_artifact_validation": artifact_validation,
            },
            artifact_paths=artifact_paths,
            reasons=reasons,
        )

    try:
        package = importer.import_workload(source, profile=profile, parameters=parameters_payload)
    except Exception as exc:
        reasons.append(_status_reason("importer_exception", "importer failed to emit WorkloadPackage", error=str(exc)))
        status_payload, artifact_paths, artifact_validation = _finalize_step1(
            output_dir=output_dir,
            status="blocked_invalid_importer_input",
            profile_id=profile_id,
            profile_version=profile.profile_version,
            importer_id=importer_id,
            importer_version=importer.importer_version,
            source_kind=resolved_source_kind,
            artifact_payloads=base_artifacts,
            reasons=reasons,
            package=None,
            lowering=None,
            validation={"valid": False, "errors": reasons, "warnings": []},
            source_path=source_path,
            timestamp=timestamp,
            framework_version=framework_version,
            environment_summary=environment_summary,
        )
        return Step1WorkflowResult(
            status="blocked_invalid_importer_input",
            output_dir=output_dir,
            ingestion_request=ingestion_request,
            artifacts={
                "step1_status": status_payload,
                "ingestion_request": base_artifacts["ingestion_request"],
                "profile_manifest": base_artifacts["profile_manifest"],
                "importer_manifest": base_artifacts["importer_manifest"],
                "step1_artifact_validation": artifact_validation,
            },
            artifact_paths=artifact_paths,
            reasons=reasons,
        )

    validation = package.validate()
    artifact_payloads: Dict[str, Mapping[str, Any]] = {
        **base_artifacts,
        "workload_package": _workload_package_payload(package),
        "workload_graph": package.graph.to_dict(),
    }
    if not validation.get("valid", False):
        reasons.append(_status_reason("invalid_workload_package", "WorkloadPackage validation failed", validation=validation))
        status_payload, artifact_paths, artifact_validation = _finalize_step1(
            output_dir=output_dir,
            status="blocked_invalid_importer_input",
            profile_id=profile_id,
            importer_id=importer_id,
            source_kind=resolved_source_kind,
            artifact_payloads=artifact_payloads,
            reasons=reasons,
            package=package,
            lowering=None,
            validation=validation,
            source_path=source_path,
            timestamp=timestamp,
            framework_version=framework_version,
            environment_summary=environment_summary,
        )
        artifacts = {**artifact_payloads, "step1_status": status_payload, "step1_artifact_validation": artifact_validation}
        return Step1WorkflowResult(
            status="blocked_invalid_importer_input",
            output_dir=output_dir,
            ingestion_request=ingestion_request,
            workload_package=package,
            source_graph=package.graph,
            artifacts=artifacts,
            artifact_paths=artifact_paths,
            reasons=reasons,
        )

    lowering = lower_compute_graph(package.graph, package)
    artifact_payloads["graph_lowering_report"] = lowering.report
    characterization = characterize_workload(package, lowering=lowering)
    artifact_payloads["workload_characterization"] = characterization
    status = "complete"
    executable_graph = lowering.executable_graph
    if lowering.report.get("status") == "unsupported" or executable_graph is None:
        status = "blocked_unsupported_graph"
        reasons.append(_status_reason(
            "unsupported_graph",
            "graph lowering is unsupported or lacks executable_graph",
            lowering_status=lowering.report.get("status"),
            unsupported_constructs=lowering.report.get("unsupported_constructs", []),
            errors=lowering.report.get("errors", []),
        ))
    else:
        artifact_payloads["executable_graph"] = executable_graph.to_dict()

    status_payload, artifact_paths, artifact_validation = _finalize_step1(
        output_dir=output_dir,
        status=status,
        profile_id=profile_id,
        importer_id=importer_id,
        source_kind=resolved_source_kind,
        artifact_payloads=artifact_payloads,
        reasons=reasons,
        package=package,
        lowering=lowering,
        validation=validation,
        source_path=source_path,
        timestamp=timestamp,
        framework_version=framework_version,
        environment_summary=environment_summary,
    )
    artifacts = {**artifact_payloads, "step1_status": status_payload, "step1_artifact_validation": artifact_validation}
    return Step1WorkflowResult(
        status=status,
        output_dir=output_dir,
        ingestion_request=ingestion_request,
        workload_characterization=characterization,
        workload_package=package,
        source_graph=package.graph,
        lowering=lowering,
        executable_graph=executable_graph if status == "complete" else None,
        artifacts=artifacts,
        artifact_paths=artifact_paths,
        reasons=reasons,
    )


def run_step1_ingestion_request_workflow(
    ingestion_request: Mapping[str, Any],
    *,
    output_dir: Path,
    profile_registry: Optional[ProfileRegistry] = None,
    importer_registry: Optional[ImporterRegistry] = None,
    timestamp: Optional[str] = None,
    framework_version: str = "generic-dse-prototype",
    environment_summary: Optional[Mapping[str, Any]] = None,
) -> Step1WorkflowResult:
    """Run Step1 from the normalized ingestion request envelope.

    The request is a generic envelope.  Domain-specific parameters remain inside
    the ``parameters`` block consumed by the selected profile/importer pair.
    """
    request = dict(ingestion_request)
    profile_block = dict(request.get("profile", {}) or {})
    importer_block = dict(request.get("importer", {}) or {})
    source_block = dict(request.get("source", {}) or {})
    parameters = dict(request.get("parameters", request.get("domain_payload", {})) or {})
    profile_id = str(profile_block.get("profile_id", request.get("profile_id", "")))
    importer_id = str(importer_block.get("importer_id", request.get("importer_id", "generic_json")))
    source_kind = str(source_block.get("source_kind", source_block.get("kind", parameters.get("source_kind", "generated"))))
    source_path = source_block.get("source_path", source_block.get("path"))
    if source_kind:
        parameters["source_kind"] = source_kind
    if source_path:
        parameters["source_path"] = str(source_path)

    source: Any = source_block.get("payload", source_block.get("source_payload"))
    if source is None and isinstance(source_block.get("graph"), Mapping):
        source = {"graph": source_block["graph"]}
    provenance = dict(request.get("provenance", {}) or {}) if isinstance(request.get("provenance", {}), Mapping) else {}

    return run_step1_workload_ingestion_workflow(
        source,
        profile_id=profile_id,
        importer_id=importer_id,
        source_kind=source_kind,
        parameters=parameters,
        output_dir=output_dir,
        profile_registry=profile_registry,
        importer_registry=importer_registry,
        source_path=str(source_path) if source_path else None,
        timestamp=timestamp or provenance.get("timestamp"),
        framework_version=framework_version,
        environment_summary=environment_summary,
    )


def verify_step1_artifact_validation(step1_dir: Path) -> Dict[str, Any]:
    """Verify a persisted Step1 validation file against current artifact bytes."""
    step1_dir = Path(step1_dir)
    validation_path = step1_dir / STEP1_ARTIFACT_FILES["step1_artifact_validation"]
    errors: list[Dict[str, Any]] = []
    warnings: list[Dict[str, Any]] = []
    if not validation_path.exists():
        return {
            "schema_version": STEP1_ARTIFACT_VERIFICATION_SCHEMA,
            "valid": False,
            "errors": [{"artifact": "step1_artifact_validation", "message": "missing step1_artifact_validation.json"}],
            "warnings": warnings,
        }
    try:
        validation = _read_json(validation_path)
    except Exception as exc:
        return {
            "schema_version": STEP1_ARTIFACT_VERIFICATION_SCHEMA,
            "valid": False,
            "errors": [{"artifact": "step1_artifact_validation", "message": f"invalid JSON: {exc}"}],
            "warnings": warnings,
        }
    if validation.get("schema_version") != STEP1_ARTIFACT_VALIDATION_SCHEMA:
        errors.append({
            "artifact": "step1_artifact_validation",
            "message": "schema_version mismatch",
            "expected": STEP1_ARTIFACT_VALIDATION_SCHEMA,
            "actual": validation.get("schema_version"),
        })
    if not validation.get("valid", False):
        errors.extend(validation.get("errors", []))
    for key, entry in dict(validation.get("artifacts", {}) or {}).items():
        filename = entry.get("file")
        if not filename:
            errors.append({"artifact": key, "message": "validation entry has no file"})
            continue
        path = step1_dir / str(filename)
        if not path.exists():
            errors.append({"artifact": key, "message": f"missing artifact {filename}"})
            continue
        expected_hash = entry.get("sha256")
        if expected_hash and _sha256(path) != expected_hash:
            errors.append({"artifact": key, "message": "checksum mismatch", "file": filename})
    return {
        "schema_version": STEP1_ARTIFACT_VERIFICATION_SCHEMA,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_artifacts": sorted(dict(validation.get("artifacts", {}) or {})),
    }


def load_step1_handoff(step1_dir: Path) -> Dict[str, Any]:
    """Load a complete Step1 handoff directory after checksum validation."""
    step1_dir = Path(step1_dir)
    verification = verify_step1_artifact_validation(step1_dir)
    if not verification.get("valid", False):
        raise Step1HandoffError(f"invalid Step1 handoff: {verification.get('errors', [])}")
    status = _read_json(step1_dir / STEP1_ARTIFACT_FILES["step1_status"])
    if status.get("status") != "complete":
        raise Step1HandoffError(f"Step1 handoff is not complete: {status.get('status')}")
    package_payload = _read_json(step1_dir / STEP1_ARTIFACT_FILES["workload_package"])
    graph_payload = _read_json(step1_dir / STEP1_ARTIFACT_FILES["workload_graph"])
    lowering_report = _read_json(step1_dir / STEP1_ARTIFACT_FILES["graph_lowering_report"])
    executable_payload = _read_json(step1_dir / STEP1_ARTIFACT_FILES["executable_graph"])
    handoff = {
        "status": status,
        "workload_package": WorkloadPackage.from_dict(package_payload),
        "workload_graph": ComputeGraph.from_dict(graph_payload),
        "graph_lowering_report": lowering_report,
        "executable_graph": ComputeGraph.from_dict(executable_payload),
        "artifact_verification": verification,
    }
    ingestion_request_path = step1_dir / STEP1_ARTIFACT_FILES["ingestion_request"]
    if ingestion_request_path.exists():
        handoff["ingestion_request"] = _read_json(ingestion_request_path)
    characterization_path = step1_dir / STEP1_ARTIFACT_FILES["workload_characterization"]
    if characterization_path.exists():
        handoff["workload_characterization"] = _read_json(characterization_path)
    return handoff


def load_step1_workload_package(step1_dir: Path) -> WorkloadPackage:
    """Return the persisted Step1 WorkloadPackage for Step2 consumption."""
    return load_step1_handoff(step1_dir)["workload_package"]
