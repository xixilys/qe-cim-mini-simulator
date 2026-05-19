#!/usr/bin/env python3
"""Helpers for remapping and admitting QE accelerated numeric requirements.

The complete-DSE v1 requirements file is a frozen read-only input.  New trusted
QE/offload attempts must materialize v2 requirements under a fresh run root so
producer outputs, command templates, and campaign outputs cannot overwrite or
re-consume stale writable v1 artifacts.  Baseline comparisons under
``qe_baselines`` and explicit ``source_requirements`` provenance remain
read-only references to the frozen v1 run.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


DEFAULT_QE_ACCELERATED_V1_OUTPUT_ROOT = "runs/dse/complete_dse_full_l4_evidence_v1"
QE_ACCELERATED_NUMERIC_REQUIREMENTS_REMAP_SCHEMA_SUFFIX = "+remapped_v2"
QE_ADMISSIBILITY_LEDGER_SCHEMA = "dse.admissibility_ledger.v1"
_NUMERIC_SENTINEL = "numeric CLI value or provenance-derived scalar"


def _as_posix(value: str | Path) -> str:
    return Path(value).as_posix()


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: str | Path) -> str:
    """Return a SHA-256 hash for an immutable artifact file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_extra_artifact_label(label: str) -> str:
    if not label:
        raise ValueError("extra artifact label must not be empty")
    if not all(ch.isalnum() or ch == "_" for ch in label):
        raise ValueError(f"extra artifact label must be snake_case alphanumeric: {label}")
    return label


def _artifact_hash_record(path: str | Path) -> Dict[str, str]:
    return {"path": _as_posix(path), "sha256": sha256_file(path)}


def _extra_artifact_hash_records(
    extra_artifact_paths: Mapping[str, str | Path] | None,
) -> Dict[str, Dict[str, str]]:
    if not extra_artifact_paths:
        return {}
    records: Dict[str, Dict[str, str]] = {}
    for label, path in sorted(extra_artifact_paths.items()):
        records[_validate_extra_artifact_label(str(label))] = _artifact_hash_record(path)
    return records


def _extra_artifact_paths_from_ledger(ledger: Mapping[str, Any]) -> Dict[str, str]:
    extra_artifacts = ledger.get("extra_artifacts") or {}
    if not isinstance(extra_artifacts, Mapping):
        raise ValueError("admissibility ledger extra_artifacts must be a mapping")
    paths: Dict[str, str] = {}
    for label, record in extra_artifacts.items():
        label = _validate_extra_artifact_label(str(label))
        if not isinstance(record, Mapping):
            raise ValueError(f"admissibility ledger extra_artifacts.{label} must be a mapping")
        path = record.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(f"admissibility ledger extra_artifacts.{label}.path is missing")
        paths[label] = path
    return paths


def _row_output_dir(output_root: Path, row: Mapping[str, Any]) -> Path:
    candidate_id = str(row.get("candidate_id") or "")
    workload_case_id = str(row.get("workload_case_id") or "")
    if not candidate_id or not workload_case_id:
        raise ValueError("QE accelerated requirement row is missing candidate_id or workload_case_id")
    return output_root / "accelerated_numeric_inputs" / candidate_id / workload_case_id


def _remap_row_string(
    value: str,
    *,
    row: Mapping[str, Any],
    source_requirements_path: str,
    output_requirements_path: str,
    output_root: Path,
    old_output_root: str,
) -> str:
    if value == _NUMERIC_SENTINEL:
        return value
    legacy_source_requirements = old_output_root.rstrip("/") + "/qe_accelerated_numeric_evidence_requirements.json"
    if value in {source_requirements_path, legacy_source_requirements}:
        return output_requirements_path
    accelerated_prefix = old_output_root.rstrip("/") + "/accelerated_numeric_inputs/"
    if value.startswith(accelerated_prefix):
        return (_row_output_dir(output_root, row) / Path(value).name).as_posix()
    # Frozen QE baselines remain read-only references to the v1 run.
    if value.startswith(old_output_root.rstrip("/") + "/qe_baselines/"):
        return value
    return value


