from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields
import json
from pathlib import Path
from typing import Any, Mapping


BACKEND_EXECUTION_REQUEST_SCHEMA_VERSION = "backend_execution_request_v0"
BACKEND_EXECUTION_REPORT_SCHEMA_VERSION = "backend_execution_report_v0"

REPORT_EXECUTION_STATUSES = {"executed", "partial", "failed", "refused"}

MODE_TO_REQUESTED_FIDELITY = {
    "systemc_standalone": "B1",
    "systemc_timed_functional": "B2",
    "gem5_systemc_smoke": "B3",
    "gem5_systemc_timed_proxy": "B4",
}

MODE_TO_CLAIM_CEILING = {
    "systemc_standalone": "systemc_standalone_proxy_only",
    "systemc_timed_functional": "systemc_timed_functional_proxy_only",
    "gem5_systemc_smoke": "gem5_systemc_smoke_only",
    "gem5_systemc_timed_proxy": "gem5_systemc_timed_proxy_only",
}

MODE_TO_BACKEND_CLASS = {
    "systemc_standalone": "systemc_standalone_proxy",
    "systemc_timed_functional": "systemc_timed_functional_proxy",
    "gem5_systemc_smoke": "gem5_systemc_smoke",
    "gem5_systemc_timed_proxy": "gem5_systemc_timed_proxy",
}

MODE_TO_SOURCE_KIND = {
    "systemc_standalone": "backend_runner_systemc",
    "systemc_timed_functional": "backend_runner_systemc",
    "gem5_systemc_smoke": "backend_runner_gem5_systemc",
    "gem5_systemc_timed_proxy": "backend_runner_gem5_systemc",
}

VALIDITY_CLASS_EXECUTABLE = "valid_executable"
VALIDITY_CLASS_DEBUG_ONLY = "debug_only"
VALIDITY_CLASS_PROJECTION_ONLY = "projection_only"
VALIDITY_CLASS_INVALID = "invalid"
VALIDITY_CLASSES = {
    VALIDITY_CLASS_EXECUTABLE,
    VALIDITY_CLASS_DEBUG_ONLY,
    VALIDITY_CLASS_PROJECTION_ONLY,
    VALIDITY_CLASS_INVALID,
}

REQUEST_OPTIONAL_MAPPING_KEYS = (
    "backend_capability_profile",
    "systemc_config",
    "host_control_flow",
    "workload_trace",
    "metrics_contract",
)

MODE_TO_CAPABILITY_FLAGS = {
    "systemc_standalone": ("supports_systemc_standalone",),
    "systemc_timed_functional": (
        "supports_systemc_timed_functional",
        "supports_systemc_timed",
    ),
    "gem5_systemc_smoke": ("supports_gem5_smoke",),
    "gem5_systemc_timed_proxy": (
        "supports_gem5_timed_proxy",
        "supports_real_bridge",
    ),
}

REQUEST_CORE_KEYS = (
    "schema_version",
    "candidate_id",
    "requested_fidelity",
    "execution_mode",
    "workload_identity",
    "candidate_identity",
    "input_refs",
    "software_runtime",
    "domain_extension",
    "expected_report_schema",
)

REPORT_CORE_KEYS = (
    "schema_version",
    "candidate_id",
    "execution_status",
    "fidelity",
    "claim_ceiling",
    "backend_class",
    "source_kind",
    "environment",
    "control_path",
    "metrics",
    "correctness_gate",
    "artifact_refs",
    "non_claims",
)

