#!/usr/bin/env python3
"""Build a QE ``h_psi`` component sidecar result for mainflow consumption.

This helper is intentionally a **bridge milestone**, not a trusted L4 offload.
It consumes the boundary/stage arrays emitted by the instrumented QE ``h_psi``
runtime and writes a flat text result that the QE process can read back into
``hpsi``.  The output is marked reference-assisted because the current bridge
uses QE-captured stage arrays as its oracle.  Downstream evidence gates must
therefore keep it blocked until a future non-reference-assisted L4 runtime
produces the same contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_hpsi_sidecar import (  # noqa: E402
    build_hpsi_component_closure_report,
    compute_hpsi_kinetic_component,
    compute_hpsi_stage_decomposition,
    compute_hpsi_vloc_delta_component,
    compute_hpsi_vnl_delta_component,
    load_hpsi_boundary_arrays,
)


SCHEMA = "dse.qe_hpsi_component_sidecar_consumable_result.v1"


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


def _complex_pairs(values: Any) -> list[complex]:
    return [_complex_pair(item) for item in values] if isinstance(values, list) else []


def _l2_norm(values: Sequence[complex]) -> float:
    return sum((abs(value) ** 2 for value in values), 0.0) ** 0.5


def _component_status(payload: Mapping[str, Any] | None) -> str:
    return str(payload.get("status") if isinstance(payload, Mapping) else "missing")


def _fft_shape_from_descriptor(fft_descriptor: Mapping[str, Any], nnr: int) -> tuple[int, int, int] | None:
    for key in ("nrx", "nr"):
        raw = fft_descriptor.get(key)
        if not isinstance(raw, list) or len(raw) != 3:
            continue
        shape = tuple(_int(item, 0) for item in raw)
        if all(item > 0 for item in shape) and shape[0] * shape[1] * shape[2] == nnr:
            return (shape[0], shape[1], shape[2])
    return None


def _compute_full_hpsi_component_model(arrays: Mapping[str, Any]) -> tuple[list[complex], list[str]]:
    """Return a Python-computed full ``h_psi`` array for the supported k-point path."""
    blockers: list[str] = []
    try:
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - environment-specific
        return [], [f"numpy_unavailable_for_full_component_model:{exc}"]

    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    lda = _int(dimensions.get("lda"), 0)
    n = _int(dimensions.get("n"), 0)
    m = _int(dimensions.get("m"), 0)
    npol = _int(arrays.get("npol"), 1)
    if npol != 1:
        blockers.append(f"full_component_model_npol_not_supported:{npol}")
    element_count = lda * max(1, npol) * m
    psi_values = _complex_pairs(arrays.get("psi_real_imag", []))
    g2kin = [_float(item) for item in arrays.get("g2kin", [])]
    if lda <= 0 or n <= 0 or m <= 0:
        blockers.append(f"invalid_dimensions_for_full_component_model:{lda}:{n}:{m}")
    if len(psi_values) != element_count:
        blockers.append(f"psi_array_length_mismatch:{len(psi_values)}:{element_count}")
    if len(g2kin) < lda:
        blockers.append(f"g2kin_array_length_mismatch:{len(g2kin)}:{lda}")

    fft_descriptor = arrays.get("fft_descriptor_dffts", {})
    vloc_inputs = arrays.get("vloc_inputs", {})
    vloc_algorithm = arrays.get("vloc_algorithm", {})
    if not isinstance(fft_descriptor, Mapping) or not isinstance(vloc_inputs, Mapping) or not isinstance(vloc_algorithm, Mapping):
        blockers.append("missing_vloc_fft_inputs_for_full_component_model")
    elif str(vloc_algorithm.get("path") or "") != "vloc_psi_k_acc":
        blockers.append(f"vloc_algorithm_path_not_supported_for_full_component_model:{vloc_algorithm.get('path')}")

    vnl_inputs = arrays.get("vnl_inputs", {})
    if not isinstance(vnl_inputs, Mapping):
        blockers.append("missing_vnl_inputs_for_full_component_model")
    elif str(vnl_inputs.get("algorithm_path") or "") != "add_vuspsi_k":
        blockers.append(f"vnl_algorithm_path_not_supported_for_full_component_model:{vnl_inputs.get('algorithm_path')}")

    if blockers:
        return [], sorted(dict.fromkeys(blockers))

    # Kinetic term.
    kinetic: list[complex] = []
    for band in range(m):
        band_base = band * lda
        for row in range(lda):
            if row < n:
                kinetic.append(g2kin[row] * psi_values[band_base + row])
            else:
                kinetic.append(0.0 + 0.0j)

    # Local potential delta: reciprocal -> real-space FFT, multiply Vrs, FFT back.
    nnr = _int(fft_descriptor.get("nnr"), 0)  # type: ignore[union-attr]
    shape = _fft_shape_from_descriptor(fft_descriptor, nnr)  # type: ignore[arg-type]
    if shape is None:
        return [], [f"fft_descriptor_shape_product_mismatch:{nnr}"]
    vrs = np.asarray([_float(item) for item in vloc_inputs.get("vrs_current_spin", [])], dtype=float)  # type: ignore[union-attr]
    igk = [_int(item) - 1 for item in vloc_inputs.get("igk_current_k", [])]  # type: ignore[union-attr]
    dffts_nl = [_int(item) - 1 for item in vloc_inputs.get("dffts_nl", [])]  # type: ignore[union-attr]
    if len(vrs) != nnr:
        return [], [f"vrs_current_spin_length_mismatch:{len(vrs)}:{nnr}"]
    reciprocal_positions = np.asarray([dffts_nl[index] for index in igk[:n]], dtype=int)
    vloc_delta: list[complex] = []
    for band in range(m):
        band_psi = psi_values[band * lda : band * lda + n]
        reciprocal_flat = np.zeros(nnr, dtype=np.complex128)
        reciprocal_flat[reciprocal_positions] = np.asarray(band_psi, dtype=np.complex128)
        reciprocal_grid = reciprocal_flat.reshape(shape, order="F")
        realspace_grid = np.fft.ifftn(reciprocal_grid)
        weighted_realspace = realspace_grid.reshape(nnr, order="F") * vrs
        weighted_grid = weighted_realspace.reshape(shape, order="F")
        vloc_reciprocal = np.fft.fftn(weighted_grid).reshape(nnr, order="F")
        band_output = [0.0 + 0.0j for _ in range(lda)]
        for row_index, value in enumerate(vloc_reciprocal[reciprocal_positions]):
            band_output[row_index] = complex(value)
        vloc_delta.extend(band_output)

    # Non-local potential delta.
    nkb = _int(vnl_inputs.get("nkb"), 0)  # type: ignore[union-attr]
    nhm = _int(vnl_inputs.get("nhm"), 0)  # type: ignore[union-attr]
    nat = _int(vnl_inputs.get("nat"), 0)  # type: ignore[union-attr]
    if nkb <= 0 or nhm <= 0 or nat <= 0:
        return [], [f"vnl_positive_dimension_missing:{nkb}:{nhm}:{nat}"]
    psi_matrix = np.asarray(psi_values, dtype=np.complex128).reshape((m, lda)).T
    vkb = np.asarray(_complex_pairs(vnl_inputs.get("vkb_real_imag", [])), dtype=np.complex128).reshape((nkb, lda)).T  # type: ignore[union-attr]
    deeq = np.asarray(vnl_inputs.get("deeq_current_spin", []), dtype=float).reshape((nat, nhm, nhm))  # type: ignore[union-attr]
    nh = [_int(item) for item in vnl_inputs.get("nh", [])]  # type: ignore[union-attr]
    ityp = [_int(item) - 1 for item in vnl_inputs.get("ityp", [])]  # type: ignore[union-attr]
    ofsbeta = [_int(item) for item in vnl_inputs.get("ofsbeta", [])]  # type: ignore[union-attr]
    becp = vkb[:n, :].conj().T @ psi_matrix[:n, :]
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
    vnl_delta = [complex(value) for value in padded.T.reshape(lda * m)]

    return [left + middle + right for left, middle, right in zip(kinetic, vloc_delta, vnl_delta)], []


def _build_consumable_result(arrays: Mapping[str, Any]) -> Dict[str, Any]:
    dimensions = arrays.get("dimensions", {}) if isinstance(arrays.get("dimensions", {}), Mapping) else {}
    reference_hpsi = _complex_pairs(arrays.get("hpsi_reference_real_imag", []))
    blockers: list[str] = []
    if not reference_hpsi:
        blockers.append("missing_hpsi_reference_real_imag_for_consumable_sidecar")

    kinetic = compute_hpsi_kinetic_component(arrays)
    vloc = compute_hpsi_vloc_delta_component(arrays)
    vnl = compute_hpsi_vnl_delta_component(arrays)
    stages = compute_hpsi_stage_decomposition(arrays)
    closure = build_hpsi_component_closure_report(
        kinetic_component_result=kinetic,
        stage_decomposition=stages,
        vloc_component_result=vloc,
        vnl_component_result=vnl,
    )
    component_statuses = {
        "kinetic": _component_status(kinetic),
        "vloc": _component_status(vloc),
        "vnl": _component_status(vnl),
        "stages": _component_status(stages),
        "closure": _component_status(closure),
    }
    for component, status in component_statuses.items():
        if component in {"kinetic", "vloc", "vnl", "stages"} and status != "passed":
            blockers.append(f"component_sidecar_{component}_not_passed:{status}")
    if closure.get("missing_compute_components"):
        blockers.append(
            "component_sidecar_closure_missing_components:"
            + ",".join(str(item) for item in closure.get("missing_compute_components", []))
        )

    computed_hpsi, compute_blockers = _compute_full_hpsi_component_model(arrays)
    blockers.extend(compute_blockers)
    if computed_hpsi and reference_hpsi:
        errors = [left - right for left, right in zip(computed_hpsi, reference_hpsi)]
        absolute_error = _l2_norm(errors)
        reference_l2 = _l2_norm(reference_hpsi)
        relative_error = absolute_error / max(reference_l2, 1.0e-300)
        if not (absolute_error <= 1.0e-12 or relative_error <= 1.0e-12):
            blockers.append(f"full_component_model_numeric_mismatch:{relative_error:.6e}")
    else:
        absolute_error = None
        reference_l2 = _l2_norm(reference_hpsi)
        relative_error = None
    full_component_model_passed = not blockers and bool(computed_hpsi)
    return {
        "schema_version": SCHEMA,
        "status": "passed_component_model" if full_component_model_passed else "blocked",
        "kernel_id": "h_psi",
        "kernel_scope": "full_h_psi",
        "dimensions": dict(dimensions),
        "element_count": len(reference_hpsi),
        "reference_hpsi_l2_norm": reference_l2,
        "result_hpsi_l2_norm": _l2_norm(computed_hpsi) if computed_hpsi else None,
        "absolute_error_to_qe_stage_reference": absolute_error,
        "relative_error_to_qe_stage_reference": relative_error,
        "component_statuses": component_statuses,
        "component_blockers": {
            "kinetic": kinetic.get("blockers", []) if isinstance(kinetic, Mapping) else ["missing_kinetic_result"],
            "vloc": vloc.get("blockers", []) if isinstance(vloc, Mapping) else ["missing_vloc_result"],
            "vnl": vnl.get("blockers", []) if isinstance(vnl, Mapping) else ["missing_vnl_result"],
            "stages": stages.get("blockers", []) if isinstance(stages, Mapping) else ["missing_stage_result"],
            "closure": closure.get("missing_compute_components", [])
            if isinstance(closure, Mapping)
            else ["missing_closure_result"],
        },
        "hpsi_result_real_imag": [[value.real, value.imag] for value in computed_hpsi],
        "blockers": sorted(dict.fromkeys(blockers)),
        "full_h_psi_recomputed": full_component_model_passed,
        "software_component_model_not_l4": True,
        "host_stage_reference_assisted": False,
        "component_model_reference_replay_only": False,
        "trusted_full_claim": False,
        "claim_boundary": (
            "QE can consume this Python component-model h_psi payload as a mainflow "
            "integration smoke, but it is software-sidecar evidence and not trusted L4/offload evidence."
        ),
    }


def _write_result_txt(path: Path, result: Mapping[str, Any]) -> None:
    values = result.get("hpsi_result_real_imag", [])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if isinstance(values, list):
            for value in values:
                pair = _complex_pair(value)
                handle.write(f"{pair.real:.17e} {pair.imag:.17e}\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary-arrays", type=Path, required=True)
    parser.add_argument("--result-txt", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "Do not print the full result JSON to stdout. This is important when QE invokes "
            "the sidecar hundreds or thousands of times and the producer captures QE stdout."
        ),
    )
    parser.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="Return non-zero if component checks block the consumable payload.",
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    arrays = load_hpsi_boundary_arrays(args.boundary_arrays)
    result = _build_consumable_result(arrays)
    _write_result_txt(args.result_txt, result)
    result["result_txt"] = str(args.result_txt)
    result["boundary_arrays"] = str(args.boundary_arrays)
    _write_json(args.summary_json, result)
    if not args.quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and result.get("status") == "blocked" else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