def _remap_global_string(
    value: str,
    *,
    source_requirements_path: str,
    output_requirements_path: str,
    output_root: Path,
    old_output_root: str,
) -> str:
    legacy_source_requirements = old_output_root.rstrip("/") + "/qe_accelerated_numeric_evidence_requirements.json"
    if value in {source_requirements_path, legacy_source_requirements}:
        return output_requirements_path
    campaign_prefix = old_output_root.rstrip("/") + "/qe_accelerated_numeric_campaign"
    if value.startswith(campaign_prefix):
        rel = Path(value).relative_to(old_output_root)
        return (output_root / rel).as_posix()
    if value.startswith(old_output_root.rstrip("/") + "/qe_baselines/"):
        return value
    return value


def _map_strings(obj: Any, mapper) -> Any:
    if isinstance(obj, dict):
        return {key: _map_strings(value, mapper) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_map_strings(value, mapper) for value in obj]
    if isinstance(obj, str):
        return mapper(obj)
    return obj


def forbidden_v1_writable_paths(
    obj: Any,
    *,
    old_output_root: str = DEFAULT_QE_ACCELERATED_V1_OUTPUT_ROOT,
    path: str = "$",
) -> list[tuple[str, str]]:
    """Return stale v1 output-root strings that are not allowed read-only refs.

    Allowed occurrences are deliberately narrow:
    * ``<old_root>/qe_baselines/...`` read-only baseline references;
    * any field whose dotted path ends in ``.source_requirements``.
    """
    hits: list[tuple[str, str]] = []
    old_root = old_output_root.rstrip("/")
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            hits.extend(
                forbidden_v1_writable_paths(
                    value,
                    old_output_root=old_root,
                    path=f"{path}.{key}",
                )
            )
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            hits.extend(
                forbidden_v1_writable_paths(
                    value,
                    old_output_root=old_root,
                    path=f"{path}[{index}]",
                )
            )
    elif isinstance(obj, str) and old_root in obj:
        allowed = obj.startswith(old_root + "/qe_baselines/") or path.endswith(".source_requirements")
        if not allowed:
            hits.append((path, obj))
    return hits


def assert_no_forbidden_v1_writable_paths(
    obj: Any,
    *,
    old_output_root: str = DEFAULT_QE_ACCELERATED_V1_OUTPUT_ROOT,
) -> None:
    """Raise when remapped requirements still reference writable v1 paths."""
    forbidden = forbidden_v1_writable_paths(obj, old_output_root=old_output_root)
    if forbidden:
        preview = ", ".join(f"{path}={value}" for path, value in forbidden[:5])
        raise ValueError(f"forbidden writable v1 paths remain after remap: {preview}")


def _row_matches(
    row: Mapping[str, Any],
    *,
    candidate_id: str | None,
    workload_case_id: str | None,
    row_id: str | None,
) -> bool:
    if candidate_id is not None and str(row.get("candidate_id")) != str(candidate_id):
        return False
    if workload_case_id is not None and str(row.get("workload_case_id")) != str(workload_case_id):
        return False
    if row_id is not None and str(row.get("row_id")) != str(row_id):
        return False
    return True