_DOMAIN_NEUTRAL_TOP_LEVEL_KEYS = {"qe", "qe_case", "qe_case_id", "qe_workload"}
_FORBIDDEN_CLAIM_TOKENS = (
    "board",
    "rtl",
    "hls",
    "asic",
    "cycle_accurate",
    "cycle-accurate",
)
_EQUIVALENCE_CLAIM_KEYS = {
    "qe_equivalence_status",
    "qe_equivalent_scf_claim",
    "qe_equivalence_claim",
    "workload_equivalent_claim",
    "workload_equivalence_claim",
    "domain_equivalence_claim",
}
_FORBIDDEN_EQUIVALENCE_CLAIM_TOKENS = (
    "qe_equivalence",
    "qe-equivalence",
    "qe equivalence",
    "qe_equivalent",
    "qe-equivalent",
    "qe equivalent",
    "workload_equivalence",
    "workload-equivalence",
    "workload equivalence",
    "workload_equivalent",
    "workload-equivalent",
    "workload equivalent",
    "domain_equivalence",
    "domain-equivalence",
    "domain equivalence",
    "domain_equivalent",
    "domain-equivalent",
    "domain equivalent",
)
_IDENTIFIER_OR_REFERENCE_EXACT_KEYS = {
    "schema_version",
    "observability_contract_id",
    "accounting_boundary_id",
    "power_boundary_id",
}
_REFUSAL_OR_ERROR_CONTEXT_KEYS = {
    "refusal_reason",
    "status_reason",
    "error",
    "errors",
    "validation_error",
    "validation_errors",
}


def _copy_required(payload: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"backend execution payload missing field: {missing[0]}")
    return {key: deepcopy(payload[key]) for key in keys}


def _require_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"backend execution field must be a mapping: {key}")
    return value


def _require_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"backend execution field must be a list: {key}")
    return value


def _reject_top_level_domain_specific_fields(payload: Mapping[str, Any]) -> None:
    for key in payload:
        lowered = str(key).lower()
        if lowered in _DOMAIN_NEUTRAL_TOP_LEVEL_KEYS or lowered.startswith("qe_"):
            raise ValueError("QE-specific fields must be nested under domain_extension.qe")


def _validate_domain_extension(payload: Mapping[str, Any]) -> None:
    extension = _require_mapping(payload, "domain_extension")
    for key, value in extension.items():
        if not isinstance(value, Mapping):
            raise ValueError(f"domain_extension.{key} must be a mapping")


def _validate_candidate_identity(payload: Mapping[str, Any]) -> None:
    candidate_identity = _require_mapping(payload, "candidate_identity")
    validity = candidate_identity.get("validity_class")
    if validity is not None and validity not in VALIDITY_CLASSES:
        raise ValueError("candidate_identity.validity_class is not recognized")
    design_axes = candidate_identity.get("design_axes")
    if design_axes is not None and not isinstance(design_axes, Mapping):
        raise ValueError("candidate_identity.design_axes must be a mapping")


def _validate_backend_capability_profile(payload: Mapping[str, Any]) -> None:
    profile = payload.get("backend_capability_profile")
    if profile is None:
        return
    if not isinstance(profile, Mapping):
        raise ValueError("backend_capability_profile must be a mapping")
    execution_mode = payload.get("execution_mode")
    flags = MODE_TO_CAPABILITY_FLAGS.get(str(execution_mode), ())
    present_flags = [flag for flag in flags if flag in profile]
    if not present_flags:
        return
    if not any(profile.get(flag) is True for flag in present_flags):
        raise ValueError(
            f"backend_capability_profile does not support execution_mode {execution_mode}"
        )


def _validate_backend_capability_profile_for_execution(payload: Mapping[str, Any]) -> None:
    profile = payload.get("backend_capability_profile")
    if not isinstance(profile, Mapping):
        raise ValueError("backend_capability_profile is required for backend execution")
    execution_mode = str(payload.get("execution_mode"))
    flags = MODE_TO_CAPABILITY_FLAGS.get(execution_mode, ())
    if not flags:
        raise ValueError(f"unsupported execution_mode: {execution_mode}")
    if not any(profile.get(flag) is True for flag in flags):
        raise ValueError(
            f"backend_capability_profile does not support execution_mode {execution_mode}"
        )


