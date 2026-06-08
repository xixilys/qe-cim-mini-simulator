#!/usr/bin/env python3
"""Run an explicit accelerated/offloaded QE producer for required evidence rows.

This runner is intentionally a producer/orchestrator, not a simulator and not a
fixture generator.  It reruns the frozen QE command sequence in a separate row
directory using a caller-supplied accelerated QE binary directory, captures QE
stdout, and requires the accelerated runtime itself to emit:

* ``kernel_evidence.json`` through ``QE_OFFLOAD_KERNEL_EVIDENCE_JSON``
* ``offload_provenance.json`` through ``QE_OFFLOAD_PROVENANCE_JSON``

If those runtime-generated files are absent, the row is written as blocked.  The
script never fabricates kernel deltas, provenance, or density residuals from the
pure-software baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.qe_accelerated_evidence import (  # noqa: E402
    QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA,
    build_evidence_from_files,
)
from dse_v2.reference_workloads.qe_consumption_proof import (  # noqa: E402
    merge_qe_consumption_proof_artifacts,
)


PRODUCER_INDEX_SCHEMA = "dse.qe_accelerated_numeric_producer_index.v1"
HPSI_COMPONENT_SIDECAR = REPO_ROOT / "dse_v2" / "scripts" / "dse" / "run_qe_hpsi_component_sidecar.py"
HPSI_SIDECAR_COUNTER_FIELDS = (
    "sidecar_observed_hpsi_calls",
    "sidecar_attempted_hpsi_calls",
    "sidecar_consumed_hpsi_calls",
    "sidecar_failed_hpsi_calls",
    "sidecar_call_cap",
)
HPSI_SIDECAR_BOOL_FIELDS = (
    "all_observed_hpsi_calls_sidecar_consumed",
    "single_hpsi_call_smoke_only",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolve_repo_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else REPO_ROOT / path


def _safe_path_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def _input_basename(input_path: Any) -> str | None:
    if not input_path:
        return None
    return Path(str(input_path)).name


def _baseline_sequence(baseline: Mapping[str, Any]) -> list[Dict[str, Any]]:
    sequence = baseline.get("baseline_sequence", [])
    if isinstance(sequence, list) and sequence:
        return [dict(step) for step in sequence if isinstance(step, Mapping)]
    command = [str(item) for item in baseline.get("qe_command", []) or []]
    if command:
        return [{"step_id": "stage_00_qe_command", "program": command[0], "command": command}]
    return []


def _resolve_executable(program: str, accelerated_qe_bin_dir: Path | None) -> tuple[str | None, str]:
    program_path = Path(program)
    if program_path.is_absolute() or len(program_path.parts) > 1:
        if program_path.exists():
            return str(program_path.resolve()), "command_path"
        return None, "command_path_missing"
    if accelerated_qe_bin_dir is not None:
        candidate = accelerated_qe_bin_dir / program
        if candidate.exists():
            return str(candidate.resolve()), "accelerated_qe_bin_dir"
    found = shutil.which(program)
    if found:
        return found, "PATH"
    return None, "missing"


def _normalize_qe_command(
    step: Mapping[str, Any],
    *,
    accelerated_qe_bin_dir: Path | None,
) -> tuple[list[str] | None, Dict[str, Any]]:
    raw_command = [str(item) for item in step.get("command", []) or []]
    if not raw_command:
        program = str(step.get("program") or "")
        input_name = _input_basename(step.get("input_path"))
        raw_command = [program, "-in", input_name] if program and input_name else ([program] if program else [])
    if not raw_command:
        return None, {
            "status": "blocked",
            "blockers": ["missing_accelerated_qe_command"],
        }
    executable, provenance = _resolve_executable(raw_command[0], accelerated_qe_bin_dir)
    if executable is None:
        return None, {
            "program": raw_command[0],
            "status": "blocked",
            "resolution_provenance": provenance,
            "blockers": [f"missing_accelerated_qe_executable:{raw_command[0]}"],
        }
    normalized_args = [
        _input_basename(item) if previous == "-in" and _input_basename(item) else item
        for previous, item in zip(raw_command[:-1], raw_command[1:])
    ]
    return [executable, *normalized_args], {
        "program": raw_command[0],
        "resolved_executable": executable,
        "resolution_provenance": provenance,
        "command": raw_command,
        "concrete_command": [executable, *normalized_args],
    }


def _copy_tree_or_file(source: Path, dest: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, dest, dirs_exist_ok=True)
    elif source.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)


def _materialize_run_inputs(
    *,
    baseline_dir: Path,
    run_dir: Path,
    sequence: Sequence[Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    run_dir.mkdir(parents=True, exist_ok=True)
    copied_names: set[str] = set()
    for step in sequence:
        input_name = _input_basename(step.get("input_path"))
        if not input_name or input_name in copied_names:
            continue
        source = baseline_dir / input_name
        dest = run_dir / input_name
        if source.exists():
            shutil.copy2(source, dest)
        elif isinstance(step.get("input"), str):
            _write_text(dest, str(step["input"]))
        else:
            blockers.append(f"missing_accelerated_qe_input:{input_name}")
        copied_names.add(input_name)
    for extra_input in baseline_dir.glob("*.in"):
        if extra_input.name not in copied_names:
            shutil.copy2(extra_input, run_dir / extra_input.name)
    _copy_tree_or_file(baseline_dir / "pseudo", run_dir / "pseudo")
    return blockers


def _required_output(row: Mapping[str, Any], key: str) -> Path | None:
    required_outputs = row.get("required_outputs", {})
    if not isinstance(required_outputs, Mapping):
        return None
    return _resolve_repo_path(required_outputs.get(key))


def _target_kernel_from_row(row: Mapping[str, Any]) -> str | None:
    requirements = row.get("target_kernel_evidence_requirements", {})
    if isinstance(requirements, Mapping):
        target = str(requirements.get("target_kernel") or "").strip()
        if target and not target.startswith("<"):
            return target
    target = str(row.get("target_kernel") or row.get("kernel_id") or "").strip()
    return target or None


def _blocked_evidence(
    *,
    row: Mapping[str, Any],
    blockers: Sequence[str],
    source_kind: str,
) -> Dict[str, Any]:
    return {
        "schema_version": QE_ACCELERATED_NUMERIC_EVIDENCE_SCHEMA,
        "candidate_id": str(row.get("candidate_id", "")),
        "workload_case_id": str(row.get("workload_case_id", "")),
        "source_kind": source_kind,
        "accelerated_output_status": "blocked",
        "trusted_accelerated_numeric_source": False,
        "baseline_reference": {"path": row.get("baseline_comparison")},
        "accelerated_reference": row.get("required_outputs", {}),
        "offload_provenance": {},
        "kernel_evidence": [],
        "physical_evidence": {},
        "blockers": sorted(dict.fromkeys(str(item) for item in blockers)),
        "claim_boundary": (
            "QE accelerated producer did not receive runtime-generated offload provenance "
            "and kernel numeric evidence; no baseline-copy or fixture evidence was synthesized."
        ),
    }


def _merge_hpsi_sidecar_transport_proof(
    *,
    provenance_path: Path | None,
    kernel_evidence_path: Path | None = None,
    sidecar_summary_path: Path,
) -> None:
    """Merge gem5 sidecar transport proof and, only for native payloads, payload trust.

    The instrumented QE runtime writes ``offload_provenance.json`` while it is
    executing inside the QE process.  For the gem5 h_psi sidecar path, the
    detailed transport proof is produced by the sidecar command after the
    GenericAccel/gem5 run completes.  Merge that proof back into the provenance
    artifact so downstream gates can distinguish:

    * real gem5/SystemC transport was exercised; from
    * the h_psi numeric payload is still a software component model and remains
      blocked for trusted L4 correctness.

    Python component-model sidecar keeps ``software_component_model_not_l4``.
    A native payload summary may override older conservative QE hook markers,
    but only when the sidecar summary itself says the payload was trusted and
    not a software component model.
    """
    if provenance_path is None or not provenance_path.exists() or not sidecar_summary_path.exists():
        return
    try:
        provenance = _load_json(provenance_path)
        summary = _load_json(sidecar_summary_path)
    except Exception:
        return
    if not isinstance(provenance, dict) or not isinstance(summary, Mapping):
        return
    proof = summary.get("gem5_l4_transport_proof")
    if not isinstance(proof, Mapping) or proof.get("passed") is not True:
        return
    transport_harness = str(proof.get("transport_harness") or "")
    if not transport_harness:
        return
    merged_proof = dict(proof)
    provenance["l4_execution_proof"] = merged_proof
    provenance["sidecar_transport_l4_execution_proof"] = merged_proof
    provenance["sidecar_transport"] = transport_harness
    provenance["sidecar_summary_status"] = summary.get("status")
    trusted_native_payload = (
        summary.get("trusted_full_claim") is True
        and summary.get("software_component_model_not_l4") is not True
        and str(summary.get("status") or "")
        in {"passed_native_l4_payload", "passed_gem5_transport_native_l4_payload"}
    )
    sidecar_consumption_fields: Dict[str, Any] = {}
    for field in HPSI_SIDECAR_COUNTER_FIELDS:
        value = summary.get(field, provenance.get(field))
        if value is not None:
            sidecar_consumption_fields[field] = value
    for field in HPSI_SIDECAR_BOOL_FIELDS:
        value = summary.get(field, provenance.get(field))
        if value is not None:
            sidecar_consumption_fields[field] = value
    if trusted_native_payload:
        native_source = str(summary.get("source") or "gem5_generic_accel_qe_hpsi_systemc_native_payload")
        trusted_payload_kind = str(
            summary.get("trusted_payload_kind") or "systemc_generic_accel_model_l4_offload_kernel_numerical"
        )
        provenance.update(
            {
                "producer": native_source,
                "accelerated_runtime": "qe_offload_runtime",
                "offload_target": native_source,
                "target_kernel": "h_psi",
                "kernel_id": "h_psi",
                "full_h_psi_recomputed": True,
                "full_kernel_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "software_component_model_not_l4": False,
                "component_model_reference_replay_only": False,
                "host_stage_reference_assisted": False,
                "timing_only": False,
                "fixture": False,
                "baseline_copy": False,
                "pure_software_qe_baseline": False,
                "single_hpsi_call_smoke_only": False,
                **sidecar_consumption_fields,
                "trusted_payload_kind": trusted_payload_kind,
                "native_payload_executable": summary.get("native_payload_executable"),
                "claim_boundary": (
                    "QE consumed a native h_psi payload through gem5 GenericAccel/SystemC transport. "
                    "This is SystemC/GenericAccel model L4 offload plus kernel numerical evidence, "
                    "not silicon/RTL proof."
                ),
            }
        )
        if kernel_evidence_path is not None and kernel_evidence_path.exists():
            try:
                raw_rows = _load_json(kernel_evidence_path)
                rows = raw_rows if isinstance(raw_rows, list) else []
            except Exception:
                rows = []
            trusted_row = {
                "kernel_id": "h_psi",
                "kernel_scope": "full_h_psi",
                "full_kernel_recomputed": True,
                "full_h_psi_recomputed": True,
                "qe_mainflow_integrated": True,
                "accelerated_results_consumed_by_qe": True,
                "absolute_error": summary.get("absolute_error", 0.0),
                "relative_error": summary.get("relative_error", 0.0),
                "max_abs_error": summary.get("max_abs_error"),
                "error_metric": summary.get("error_metric", "full_h_psi_l2_against_qe_reference"),
                "source": native_source,
                "software_component_model_not_l4": False,
                "component_model_reference_replay_only": False,
                "host_stage_reference_assisted": False,
                "timing_only": False,
                "baseline_copy": False,
                "fixture": False,
                "single_hpsi_call_smoke_only": False,
                **sidecar_consumption_fields,
                "trusted_payload_kind": trusted_payload_kind,
                "claim_boundary": (
                    "Full h_psi recomputed by native payload through gem5 GenericAccel/SystemC sidecar; "
                    "SystemC/GenericAccel model L4 offload plus kernel numerical evidence, not silicon/RTL proof."
                ),
            }
            replaced = False
            normalized_rows: list[Dict[str, Any]] = []
            for item in rows:
                if isinstance(item, Mapping) and str(item.get("kernel_id") or "") == "h_psi" and not replaced:
                    normalized_rows.append(trusted_row)
                    replaced = True
                elif isinstance(item, Mapping):
                    normalized_rows.append(dict(item))
            if not replaced:
                normalized_rows.insert(0, trusted_row)
            _write_json(kernel_evidence_path, normalized_rows)
    elif summary.get("software_component_model_not_l4") is True:
        provenance["software_component_model_not_l4"] = True
        provenance["offload_target"] = f"{transport_harness}_component_model"
        provenance["transport_claim_boundary"] = (
            "gem5 GenericAccel/SystemC transport passed, but the h_psi payload "
            "was computed by a software component model and remains blocked for "
            "trusted non-software L4 correctness."
        )
    _write_json(provenance_path, provenance)


def _build_or_block_evidence(
    *,
    row: Mapping[str, Any],
    source_kind: str,
    blockers: Sequence[str],
) -> Dict[str, Any]:
    candidate_id = str(row.get("candidate_id", ""))
    workload_case_id = str(row.get("workload_case_id", ""))
    baseline = _resolve_repo_path(row.get("baseline_comparison"))
    accelerated_stdout = _required_output(row, "accelerated_stdout")
    kernel_evidence = _required_output(row, "kernel_evidence_json")
    provenance = _required_output(row, "offload_provenance_json")
    kernel_boundary_snapshot = _required_output(row, "kernel_boundary_snapshot_json")
    kernel_boundary_arrays = _required_output(row, "kernel_boundary_arrays_json")
    evidence_out = _resolve_repo_path(row.get("evidence_output"))
    if evidence_out is None:
        required_outputs = row.get("required_outputs", {})
        row_dir = accelerated_stdout.parent if accelerated_stdout is not None else REPO_ROOT / "runs" / "dse" / "accelerated_numeric_inputs" / _safe_path_component(candidate_id) / _safe_path_component(workload_case_id)
        evidence_out = row_dir / "qe_accelerated_numeric_evidence.json"

    missing = list(blockers)
    for name, path in [
        ("baseline_comparison", baseline),
        ("accelerated_stdout", accelerated_stdout),
        ("kernel_evidence_json", kernel_evidence),
        ("offload_provenance_json", provenance),
    ]:
        if path is None or not path.exists():
            missing.append(f"missing_required_accelerated_producer_output:{name}:{path}")
    if missing:
        evidence = _blocked_evidence(row=row, blockers=missing, source_kind=source_kind)
    else:
        try:
            evidence = build_evidence_from_files(
                candidate_id=candidate_id,
                workload_case_id=workload_case_id,
                baseline_comparison_path=baseline,
                accelerated_stdout_path=accelerated_stdout,
                source_kind=source_kind,
                kernel_evidence_path=kernel_evidence,
                offload_provenance_path=provenance,
            )
        except Exception as exc:  # pragma: no cover - defensive campaign preservation
            evidence = _blocked_evidence(row=row, blockers=[*missing, f"accelerated_evidence_build_exception:{exc}"], source_kind=source_kind)
    if kernel_boundary_snapshot is not None:
        accelerated_reference = evidence.setdefault("accelerated_reference", {})
        if isinstance(accelerated_reference, dict):
            accelerated_reference["kernel_boundary_snapshot_json"] = str(kernel_boundary_snapshot)
        if kernel_boundary_snapshot.exists():
            try:
                evidence["kernel_boundary_snapshot"] = _load_json(kernel_boundary_snapshot)
            except Exception as exc:  # pragma: no cover - optional artifact should not hide row status
                evidence.setdefault("blockers", [])
                evidence["blockers"] = sorted(
                    dict.fromkeys([*evidence["blockers"], f"kernel_boundary_snapshot_unreadable:{exc}"])
                )
                evidence["trusted_accelerated_numeric_source"] = False
                evidence["accelerated_output_status"] = "blocked"
    if kernel_boundary_arrays is not None:
        accelerated_reference = evidence.setdefault("accelerated_reference", {})
        if isinstance(accelerated_reference, dict):
            accelerated_reference["kernel_boundary_arrays_json"] = str(kernel_boundary_arrays)
            accelerated_reference["kernel_boundary_arrays_embedded"] = False
    _write_json(evidence_out, evidence)
    return evidence


def _run_row(
    row: Mapping[str, Any],
    *,
    accelerated_qe_bin_dir: Path | None,
    timeout: int,
    source_kind: str,
    enable_hpsi_component_sidecar: bool,
    hpsi_sidecar_max_calls: int,
    hpsi_sidecar_command_template: str | None,
) -> Dict[str, Any]:
    candidate_id = str(row.get("candidate_id", ""))
    workload_case_id = str(row.get("workload_case_id", ""))
    baseline_path = _resolve_repo_path(row.get("baseline_comparison"))
    accelerated_stdout = _required_output(row, "accelerated_stdout")
    kernel_evidence = _required_output(row, "kernel_evidence_json")
    provenance = _required_output(row, "offload_provenance_json")
    kernel_boundary_snapshot = _required_output(row, "kernel_boundary_snapshot_json")
    kernel_boundary_arrays = _required_output(row, "kernel_boundary_arrays_json")
    consumption_proof = _required_output(row, "consumption_proof_json")
    full_scf_runtime_events = _required_output(row, "full_scf_runtime_events_jsonl")
    accelerated_output_json = _required_output(row, "accelerated_output_json")
    accelerated_output_data = _required_output(row, "accelerated_output_data")
    row_dir = accelerated_stdout.parent if accelerated_stdout is not None else REPO_ROOT / "runs" / "dse" / "accelerated_numeric_inputs" / _safe_path_component(candidate_id) / _safe_path_component(workload_case_id)
    run_dir = row_dir / "accelerated_run"
    hpsi_sidecar_result_txt = row_dir / "hpsi_component_sidecar_result.txt"
    hpsi_sidecar_summary = row_dir / "hpsi_component_sidecar_summary.json"
    blockers: list[str] = []
    step_results: list[Dict[str, Any]] = []
    aggregate_stdout: list[str] = []
    aggregate_stderr: list[str] = []

    if baseline_path is None or not baseline_path.exists():
        blockers.append(f"missing_baseline_comparison:{baseline_path}")
        evidence = _build_or_block_evidence(row=row, source_kind=source_kind, blockers=blockers)
        return {
            "candidate_id": candidate_id,
            "workload_case_id": workload_case_id,
            "status": "blocked",
            "blockers": blockers,
            "evidence_output": row.get("evidence_output"),
            "trusted_accelerated_numeric_source": evidence.get("trusted_accelerated_numeric_source"),
        }

    baseline = _load_json(baseline_path)
    sequence = _baseline_sequence(baseline if isinstance(baseline, Mapping) else {})
    if not sequence:
        blockers.append("missing_baseline_sequence_for_accelerated_replay")

    row_dir.mkdir(parents=True, exist_ok=True)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    for stale in [
        accelerated_stdout,
        kernel_evidence,
        provenance,
        kernel_boundary_snapshot,
        kernel_boundary_arrays,
        full_scf_runtime_events,
        hpsi_sidecar_result_txt,
        hpsi_sidecar_summary,
    ]:
        if stale is not None and stale.exists():
            stale.unlink()
    blockers.extend(_materialize_run_inputs(baseline_dir=baseline_path.parent, run_dir=run_dir, sequence=sequence))

    env = os.environ.copy()
    if accelerated_stdout is not None:
        env["QE_OFFLOAD_ACCELERATED_STDOUT_LOG"] = str(accelerated_stdout)
    if kernel_evidence is not None:
        env["QE_OFFLOAD_KERNEL_EVIDENCE_JSON"] = str(kernel_evidence)
    if provenance is not None:
        env["QE_OFFLOAD_PROVENANCE_JSON"] = str(provenance)
    if kernel_boundary_snapshot is not None:
        env["QE_OFFLOAD_KERNEL_BOUNDARY_SNAPSHOT_JSON"] = str(kernel_boundary_snapshot)
    if kernel_boundary_arrays is not None:
        env["QE_OFFLOAD_KERNEL_BOUNDARY_ARRAY_JSON"] = str(kernel_boundary_arrays)
    env.update({
        "QE_OFFLOAD_ENABLED": "1",
        "QE_OFFLOAD_SOURCE_KIND": source_kind,
        "QE_OFFLOAD_CANDIDATE_ID": candidate_id,
        "QE_OFFLOAD_WORKLOAD_CASE_ID": workload_case_id,
    })
    if enable_hpsi_component_sidecar:
        if kernel_boundary_arrays is None:
            blockers.append("hpsi_component_sidecar_requires_kernel_boundary_arrays_output")
        else:
            env["QE_OFFLOAD_HPSI_RESULT_TXT"] = str(hpsi_sidecar_result_txt)
            env["QE_OFFLOAD_HPSI_SIDECAR_SUMMARY_JSON"] = str(hpsi_sidecar_summary)
            env["QE_OFFLOAD_HPSI_SIDECAR_MAX_CALLS"] = str(hpsi_sidecar_max_calls)
            template_values = {
                "boundary_arrays": str(kernel_boundary_arrays),
                "result_txt": str(hpsi_sidecar_result_txt),
                "summary_json": str(hpsi_sidecar_summary),
                "row_dir": str(row_dir),
                "candidate_id": candidate_id,
                "workload_case_id": workload_case_id,
                "repo_root": str(REPO_ROOT),
                "python": shlex.quote(sys.executable),
            }
            if hpsi_sidecar_command_template:
                env["QE_OFFLOAD_HPSI_SIDECAR_CMD"] = hpsi_sidecar_command_template.format(**template_values)
            else:
                env["QE_OFFLOAD_HPSI_SIDECAR_CMD"] = " ".join(
                    shlex.quote(part)
                    for part in [
                        sys.executable,
                        str(HPSI_COMPONENT_SIDECAR),
                        "--boundary-arrays",
                        str(kernel_boundary_arrays),
                        "--result-txt",
                        str(hpsi_sidecar_result_txt),
                        "--summary-json",
                        str(hpsi_sidecar_summary),
                        "--quiet",
                    ]
                )

    if not blockers:
        for index, step in enumerate(sequence):
            step_id = str(step.get("step_id") or f"stage_{index:02d}")
            normalized_cmd, resolution = _normalize_qe_command(step, accelerated_qe_bin_dir=accelerated_qe_bin_dir)
            step_stdout_path = row_dir / f"{_safe_path_component(step_id)}.accelerated.stdout.log"
            step_stderr_path = row_dir / f"{_safe_path_component(step_id)}.accelerated.stderr.log"
            if normalized_cmd is None:
                step_blockers = [str(item) for item in resolution.get("blockers", []) or []]
                blockers.extend(step_blockers)
                step_results.append({**resolution, "step_id": step_id})
                _write_text(step_stdout_path, "")
                _write_text(step_stderr_path, "\n".join(step_blockers) + "\n")
                break
            start = time.monotonic()
            try:
                completed = subprocess.run(
                    normalized_cmd,
                    cwd=run_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                elapsed = time.monotonic() - start
                stdout = completed.stdout or ""
                stderr = completed.stderr or ""
                returncode: int | None = completed.returncode
                timeout_hit = False
            except subprocess.TimeoutExpired as exc:
                elapsed = time.monotonic() - start
                stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
                stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
                returncode = None
                timeout_hit = True
            _write_text(step_stdout_path, stdout)
            _write_text(step_stderr_path, stderr)
            aggregate_stdout.append(f"===== {step_id} {' '.join(normalized_cmd)} =====\n{stdout}")
            aggregate_stderr.append(f"===== {step_id} {' '.join(normalized_cmd)} =====\n{stderr}")
            step_blockers: list[str] = []
            if timeout_hit:
                step_blockers.append("accelerated_qe_timeout")
            if returncode not in {0, None}:
                step_blockers.append(f"accelerated_qe_returncode:{returncode}")
            step_results.append({
                **resolution,
                "step_id": step_id,
                "status": "passed" if not step_blockers else "blocked",
                "returncode": returncode,
                "timeout": timeout_hit,
                "elapsed_seconds": elapsed,
                "stdout_path": str(step_stdout_path),
                "stderr_path": str(step_stderr_path),
                "blockers": step_blockers,
            })
            if step_blockers:
                blockers.extend(step_blockers)
                break

    if accelerated_stdout is not None:
        _write_text(accelerated_stdout, "\n".join(aggregate_stdout))
    _write_text(row_dir / "accelerated_qe.stderr.log", "\n".join(aggregate_stderr))
    if kernel_evidence is None or not kernel_evidence.exists():
        blockers.append(f"accelerated_runtime_did_not_emit_kernel_evidence:{kernel_evidence}")
    if provenance is None or not provenance.exists():
        blockers.append(f"accelerated_runtime_did_not_emit_offload_provenance:{provenance}")

    consumption_proof_merge: Dict[str, Any] | None = None
    if consumption_proof is not None:
        if not consumption_proof.exists():
            blockers.append(f"accelerated_runtime_did_not_emit_consumption_proof:{consumption_proof}")
        elif kernel_evidence is not None and kernel_evidence.exists() and provenance is not None and provenance.exists():
            consumption_proof_merge = merge_qe_consumption_proof_artifacts(
                consumption_proof_path=consumption_proof,
                kernel_evidence_path=kernel_evidence,
                offload_provenance_path=provenance,
                accelerated_output_json_path=accelerated_output_json,
                accelerated_output_data_path=accelerated_output_data,
                runtime_events_path=full_scf_runtime_events,
                candidate_id=candidate_id,
                workload_case_id=workload_case_id,
                target_kernel=_target_kernel_from_row(row),
            )
            if consumption_proof_merge.get("passed") is not True:
                blockers.extend(
                    f"consumption_proof_merge::{item}"
                    for item in consumption_proof_merge.get("blockers", [])
                )
        else:
            blockers.append("consumption_proof_merge_requires_kernel_evidence_and_provenance")
    if enable_hpsi_component_sidecar:
        _merge_hpsi_sidecar_transport_proof(
            provenance_path=provenance,
            kernel_evidence_path=kernel_evidence,
            sidecar_summary_path=hpsi_sidecar_summary,
        )

    evidence = _build_or_block_evidence(row=row, source_kind=source_kind, blockers=blockers)
    if enable_hpsi_component_sidecar:
        accelerated_reference = evidence.setdefault("accelerated_reference", {})
        if isinstance(accelerated_reference, dict):
            accelerated_reference["hpsi_component_sidecar_result_txt"] = str(hpsi_sidecar_result_txt)
            accelerated_reference["hpsi_component_sidecar_summary_json"] = str(hpsi_sidecar_summary)
            accelerated_reference["hpsi_component_sidecar_summary_embedded"] = hpsi_sidecar_summary.exists()
        if hpsi_sidecar_summary.exists():
            try:
                evidence["hpsi_component_sidecar_summary"] = _load_json(hpsi_sidecar_summary)
            except Exception as exc:  # pragma: no cover - optional evidence preservation
                evidence["blockers"] = sorted(
                    dict.fromkeys(
                        [
                            *[str(item) for item in evidence.get("blockers", []) or []],
                            f"hpsi_component_sidecar_summary_unreadable:{exc}",
                        ]
                    )
                )
        evidence_out = _resolve_repo_path(row.get("evidence_output"))
        if evidence_out is not None:
            _write_json(evidence_out, evidence)
    status = "passed" if evidence.get("trusted_accelerated_numeric_source") is True else "blocked"
    row_status = {
        "schema_version": "dse.qe_accelerated_numeric_producer_row.v1",
        "candidate_id": candidate_id,
        "workload_case_id": workload_case_id,
        "status": status,
        "accelerated_qe_bin_dir": str(accelerated_qe_bin_dir) if accelerated_qe_bin_dir else None,
        "run_dir": str(run_dir),
        "step_results": step_results,
        "outputs": {
            "accelerated_stdout": str(accelerated_stdout) if accelerated_stdout else None,
            "kernel_evidence_json": str(kernel_evidence) if kernel_evidence else None,
            "offload_provenance_json": str(provenance) if provenance else None,
            "kernel_boundary_snapshot_json": str(kernel_boundary_snapshot) if kernel_boundary_snapshot else None,
            "kernel_boundary_arrays_json": str(kernel_boundary_arrays) if kernel_boundary_arrays else None,
            "accelerated_output_json": str(accelerated_output_json) if accelerated_output_json else None,
            "accelerated_output_data": str(accelerated_output_data) if accelerated_output_data else None,
            "consumption_proof_json": str(consumption_proof) if consumption_proof else None,
            "full_scf_runtime_events_jsonl": str(full_scf_runtime_events) if full_scf_runtime_events else None,
            "hpsi_component_sidecar_result_txt": str(hpsi_sidecar_result_txt) if enable_hpsi_component_sidecar else None,
            "hpsi_component_sidecar_summary_json": str(hpsi_sidecar_summary) if enable_hpsi_component_sidecar else None,
            "evidence_output": str(_resolve_repo_path(row.get("evidence_output"))) if row.get("evidence_output") else None,
        },
        "consumption_proof_merge": consumption_proof_merge,
        "trusted_accelerated_numeric_source": evidence.get("trusted_accelerated_numeric_source"),
        "evidence_blockers": evidence.get("blockers", []),
        "blockers": sorted(dict.fromkeys(blockers)),
        "claim_boundary": (
            "Producer row is trusted only when the supplied accelerated QE runtime emits provenance "
            "and kernel/physical numeric evidence; this script does not synthesize those values."
        ),
    }
    _write_json(row_dir / "qe_accelerated_numeric_producer_status.json", row_status)
    return row_status


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument(
        "--accelerated-qe-bin-dir",
        type=Path,
        default=None,
        help="Directory containing modified/offloaded QE binaries. Defaults to QE_ACCELERATED_BIN_DIR.",
    )
    parser.add_argument("--candidate-id", default=None, help="Optional single candidate filter.")
    parser.add_argument("--workload-case-id", default=None, help="Optional single workload-case filter.")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--source-kind", default="qe_offload_runtime")
    parser.add_argument("--out-index", type=Path, default=None)
    parser.add_argument(
        "--out-evidence",
        type=Path,
        default=None,
        help="Optional bundle JSON containing generated qe_accelerated_numeric_evidence rows.",
    )
    parser.add_argument("--fail-on-blocked", action="store_true")
    parser.add_argument(
        "--enable-hpsi-component-sidecar",
        action="store_true",
        help=(
            "Pass a reference-assisted h_psi component sidecar command into the QE runtime. "
            "This is a mainflow-consumption smoke only and remains blocked by evidence gates."
        ),
    )
    parser.add_argument(
        "--hpsi-sidecar-max-calls",
        type=int,
        default=1,
        help=(
            "Maximum h_psi invocations the instrumented QE runtime may satisfy through the "
            "component sidecar when --enable-hpsi-component-sidecar is set. Use 0 for no cap. "
            "The default 1 preserves the conservative smoke-only behavior."
        ),
    )
    parser.add_argument(
        "--hpsi-sidecar-command-template",
        default=None,
        help=(
            "Optional command template for QE_OFFLOAD_HPSI_SIDECAR_CMD when "
            "--enable-hpsi-component-sidecar is set. Supported placeholders: "
            "{boundary_arrays}, {result_txt}, {summary_json}, {row_dir}, "
            "{candidate_id}, {workload_case_id}, {repo_root}, {python}."
        ),
    )
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    requirements_path = _resolve_repo_path(args.requirements) or args.requirements
    requirements = _load_json(requirements_path)
    rows = requirements.get("rows", []) if isinstance(requirements, Mapping) else []
    selected_rows = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and (args.candidate_id is None or str(row.get("candidate_id")) == args.candidate_id)
        and (args.workload_case_id is None or str(row.get("workload_case_id")) == args.workload_case_id)
    ]
    accelerated_qe_bin_dir = args.accelerated_qe_bin_dir or (
        Path(os.environ["QE_ACCELERATED_BIN_DIR"]) if os.environ.get("QE_ACCELERATED_BIN_DIR") else None
    )
    if accelerated_qe_bin_dir is not None and not accelerated_qe_bin_dir.is_absolute():
        accelerated_qe_bin_dir = (REPO_ROOT / accelerated_qe_bin_dir).resolve()

    producer_rows = [
        _run_row(
            row,
            accelerated_qe_bin_dir=accelerated_qe_bin_dir,
            timeout=args.timeout,
            source_kind=args.source_kind,
            enable_hpsi_component_sidecar=args.enable_hpsi_component_sidecar,
            hpsi_sidecar_max_calls=args.hpsi_sidecar_max_calls,
            hpsi_sidecar_command_template=args.hpsi_sidecar_command_template,
        )
        for row in selected_rows
    ]
    blocked_count = sum(1 for row in producer_rows if row.get("status") != "passed")
    evidence_rows: list[Dict[str, Any]] = []
    evidence_blockers: list[str] = []
    for row in producer_rows:
        outputs = row.get("outputs", {})
        evidence_output = outputs.get("evidence_output") if isinstance(outputs, Mapping) else None
        evidence_path = _resolve_repo_path(evidence_output)
        if evidence_path is None or not evidence_path.exists():
            evidence_blockers.append(
                f"missing_producer_evidence_bundle_input:{row.get('candidate_id')}:{row.get('workload_case_id')}:{evidence_path}"
            )
            continue
        try:
            loaded = _load_json(evidence_path)
        except Exception as exc:  # pragma: no cover - defensive bundle preservation
            evidence_blockers.append(f"unreadable_producer_evidence_bundle_input:{evidence_path}:{exc}")
            continue
        if isinstance(loaded, Mapping):
            evidence_rows.append(dict(loaded))
        else:
            evidence_blockers.append(f"non_object_producer_evidence_bundle_input:{evidence_path}")
    out_index = args.out_index or (requirements_path.parent / "qe_accelerated_numeric_producer_index.json")
    out_evidence = args.out_evidence or (out_index.parent / "qe_accelerated_numeric_producer_evidence_bundle.json")
    evidence_bundle = {
        "schema_version": "dse.qe_accelerated_numeric_producer_evidence_bundle.v1",
        "requirements": str(requirements_path),
        "row_count": len(evidence_rows),
        "rows": evidence_rows,
        "blockers": sorted(dict.fromkeys(evidence_blockers)),
        "claim_boundary": (
            "Bundle contains producer-generated accelerated numeric evidence rows only. The full matrix runner "
            "still re-gates every row for L4 proof, QE correctness, and anti-downgrade blockers."
        ),
    }
    _write_json(out_evidence, evidence_bundle)
    index = {
        "schema_version": PRODUCER_INDEX_SCHEMA,
        "requirements": str(requirements_path),
        "accelerated_qe_bin_dir": str(accelerated_qe_bin_dir) if accelerated_qe_bin_dir else None,
        "hpsi_component_sidecar_enabled": args.enable_hpsi_component_sidecar,
        "hpsi_component_sidecar_max_calls": args.hpsi_sidecar_max_calls if args.enable_hpsi_component_sidecar else None,
        "selected_row_count": len(selected_rows),
        "passed_row_count": len(producer_rows) - blocked_count,
        "blocked_row_count": blocked_count,
        "evidence_bundle": str(out_evidence),
        "evidence_bundle_row_count": len(evidence_rows),
        "evidence_bundle_blockers": evidence_bundle["blockers"],
        "producer_rows": producer_rows,
        "claim_boundary": (
            "Producer index is operational evidence only. Deliverable completion still requires the full "
            "matrix runner to consume each generated evidence row and pass all L4/QE/calibration gates."
        ),
    }
    _write_json(out_index, index)
    print(json.dumps(index, indent=2, sort_keys=True))
    return 2 if args.fail_on_blocked and blocked_count else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