def remap_qe_accelerated_numeric_requirements(
    requirements: Mapping[str, Any],
    *,
    source_requirements_path: str | Path,
    output_requirements_path: str | Path,
    output_root: str | Path,
    candidate_id: str | None = None,
    workload_case_id: str | None = None,
    row_id: str | None = None,
    expected_row_count: int | None = None,
    old_output_root: str = DEFAULT_QE_ACCELERATED_V1_OUTPUT_ROOT,
) -> Dict[str, Any]:
    """Return a v2 requirements payload remapped under ``output_root``.

    ``candidate_id``/``workload_case_id``/``row_id`` select one or more rows.
    With no selector, all rows are remapped and the source ``row_count`` is used
    as the expected count when present.
    """
    source_path = _as_posix(source_requirements_path)
    output_path = _as_posix(output_requirements_path)
    root = Path(output_root)
    old_root = old_output_root.rstrip("/")
    data: Dict[str, Any] = copy.deepcopy(dict(requirements))
    source_rows = data.get("rows", [])
    if not isinstance(source_rows, list):
        raise ValueError("QE accelerated requirements payload must contain a rows list")
    if expected_row_count is None and not any([candidate_id, workload_case_id, row_id]):
        expected_row_count = int(data.get("row_count", len(source_rows)))

    def global_mapper(value: str) -> str:
        return _remap_global_string(
            value,
            source_requirements_path=source_path,
            output_requirements_path=output_path,
            output_root=root,
            old_output_root=old_root,
        )

    remapped = _map_strings({key: value for key, value in data.items() if key != "rows"}, global_mapper)
    rows: list[Dict[str, Any]] = []
    for source_row in source_rows:
        if not isinstance(source_row, Mapping):
            continue
        if not _row_matches(
            source_row,
            candidate_id=candidate_id,
            workload_case_id=workload_case_id,
            row_id=row_id,
        ):
            continue
        row = copy.deepcopy(dict(source_row))

        def row_mapper(value: str) -> str:
            return _remap_row_string(
                value,
                row=row,
                source_requirements_path=source_path,
                output_requirements_path=output_path,
                output_root=root,
                old_output_root=old_root,
            )

        row = _map_strings(row, row_mapper)
        row["evidence_output"] = (_row_output_dir(root, row) / "qe_accelerated_numeric_evidence.json").as_posix()
        rows.append(row)

    remapped["rows"] = rows
    remapped["row_count"] = len(rows)
    remapped["source_requirements"] = source_path
    remapped["writable_output_root"] = root.as_posix()
    schema_version = str(data.get("schema_version") or "dse.qe_accelerated_numeric_evidence_requirements.v1")
    if not schema_version.endswith(QE_ACCELERATED_NUMERIC_REQUIREMENTS_REMAP_SCHEMA_SUFFIX):
        schema_version += QE_ACCELERATED_NUMERIC_REQUIREMENTS_REMAP_SCHEMA_SUFFIX
    remapped["schema_version"] = schema_version

    assert_no_forbidden_v1_writable_paths(remapped, old_output_root=old_root)
    if expected_row_count is not None and len(rows) != int(expected_row_count):
        raise ValueError(f"unexpected remapped row count: rows={len(rows)} expected={expected_row_count}")
    if not rows:
        raise ValueError("remapped requirements selected zero rows")
    return remapped


def write_remapped_qe_accelerated_numeric_requirements(
    *,
    source_requirements_path: str | Path,
    output_requirements_path: str | Path,
    output_root: str | Path,
    candidate_id: str | None = None,
    workload_case_id: str | None = None,
    row_id: str | None = None,
    expected_row_count: int | None = None,
    old_output_root: str = DEFAULT_QE_ACCELERATED_V1_OUTPUT_ROOT,
) -> Dict[str, Any]:
    """Load, remap, write, and return a QE accelerated requirements payload."""
    payload = _load_json(source_requirements_path)
    remapped = remap_qe_accelerated_numeric_requirements(
        payload,
        source_requirements_path=source_requirements_path,
        output_requirements_path=output_requirements_path,
        output_root=output_root,
        candidate_id=candidate_id,
        workload_case_id=workload_case_id,
        row_id=row_id,
        expected_row_count=expected_row_count,
        old_output_root=old_output_root,
    )
    _write_json(output_requirements_path, remapped)
    return remapped


def _row_identity(row: Mapping[str, Any]) -> str:
    if row.get("row_id"):
        return str(row["row_id"])
    return f"{row.get('candidate_id')}::{row.get('workload_case_id')}"



def _row_requires_hpsi_sidecar_counter_validation(row: Mapping[str, Any]) -> bool:
    text_parts: list[str] = []
    for key in ("offload_provenance", "kernel_evidence", "hpsi_component_sidecar_summary"):
        value = row.get(key)
        if isinstance(value, Mapping):
            text_parts.extend(str(value.get(field) or "") for field in ("producer", "offload_target", "source", "trusted_payload_kind", "claim_boundary"))
            text_parts.append(str(value.get("kernel_id") or ""))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    text_parts.extend(str(item.get(field) or "") for field in ("source", "trusted_payload_kind", "claim_boundary"))
                    text_parts.append(str(item.get("kernel_id") or ""))
    text = " ".join(text_parts).lower()
    if "h_psi" not in text and "hpsi" not in text:
        return False
    return any(hint in text for hint in ("native_payload", "component_sidecar", "qe_hpsi", "systemc"))