def _validate_metrics_contract_for_execution(payload: Mapping[str, Any]) -> None:
    metrics_contract = payload.get("metrics_contract")
    if not isinstance(metrics_contract, Mapping):
        raise ValueError("metrics_contract is required for backend execution")
    required_groups = metrics_contract.get("required_groups")
    if required_groups is not None and not isinstance(required_groups, list):
        raise ValueError("metrics_contract.required_groups must be a list")


def _validate_optional_request_mappings(payload: Mapping[str, Any]) -> None:
    for key in REQUEST_OPTIONAL_MAPPING_KEYS:
        value = payload.get(key)
        if value is not None and not isinstance(value, Mapping):
            raise ValueError(f"{key} must be a mapping")
    _validate_backend_capability_profile(payload)


def _validate_qe_extension_when_required(payload: Mapping[str, Any]) -> None:
    workload_identity = payload.get("workload_identity")
    if not isinstance(workload_identity, Mapping):
        return
    if workload_identity.get("domain") == "dft" and workload_identity.get("adapter") == "qe":
        extension = _require_mapping(payload, "domain_extension")
        if not isinstance(extension.get("qe"), Mapping):
            raise ValueError("QE backend requests require domain_extension.qe")


def _validate_request_mode(payload: Mapping[str, Any]) -> None:
    execution_mode = payload.get("execution_mode")
    if execution_mode not in MODE_TO_REQUESTED_FIDELITY:
        raise ValueError(f"unsupported execution_mode: {execution_mode}")
    requested_fidelity = payload.get("requested_fidelity")
    expected = MODE_TO_REQUESTED_FIDELITY[str(execution_mode)]
    if requested_fidelity != expected:
        raise ValueError(
            f"requested_fidelity {requested_fidelity} does not match "
            f"execution_mode {execution_mode} ({expected})"
        )


def _validate_report_mode(payload: Mapping[str, Any]) -> None:
    fidelity = payload.get("fidelity")
    if fidelity not in MODE_TO_CLAIM_CEILING:
        raise ValueError(f"unsupported report fidelity: {fidelity}")
    expected = MODE_TO_CLAIM_CEILING[str(fidelity)]
    if payload.get("claim_ceiling") != expected:
        raise ValueError(f"claim_ceiling must be {expected} for {fidelity}")
    expected_backend_class = MODE_TO_BACKEND_CLASS[str(fidelity)]
    if payload.get("backend_class") != expected_backend_class:
        raise ValueError(f"backend_class must be {expected_backend_class} for {fidelity}")
    expected_source_kind = MODE_TO_SOURCE_KIND[str(fidelity)]
    if payload.get("source_kind") != expected_source_kind:
        raise ValueError(f"source_kind must be {expected_source_kind} for {fidelity}")


def _validate_expected_report_schema(payload: Mapping[str, Any]) -> None:
    expected = payload.get("expected_report_schema")
    if expected != BACKEND_EXECUTION_REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"expected_report_schema must be {BACKEND_EXECUTION_REPORT_SCHEMA_VERSION}"
        )


