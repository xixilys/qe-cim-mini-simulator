#!/usr/bin/env python3
"""QE ``h_psi`` boundary probe helpers for the Generic SystemC/GenericAccel path.

The helpers in this module intentionally produce **foundation evidence** only.
They can prove that a captured QE ``h_psi`` boundary snapshot was packaged into a
Generic SystemC request and executed through the local generic accelerator timing
path, but they do not claim that the full QE ``h_psi`` kernel was recomputed by
hardware.  The accelerated-numeric evidence gates therefore keep these rows
blocked until a future runtime provides full-kernel recomputation evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


QE_HPSI_SIDECAR_RESULT_SCHEMA = "dse.qe_hpsi_generic_accel_sidecar_result.v1"


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


def load_hpsi_boundary_snapshot(path: Path) -> Dict[str, Any]:
    """Load and minimally validate a QE ``h_psi`` boundary snapshot."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"h_psi boundary snapshot is not a JSON object: {path}")
    if str(payload.get("kernel_id")) != "h_psi":
        raise ValueError(f"snapshot kernel_id must be h_psi: {path}")
    dimensions = payload.get("dimensions", {})
    if not isinstance(dimensions, Mapping):
        raise ValueError(f"snapshot dimensions must be a JSON object: {path}")
    for field in ("lda", "n", "m"):
        if _int(dimensions.get(field), 0) <= 0:
            raise ValueError(f"snapshot dimension {field!r} must be positive: {path}")
    return dict(payload)


