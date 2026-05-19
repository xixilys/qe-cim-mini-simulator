#!/usr/bin/env python3
"""GenericAccel/SystemC sidecar adapter for QE ``h_psi`` component payloads.

This executable is intentionally shaped like a ``generic_sim`` sidecar:
``--request <json> --result <json>``.  The gem5 GenericAccel model can invoke
it through the existing ``--use-systemc`` path.  The adapter then reuses the
QE h_psi component sidecar to write the consumable text payload that QE can
read back.

Claim boundary: this proves GenericAccel sidecar transport can invoke the QE
component model and produce a QE-consumable payload.  It does **not** make the
Python component model a trusted non-software L4 implementation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.scripts.dse.run_qe_hpsi_component_sidecar import run as run_component_sidecar  # noqa: E402


SCHEMA = "dse.qe_hpsi_component_gsim_sidecar_result.v1"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_repo_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value))
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _component_payload(request: Mapping[str, Any]) -> Mapping[str, Any]:
    extension = request.get("extension_payload", {})
    if not isinstance(extension, Mapping):
        return {}
    explicit = extension.get("qe_hpsi_component_sidecar", {})
    if isinstance(explicit, Mapping) and explicit:
        return explicit
    evidence = extension.get("qe_accelerated_numeric_evidence", {})
    if isinstance(evidence, Mapping):
        accelerated_reference = evidence.get("accelerated_reference", {})
        if isinstance(accelerated_reference, Mapping):
            return accelerated_reference
    return {}


def _path_from_payload(payload: Mapping[str, Any], *names: str) -> Path | None:
    for name in names:
        path = _resolve_repo_path(payload.get(name))
        if path is not None:
            return path
    return None


def _payload_mode(request: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    explicit = str(payload.get("payload_mode") or "").strip()
    if explicit:
        return explicit
    dispatch = request.get("sidecar_dispatch", {})
    if isinstance(dispatch, Mapping):
        return str(dispatch.get("payload_mode") or "component_model").strip() or "component_model"
    return "component_model"


def _run_native_payload(
    *,
    native_payload: Path,
    boundary_arrays: Path,
    result_txt: Path,
    summary_json: Path,
) -> tuple[int, Mapping[str, Any]]:
    completed = subprocess.run(
        [
            str(native_payload),
            "--boundary-arrays",
            str(boundary_arrays),
            "--result-txt",
            str(result_txt),
            "--summary-json",
            str(summary_json),
            "--fail-on-blocked",
            "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if summary_json.exists():
        loaded = _load_json(summary_json)
        if isinstance(loaded, Mapping):
            return completed.returncode, loaded
    return completed.returncode, {
        "status": "blocked",
        "blockers": [
            f"native_hpsi_payload_missing_summary:{summary_json}",
            f"native_hpsi_payload_returncode:{completed.returncode}",
        ],
        "native_payload_stdout": completed.stdout,
        "native_payload_stderr": completed.stderr,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    request = _load_json(args.request)
    if not isinstance(request, Mapping):
        raise ValueError(f"request must be a JSON object: {args.request}")
    payload = _component_payload(request)
    payload_mode = _payload_mode(request, payload)
    boundary_arrays = _path_from_payload(payload, "boundary_arrays_json", "kernel_boundary_arrays_json")
    result_txt = _path_from_payload(payload, "result_txt", "hpsi_component_sidecar_result_txt")
    summary_json = _path_from_payload(payload, "summary_json", "hpsi_component_sidecar_summary_json")
    native_payload = _path_from_payload(payload, "native_payload_executable", "native_hpsi_payload_executable")

    blockers: list[str] = []
    for label, path in [
        ("boundary_arrays_json", boundary_arrays),
        ("result_txt", result_txt),
        ("summary_json", summary_json),
    ]:
        if path is None:
            blockers.append(f"missing_qe_hpsi_component_sidecar_payload:{label}")
    if boundary_arrays is not None and not boundary_arrays.exists():
        blockers.append(f"missing_boundary_arrays_json:{boundary_arrays}")

    component_rc = 2
    component_summary: Mapping[str, Any] = {}
    if not blockers and boundary_arrays is not None and result_txt is not None and summary_json is not None:
        if payload_mode == "native_l4":
            if native_payload is None:
                blockers.append("missing_native_hpsi_payload_executable")
            elif not native_payload.exists():
                blockers.append(f"native_hpsi_payload_executable_missing:{native_payload}")
            else:
                component_rc, component_summary = _run_native_payload(
                    native_payload=native_payload,
                    boundary_arrays=boundary_arrays,
                    result_txt=result_txt,
                    summary_json=summary_json,
                )
        else:
            component_rc = run_component_sidecar(
                [
                    "--boundary-arrays",
                    str(boundary_arrays),
                    "--result-txt",
                    str(result_txt),
                    "--summary-json",
                    str(summary_json),
                    "--quiet",
                ]
            )
        if summary_json.exists():
            loaded = _load_json(summary_json)
            if isinstance(loaded, Mapping):
                component_summary = loaded
        if component_rc != 0:
            blockers.append(f"component_sidecar_returncode:{component_rc}")
        expected_status = "passed_native_l4_payload" if payload_mode == "native_l4" else "passed_component_model"
        if component_summary.get("status") != expected_status:
            blockers.append(f"component_sidecar_status:{component_summary.get('status')}")

    status = "passed" if not blockers else "blocked"
    trusted_native_payload = (
        payload_mode == "native_l4"
        and status == "passed"
        and component_summary.get("trusted_full_claim") is True
        and component_summary.get("software_component_model_not_l4") is not True
    )
    result = {
        "schema_version": SCHEMA,
        "run_id": str(request.get("run_id", "unknown")),
        "status": status,
        "blockers": sorted(dict.fromkeys(blockers)),
        "payload_mode": payload_mode,
        "artifacts": {
            "request_json": str(args.request),
            "boundary_arrays_json": str(boundary_arrays) if boundary_arrays is not None else None,
            "hpsi_result_txt": str(result_txt) if result_txt is not None else None,
            "component_summary_json": str(summary_json) if summary_json is not None else None,
            "native_payload_executable": str(native_payload) if native_payload is not None else None,
        },
        "component_summary_status": component_summary.get("status"),
        "full_h_psi_recomputed": component_summary.get("full_h_psi_recomputed") is True,
        "software_component_model_not_l4": False if trusted_native_payload else True,
        "trusted_full_claim": trusted_native_payload,
        "claim_boundary": (
            "GenericAccel/SystemC sidecar transport invoked a native h_psi payload model. "
            "This is SystemC/GenericAccel model L4 offload plus kernel numerical evidence, not silicon/RTL proof."
            if trusted_native_payload
            else "GenericAccel/SystemC sidecar transport invoked a Python QE h_psi component model. "
            "This is transport/foundation evidence only, not trusted non-software L4 offload evidence."
        ),
    }
    _write_json(args.result, result)
    if not args.quiet:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if status == "passed" else 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