def _validate_row_hpsi_sidecar_counters(row: Mapping[str, Any], row_id: str) -> list[str]:
    if not _row_requires_hpsi_sidecar_counter_validation(row):
        return []
    provenance = row.get("offload_provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    kernel_rows = row.get("kernel_evidence")
    kernel_rows = kernel_rows if isinstance(kernel_rows, list) else []
    blockers: list[str] = []
    for source_name, item in [("offload_provenance", provenance), *[(f"kernel_evidence:{idx}", item) for idx, item in enumerate(kernel_rows) if isinstance(item, Mapping)]]:
        for field in ("sidecar_observed_hpsi_calls", "sidecar_attempted_hpsi_calls", "sidecar_consumed_hpsi_calls", "sidecar_failed_hpsi_calls"):
            try:
                value = int(item.get(field))
            except (TypeError, ValueError):
                blockers.append(f"row {row_id} {source_name} missing {field}")
                continue
            if field == "sidecar_observed_hpsi_calls" and value <= 0:
                blockers.append(f"row {row_id} {source_name} sidecar_observed_hpsi_calls must be > 0")
            if field == "sidecar_failed_hpsi_calls" and value != 0:
                blockers.append(f"row {row_id} {source_name} sidecar_failed_hpsi_calls must be 0")
        observed = item.get("sidecar_observed_hpsi_calls")
        if item.get("sidecar_attempted_hpsi_calls") != observed:
            blockers.append(f"row {row_id} {source_name} attempted hpsi calls do not match observed")
        if item.get("sidecar_consumed_hpsi_calls") != observed:
            blockers.append(f"row {row_id} {source_name} consumed hpsi calls do not match observed")
        if item.get("all_observed_hpsi_calls_sidecar_consumed") is not True:
            blockers.append(f"row {row_id} {source_name} missing all_observed_hpsi_calls_sidecar_consumed=true")
        if item.get("single_hpsi_call_smoke_only") is not False:
            blockers.append(f"row {row_id} {source_name} missing single_hpsi_call_smoke_only=false")
    return blockers

def validate_qe_producer_counts(
    *,
    requirements: Mapping[str, Any],
    producer_index: Mapping[str, Any],
    evidence_bundle: Mapping[str, Any],
    require_all_passed: bool = True,
) -> Dict[str, Any]:
    """Validate producer index/bundle counts against remapped requirements."""
    expected = int(requirements.get("row_count", 0))
    if expected <= 0:
        raise ValueError("remapped requirements selected zero rows")
    bundle_rows = evidence_bundle.get("rows", [])
    if not isinstance(bundle_rows, list):
        raise ValueError("producer evidence bundle rows must be a list")

    checks = {
        "selected_row_count": int(producer_index.get("selected_row_count", -1)),
        "evidence_bundle_row_count": int(producer_index.get("evidence_bundle_row_count", -1)),
        "bundle_row_count": int(evidence_bundle.get("row_count", -1)),
        "bundle_len_rows": len(bundle_rows),
        "passed_row_count": int(producer_index.get("passed_row_count", -1)),
        "blocked_row_count": int(producer_index.get("blocked_row_count", -1)),
        "expected_row_count": expected,
    }
    for name in ("selected_row_count", "evidence_bundle_row_count", "bundle_row_count", "bundle_len_rows"):
        if checks[name] != expected:
            raise ValueError(f"producer {name} does not match remapped requirements: {checks[name]} != {expected}")
    if checks["passed_row_count"] + checks["blocked_row_count"] != checks["selected_row_count"]:
        raise ValueError(
            "producer passed/blocked counts do not add up to selected rows: "
            f"passed={checks['passed_row_count']} blocked={checks['blocked_row_count']} "
            f"selected={checks['selected_row_count']}"
        )
    if require_all_passed:
        if checks["passed_row_count"] != expected or checks["blocked_row_count"] != 0:
            raise ValueError(
                "producer did not pass every remapped requirement row: "
                f"passed={checks['passed_row_count']} blocked={checks['blocked_row_count']} expected={expected}"
            )
        index_blockers = producer_index.get("evidence_bundle_blockers") or []
        bundle_blockers = evidence_bundle.get("blockers") or []
        if index_blockers or bundle_blockers:
            raise ValueError(
                "producer bundle still contains blockers: "
                f"index={list(index_blockers)} bundle={list(bundle_blockers)}"
            )

    required_ids = {_row_identity(row) for row in requirements.get("rows", []) if isinstance(row, Mapping)}
    bundle_ids = {_row_identity(row) for row in bundle_rows if isinstance(row, Mapping)}
    if required_ids != bundle_ids:
        raise ValueError(
            "producer bundle row identities do not match remapped requirements: "
            f"missing={sorted(required_ids - bundle_ids)} extra={sorted(bundle_ids - required_ids)}"
        )
    if require_all_passed:
        counter_blockers: list[str] = []
        for row in bundle_rows:
            if isinstance(row, Mapping):
                counter_blockers.extend(_validate_row_hpsi_sidecar_counters(row, _row_identity(row)))
        if counter_blockers:
            raise ValueError("producer bundle h_psi sidecar consumption counters invalid: " + "; ".join(counter_blockers))
    return checks


def _default_environment() -> Dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cwd": os.getcwd(),
    }