def load_hpsi_boundary_arrays(path: Path) -> Dict[str, Any]:
    """Load a QE h_psi expanded boundary array artifact."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"h_psi boundary arrays artifact is not a JSON object: {path}")
    if str(payload.get("kernel_id")) != "h_psi":
        raise ValueError(f"boundary arrays kernel_id must be h_psi: {path}")
    dimensions = payload.get("dimensions", {})
    if not isinstance(dimensions, Mapping):
        raise ValueError(f"boundary arrays dimensions must be a JSON object: {path}")
    for field in ("lda", "n", "m"):
        if _int(dimensions.get(field), 0) <= 0:
            raise ValueError(f"boundary arrays dimension {field!r} must be positive: {path}")
    psi = payload.get("psi_real_imag", [])
    hpsi = payload.get("hpsi_reference_real_imag", [])
    g2kin = payload.get("g2kin", [])
    if not isinstance(psi, list) or not isinstance(hpsi, list) or not isinstance(g2kin, list):
        raise ValueError(f"boundary arrays must contain psi_real_imag, hpsi_reference_real_imag, and g2kin arrays: {path}")
    return dict(payload)


def _complex_pair(value: Any) -> complex:
    if not isinstance(value, Sequence) or len(value) < 2:
        return 0.0 + 0.0j
    return complex(_float(value[0]), _float(value[1]))


def _complex_pairs(values: Any) -> list[complex]:
    return [_complex_pair(item) for item in values] if isinstance(values, list) else []


def _l2_norm(values: Sequence[complex]) -> float:
    return sum((abs(value) ** 2 for value in values), 0.0) ** 0.5


def _max_abs(values: Sequence[complex]) -> float:
    return max((abs(value) for value in values), default=0.0)


def compute_hpsi_kinetic_component(arrays: Mapping[str, Any]) -> Dict[str, Any]:
    """Compute the explicit kinetic term ``g2kin * psi`` from captured QE arrays.

    This is a real numerical computation over QE data, but it is only the first
    term of ``h_psi`` before local/nonlocal potential and other additions.  The
    result must therefore stay in partial-component/foundation claim space.
    """
    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 1)
    n = _int(dimensions.get("n"), lda)
    m = _int(dimensions.get("m"), 1)
    npol = _int(arrays.get("npol"), 1)
    row_count = lda * max(1, npol)
    element_count = row_count * m
    psi = [_complex_pair(item) for item in arrays.get("psi_real_imag", [])]
    reference_full_hpsi = [_complex_pair(item) for item in arrays.get("hpsi_reference_real_imag", [])]
    reference_kinetic_hpsi = [_complex_pair(item) for item in arrays.get("hpsi_kinetic_reference_real_imag", [])]
    g2kin = [_float(item) for item in arrays.get("g2kin", [])]
    blockers: list[str] = []
    if len(psi) != element_count:
        blockers.append(f"psi_array_length_mismatch:{len(psi)}:{element_count}")
    if len(reference_full_hpsi) != element_count:
        blockers.append(f"hpsi_reference_array_length_mismatch:{len(reference_full_hpsi)}:{element_count}")
    has_kinetic_reference = bool(reference_kinetic_hpsi)
    if has_kinetic_reference and len(reference_kinetic_hpsi) != element_count:
        blockers.append(f"hpsi_kinetic_reference_array_length_mismatch:{len(reference_kinetic_hpsi)}:{element_count}")
    if len(g2kin) < lda:
        blockers.append(f"g2kin_array_length_mismatch:{len(g2kin)}:{lda}")

    usable = min(len(psi), len(reference_full_hpsi), element_count)
    if has_kinetic_reference:
        usable = min(usable, len(reference_kinetic_hpsi))
    kinetic: list[complex] = []
    for flat_index in range(usable):
        row_index = flat_index % row_count
        g_index = row_index % lda
        if g_index < n and g_index < len(g2kin):
            kinetic.append(g2kin[g_index] * psi[flat_index])
        else:
            kinetic.append(0.0 + 0.0j)
    reference_slice = reference_full_hpsi[:usable]
    residual = [reference - value for reference, value in zip(reference_slice, kinetic)]
    kinetic_l2 = _l2_norm(kinetic)
    reference_l2 = _l2_norm(reference_slice)
    residual_l2 = _l2_norm(residual)
    kinetic_reference_slice = reference_kinetic_hpsi[:usable] if has_kinetic_reference else []
    kinetic_error = [
        reference - value for reference, value in zip(kinetic_reference_slice, kinetic)
    ] if has_kinetic_reference else []
    kinetic_reference_l2 = _l2_norm(kinetic_reference_slice) if has_kinetic_reference else None
    kinetic_error_l2 = _l2_norm(kinetic_error) if has_kinetic_reference else None
    kinetic_max_abs_error = max((abs(value) for value in kinetic_error), default=None) if has_kinetic_reference else None
    return {
        "schema_version": "dse.qe_hpsi_kinetic_component_result.v1",
        "kernel_id": "h_psi_kinetic_component",
        "kernel_scope": "partial_h_psi_kinetic_component",
        "status": "passed" if not blockers else "blocked",
        "dimensions": {"lda": lda, "n": n, "m": m, "npol": npol},
        "element_count": element_count,
        "computed_element_count": usable,
        "kinetic_l2_norm": kinetic_l2,
        "qe_kinetic_reference_available": has_kinetic_reference,
        "qe_kinetic_reference_l2_norm": kinetic_reference_l2,
        "qe_kinetic_reference_error_l2_norm": kinetic_error_l2,
        "qe_kinetic_reference_relative_l2_error": (
            kinetic_error_l2 / max(kinetic_reference_l2 or 0.0, 1.0e-300)
            if kinetic_error_l2 is not None
            else None
        ),
        "qe_kinetic_reference_max_abs_error": kinetic_max_abs_error,
        "reference_full_hpsi_l2_norm": reference_l2,
        "residual_to_full_hpsi_l2_norm": residual_l2,
        "residual_to_full_hpsi_relative_l2": residual_l2 / max(reference_l2, 1.0e-300),
        "sample_kinetic_real_imag": [[value.real, value.imag] for value in kinetic[:8]],
        "blockers": blockers,
        "full_h_psi_recomputed": False,
        "partial_component_only": True,
        "claim_boundary": (
            "Numerically computes the kinetic g2kin*psi term from captured QE arrays only; "
            "local/nonlocal potential and full h_psi recomputation remain missing."
        ),
    }


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
    for flag_name, blocker in [
        ("real_space", "vloc_real_space_combined_vloc_vnl_path_not_separable"),
        ("has_task_groups", "vloc_task_group_path_not_supported_by_component_runner"),
        ("noncolin", "vloc_noncollinear_path_not_supported_by_component_runner"),
    ]:
        if algorithm.get(flag_name) is True:
            blockers.append(blocker)

    vrs = inputs.get("vrs_current_spin", [])
    if not isinstance(vrs, list):
        blockers.append("vrs_current_spin_not_array")
        vrs = []
    nnr = _int(fft_descriptor.get("nnr"), 0)
    if nnr <= 0:
        blockers.append("fft_descriptor_missing_positive_nnr")
    elif len(vrs) != nnr:
        blockers.append(f"vrs_current_spin_length_mismatch:{len(vrs)}:{nnr}")

    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    n = _int(dimensions.get("n"), 0)
    igk = inputs.get("igk_current_k", [])
    dffts_nl = inputs.get("dffts_nl", [])
    if algorithm.get("gamma_only") is not True:
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
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": "Vloc input-contract audit only; not full h_psi evidence.",
    }


def _fft_shape_from_descriptor(fft_descriptor: Mapping[str, Any], nnr: int) -> tuple[int, int, int] | None:
    for key in ("nrx", "nr"):
        raw = fft_descriptor.get(key)
        if not isinstance(raw, list) or len(raw) != 3:
            continue
        shape = tuple(_int(item, 0) for item in raw)
        if all(item > 0 for item in shape) and shape[0] * shape[1] * shape[2] == nnr:
            return (shape[0], shape[1], shape[2])
    return None


def compute_hpsi_vloc_delta_component(arrays: Mapping[str, Any]) -> Dict[str, Any]:
    """Compute the reciprocal-space ``V_loc * psi`` delta from captured QE inputs.

    This reproduces the standard non-gamma ``vloc_psi_k_acc`` dual-space path:
    scatter coefficients through ``dffts%nl(igk_k)``, inverse FFT to real
    space, multiply by the captured local potential ``vrs``, FFT back, and
    gather the same reciprocal coefficients.  It is still only one component of
    ``h_psi`` and must remain outside trusted full-kernel evidence.
    """
    input_contract = _vloc_input_contract(arrays)
    blockers = [str(item) for item in input_contract.get("blockers", []) or []]
    algorithm_path = str(input_contract.get("algorithm_path") or "")
    if algorithm_path != "vloc_psi_k_acc":
        blockers.append(f"vloc_algorithm_path_not_implemented:{algorithm_path or 'missing'}")

    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 0)
    n = _int(dimensions.get("n"), 0)
    m = _int(dimensions.get("m"), 0)
    element_count = lda * m
    target = [
        after - kinetic
        for kinetic, after in zip(
            _complex_pairs(arrays.get("hpsi_kinetic_reference_real_imag", [])),
            _complex_pairs(arrays.get("hpsi_after_vloc_reference_real_imag", [])),
        )
    ]

    if blockers:
        return {
            "schema_version": "dse.qe_hpsi_vloc_delta_component_result.v1",
            "kernel_id": "h_psi_vloc_delta_component",
            "kernel_scope": "partial_h_psi_vloc_delta_component",
            "status": "blocked",
            "dimensions": {"lda": lda, "n": n, "m": m},
            "element_count": element_count,
            "computed_element_count": 0,
            "absolute_error": None,
            "relative_error": None,
            "max_abs_error": None,
            "target_l2_norm": _l2_norm(target),
            "input_contract": input_contract,
            "blockers": sorted(dict.fromkeys(blockers)),
            "full_h_psi_recomputed": False,
            "partial_component_only": True,
            "claim_boundary": "Vloc component blocked before compute; not full h_psi evidence.",
        }

    try:
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional local environment path
        return {
            "schema_version": "dse.qe_hpsi_vloc_delta_component_result.v1",
            "kernel_id": "h_psi_vloc_delta_component",
            "kernel_scope": "partial_h_psi_vloc_delta_component",
            "status": "blocked",
            "dimensions": {"lda": lda, "n": n, "m": m},
            "element_count": element_count,
            "computed_element_count": 0,
            "absolute_error": None,
            "relative_error": None,
            "max_abs_error": None,
            "target_l2_norm": _l2_norm(target),
            "input_contract": input_contract,
            "blockers": [f"numpy_unavailable_for_vloc_fft:{exc}"],
            "full_h_psi_recomputed": False,
            "partial_component_only": True,
            "claim_boundary": "Vloc component requires numpy FFT in this prototype.",
        }

    fft_descriptor = arrays.get("fft_descriptor_dffts", {})
    inputs = arrays.get("vloc_inputs", {})
    if not isinstance(fft_descriptor, Mapping) or not isinstance(inputs, Mapping):
        raise ValueError("vloc input contract unexpectedly passed without descriptor/input mappings")
    nnr = _int(fft_descriptor.get("nnr"), 0)
    shape = _fft_shape_from_descriptor(fft_descriptor, nnr)
    psi = _complex_pairs(arrays.get("psi_real_imag", []))
    vrs = [_float(item) for item in inputs.get("vrs_current_spin", [])]
    igk = [_int(item) - 1 for item in inputs.get("igk_current_k", [])]
    dffts_nl = [_int(item) - 1 for item in inputs.get("dffts_nl", [])]
    local_blockers: list[str] = []
    if shape is None:
        local_blockers.append(f"fft_descriptor_shape_product_mismatch:{nnr}")
    if len(psi) < element_count:
        local_blockers.append(f"psi_array_length_mismatch:{len(psi)}:{element_count}")
    if len(target) != element_count:
        local_blockers.append(f"vloc_target_length_mismatch:{len(target)}:{element_count}")
    if local_blockers:
        return {
            "schema_version": "dse.qe_hpsi_vloc_delta_component_result.v1",
            "kernel_id": "h_psi_vloc_delta_component",
            "kernel_scope": "partial_h_psi_vloc_delta_component",
            "status": "blocked",
            "dimensions": {"lda": lda, "n": n, "m": m},
            "element_count": element_count,
            "computed_element_count": 0,
            "absolute_error": None,
            "relative_error": None,
            "max_abs_error": None,
            "target_l2_norm": _l2_norm(target),
            "input_contract": input_contract,
            "blockers": local_blockers,
            "full_h_psi_recomputed": False,
            "partial_component_only": True,
            "claim_boundary": "Vloc component blocked by malformed arrays.",
        }

    vrs_np = np.asarray(vrs, dtype=float)
    computed: list[complex] = []
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
        computed.extend(band_output)

    errors = [left - right for left, right in zip(computed, target)]
    absolute_error = _l2_norm(errors)
    target_l2 = _l2_norm(target)
    relative_error = absolute_error / max(target_l2, 1.0e-300)
    passed = absolute_error <= 1.0e-12 or relative_error <= 1.0e-12
    return {
        "schema_version": "dse.qe_hpsi_vloc_delta_component_result.v1",
        "kernel_id": "h_psi_vloc_delta_component",
        "kernel_scope": "partial_h_psi_vloc_delta_component",
        "status": "passed" if passed else "failed",
        "dimensions": {"lda": lda, "n": n, "m": m},
        "element_count": element_count,
        "computed_element_count": len(computed),
        "absolute_error": absolute_error,
        "relative_error": relative_error,
        "max_abs_error": _max_abs(errors),
        "target_l2_norm": target_l2,
        "input_contract": input_contract,
        "blockers": [] if passed else [f"vloc_component_numeric_mismatch:{relative_error:.6e}"],
        "full_h_psi_recomputed": False,
        "partial_component_only": True,
        "claim_boundary": "Partial V_loc*psi delta only; not sufficient for full h_psi correctness.",
    }


def _vnl_input_contract(arrays: Mapping[str, Any]) -> Dict[str, Any]:
    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 0)
    m = _int(dimensions.get("m"), 0)
    inputs = arrays.get("vnl_inputs", {})
    blockers: list[str] = []
    if not isinstance(inputs, Mapping):
        inputs = {}
        blockers.append("missing_vnl_inputs")
    algorithm_path = str(inputs.get("algorithm_path") or "")
    if algorithm_path != "add_vuspsi_k":
        blockers.append(f"vnl_algorithm_path_not_implemented:{algorithm_path or 'missing'}")
    if inputs.get("supported_by_python_sidecar") is not True:
        blockers.append("vnl_inputs_not_marked_supported_by_python_sidecar")
    nkb = _int(inputs.get("nkb"), 0)
    nhm = _int(inputs.get("nhm"), 0)
    nat = _int(inputs.get("nat"), 0)
    ntyp = _int(inputs.get("ntyp"), 0)
    nh = inputs.get("nh", [])
    ityp = inputs.get("ityp", [])
    ofsbeta = inputs.get("ofsbeta", [])
    vkb = inputs.get("vkb_real_imag", [])
    deeq = inputs.get("deeq_current_spin", [])
    becp = inputs.get("becp_k_reference_real_imag", [])
    expected = {
        "nh": ntyp,
        "ityp": nat,
        "ofsbeta": nat,
        "vkb_real_imag": lda * nkb,
        "deeq_current_spin": nhm * nhm * nat,
        "becp_k_reference_real_imag": nkb * m,
    }
    actual = {
        "nh": len(nh) if isinstance(nh, list) else -1,
        "ityp": len(ityp) if isinstance(ityp, list) else -1,
        "ofsbeta": len(ofsbeta) if isinstance(ofsbeta, list) else -1,
        "vkb_real_imag": len(vkb) if isinstance(vkb, list) else -1,
        "deeq_current_spin": len(deeq) if isinstance(deeq, list) else -1,
        "becp_k_reference_real_imag": len(becp) if isinstance(becp, list) else -1,
    }
    for key, expected_len in expected.items():
        if expected_len <= 0 or actual[key] != expected_len:
            blockers.append(f"vnl_input_length_mismatch:{key}:{actual[key]}:{expected_len}")
    return {
        "status": "passed" if not blockers else "blocked",
        "algorithm_path": algorithm_path or None,
        "nkb": nkb,
        "nhm": nhm,
        "nat": nat,
        "ntyp": ntyp,
        "lengths": actual,
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": "Vnl input-contract audit only; not full h_psi evidence.",
    }


def compute_hpsi_vnl_delta_component(arrays: Mapping[str, Any]) -> Dict[str, Any]:
    """Compute the standard k-point ``add_vuspsi`` nonlocal delta.

    The prototype recomputes the serial/non-gamma path from captured QE inputs:
    ``becp = vkb^H psi``, ``ps = deeq * becp`` per atom/type block, then
    ``V_NL psi = vkb * ps``.  It remains a partial component and does not cover
    gamma, noncollinear, real-space combined Vloc/Vnl, or final h_psi terms.
    """
    input_contract = _vnl_input_contract(arrays)
    blockers = [str(item) for item in input_contract.get("blockers", []) or []]
    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 0)
    n = _int(dimensions.get("n"), 0)
    m = _int(dimensions.get("m"), 0)
    element_count = lda * m
    target = [
        after - before
        for before, after in zip(
            _complex_pairs(arrays.get("hpsi_after_vloc_reference_real_imag", [])),
            _complex_pairs(arrays.get("hpsi_after_vnl_reference_real_imag", [])),
        )
    ]
    base = {
        "schema_version": "dse.qe_hpsi_vnl_delta_component_result.v1",
        "kernel_id": "h_psi_vnl_delta_component",
        "kernel_scope": "partial_h_psi_vnl_delta_component",
        "dimensions": {"lda": lda, "n": n, "m": m},
        "element_count": element_count,
        "target_l2_norm": _l2_norm(target),
        "input_contract": input_contract,
        "full_h_psi_recomputed": False,
        "partial_component_only": True,
    }
    if blockers:
        return {
            **base,
            "status": "blocked",
            "computed_element_count": 0,
            "absolute_error": None,
            "relative_error": None,
            "max_abs_error": None,
            "becp_reference_relative_error": None,
            "blockers": sorted(dict.fromkeys(blockers)),
            "claim_boundary": "Vnl component blocked before compute; not full h_psi evidence.",
        }
    try:
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional local environment path
        return {
            **base,
            "status": "blocked",
            "computed_element_count": 0,
            "absolute_error": None,
            "relative_error": None,
            "max_abs_error": None,
            "becp_reference_relative_error": None,
            "blockers": [f"numpy_unavailable_for_vnl_gemm:{exc}"],
            "claim_boundary": "Vnl component requires numpy GEMM in this prototype.",
        }

    inputs = arrays["vnl_inputs"] if isinstance(arrays.get("vnl_inputs"), Mapping) else {}
    nkb = _int(inputs.get("nkb"), 0)
    nhm = _int(inputs.get("nhm"), 0)
    nat = _int(inputs.get("nat"), 0)
    psi = np.asarray(_complex_pairs(arrays.get("psi_real_imag", [])), dtype=np.complex128).reshape((m, lda)).T
    vkb = np.asarray(_complex_pairs(inputs.get("vkb_real_imag", [])), dtype=np.complex128).reshape((nkb, lda)).T
    becp_reference = np.asarray(
        _complex_pairs(inputs.get("becp_k_reference_real_imag", [])),
        dtype=np.complex128,
    ).reshape((m, nkb)).T
    deeq = np.asarray(inputs.get("deeq_current_spin", []), dtype=float).reshape((nat, nhm, nhm))
    nh = [_int(item) for item in inputs.get("nh", [])]
    ityp = [_int(item) - 1 for item in inputs.get("ityp", [])]
    ofsbeta = [_int(item) for item in inputs.get("ofsbeta", [])]

    becp = vkb[:n, :].conj().T @ psi[:n, :]
    becp_error = becp - becp_reference
    becp_reference_norm = float(np.linalg.norm(becp_reference))
    becp_reference_relative_error = float(np.linalg.norm(becp_error) / max(becp_reference_norm, 1.0e-300))
    ps = np.zeros((nkb, m), dtype=np.complex128)
    for atom_index in range(nat):
        type_index = ityp[atom_index]
        projector_count = nh[type_index]
        start = ofsbeta[atom_index]
        deeaux = deeq[atom_index, :projector_count, :projector_count].T
        ps[start : start + projector_count, :] = deeaux @ becp[start : start + projector_count, :]
    computed_matrix = vkb[:n, :] @ ps
    padded = np.zeros((lda, m), dtype=np.complex128)
    padded[:n, :] = computed_matrix
    computed = [complex(value) for value in padded.T.reshape(lda * m)]
    errors = [left - right for left, right in zip(computed, target)]
    absolute_error = _l2_norm(errors)
    target_l2 = _l2_norm(target)
    relative_error = absolute_error / max(target_l2, 1.0e-300)
    passed = (
        (absolute_error <= 1.0e-12 or relative_error <= 1.0e-12)
        and becp_reference_relative_error <= 1.0e-12
    )
    return {
        **base,
        "status": "passed" if passed else "failed",
        "computed_element_count": len(computed),
        "absolute_error": absolute_error,
        "relative_error": relative_error,
        "max_abs_error": _max_abs(errors),
        "becp_reference_relative_error": becp_reference_relative_error,
        "blockers": [] if passed else [f"vnl_component_numeric_mismatch:{relative_error:.6e}"],
        "claim_boundary": "Partial V_NL psi delta only; not sufficient for full h_psi correctness.",
    }


def compute_hpsi_stage_decomposition(arrays: Mapping[str, Any]) -> Dict[str, Any]:
    """Summarize captured QE h_psi stage references and residual components."""
    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 1)
    m = _int(dimensions.get("m"), 1)
    npol = _int(arrays.get("npol"), 1)
    element_count = lda * max(1, npol) * m
    stage_fields = {
        "kinetic": "hpsi_kinetic_reference_real_imag",
        "after_vloc": "hpsi_after_vloc_reference_real_imag",
        "after_vnl": "hpsi_after_vnl_reference_real_imag",
        "final": "hpsi_reference_real_imag",
    }
    stages: dict[str, list[complex]] = {}
    blockers: list[str] = []
    for stage_name, field in stage_fields.items():
        values = arrays.get(field, [])
        if not isinstance(values, list) or len(values) != element_count:
            blockers.append(f"stage_array_missing_or_length_mismatch:{field}:{len(values) if isinstance(values, list) else 'not_list'}:{element_count}")
            stages[stage_name] = []
            continue
        stages[stage_name] = [_complex_pair(item) for item in values]

    def _delta_l2(left: str, right: str) -> float | None:
        left_values = stages.get(left, [])
        right_values = stages.get(right, [])
        if len(left_values) != element_count or len(right_values) != element_count:
            return None
        return _l2_norm([b - a for a, b in zip(left_values, right_values)])

    final_l2 = _l2_norm(stages["final"]) if len(stages.get("final", [])) == element_count else None
    kinetic_to_vloc = _delta_l2("kinetic", "after_vloc")
    vloc_to_vnl = _delta_l2("after_vloc", "after_vnl")
    vnl_to_final = _delta_l2("after_vnl", "final")
    return {
        "schema_version": "dse.qe_hpsi_stage_decomposition.v1",
        "kernel_id": "h_psi",
        "status": "passed" if not blockers else "blocked",
        "dimensions": {"lda": lda, "m": m, "npol": npol},
        "element_count": element_count,
        "stage_l2_norms": {
            stage_name: _l2_norm(values) if len(values) == element_count else None
            for stage_name, values in stages.items()
        },
        "component_delta_l2_norms": {
            "kinetic_to_after_vloc": kinetic_to_vloc,
            "after_vloc_to_after_vnl": vloc_to_vnl,
            "after_vnl_to_final": vnl_to_final,
        },
        "component_delta_relative_to_final_l2": {
            "kinetic_to_after_vloc": kinetic_to_vloc / max(final_l2 or 0.0, 1.0e-300) if kinetic_to_vloc is not None else None,
            "after_vloc_to_after_vnl": vloc_to_vnl / max(final_l2 or 0.0, 1.0e-300) if vloc_to_vnl is not None else None,
            "after_vnl_to_final": vnl_to_final / max(final_l2 or 0.0, 1.0e-300) if vnl_to_final is not None else None,
        },
        "blockers": blockers,
        "full_h_psi_recomputed": False,
        "claim_boundary": "Captured QE stage references for decomposition only; not an accelerated full h_psi recompute.",
    }


def build_hpsi_component_target_arrays(arrays: Mapping[str, Any]) -> Dict[str, Any]:
    """Build explicit reference target arrays for h_psi component kernels."""
    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 1)
    m = _int(dimensions.get("m"), 1)
    npol = _int(arrays.get("npol"), 1)
    element_count = lda * max(1, npol) * m
    fields = {
        "kinetic": "hpsi_kinetic_reference_real_imag",
        "after_vloc": "hpsi_after_vloc_reference_real_imag",
        "after_vnl": "hpsi_after_vnl_reference_real_imag",
        "final": "hpsi_reference_real_imag",
    }
    blockers: list[str] = []
    stages: dict[str, list[complex]] = {}
    for stage_name, field in fields.items():
        raw_values = arrays.get(field, [])
        if not isinstance(raw_values, list) or len(raw_values) != element_count:
            blockers.append(f"stage_array_missing_or_length_mismatch:{field}:{len(raw_values) if isinstance(raw_values, list) else 'not_list'}:{element_count}")
            stages[stage_name] = []
        else:
            stages[stage_name] = [_complex_pair(item) for item in raw_values]

    def _delta(left: str, right: str) -> list[complex]:
        if len(stages.get(left, [])) != element_count or len(stages.get(right, [])) != element_count:
            return []
        return [b - a for a, b in zip(stages[left], stages[right])]

    component_arrays = {
        "kinetic_output_real_imag": stages.get("kinetic", []),
        "vloc_delta_reference_real_imag": _delta("kinetic", "after_vloc"),
        "vnl_delta_reference_real_imag": _delta("after_vloc", "after_vnl"),
        "post_vnl_final_adjustment_reference_real_imag": _delta("after_vnl", "final"),
    }

    def _summary(values: Sequence[complex]) -> Dict[str, Any]:
        return {
            "element_count": len(values),
            "l2_norm": _l2_norm(values),
            "max_abs": max((abs(value) for value in values), default=0.0),
        }

    serialized_arrays = {
        name: [[value.real, value.imag] for value in values]
        for name, values in component_arrays.items()
    }
    summaries = {name: _summary(values) for name, values in component_arrays.items()}
    return {
        "schema_version": "dse.qe_hpsi_component_target_arrays.v1",
        "status": "passed" if not blockers else "blocked",
        "kernel_id": "h_psi",
        "dimensions": {"lda": lda, "m": m, "npol": npol},
        "element_count": element_count,
        "component_summaries": summaries,
        **serialized_arrays,
        "blockers": blockers,
        "trusted_full_h_psi": False,
        "claim_boundary": (
            "Reference target arrays for future component kernels only. These arrays are captured/derived "
            "from QE host stage references and do not prove accelerated full h_psi recomputation."
        ),
    }


def build_hpsi_component_closure_report(
    *,
    kinetic_component_result: Mapping[str, Any] | None,
    stage_decomposition: Mapping[str, Any],
    vloc_component_result: Mapping[str, Any] | None = None,
    vnl_component_result: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build an actionable component-by-component closure report for h_psi."""
    relative = (
        stage_decomposition.get("component_delta_relative_to_final_l2", {})
        if isinstance(stage_decomposition.get("component_delta_relative_to_final_l2", {}), Mapping)
        else {}
    )
    delta_l2 = (
        stage_decomposition.get("component_delta_l2_norms", {})
        if isinstance(stage_decomposition.get("component_delta_l2_norms", {}), Mapping)
        else {}
    )
    kinetic_ok = (
        isinstance(kinetic_component_result, Mapping)
        and kinetic_component_result.get("status") == "passed"
        and kinetic_component_result.get("qe_kinetic_reference_relative_l2_error") == 0.0
    )
    vloc_ok = (
        isinstance(vloc_component_result, Mapping)
        and vloc_component_result.get("status") == "passed"
        and _float(vloc_component_result.get("relative_error"), 1.0) <= 1.0e-12
    )
    vnl_ok = (
        isinstance(vnl_component_result, Mapping)
        and vnl_component_result.get("status") == "passed"
        and _float(vnl_component_result.get("relative_error"), 1.0) <= 1.0e-12
    )
    after_vnl_to_final = _float(relative.get("after_vnl_to_final"), 0.0)
    components = [
        {
            "component_id": "kinetic_g2kin_times_psi",
            "status": "matched_partial_component" if kinetic_ok else "blocked",
            "trusted_full_h_psi": False,
            "relative_l2_error_to_qe_stage": kinetic_component_result.get("qe_kinetic_reference_relative_l2_error")
            if isinstance(kinetic_component_result, Mapping)
            else None,
            "next_blocker": None if kinetic_ok else "missing_or_failed_kinetic_stage_reference_match",
            "claim_boundary": "Partial kinetic component only.",
        },
        {
            "component_id": "local_potential_vloc_delta",
            "status": "matched_partial_component" if vloc_ok else "reference_captured_missing_compute",
            "trusted_full_h_psi": False,
            "delta_l2_norm": delta_l2.get("kinetic_to_after_vloc"),
            "relative_to_final_l2": relative.get("kinetic_to_after_vloc"),
            "relative_l2_error_to_qe_stage": vloc_component_result.get("relative_error")
            if isinstance(vloc_component_result, Mapping)
            else None,
            "next_blocker": None if vloc_ok else "implement_vloc_kernel_inputs_fft_vrs_and_compare_to_after_vloc_minus_kinetic",
            "claim_boundary": "Partial Vloc component only; not full h_psi evidence.",
        },
        {
            "component_id": "nonlocal_potential_vnl_delta",
            "status": "matched_partial_component" if vnl_ok else "reference_captured_missing_compute",
            "trusted_full_h_psi": False,
            "delta_l2_norm": delta_l2.get("after_vloc_to_after_vnl"),
            "relative_to_final_l2": relative.get("after_vloc_to_after_vnl"),
            "relative_l2_error_to_qe_stage": vnl_component_result.get("relative_error")
            if isinstance(vnl_component_result, Mapping)
            else None,
            "next_blocker": None if vnl_ok else "implement_nonlocal_vkb_becp_add_vuspsi_component_and_compare_to_after_vnl_minus_after_vloc",
            "claim_boundary": "Partial Vnl component only; not full h_psi evidence.",
        },
        {
            "component_id": "post_vnl_final_adjustment",
            "status": "zero_for_current_probe" if after_vnl_to_final == 0.0 else "reference_captured_missing_compute",
            "trusted_full_h_psi": False,
            "delta_l2_norm": delta_l2.get("after_vnl_to_final"),
            "relative_to_final_l2": relative.get("after_vnl_to_final"),
            "next_blocker": None if after_vnl_to_final == 0.0 else "implement_post_vnl_adjustments_for_this_workload_case",
            "claim_boundary": "Only covers the current frozen probe; other QE cases may need meta/U/exx/field/final adjustments.",
        },
    ]
    missing = [component["component_id"] for component in components if component["status"] == "reference_captured_missing_compute"]
    return {
        "schema_version": "dse.qe_hpsi_component_closure_report.v1",
        "status": "blocked_until_all_components_computed" if missing else "partial_components_matched_but_not_full_l4",
        "trusted_full_h_psi": False,
        "components": components,
        "missing_compute_components": missing,
        "claim_boundary": (
            "Component closure report is an execution guide. It does not upgrade sidecar/stage evidence "
            "into trusted full h_psi correctness."
        ),
    }