def _iter_json_items(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    items = [(path, value)]
    if isinstance(value, Mapping):
        for key, child in value.items():
            items.extend(_iter_json_items(child, path + (str(key),)))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            items.extend(_iter_json_items(child, path + (str(index),)))
    return items


def _is_explicit_non_claim_text(text: str) -> bool:
    normalized = text.strip().lower().replace("-", "_")
    return normalized.startswith("no_") or normalized.startswith("not_")


def _is_negated_or_unclaimed_text(text: str) -> bool:
    normalized = text.strip().lower().replace("-", "_")
    if normalized.startswith("no_") or normalized.startswith("not_"):
        return True
    return any(
        marker in text
        for marker in (
            "not ",
            "no ",
            "without ",
            "unclaimed",
            "not_claimed",
            "non-claim",
            "non_claim",
        )
    )


def _is_identifier_or_reference_key(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in _IDENTIFIER_OR_REFERENCE_EXACT_KEYS
        or lowered.endswith("_id")
        or lowered.endswith("_ids")
        or lowered.endswith("_ref")
        or lowered.endswith("_refs")
    )


def _is_identifier_or_reference_path(path: tuple[str, ...]) -> bool:
    return bool(path) and _is_identifier_or_reference_key(path[-1])


def _is_refusal_or_error_context_path(path: tuple[str, ...]) -> bool:
    return bool(path) and path[-1].lower() in _REFUSAL_OR_ERROR_CONTEXT_KEYS


def _reject_hidden_equivalence_claims(payload: Mapping[str, Any]) -> None:
    for path, value in _iter_json_items(payload):
        if not path:
            continue
        key = path[-1].lower()
        if key in _EQUIVALENCE_CLAIM_KEYS and value is not False:
            if isinstance(value, str) and _is_negated_or_unclaimed_text(value.lower()):
                continue
            dotted = ".".join(path)
            raise ValueError(f"{dotted} must be false or absent in backend execution artifacts")
        if isinstance(value, str):
            lowered = value.lower()
            if any(token in lowered for token in _FORBIDDEN_EQUIVALENCE_CLAIM_TOKENS):
                if not _is_negated_or_unclaimed_text(lowered):
                    dotted = ".".join(path)
                    raise ValueError(f"{dotted} must not claim QE/workload/domain equivalence")


def _reject_forbidden_claim_text(payload: Mapping[str, Any]) -> None:
    allow_error_context = payload.get("execution_status") in {"refused", "failed", "partial"}
    for path, value in _iter_json_items(payload):
        identifier_or_reference_path = _is_identifier_or_reference_path(path)
        if path:
            key = path[-1].lower()
            if (
                not identifier_or_reference_path
                and any(token in key for token in _FORBIDDEN_CLAIM_TOKENS)
            ):
                if not _is_explicit_non_claim_text(key):
                    raise ValueError(
                        "backend execution artifacts must not claim "
                        "board/RTL/HLS/ASIC/cycle-accurate evidence"
                    )
        if not isinstance(value, str):
            continue
        if identifier_or_reference_path or (
            allow_error_context and _is_refusal_or_error_context_path(path)
        ):
            continue
        text = value
        lowered = text.lower()
        if any(token in lowered for token in _FORBIDDEN_CLAIM_TOKENS):
            # Non-claim phrases are allowed to mention forbidden implementation classes.
            if _is_explicit_non_claim_text(lowered):
                continue
            raise ValueError(
                "backend execution artifacts must not claim "
                "board/RTL/HLS/ASIC/cycle-accurate evidence"
            )


def _validate_correctness_gate(payload: Mapping[str, Any]) -> None:
    correctness_gate = _require_mapping(payload, "correctness_gate")
    if correctness_gate.get("workload_equivalent_claim") is not False:
        raise ValueError("correctness_gate.workload_equivalent_claim must be false")
    if correctness_gate.get("domain_equivalence_claim") is not False:
        raise ValueError("correctness_gate.domain_equivalence_claim must be false")


def _validate_report_non_claims(payload: Mapping[str, Any]) -> None:
    non_claims = _require_list(payload, "non_claims")
    if not any("qe_equivalent" in str(value) for value in non_claims):
        raise ValueError("backend report must include QE-equivalence non-claim")
    if not any("rtl_hls_board" in str(value) or "rtl" in str(value) for value in non_claims):
        raise ValueError("backend report must include implementation non-claim")


def validate_backend_execution_request(payload: Mapping[str, Any]) -> None:
    _copy_required(payload, REQUEST_CORE_KEYS)
    if payload["schema_version"] != BACKEND_EXECUTION_REQUEST_SCHEMA_VERSION:
        raise ValueError("unsupported backend execution request schema_version")
    _reject_top_level_domain_specific_fields(payload)
    _validate_domain_extension(payload)
    _validate_qe_extension_when_required(payload)
    _validate_candidate_identity(payload)
    _validate_optional_request_mappings(payload)
    _validate_request_mode(payload)
    _validate_expected_report_schema(payload)
    for key in ("workload_identity", "candidate_identity", "input_refs", "software_runtime"):
        _require_mapping(payload, key)
    _reject_hidden_equivalence_claims(payload)
    _reject_forbidden_claim_text(payload)


def validate_backend_execution_report(payload: Mapping[str, Any]) -> None:
    _copy_required(payload, REPORT_CORE_KEYS)
    if payload["schema_version"] != BACKEND_EXECUTION_REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported backend execution report schema_version")
    _reject_top_level_domain_specific_fields(payload)
    _validate_report_mode(payload)
    status = payload.get("execution_status")
    if status not in REPORT_EXECUTION_STATUSES:
        raise ValueError(
            "backend report execution_status must be executed, partial, failed, or refused"
        )
    for key in ("environment", "control_path", "metrics", "artifact_refs"):
        _require_mapping(payload, key)
    _validate_correctness_gate(payload)
    _validate_report_non_claims(payload)
    _reject_hidden_equivalence_claims(payload)
    _reject_forbidden_claim_text(payload)


def request_candidate_validity_class(payload: Mapping[str, Any]) -> str | None:
    candidate_identity = payload.get("candidate_identity")
    if not isinstance(candidate_identity, Mapping):
        return None
    validity = candidate_identity.get("validity_class")
    return validity if isinstance(validity, str) else None


def request_is_executable_candidate(payload: Mapping[str, Any]) -> bool:
    return request_candidate_validity_class(payload) == VALIDITY_CLASS_EXECUTABLE


def validate_backend_execution_request_for_execution(payload: Mapping[str, Any]) -> None:
    validate_backend_execution_request(payload)
    if not request_is_executable_candidate(payload):
        raise ValueError(
            "backend execution requires candidate_identity.validity_class=valid_executable"
        )
    _validate_backend_capability_profile_for_execution(payload)
    _validate_metrics_contract_for_execution(payload)


@dataclass(frozen=True)
class BackendExecutionRequest:
    schema_version: str
    candidate_id: str
    requested_fidelity: str
    execution_mode: str
    workload_identity: dict[str, Any]
    candidate_identity: dict[str, Any]
    input_refs: dict[str, Any]
    software_runtime: dict[str, Any]
    domain_extension: dict[str, Any]
    expected_report_schema: str
    extra_fields: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BackendExecutionRequest":
        validate_backend_execution_request(payload)
        extra_fields = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key not in REQUEST_CORE_KEYS
        }
        return cls(
            **_copy_required(payload, REQUEST_CORE_KEYS),
            extra_fields=extra_fields or None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            field.name: deepcopy(getattr(self, field.name))
            for field in fields(self)
            if field.name != "extra_fields"
        }
        if self.extra_fields is not None:
            payload.update(deepcopy(self.extra_fields))
        return payload


@dataclass(frozen=True)
class BackendExecutionReport:
    schema_version: str
    candidate_id: str
    execution_status: str
    fidelity: str
    claim_ceiling: str
    backend_class: str
    source_kind: str
    environment: dict[str, Any]
    control_path: dict[str, Any]
    metrics: dict[str, Any]
    correctness_gate: dict[str, Any]
    artifact_refs: dict[str, Any]
    non_claims: list[Any]
    extra_fields: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BackendExecutionReport":
        validate_backend_execution_report(payload)
        extra_fields = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key not in REPORT_CORE_KEYS
        }
        return cls(
            **_copy_required(payload, REPORT_CORE_KEYS),
            extra_fields=extra_fields or None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            field.name: deepcopy(getattr(self, field.name))
            for field in fields(self)
            if field.name != "extra_fields"
        }
        if self.extra_fields is not None:
            payload.update(deepcopy(self.extra_fields))
        return payload


def load_backend_execution_request(path: Path | str) -> BackendExecutionRequest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BackendExecutionRequest.from_dict(payload)


def load_backend_execution_report(path: Path | str) -> BackendExecutionReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BackendExecutionReport.from_dict(payload)