def build_qe_admissibility_ledger(
    *,
    run_dir: str | Path,
    bundle_path: str | Path,
    producer_index_path: str | Path,
    requirements_path: str | Path,
    source_requirements_path: str | Path,
    writable_output_root: str | Path,
    producer_command: Sequence[str],
    campaign_id: str,
    status: str = "final_admissible",
    required_final_gate: str = "complete_dse_full_l4_matrix_zero_blocked_rows",
    environment: Mapping[str, Any] | None = None,
    git_revision: str | None = None,
    note: str | None = None,
    extra_artifact_paths: Mapping[str, str | Path] | None = None,
) -> Dict[str, Any]:
    """Build a hash-bound admissibility ledger for a producer evidence bundle."""
    req_data = _load_json(requirements_path)
    rows = req_data.get("rows", []) if isinstance(req_data, Mapping) else []
    if not isinstance(rows, list):
        raise ValueError("requirements rows must be a list")
    if git_revision is None:
        git_revision = subprocess.getoutput("git rev-parse --short HEAD 2>/dev/null || true")
    ledger: Dict[str, Any] = {
        "schema_version": QE_ADMISSIBILITY_LEDGER_SCHEMA,
        "status": status,
        "run_id": Path(run_dir).name,
        "bundle_path": _as_posix(bundle_path),
        "bundle_sha256": sha256_file(bundle_path),
        "producer_index": _as_posix(producer_index_path),
        "producer_index_sha256": sha256_file(producer_index_path),
        "requirements_path": _as_posix(requirements_path),
        "requirements_sha256": sha256_file(requirements_path),
        "source_requirements": _as_posix(source_requirements_path),
        "source_requirements_sha256": sha256_file(source_requirements_path),
        "writable_output_root": _as_posix(writable_output_root),
        "campaign_id": campaign_id,
        "workload_case_count": len({str(row.get("workload_case_id")) for row in rows if isinstance(row, Mapping)}),
        "trial_row_count": int(req_data.get("row_count", len(rows))),
        "producer_command": [str(item) for item in producer_command],
        "environment": dict(environment or _default_environment()),
        "git_revision": git_revision,
        "required_final_gate": required_final_gate,
    }
    if note is not None:
        ledger["note"] = note
    extra_artifacts = _extra_artifact_hash_records(extra_artifact_paths)
    if extra_artifacts:
        ledger["extra_artifacts"] = extra_artifacts
        for label, record in extra_artifacts.items():
            ledger[f"{label}_path"] = record["path"]
            ledger[f"{label}_sha256"] = record["sha256"]
    return ledger