def build_hpsi_boundary_probe_request(
    *,
    candidate_id: str,
    workload_case_id: str,
    snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build a domain-neutral Generic SystemC request for the h_psi boundary probe."""
    dimensions = snapshot.get("dimensions", {}) if isinstance(snapshot.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 1)
    n = _int(dimensions.get("n"), lda)
    m = _int(dimensions.get("m"), 1)
    element_count = max(1, lda * m)
    complex_fp64_bytes = element_count * 16
    flops = max(1.0, float(n * m * 8))
    return {
        "schema_version": "gsim.request.v1",
        "run_id": f"{candidate_id}__{workload_case_id}__hpsi_boundary_probe",
        "mode": "standalone_systemc",
        "design_point": {
            "design_point_id": candidate_id,
            "workload_id": workload_case_id,
            "architecture_id": "generic_accel_hpsi_boundary_probe",
            "mapping_id": "hpsi_boundary_probe_to_generic_accel",
            "selected_candidate_id": candidate_id,
            "scheduling_policy": "static",
            "precision_policy": {"default": "FP64_complex"},
        },
        "workload": {
            "graph_id": f"{workload_case_id}_hpsi_boundary_probe",
            "nodes": {
                "hpsi_boundary_norm_probe": {
                    "op_type": "reduction",
                    "inputs": ["psi_boundary_stats"],
                    "outputs": ["hpsi_boundary_stats"],
                    "estimated_flops": flops,
                    "estimated_memory_bytes": float(complex_fp64_bytes * 2),
                    "attributes": {
                        "qe_kernel_id": "h_psi",
                        "kernel_scope": "h_psi_boundary_norm_transport_probe",
                        "full_h_psi_recomputed": "false",
                        "lda": str(lda),
                        "n": str(n),
                        "m": str(m),
                        "psi_l2_norm": str(_float(snapshot.get("psi_l2_norm"))),
                        "reference_hpsi_l2_norm": str(_float(snapshot.get("hpsi_l2_norm"))),
                    },
                }
            },
            "edges": [],
            "metadata": {
                "workload_family": "qe_hpsi_sidecar_probe",
                "claim_boundary": "boundary_norm_transport_probe_only",
            },
        },
        "architecture": {
            "host": {"cpu_model": "host_reference", "clock_mhz": 3000.0, "memory_bw_gbps": 100.0, "cores": 1},
            "interconnect": {"type": "pcie", "bandwidth_gbps": 64.0, "latency_ns": 800.0},
            "accelerators": [
                {
                    "accel_id": "generic_accel_0",
                    "accel_type": "fpga",
                    "clock_mhz": 250.0,
                    "local_memory_kb": 2048,
                    "power": {"static_w": 3.0, "max_w": 25.0},
                    "capabilities": {
                        "reduction": {"peak_gops": 64.0, "efficiency": 0.75},
                        "generic_op": {"peak_gops": 32.0, "efficiency": 0.60},
                    },
                    "microarchitecture": {
                        "accel_type": "fpga",
                        "array_size": 16,
                        "local_sram_kb": 2048,
                        "dma_channels": 1,
                        "memory_ports": 2,
                        "memory_bandwidth_gbps": 64.0,
                    },
                }
            ],
        },
        "mapping": {"hpsi_boundary_norm_probe": "generic_accel_0"},
        "scheduling": {"policy": "static", "allow_overlap_dma_compute": True, "double_buffer": True},
        "output": {"result_json": "generic_sim_result.json", "trace_json": "generic_sim_trace.json"},
        "extension_payload": {
            "schema_version": "dse.qe_hpsi_boundary_probe_payload.v1",
            "candidate_id": candidate_id,
            "workload_case_id": workload_case_id,
            "kernel_boundary_snapshot": dict(snapshot),
            "claim_boundary": "This payload contains captured QE boundary norms only, not full arrays or a full h_psi recompute.",
        },
    }


def build_sidecar_result(
    *,
    candidate_id: str,
    workload_case_id: str,
    snapshot: Mapping[str, Any],
    simulator_result: Mapping[str, Any] | None,
    simulator_result_path: Path,
    request_path: Path,
) -> Dict[str, Any]:
    """Build a replayable sidecar result with an explicit non-completion boundary."""
    sim_result = simulator_result if isinstance(simulator_result, Mapping) else {}
    status = "passed" if str(sim_result.get("status")) == "passed" else "blocked"
    reference_hpsi_l2 = _float(snapshot.get("hpsi_l2_norm"))
    observed_hpsi_l2 = reference_hpsi_l2 if status == "passed" else None
    absolute_error = abs((observed_hpsi_l2 or 0.0) - reference_hpsi_l2) if observed_hpsi_l2 is not None else None
    relative_error = absolute_error / max(abs(reference_hpsi_l2), 1.0e-300) if absolute_error is not None else None
    return {
        "schema_version": QE_HPSI_SIDECAR_RESULT_SCHEMA,
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "status": status,
        "source_kind": "gem5_generic_accel_qe_extension",
        "kernel_id": "h_psi",
        "kernel_scope": "h_psi_boundary_norm_transport_probe",
        "full_h_psi_recomputed": False,
        "boundary_norm_probe_only": True,
        "reference_boundary": {
            "psi_l2_norm": _float(snapshot.get("psi_l2_norm")),
            "hpsi_l2_norm": reference_hpsi_l2,
            "hpsi_abs_sum": _float(snapshot.get("hpsi_abs_sum")),
            "dimensions": dict(snapshot.get("dimensions", {})) if isinstance(snapshot.get("dimensions", {}), Mapping) else {},
        },
        "observed_boundary": {
            "hpsi_l2_norm": observed_hpsi_l2,
            "absolute_error": absolute_error,
            "relative_error": relative_error,
        },
        "generic_systemc_result": dict(sim_result),
        "artifacts": {
            "request_path": str(request_path),
            "generic_sim_result_path": str(simulator_result_path),
        },
        "claim_boundary": (
            "Foundation only: GenericAccel/SystemC consumed a captured h_psi boundary probe. "
            "It is not full QE h_psi recomputation and must remain blocked for deliverable correctness."
        ),
    }


def build_sidecar_kernel_evidence(
    sidecar_result: Mapping[str, Any],
    kinetic_component_result: Mapping[str, Any] | None = None,
    stage_decomposition: Mapping[str, Any] | None = None,
    vloc_component_result: Mapping[str, Any] | None = None,
    vnl_component_result: Mapping[str, Any] | None = None,
) -> list[Dict[str, Any]]:
    """Convert a sidecar result into kernel evidence that remains anti-downgrade gated."""
    observed = sidecar_result.get("observed_boundary", {})
    observed_map = observed if isinstance(observed, Mapping) else {}
    rows = [
        {
            "kernel_id": "h_psi",
            "kernel_scope": "h_psi_boundary_norm_transport_probe",
            "full_kernel_recomputed": False,
            "boundary_norm_probe_only": True,
            "absolute_error": _float(observed_map.get("absolute_error"), 0.0),
            "relative_error": _float(observed_map.get("relative_error"), 0.0),
            "error_metric": "boundary_hpsi_l2_norm_only",
            "source": "gem5_generic_accel_qe_extension",
            "timing_only": False,
            "reference_boundary": dict(sidecar_result.get("reference_boundary", {}))
            if isinstance(sidecar_result.get("reference_boundary", {}), Mapping)
            else {},
            "claim_boundary": "Boundary-norm transport probe only; full h_psi kernel was not recomputed.",
        }
    ]
    if isinstance(kinetic_component_result, Mapping):
        rows.append(
            {
                "kernel_id": "h_psi_kinetic_component",
                "kernel_scope": "partial_h_psi_kinetic_component",
                "full_kernel_recomputed": False,
                "partial_component_only": True,
                "absolute_error": kinetic_component_result.get("qe_kinetic_reference_max_abs_error")
                if kinetic_component_result.get("qe_kinetic_reference_available")
                else (0.0 if kinetic_component_result.get("status") == "passed" else None),
                "relative_error": kinetic_component_result.get("qe_kinetic_reference_relative_l2_error")
                if kinetic_component_result.get("qe_kinetic_reference_available")
                else (0.0 if kinetic_component_result.get("status") == "passed" else None),
                "error_metric": "qe_kinetic_stage_reference" if kinetic_component_result.get("qe_kinetic_reference_available") else "python_kinetic_formula_self_check",
                "source": "gem5_generic_accel_qe_extension",
                "timing_only": False,
                "computed_element_count": kinetic_component_result.get("computed_element_count"),
                "residual_to_full_hpsi_l2_norm": kinetic_component_result.get("residual_to_full_hpsi_l2_norm"),
                "residual_to_full_hpsi_relative_l2": kinetic_component_result.get("residual_to_full_hpsi_relative_l2"),
                "claim_boundary": "Partial h_psi kinetic component only; not sufficient for full h_psi correctness.",
            }
        )
    if isinstance(stage_decomposition, Mapping):
        rows.append(
            {
                "kernel_id": "h_psi_stage_decomposition",
                "kernel_scope": "captured_qe_stage_references",
                "full_kernel_recomputed": False,
                "partial_component_only": True,
                "absolute_error": 0.0 if stage_decomposition.get("status") == "passed" else None,
                "relative_error": 0.0 if stage_decomposition.get("status") == "passed" else None,
                "error_metric": "qe_stage_capture_consistency",
                "source": "qe_host_stage_reference_capture",
                "timing_only": False,
                "component_delta_l2_norms": dict(stage_decomposition.get("component_delta_l2_norms", {}))
                if isinstance(stage_decomposition.get("component_delta_l2_norms", {}), Mapping)
                else {},
                "claim_boundary": "Stage decomposition only; not a hardware recompute of full h_psi.",
            }
        )
    if isinstance(vloc_component_result, Mapping):
        rows.append(
            {
                "kernel_id": "h_psi_vloc_delta_component",
                "kernel_scope": "partial_h_psi_vloc_delta_component",
                "full_kernel_recomputed": False,
                "partial_component_only": True,
                "absolute_error": vloc_component_result.get("absolute_error"),
                "relative_error": vloc_component_result.get("relative_error"),
                "error_metric": "qe_vloc_delta_stage_reference",
                "source": "gem5_generic_accel_qe_extension",
                "timing_only": False,
                "computed_element_count": vloc_component_result.get("computed_element_count"),
                "target_l2_norm": vloc_component_result.get("target_l2_norm"),
                "claim_boundary": "Partial Vloc delta component only; not sufficient for full h_psi correctness.",
            }
        )
    if isinstance(vnl_component_result, Mapping):
        rows.append(
            {
                "kernel_id": "h_psi_vnl_delta_component",
                "kernel_scope": "partial_h_psi_vnl_delta_component",
                "full_kernel_recomputed": False,
                "partial_component_only": True,
                "absolute_error": vnl_component_result.get("absolute_error"),
                "relative_error": vnl_component_result.get("relative_error"),
                "error_metric": "qe_vnl_delta_stage_reference",
                "source": "gem5_generic_accel_qe_extension",
                "timing_only": False,
                "computed_element_count": vnl_component_result.get("computed_element_count"),
                "target_l2_norm": vnl_component_result.get("target_l2_norm"),
                "becp_reference_relative_error": vnl_component_result.get("becp_reference_relative_error"),
                "claim_boundary": "Partial Vnl delta component only; not sufficient for full h_psi correctness.",
            }
        )
    if (
        isinstance(kinetic_component_result, Mapping)
        and isinstance(stage_decomposition, Mapping)
        and isinstance(vloc_component_result, Mapping)
        and isinstance(vnl_component_result, Mapping)
        and kinetic_component_result.get("status") == "passed"
        and vloc_component_result.get("status") == "passed"
        and vnl_component_result.get("status") == "passed"
    ):
        component_deltas = (
            stage_decomposition.get("component_delta_l2_norms", {})
            if isinstance(stage_decomposition.get("component_delta_l2_norms", {}), Mapping)
            else {}
        )
        stage_l2 = (
            stage_decomposition.get("stage_l2_norms", {})
            if isinstance(stage_decomposition.get("stage_l2_norms", {}), Mapping)
            else {}
        )
        post_vnl_adjustment = _float(component_deltas.get("after_vnl_to_final"), 0.0)
        if post_vnl_adjustment <= 1.0e-12:
            kinetic_error = _float(kinetic_component_result.get("qe_kinetic_reference_error_l2_norm"), 0.0)
            vloc_error = _float(vloc_component_result.get("absolute_error"), 0.0)
            vnl_error = _float(vnl_component_result.get("absolute_error"), 0.0)
            aggregate_error = (kinetic_error**2 + vloc_error**2 + vnl_error**2 + post_vnl_adjustment**2) ** 0.5
            final_l2 = _float(stage_l2.get("final"), 0.0)
            rows.append(
                {
                    "kernel_id": "h_psi",
                    "kernel_scope": "full_h_psi",
                    "full_kernel_recomputed": True,
                    "boundary_norm_probe_only": False,
                    "partial_component_only": False,
                    "absolute_error": aggregate_error,
                    "relative_error": aggregate_error / max(final_l2, 1.0e-300),
                    "error_metric": "component_sum_vs_qe_hpsi_stage_reference",
                    "source": "python_qe_hpsi_component_model",
                    "timing_only": False,
                    "component_rows": [
                        "h_psi_kinetic_component",
                        "h_psi_vloc_delta_component",
                        "h_psi_vnl_delta_component",
                    ],
                    "claim_boundary": (
                        "Full h_psi numerical component recompute for this captured QE boundary only; "
                        "not by itself L4 hardware/offload closure."
                    ),
                }
            )
    return rows


def build_sidecar_offload_provenance(
    *,
    sidecar_result: Mapping[str, Any],
    producer: str,
    density_residual: float = 0.0,
) -> Dict[str, Any]:
    """Build provenance for the sidecar probe without upgrading it to full correctness."""
    return {
        "producer": producer,
        "accelerated_runtime": "gem5_generic_accel_qe_extension",
        "offload_target": "generic_systemc_bridge",
        "timing_only": False,
        "baseline_copy": False,
        "fixture": False,
        "pure_software_qe_baseline": False,
        "full_h_psi_recomputed": False,
        "boundary_norm_probe_only": True,
        "physical_evidence": {"density_residual": density_residual},
        "sidecar_result_status": sidecar_result.get("status"),
        "sidecar_artifacts": dict(sidecar_result.get("artifacts", {}))
        if isinstance(sidecar_result.get("artifacts", {}), Mapping)
        else {},
        "claim_boundary": "Provenance records a real sidecar/GenericAccel bridge probe, not full QE kernel offload.",
    }


__all__ = [
    "QE_HPSI_SIDECAR_RESULT_SCHEMA",
    "build_hpsi_boundary_probe_request",
    "build_sidecar_kernel_evidence",
    "build_sidecar_offload_provenance",
    "build_sidecar_result",
    "compute_hpsi_kinetic_component",
    "compute_hpsi_vloc_delta_component",
    "compute_hpsi_vnl_delta_component",
    "compute_hpsi_stage_decomposition",
    "build_hpsi_component_closure_report",
    "build_hpsi_component_target_arrays",
    "load_hpsi_boundary_arrays",
    "load_hpsi_boundary_snapshot",
]
