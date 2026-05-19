#!/usr/bin/env python3
"""Run one explicit QE h_psi component kernel against captured target arrays.

This runner is intentionally component-scoped.  It can compute the kinetic
``g2kin * psi`` term from captured QE inputs and compare it to the component
target arrays.  ``vloc`` can also audit whether QE exported the real inputs
needed for a future dual-space local-potential recompute.  ``vloc`` and ``vnl``
remain blocked until their algorithms are implemented; target arrays are never
replayed as if they were computation.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_hpsi_sidecar import (  # noqa: E402
    compute_hpsi_vnl_delta_component,
    load_hpsi_boundary_arrays,
)


COMPONENT_RESULT_SCHEMA = "dse.qe_hpsi_component_kernel_result.v1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _complex_pair(value: Any) -> complex:
    if not isinstance(value, Sequence) or len(value) < 2:
        return 0.0 + 0.0j
    return complex(_float(value[0]), _float(value[1]))


def _pairs(values: Any) -> list[complex]:
    return [_complex_pair(item) for item in values] if isinstance(values, list) else []


def _l2(values: Sequence[complex]) -> float:
    return math.sqrt(sum(abs(value) ** 2 for value in values))


def _max_abs(values: Sequence[complex]) -> float:
    return max((abs(value) for value in values), default=0.0)


def _compare(
    computed: Sequence[complex],
    target: Sequence[complex],
    *,
    relative_tolerance: float = 1.0e-12,
    absolute_tolerance: float = 1.0e-12,
) -> Dict[str, Any]:
    if len(computed) != len(target):
        return {
            "status": "blocked",
            "absolute_error": None,
            "relative_error": None,
            "max_abs_error": None,
            "blockers": [f"length_mismatch:{len(computed)}:{len(target)}"],
        }
    errors = [left - right for left, right in zip(computed, target)]
    abs_error = _l2(errors)
    target_l2 = _l2(target)
    rel_error = abs_error / max(target_l2, 1.0e-300)
    passed = abs_error <= absolute_tolerance or rel_error <= relative_tolerance
    return {
        "status": "passed" if passed else "failed",
        "absolute_error": abs_error,
        "relative_error": rel_error,
        "max_abs_error": _max_abs(errors),
        "blockers": [] if passed else [f"component_numeric_mismatch:{rel_error:.6e}:{relative_tolerance:.6e}"],
    }


def _compute_kinetic(arrays: Mapping[str, Any]) -> tuple[list[complex], list[str]]:
    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 1)
    n = _int(dimensions.get("n"), lda)
    m = _int(dimensions.get("m"), 1)
    npol = _int(arrays.get("npol"), 1)
    row_count = lda * max(1, npol)
    element_count = row_count * m
    psi = _pairs(arrays.get("psi_real_imag", []))
    g2kin = [_float(item) for item in arrays.get("g2kin", [])] if isinstance(arrays.get("g2kin", []), list) else []
    blockers: list[str] = []
    if len(psi) != element_count:
        blockers.append(f"psi_array_length_mismatch:{len(psi)}:{element_count}")
    if len(g2kin) < lda:
        blockers.append(f"g2kin_array_length_mismatch:{len(g2kin)}:{lda}")
    if blockers:
        return [], blockers
    computed: list[complex] = []
    for flat_index, value in enumerate(psi):
        row_index = flat_index % row_count
        g_index = row_index % lda
        computed.append(g2kin[g_index] * value if g_index < n else 0.0 + 0.0j)
    return computed, []


def _vloc_input_contract(arrays: Mapping[str, Any]) -> Dict[str, Any]:
    algorithm = arrays.get("vloc_algorithm", {})
    fft_descriptor = arrays.get("fft_descriptor_dffts", {})
    inputs = arrays.get("vloc_inputs", {})
    blockers: list[str] = []
    if not isinstance(algorithm, Mapping):
        blockers.append("missing_vloc_algorithm_metadata")
        algorithm = {}
    if not isinstance(fft_descriptor, Mapping):
        blockers.append("missing_fft_descriptor_dffts")
        fft_descriptor = {}
    if not isinstance(inputs, Mapping):
        blockers.append("missing_vloc_inputs")
        inputs = {}

    path = str(algorithm.get("path") or "")
    if not path:
        blockers.append("missing_vloc_algorithm_path")
    if algorithm.get("real_space") is True:
        blockers.append("vloc_real_space_combined_vloc_vnl_path_not_separable")
    if algorithm.get("has_task_groups") is True:
        blockers.append("vloc_task_group_path_not_supported_by_component_runner")
    if algorithm.get("noncolin") is True:
        blockers.append("vloc_noncollinear_path_not_supported_by_component_runner")

    vrs = inputs.get("vrs_current_spin", [])
    if not isinstance(vrs, list):
        blockers.append("vrs_current_spin_not_array")
        vrs = []
    nnr = _int(fft_descriptor.get("nnr"), 0)
    if nnr <= 0:
        blockers.append("fft_descriptor_missing_positive_nnr")
    elif len(vrs) != nnr:
        blockers.append(f"vrs_current_spin_length_mismatch:{len(vrs)}:{nnr}")

    igk = inputs.get("igk_current_k", [])
    dffts_nl = inputs.get("dffts_nl", [])
    gamma_only = algorithm.get("gamma_only") is True
    if not gamma_only:
        dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
        n = _int(dimensions.get("n"), 0)
        if not isinstance(igk, list):
            blockers.append("igk_current_k_not_array_for_k_path")
        elif n > 0 and len(igk) < n:
            blockers.append(f"igk_current_k_length_mismatch:{len(igk)}:{n}")
        if not isinstance(dffts_nl, list):
            blockers.append("dffts_nl_not_array_for_k_path")
        elif dffts_nl and igk and max((_int(item) for item in igk), default=0) > len(dffts_nl):
            blockers.append(
                f"igk_current_k_refs_missing_dffts_nl:{max((_int(item) for item in igk), default=0)}:{len(dffts_nl)}"
            )

    return {
        "status": "passed" if not blockers else "blocked",
        "algorithm_path": path or None,
        "fft_descriptor_summary": {
            "nr": fft_descriptor.get("nr"),
            "nrx": fft_descriptor.get("nrx"),
            "nnr": fft_descriptor.get("nnr"),
            "ngw": fft_descriptor.get("ngw"),
            "ngm": fft_descriptor.get("ngm"),
            "lpara": fft_descriptor.get("lpara"),
            "lgamma": fft_descriptor.get("lgamma"),
        },
        "vrs_element_count": len(vrs),
        "igk_element_count": len(igk) if isinstance(igk, list) else None,
        "dffts_nl_element_count": len(dffts_nl) if isinstance(dffts_nl, list) else None,
        "blockers": blockers,
        "claim_boundary": (
            "This only proves the vloc input contract was captured. It does not recompute "
            "the FFT-based V_loc*psi delta and must not be trusted as full h_psi evidence."
        ),
    }


def _fft_shape_from_descriptor(fft_descriptor: Mapping[str, Any], nnr: int) -> tuple[int, int, int] | None:
    for key in ("nrx", "nr"):
        raw = fft_descriptor.get(key)
        if not isinstance(raw, list) or len(raw) != 3:
            continue
        shape = tuple(_int(item, 0) for item in raw)
        if all(item > 0 for item in shape) and shape[0] * shape[1] * shape[2] == nnr:
            return shape  # type: ignore[return-value]
    return None


def _compute_vloc_delta(arrays: Mapping[str, Any]) -> tuple[list[complex], list[str], Dict[str, Any]]:
    input_contract = _vloc_input_contract(arrays)
    blockers = [str(item) for item in input_contract.get("blockers", []) or []]
    algorithm_path = str(input_contract.get("algorithm_path") or "")
    if algorithm_path != "vloc_psi_k_acc":
        blockers.append(f"vloc_algorithm_path_not_implemented:{algorithm_path or 'missing'}")
    if blockers:
        return [], sorted(dict.fromkeys(blockers)), input_contract

    try:
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-dependent optional acceleration path
        return [], [f"numpy_unavailable_for_vloc_fft:{exc}"], input_contract

    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 0)
    n = _int(dimensions.get("n"), 0)
    m = _int(dimensions.get("m"), 0)
    fft_descriptor = arrays.get("fft_descriptor_dffts", {})
    inputs = arrays.get("vloc_inputs", {})
    if not isinstance(fft_descriptor, Mapping) or not isinstance(inputs, Mapping):
        return [], ["missing_vloc_fft_descriptor_or_inputs"], input_contract
    nnr = _int(fft_descriptor.get("nnr"), 0)
    shape = _fft_shape_from_descriptor(fft_descriptor, nnr)
    if shape is None:
        return [], [f"fft_descriptor_shape_product_mismatch:{nnr}"], input_contract

    psi = _pairs(arrays.get("psi_real_imag", []))
    vrs = [_float(item) for item in inputs.get("vrs_current_spin", [])]
    igk = [_int(item) - 1 for item in inputs.get("igk_current_k", [])]
    dffts_nl = [_int(item) - 1 for item in inputs.get("dffts_nl", [])]
    local_blockers: list[str] = []
    if lda <= 0 or n <= 0 or m <= 0:
        local_blockers.append(f"invalid_dimensions:{lda}:{n}:{m}")
    if len(psi) < lda * m:
        local_blockers.append(f"psi_array_length_mismatch:{len(psi)}:{lda * m}")
    if len(vrs) != nnr:
        local_blockers.append(f"vrs_current_spin_length_mismatch:{len(vrs)}:{nnr}")
    if len(igk) < n:
        local_blockers.append(f"igk_current_k_length_mismatch:{len(igk)}:{n}")
    if not dffts_nl:
        local_blockers.append("missing_dffts_nl_mapping")
    elif max(igk[:n], default=-1) >= len(dffts_nl):
        local_blockers.append(f"dffts_nl_mapping_too_short:{len(dffts_nl)}:{max(igk[:n], default=-1) + 1}")
    if local_blockers:
        return [], local_blockers, input_contract

    vrs_np = np.asarray(vrs, dtype=float)
    output: list[complex] = []
    for band in range(m):
        band_psi = psi[band * lda : band * lda + n]
        reciprocal_flat = np.zeros(nnr, dtype=np.complex128)
        reciprocal_positions = np.asarray([dffts_nl[index] for index in igk[:n]], dtype=int)
        reciprocal_flat[reciprocal_positions] = np.asarray(band_psi, dtype=np.complex128)
        reciprocal_grid = reciprocal_flat.reshape(shape, order="F")
        realspace_grid = np.fft.ifftn(reciprocal_grid)
        weighted_realspace = realspace_grid.reshape(nnr, order="F") * vrs_np
        weighted_grid = weighted_realspace.reshape(shape, order="F")
        vloc_reciprocal = np.fft.fftn(weighted_grid).reshape(nnr, order="F")
        band_output = [0.0 + 0.0j for _ in range(lda)]
        for row_index, value in enumerate(vloc_reciprocal[reciprocal_positions]):
            band_output[row_index] = complex(value)
        output.extend(band_output)
    return output, [], input_contract


def _blocked_component(component: str, targets: Mapping[str, Any], arrays: Mapping[str, Any]) -> Dict[str, Any]:
    target_key = {
        "vloc_delta": "vloc_delta_reference_real_imag",
        "vnl_delta": "vnl_delta_reference_real_imag",
    }[component]
    summaries = targets.get("component_summaries", {}) if isinstance(targets.get("component_summaries", {}), Mapping) else {}
    missing_inputs = {
        "vloc_delta": [
            "vrs_local_potential_grid",
            "fft_grid_descriptor_dffts",
            "gamma_only_real_space_path_selection",
            "vloc_psi_algorithm_sidecar",
        ],
        "vnl_delta": [
            "vkb_projectors",
            "becp_coefficients_or_calbec_recompute",
            "nkb_projector_count",
            "add_vuspsi_algorithm_sidecar",
        ],
    }[component]
    input_contract: Dict[str, Any] | None = None
    if component == "vloc_delta":
        input_contract = _vloc_input_contract(arrays)
        present_keys = set()
        if isinstance(arrays.get("vloc_inputs"), Mapping):
            present_keys.add("vrs_local_potential_grid")
        if isinstance(arrays.get("fft_descriptor_dffts"), Mapping):
            present_keys.add("fft_grid_descriptor_dffts")
        if isinstance(arrays.get("vloc_algorithm"), Mapping):
            present_keys.add("vloc_psi_algorithm_sidecar")
            present_keys.add("gamma_only_real_space_path_selection")
        missing_inputs = [
            item for item in missing_inputs if item not in present_keys
        ] + [str(item) for item in input_contract.get("blockers", [])]

    blockers = [f"component_compute_not_implemented:{component}", *missing_inputs]
    return {
        "component_id": component,
        "status": "blocked",
        "computed": False,
        "target_key": target_key,
        "target_summary": summaries.get(target_key, {}),
        **({"input_contract": input_contract} if input_contract is not None else {}),
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": "Reference target is available, but no component compute was executed.",
    }


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=["kinetic", "vloc_delta", "vnl_delta"], required=True)
    parser.add_argument("--boundary-arrays", type=Path, required=True)
    parser.add_argument("--component-targets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args(argv)

    arrays = load_hpsi_boundary_arrays(args.boundary_arrays)
    targets = _read_json(args.component_targets)
    if not isinstance(targets, Mapping):
        raise ValueError(f"component targets must be a JSON object: {args.component_targets}")

    if args.component == "kinetic":
        computed, compute_blockers = _compute_kinetic(arrays)
        target = _pairs(targets.get("kinetic_output_real_imag", []))
        comparison = _compare(computed, target) if not compute_blockers else {
            "status": "blocked",
            "absolute_error": None,
            "relative_error": None,
            "max_abs_error": None,
            "blockers": compute_blockers,
        }
        result = {
            "schema_version": COMPONENT_RESULT_SCHEMA,
            "component_id": "kinetic",
            "status": comparison["status"],
            "computed": comparison["status"] == "passed",
            "absolute_error": comparison["absolute_error"],
            "relative_error": comparison["relative_error"],
            "max_abs_error": comparison["max_abs_error"],
            "target_summary": targets.get("component_summaries", {}).get("kinetic_output_real_imag", {})
            if isinstance(targets.get("component_summaries", {}), Mapping)
            else {},
            "blockers": comparison["blockers"],
            "trusted_full_h_psi": False,
            "claim_boundary": "Kinetic component only; passing this does not satisfy full h_psi correctness.",
        }
    elif args.component == "vloc_delta":
        computed, compute_blockers, input_contract = _compute_vloc_delta(arrays)
        target = _pairs(targets.get("vloc_delta_reference_real_imag", []))
        comparison = _compare(computed, target) if not compute_blockers else {
            "status": "blocked",
            "absolute_error": None,
            "relative_error": None,
            "max_abs_error": None,
            "blockers": sorted(dict.fromkeys(compute_blockers)),
        }
        result = {
            "schema_version": COMPONENT_RESULT_SCHEMA,
            "component_id": "vloc_delta",
            "status": comparison["status"],
            "computed": comparison["status"] == "passed",
            "absolute_error": comparison["absolute_error"],
            "relative_error": comparison["relative_error"],
            "max_abs_error": comparison["max_abs_error"],
            "target_key": "vloc_delta_reference_real_imag",
            "target_summary": targets.get("component_summaries", {}).get("vloc_delta_reference_real_imag", {})
            if isinstance(targets.get("component_summaries", {}), Mapping)
            else {},
            "input_contract": input_contract,
            "blockers": comparison["blockers"],
            "trusted_full_h_psi": False,
            "claim_boundary": (
                "V_loc delta component only; passing this does not satisfy full h_psi correctness "
                "because nonlocal and final QE paths remain outside this component."
            ),
        }
    elif args.component == "vnl_delta":
        vnl_result = compute_hpsi_vnl_delta_component(arrays)
        result = {
            "schema_version": COMPONENT_RESULT_SCHEMA,
            "component_id": "vnl_delta",
            "status": vnl_result.get("status"),
            "computed": vnl_result.get("status") == "passed",
            "absolute_error": vnl_result.get("absolute_error"),
            "relative_error": vnl_result.get("relative_error"),
            "max_abs_error": vnl_result.get("max_abs_error"),
            "target_key": "vnl_delta_reference_real_imag",
            "target_summary": targets.get("component_summaries", {}).get("vnl_delta_reference_real_imag", {})
            if isinstance(targets.get("component_summaries", {}), Mapping)
            else {},
            "input_contract": vnl_result.get("input_contract"),
            "becp_reference_relative_error": vnl_result.get("becp_reference_relative_error"),
            "blockers": vnl_result.get("blockers", []),
            "trusted_full_h_psi": False,
            "claim_boundary": (
                "V_NL delta component only; passing this does not satisfy full h_psi correctness "
                "outside the captured k-point add_vuspsi path."
            ),
        }
    else:
        result = {
            "schema_version": COMPONENT_RESULT_SCHEMA,
            **_blocked_component(args.component, targets, arrays),
            "trusted_full_h_psi": False,
        }

    _write_json(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and result["status"] != "passed" else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