def validate_qe_admissibility_ledger(
    ledger: Mapping[str, Any],
    *,
    bundle_path: str | Path,
    producer_index_path: str | Path,
    requirements_path: str | Path,
    source_requirements_path: str | Path,
    expected_status: str = "final_admissible",
    extra_artifact_paths: Mapping[str, str | Path] | None = None,
) -> Dict[str, Any]:
    """Validate ledger identity and artifact hashes before final consumption."""
    required = (
        "schema_version",
        "status",
        "bundle_path",
        "bundle_sha256",
        "producer_index",
        "producer_index_sha256",
        "requirements_path",
        "requirements_sha256",
        "source_requirements",
        "source_requirements_sha256",
        "writable_output_root",
        "campaign_id",
        "trial_row_count",
        "producer_command",
        "environment",
    )
    for field in required:
        if field not in ledger or ledger.get(field) in (None, "", []):
            raise ValueError(f"admissibility ledger missing required field: {field}")
    if ledger.get("schema_version") != QE_ADMISSIBILITY_LEDGER_SCHEMA:
        raise ValueError(f"unexpected admissibility ledger schema: {ledger.get('schema_version')}")
    if ledger.get("status") != expected_status:
        raise ValueError(f"bundle is not {expected_status}: {ledger.get('status')}")

    expected_paths = {
        "bundle_path": _as_posix(bundle_path),
        "producer_index": _as_posix(producer_index_path),
        "requirements_path": _as_posix(requirements_path),
        "source_requirements": _as_posix(source_requirements_path),
    }
    for field, expected in expected_paths.items():
        if ledger.get(field) != expected:
            raise ValueError(f"admissibility ledger {field} does not match expected path")
    expected_hashes = {
        "bundle_sha256": sha256_file(bundle_path),
        "producer_index_sha256": sha256_file(producer_index_path),
        "requirements_sha256": sha256_file(requirements_path),
        "source_requirements_sha256": sha256_file(source_requirements_path),
    }
    for field, expected in expected_hashes.items():
        if ledger.get(field) != expected:
            raise ValueError(f"admissibility ledger {field} does not match artifact hash")

    ledger_extra_paths = _extra_artifact_paths_from_ledger(ledger)
    expected_extra_paths: Dict[str, str | Path] = dict(ledger_extra_paths)
    if extra_artifact_paths:
        expected_extra_paths.update(
            {_validate_extra_artifact_label(str(label)): path for label, path in extra_artifact_paths.items()}
        )
    expected_extra_artifacts = _extra_artifact_hash_records(expected_extra_paths)
    ledger_extra_artifacts = ledger.get("extra_artifacts") or {}
    if not isinstance(ledger_extra_artifacts, Mapping):
        raise ValueError("admissibility ledger extra_artifacts must be a mapping")
    for label, expected_record in expected_extra_artifacts.items():
        ledger_record = ledger_extra_artifacts.get(label)
        if not isinstance(ledger_record, Mapping):
            raise ValueError(f"admissibility ledger extra_artifacts.{label} is missing")
        if ledger_record.get("path") != expected_record["path"]:
            raise ValueError(f"admissibility ledger extra_artifacts.{label}.path does not match expected path")
        if ledger_record.get("sha256") != expected_record["sha256"]:
            raise ValueError(f"admissibility ledger {label}_sha256 does not match artifact hash")
        if ledger.get(f"{label}_path") != expected_record["path"]:
            raise ValueError(f"admissibility ledger {label}_path does not match expected path")
        if ledger.get(f"{label}_sha256") != expected_record["sha256"]:
            raise ValueError(f"admissibility ledger {label}_sha256 does not match artifact hash")
        expected_hashes[f"{label}_sha256"] = expected_record["sha256"]
    return dict(expected_hashes)


def write_qe_admissibility_ledger(
    ledger_path: str | Path,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build and write a QE admissibility ledger."""
    ledger = build_qe_admissibility_ledger(**kwargs)
    _write_json(ledger_path, ledger)
    return ledger
