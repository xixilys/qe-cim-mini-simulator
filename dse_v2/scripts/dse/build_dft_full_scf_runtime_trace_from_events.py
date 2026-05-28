#!/usr/bin/env python3
"""Build a strict DFT/QE full-SCF runtime trace from measured event logs.

This command is the canonical postprocess bridge for patched QE runtimes,
GenericAccel bridges, hardware counters, or wall-clock instrumentation that
emit measured per-row events outside the QE process.  It does not invent costs
or relax the final numerical gate: the generated trace is immediately checked
through the same fail-closed trace-to-accounting validator used by the producer.
Malformed, timing-model, fixture, proofless, or incomplete event logs produce a
blocked ``full_scf_runtime_trace.json`` artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.reference_workloads.dft_full_scf_accounting import (  # noqa: E402
    FULL_SCF_RUNTIME_TRACE_SCHEMA,
    TRUSTED_RUNTIME_TRACE_SOURCES,
    UNTRUSTED_RUNTIME_TRACE_SOURCES,
    build_full_scf_row_accounting_from_runtime_trace,
)

FULL_SCF_RUNTIME_EVENT_MANIFEST_SCHEMA = "dse.dft.numerical.full_scf_runtime_event_manifest.v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists():
        payload.update({"hash_algorithm": "sha256", "hash": _sha256_file(path)})
    return payload


def _load_json_value(path: Path) -> tuple[Any | None, list[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except FileNotFoundError:
        return None, [f"runtime_trace_builder_missing_input:{path}"]
    except json.JSONDecodeError as exc:
        return None, [f"runtime_trace_builder_json_decode_failed:{path}:{exc}"]
    except OSError as exc:
        return None, [f"runtime_trace_builder_input_unreadable:{path}:{exc}"]


def _load_mapping(path: Path | None, *, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, []
    value, blockers = _load_json_value(path)
    if blockers:
        return None, blockers
    if isinstance(value, Mapping):
        return dict(value), []
    return None, [f"runtime_trace_builder_{label}_not_json_object:{path}"]


def _event_records_from_json(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("events", "runtime_events", "schedule", "schedule_events"):
            events = value.get(key)
            if isinstance(events, list):
                return [dict(item) for item in events if isinstance(item, Mapping)]
        if value.get("category"):
            return [dict(value)]
        return []
    return None


def _load_events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    value, blockers = _load_json_value(path)
    if not blockers:
        events = _event_records_from_json(value)
        if events is not None:
            return events, []

    # Fall back to JSONL so C/Python runtimes can append one event per line.
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return [], [f"runtime_trace_builder_missing_event_log:{path}"]
    except OSError as exc:
        return [], [f"runtime_trace_builder_event_log_unreadable:{path}:{exc}"]

    events: list[dict[str, Any]] = []
    jsonl_blockers: list[str] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError as exc:
            jsonl_blockers.append(f"runtime_trace_builder_jsonl_decode_failed:{path}:{index}:{exc}")
            continue
        if not isinstance(item, Mapping):
            jsonl_blockers.append(f"runtime_trace_builder_jsonl_event_not_object:{path}:{index}")
            continue
        events.append(dict(item))
    if events:
        return events, jsonl_blockers
    if jsonl_blockers:
        return [], jsonl_blockers
    return [], blockers or [f"runtime_trace_builder_events_not_list_or_object:{path}"]


def _proof_passed(proof: Mapping[str, Any] | None) -> bool:
    return isinstance(proof, Mapping) and proof.get("passed") is True


def _trusted_source(source: str) -> bool:
    normalized = source.strip().lower()
    return normalized in TRUSTED_RUNTIME_TRACE_SOURCES and normalized not in UNTRUSTED_RUNTIME_TRACE_SOURCES


def _physical_evidence(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    physical, blockers = _load_mapping(args.physical_evidence_json, label="physical_evidence")
    payload = physical or {}
    if args.density_residual is not None:
        payload["density_residual"] = args.density_residual
    return payload, blockers


def _load_event_manifest(path: Path | None) -> tuple[dict[str, Any] | None, list[str]]:
    manifest, blockers = _load_mapping(path, label="runtime_event_manifest")
    if manifest is None:
        return None, blockers
    if manifest.get("schema_version") != FULL_SCF_RUNTIME_EVENT_MANIFEST_SCHEMA:
        blockers.append("runtime_trace_builder_event_manifest_schema_mismatch")
    return manifest, blockers


def _manifest_event_coverage_blockers(
    manifest: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]],
    *,
    candidate_id: str | None,
    workload_case_id: str | None,
    measurement_source: str,
) -> list[str]:
    if manifest is None:
        return []
    blockers: list[str] = []
    manifest_candidate = str(manifest.get("candidate_id") or "").strip()
    if manifest_candidate and candidate_id and manifest_candidate != candidate_id:
        blockers.append("runtime_trace_builder_event_manifest_candidate_id_mismatch")
    manifest_workload = str(manifest.get("workload_case_id") or "").strip()
    if manifest_workload and workload_case_id and manifest_workload != workload_case_id:
        blockers.append("runtime_trace_builder_event_manifest_workload_case_id_mismatch")
    manifest_source = str(manifest.get("measurement_source") or "").strip().lower()
    if manifest_source and manifest_source != measurement_source:
        blockers.append("runtime_trace_builder_event_manifest_measurement_source_mismatch")

    required_categories = manifest.get("required_event_categories")
    if not isinstance(required_categories, Mapping):
        blockers.append("runtime_trace_builder_event_manifest_missing_required_event_categories")
        return blockers

    require_event_identity = manifest.get("required_event_identity") is True
    expected_candidate = candidate_id or manifest_candidate
    expected_workload = workload_case_id or manifest_workload

    for category, spec_value in required_categories.items():
        if not isinstance(spec_value, Mapping):
            blockers.append(f"runtime_trace_builder_event_manifest_category_spec_not_object:{category}")
            continue
        id_field = str(spec_value.get("id_field") or "id").strip()
        required_ids_value = spec_value.get("required_ids")
        required_ids = [str(item) for item in required_ids_value] if isinstance(required_ids_value, list) else []
        if not id_field:
            blockers.append(f"runtime_trace_builder_event_manifest_category_missing_id_field:{category}")
            continue
        if not required_ids:
            blockers.append(f"runtime_trace_builder_event_manifest_category_missing_required_ids:{category}")
            continue
        observed = {
            str(event.get(id_field) or "")
            for event in events
            if str(event.get("category") or "") == str(category)
        }
        for required_id in required_ids:
            if required_id not in observed:
                blockers.append(
                    f"runtime_trace_builder_event_manifest_missing_event:{category}:{id_field}:{required_id}"
                )
        if require_event_identity:
            for event in events:
                if str(event.get("category") or "") != str(category):
                    continue
                event_id = str(event.get(id_field) or "")
                if event_id not in required_ids:
                    continue
                event_candidate = str(event.get("candidate_id") or "").strip()
                if expected_candidate and not event_candidate:
                    blockers.append(
                        f"runtime_trace_builder_event_manifest_event_missing_candidate_id:{category}:{id_field}:{event_id}"
                    )
                elif expected_candidate and event_candidate != expected_candidate:
                    blockers.append(
                        f"runtime_trace_builder_event_manifest_event_candidate_id_mismatch:{category}:{id_field}:{event_id}"
                    )
                workload_values = [
                    str(event.get(field_name) or "").strip()
                    for field_name in ("workload_case_id", "workload_id")
                    if str(event.get(field_name) or "").strip()
                ]
                if expected_workload and not workload_values:
                    blockers.append(
                        f"runtime_trace_builder_event_manifest_event_missing_workload_case_id:{category}:{id_field}:{event_id}"
                    )
                elif expected_workload and expected_workload not in workload_values:
                    blockers.append(
                        f"runtime_trace_builder_event_manifest_event_workload_case_id_mismatch:{category}:{id_field}:{event_id}"
                    )

    trace_booleans = manifest.get("required_trace_booleans")
    if isinstance(trace_booleans, Mapping):
        for key, expected in trace_booleans.items():
            if expected is True and key not in {
                "trusted_runtime_trace",
                "host_accelerator_end_to_end",
                "full_scf_schedule_consumed",
                "host_bound_costs_included",
            }:
                blockers.append(f"runtime_trace_builder_event_manifest_unknown_required_trace_boolean:{key}")

    forbidden_markers = manifest.get("forbidden_markers")
    if isinstance(forbidden_markers, list):
        for index, event in enumerate(events):
            for marker in forbidden_markers:
                marker_key = str(marker)
                if event.get(marker_key) is True:
                    blockers.append(f"runtime_trace_builder_event_{index}_manifest_forbidden_marker:{marker_key}")
    return sorted(dict.fromkeys(blockers))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events",
        type=Path,
        required=True,
        help=(
            "Measured runtime event log as JSON, JSON object with events/runtime_events, "
            "or JSONL with one event object per line."
        ),
    )
    parser.add_argument("--out", type=Path, required=True, help="Output full_scf_runtime_trace.json path.")
    parser.add_argument(
        "--event-manifest",
        type=Path,
        default=Path(os.environ["QE_OFFLOAD_FULL_SCF_RUNTIME_EVENT_MANIFEST_JSON"])
        if os.environ.get("QE_OFFLOAD_FULL_SCF_RUNTIME_EVENT_MANIFEST_JSON")
        else None,
        help=(
            "Optional row-local full_scf_runtime_event_manifest.json. When provided, "
            "the builder fail-closes unless the event log covers the manifest's "
            "required categories/IDs and row identity."
        ),
    )
    parser.add_argument("--candidate-id", default=os.environ.get("QE_OFFLOAD_CANDIDATE_ID"))
    parser.add_argument("--workload-case-id", default=os.environ.get("QE_OFFLOAD_WORKLOAD_CASE_ID"))
    parser.add_argument(
        "--measurement-source",
        default=os.environ.get("QE_OFFLOAD_RUNTIME_TRACE_SOURCE"),
        help=(
            "Trusted source label for this measured trace, e.g. qe_offload_runtime_trace, "
            "hardware_counter, wall_clock_instrumentation, or gem5_generic_accel_runtime_counter."
        ),
    )
    parser.add_argument("--runtime-execution-proof-json", type=Path, default=None)
    parser.add_argument("--l4-execution-proof-json", type=Path, default=None)
    parser.add_argument("--hardware-counter-proof-json", type=Path, default=None)
    parser.add_argument("--tool-execution-proof-json", type=Path, default=None)
    parser.add_argument("--physical-evidence-json", type=Path, default=None)
    parser.add_argument("--density-residual", type=float, default=None)
    parser.add_argument("--host-accelerator-end-to-end", action="store_true")
    parser.add_argument("--full-scf-schedule-consumed", action="store_true")
    parser.add_argument("--host-bound-costs-included", action="store_true")
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args(argv)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _finite_duration_blockers(events: Sequence[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for index, event in enumerate(events):
        raw_duration = None
        for field_name in ("duration_s", "cost_s", "elapsed_s", "elapsed_seconds", "wall_time_s"):
            if field_name in event:
                value = event.get(field_name)
                if value is None:
                    continue
                raw_duration = value
                break
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(duration):
            blockers.append(f"runtime_trace_builder_event_{index}_duration_not_finite")
    return blockers


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    events, blockers = _load_events(args.events)
    blockers.extend(_finite_duration_blockers(events))
    source = str(args.measurement_source or "").strip().lower()
    if not _trusted_source(source):
        blockers.append(f"runtime_trace_builder_untrusted_or_missing_source:{source or 'missing'}")

    runtime_proof, proof_blockers = _load_mapping(args.runtime_execution_proof_json, label="runtime_execution_proof")
    blockers.extend(proof_blockers)
    l4_proof, proof_blockers = _load_mapping(args.l4_execution_proof_json, label="l4_execution_proof")
    blockers.extend(proof_blockers)
    hardware_counter_proof, proof_blockers = _load_mapping(
        args.hardware_counter_proof_json,
        label="hardware_counter_proof",
    )
    blockers.extend(proof_blockers)
    tool_proof, proof_blockers = _load_mapping(args.tool_execution_proof_json, label="tool_execution_proof")
    blockers.extend(proof_blockers)
    proof_passed = any(
        _proof_passed(proof)
        for proof in (runtime_proof, l4_proof, hardware_counter_proof, tool_proof)
    )
    if not proof_passed:
        blockers.append("runtime_trace_builder_missing_passed_execution_proof")

    event_manifest, manifest_blockers = _load_event_manifest(args.event_manifest)
    blockers.extend(manifest_blockers)
    blockers.extend(
        _manifest_event_coverage_blockers(
            event_manifest,
            events,
            candidate_id=args.candidate_id,
            workload_case_id=args.workload_case_id,
            measurement_source=source,
        )
    )

    physical_evidence, physical_blockers = _physical_evidence(args)
    blockers.extend(physical_blockers)

    trace: dict[str, Any] = {
        "schema_version": FULL_SCF_RUNTIME_TRACE_SCHEMA,
        "candidate_id": args.candidate_id,
        "workload_case_id": args.workload_case_id,
        "status": "passed",
        "passed": True,
        "trusted_runtime_trace": _trusted_source(source) and proof_passed,
        "runtime_trace_source": source,
        "comparison_scope": "full_scf_host_accelerator_end_to_end",
        "host_accelerator_end_to_end": args.host_accelerator_end_to_end,
        "full_scf_schedule_consumed": args.full_scf_schedule_consumed,
        "host_bound_costs_included": args.host_bound_costs_included,
        "fixture": False,
        "baseline_copy": False,
        "timing_only": False,
        "source_event_log": _artifact_ref(args.events),
        "runtime_event_manifest_reference": _artifact_ref(args.event_manifest),
        "runtime_event_manifest": event_manifest,
        "runtime_execution_proof_reference": _artifact_ref(args.runtime_execution_proof_json),
        "l4_execution_proof_reference": _artifact_ref(args.l4_execution_proof_json),
        "hardware_counter_proof_reference": _artifact_ref(args.hardware_counter_proof_json),
        "tool_execution_proof_reference": _artifact_ref(args.tool_execution_proof_json),
        "runtime_execution_proof": runtime_proof,
        "l4_execution_proof": l4_proof,
        "hardware_counter_proof": hardware_counter_proof,
        "tool_execution_proof": tool_proof,
        "physical_evidence": physical_evidence,
        "events": events,
        "builder": {
            "tool": Path(__file__).name,
            "runtime_event_manifest_enforced": event_manifest is not None,
            "claim_boundary": (
                "Measured-event ingestion only; final trust still requires strict "
                "full-SCF accounting validation and row-level QE evidence gates."
            ),
        },
    }

    preview = build_full_scf_row_accounting_from_runtime_trace(
        trace,
        candidate_id=args.candidate_id,
        workload_case_id=args.workload_case_id,
        trace_path=args.out,
    )
    blockers = sorted(dict.fromkeys([*blockers, *[str(item) for item in preview.get("blockers", []) or []]]))
    if blockers:
        trace.update({"status": "blocked", "passed": False, "blockers": blockers})
    else:
        trace["blockers"] = []
    _write_json(args.out, trace)
    print(json.dumps({"output": str(args.out), "status": trace["status"], "blockers": trace["blockers"]}))
    if args.fail_on_blocked and trace["status"] != "passed":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
