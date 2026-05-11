from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .interfaces import DESIGN_POINT_IDENTITY_KEYS


VALIDITY_CLASSES = ("valid_executable", "projection_only", "invalid")
EXECUTABLE_FAMILIES = {"F1", "F2", "F3"}
PROJECTION_ONLY_FAMILIES = {"F4", "F5", "custom"}
KNOWN_FAMILIES = EXECUTABLE_FAMILIES | PROJECTION_ONLY_FAMILIES
DEFAULT_AXIS_VALUES: dict[str, set[str]] = {
    "family": KNOWN_FAMILIES,
    "diag_policy": {"cpu_only", "device_first_fallback", "aggressive_device"},
    "offload_scope": {"single_hotpath", "balanced", "device_heavy"},
    "resident_policy": {"fit_first", "spill_tolerant"},
    "partition_strategy": {
        "single_hotpath_partition",
        "operator_build_fused__diag__refresh",
        "operator__build__diag__refresh",
        "operator__build_diag_fused__refresh",
        "operator_build_fused__diag_refresh_fused",
    },
}


@dataclass(frozen=True)
class ValidationResult:
    validity_class: str
    claim_ceiling: str
    missing_evidence: list[str]
    promotion_blockers: list[str]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "design_point_validation_v0",
            "validity_class": self.validity_class,
            "claim_ceiling": self.claim_ceiling,
            "missing_evidence": list(self.missing_evidence),
            "promotion_blockers": list(self.promotion_blockers),
            "reasons": list(self.reasons),
        }


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    return {}


def _capability_flag(backend_capability: Mapping[str, Any] | None, key: str) -> bool:
    if backend_capability is None:
        return False
    return bool(backend_capability.get(key))


def _axis_values(
    design_space_spec: Any | None = None,
    allowed_axes: Mapping[str, Sequence[Any]] | None = None,
) -> dict[str, set[str]]:
    if allowed_axes is not None:
        return {key: {str(item) for item in value} for key, value in allowed_axes.items()}
    spec_axes = getattr(design_space_spec, "design_axes", None)
    if isinstance(spec_axes, Mapping):
        return {key: {str(item) for item in value} for key, value in spec_axes.items()}
    return {key: set(value) for key, value in DEFAULT_AXIS_VALUES.items()}


class DesignPointValidator:
    def validate(
        self,
        design_point: Any,
        workload: Any | None = None,
        backend_capability: Mapping[str, Any] | None = None,
        design_space_spec: Any | None = None,
        allowed_axes: Mapping[str, Sequence[Any]] | None = None,
    ) -> ValidationResult:
        point = _payload(design_point)
        missing_axes = [key for key in DESIGN_POINT_IDENTITY_KEYS if not point.get(key)]
        if missing_axes:
            return ValidationResult(
                validity_class="invalid",
                claim_ceiling="descriptor_only",
                missing_evidence=[],
                promotion_blockers=["invalid_design_axes"],
                reasons=[f"missing_design_axis:{key}" for key in missing_axes],
            )

        axis_values = _axis_values(design_space_spec=design_space_spec, allowed_axes=allowed_axes)
        invalid_axes = [
            (key, str(point[key]))
            for key in DESIGN_POINT_IDENTITY_KEYS
            if str(point[key]) not in axis_values.get(key, set())
        ]
        if invalid_axes:
            return ValidationResult(
                validity_class="invalid",
                claim_ceiling="descriptor_only",
                missing_evidence=[],
                promotion_blockers=["invalid_design_axes"],
                reasons=[
                    (
                        f"unknown_family:{value}"
                        if key == "family"
                        else f"unknown_design_axis_value:{key}:{value}"
                    )
                    for key, value in invalid_axes
                ],
            )

        family = str(point["family"])
        if family in PROJECTION_ONLY_FAMILIES:
            return ValidationResult(
                validity_class="projection_only",
                claim_ceiling="descriptor_only",
                missing_evidence=["backend_executor_for_projection_family"],
                promotion_blockers=["projection_family_not_backend_executable"],
                reasons=[f"projection_only_family:{family}"],
            )

        if (
            point.get("diag_policy") == "aggressive_device"
            and not _capability_flag(backend_capability, "device_diag_engine")
        ):
            return ValidationResult(
                validity_class="invalid",
                claim_ceiling="descriptor_only",
                missing_evidence=["device_diag_engine"],
                promotion_blockers=["device_diag_engine_missing"],
                reasons=["aggressive_device_requires_device_diag_engine"],
            )

        missing_evidence = []
        if point.get("resident_policy") == "fit_first":
            missing_evidence.append("resident_capacity_evidence")
        if point.get("offload_scope") == "device_heavy":
            missing_evidence.append("host_device_link_bandwidth_evidence")
        if point.get("partition_strategy") == "single_hotpath_partition" and point.get("offload_scope") == "device_heavy":
            missing_evidence.append("partition_dependency_evidence")
        if not _capability_flag(backend_capability, "target_resource_model"):
            missing_evidence.append("target_resource_model")
        target_class = None
        if backend_capability is not None:
            target_class = backend_capability.get("target_class")
        if target_class in {"asic", "fpga"} and not _capability_flag(backend_capability, "target_resource_model"):
            missing_evidence.append(f"{target_class}_resource_model")

        return ValidationResult(
            validity_class="valid_executable",
            claim_ceiling="descriptor_only",
            missing_evidence=missing_evidence,
            promotion_blockers=[],
            reasons=["valid_executable_stage_a_descriptor"],
        )


def validate_design_point(
    design_point: Any,
    workload: Any | None = None,
    backend_capability: Mapping[str, Any] | None = None,
    design_space_spec: Any | None = None,
    allowed_axes: Mapping[str, Sequence[Any]] | None = None,
) -> dict[str, Any]:
    return DesignPointValidator().validate(
        design_point=design_point,
        workload=workload,
        backend_capability=backend_capability,
        design_space_spec=design_space_spec,
        allowed_axes=allowed_axes,
    ).to_dict()
