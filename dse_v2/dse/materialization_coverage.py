#!/usr/bin/env python3
"""Step2 materialization coverage audit helpers.

These helpers are control-plane checks only: they prove that Campaign Step2
materialization requests were replayed into explicit Step3 admission queues.
They do not execute Step3, validate simulation evidence, or establish final
ranking claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _rel_to(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _requested_mapping_candidate_id(request: Mapping[str, Any]) -> str:
    materialization_inputs = _as_mapping(request.get("materialization_inputs"))
    return str(
        request.get("mapping_candidate_id")
        or materialization_inputs.get("mapping_candidate_id")
        or ""
    )


def _request_identity_field(request: Mapping[str, Any], key: str) -> str:
    materialization_inputs = _as_mapping(request.get("materialization_inputs"))
    return str(request.get(key) or materialization_inputs.get(key) or "")


def _entry_materialization_provenance(entry: Mapping[str, Any]) -> Dict[str, Any]:
    return _as_mapping(entry.get("materialization_provenance"))


def _entry_materialization_inputs(entry: Mapping[str, Any]) -> Dict[str, Any]:
    return _as_mapping(_entry_materialization_provenance(entry).get("materialization_inputs"))


def _entry_selected_mapping_source(entry: Mapping[str, Any]) -> Dict[str, Any]:
    return _as_mapping(_entry_materialization_provenance(entry).get("selected_mapping_source"))


def build_materialization_coverage_audit(
    *,
    out_dir: Path,
    requests: Sequence[Mapping[str, Any]],
    materialized_records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Check that every Step2 request has an authorized non-executed queue.

    A closed audit requires one materialized record per request, one authorized
    Step3 queue entry per request, no hidden Step3 execution artifacts, and no
    record/request identity mismatch.
    """

    blockers: List[Dict[str, str]] = []
    rows: List[Dict[str, Any]] = []
    request_by_id = {
        str(request.get("request_id") or f"request-{index}"): request
        for index, request in enumerate(requests, start=1)
        if isinstance(request, Mapping)
    }
    record_ids = [
        str(record.get("request_id") or "")
        for record in materialized_records
        if isinstance(record, Mapping)
    ]
    record_id_counts = {request_id: record_ids.count(request_id) for request_id in set(record_ids)}
    execution_artifact_names = {
        "simulation_request.json",
        "simulation_result.json",
        "verdict.json",
        "claim_validation.json",
        "final_report.json",
    }
    authorized_queue_entry_count = 0
    materialized_request_ids: set[str] = set()
    no_execution_artifact_count = 0

    for record in materialized_records:
        request_id = str(record.get("request_id") or "")
        request = request_by_id.get(request_id, {})
        materialized_dir = out_dir / str(record.get("materialized_dir") or "")
        queue_ref = str(record.get("step3_simulation_queue_ref") or "")
        queue_path = out_dir / queue_ref if queue_ref else materialized_dir / "step3_simulation_queue.json"
        queue = _load_json(queue_path)
        entries = [
            dict(entry)
            for entry in queue.get("entries", []) or []
            if isinstance(entry, Mapping)
        ]
        authorized_entries = [
            entry
            for entry in entries
            if str(entry.get("step3_queue_authorization_status") or "") == "authorized_by_step2_materialization"
        ]
        unexpected_execution_artifacts = sorted(
            name for name in execution_artifact_names if (materialized_dir / name).exists()
        )
        row_blockers: List[str] = []
        if request_id not in request_by_id:
            row_blockers.append("materialization_record_missing_matching_request")
        if record_id_counts.get(request_id, 0) > 1:
            row_blockers.append("materialization_request_duplicate_records")
        if record.get("materialization_status") != "materialized_by_step2_writer":
            row_blockers.append("request_not_materialized_by_step2_writer")
        if record.get("canonical_step3_queue_written") is not True:
            row_blockers.append("canonical_step3_queue_not_written")
        if not queue_path.exists():
            row_blockers.append("step3_simulation_queue_file_missing")
        if int(queue.get("entry_count", len(entries)) or 0) != len(entries):
            row_blockers.append("step3_queue_entry_count_mismatch")
        if len(entries) != 1:
            row_blockers.append("materialized_queue_not_selected_entry_only")
        if len(authorized_entries) != len(entries) or not authorized_entries:
            row_blockers.append("materialized_queue_missing_authorized_entry")
        if queue.get("execution_allowed") not in (None, False):
            row_blockers.append("materialized_queue_execution_allowed")
        if queue.get("trusted_final_claim") not in (None, False):
            row_blockers.append("materialized_queue_trusted_final_claim")
        if queue.get("release_completion_eligible") not in (None, False):
            row_blockers.append("materialized_queue_release_completion_eligible")
        for entry in entries:
            if entry.get("trusted_final_claim") not in (None, False):
                row_blockers.append("materialized_queue_entry_trusted_final_claim")
            if entry.get("release_completion_eligible") not in (None, False):
                row_blockers.append("materialized_queue_entry_release_completion_eligible")
        if unexpected_execution_artifacts:
            row_blockers.append("materialization_wrote_step3_execution_artifacts")

        requested_mapping_id = _requested_mapping_candidate_id(request)
        entry_mapping_ids = {
            str(entry.get("mapping_candidate_id") or "")
            for entry in entries
            if str(entry.get("mapping_candidate_id") or "")
        }

        requested_mapping_hash = _request_identity_field(request, "mapping_parameter_hash")
        requested_search_id = _request_identity_field(request, "search_policy_candidate_id")
        requested_search_hash = _request_identity_field(request, "search_policy_parameter_hash")
        requested_parent_search_id = _request_identity_field(request, "parent_search_policy_candidate_id")
        requested_parent_search_hash = _request_identity_field(request, "parent_search_policy_parameter_hash")
        entry_mapping_hashes: set[str] = set()
        entry_search_ids: set[str] = set()
        entry_search_hashes: set[str] = set()
        selected_mapping_candidate_ids: set[str] = set()
        selected_mapping_hashes: set[str] = set()
        selected_search_ids: set[str] = set()
        selected_search_hashes: set[str] = set()
        requested_mapping_id_resolved_by_selected_source = False
        for entry in authorized_entries:
            provenance = _entry_materialization_provenance(entry)
            inputs = _entry_materialization_inputs(entry)
            selected_source = _entry_selected_mapping_source(entry)
            if str(provenance.get("request_id") or "") != request_id:
                row_blockers.append("materialization_provenance_request_id_mismatch")
            for value in (
                inputs.get("mapping_parameter_hash"),
                entry.get("mapping_parameter_hash"),
            ):
                if value:
                    entry_mapping_hashes.add(str(value))
            for value in (
                inputs.get("search_policy_candidate_id"),
                entry.get("search_policy_candidate_id"),
            ):
                if value:
                    entry_search_ids.add(str(value))
            for value in (
                inputs.get("search_policy_parameter_hash"),
                entry.get("search_policy_parameter_hash"),
            ):
                if value:
                    entry_search_hashes.add(str(value))
            if selected_source.get("matched_mapping_candidate_id") and requested_mapping_id:
                if str(selected_source.get("matched_mapping_candidate_id")) != requested_mapping_id:
                    row_blockers.append("selected_mapping_source_mapping_id_mismatch")
            for value in (
                selected_source.get("matched_mapping_candidate_id"),
                selected_source.get("matched_candidate_id"),
            ):
                if value:
                    selected_mapping_candidate_ids.add(str(value))
            if requested_mapping_id:
                provenance_requested_mapping_id = str(inputs.get("mapping_candidate_id") or "")
                if (
                    provenance_requested_mapping_id == requested_mapping_id
                    and requested_mapping_id in selected_mapping_candidate_ids
                ):
                    requested_mapping_id_resolved_by_selected_source = True
            for value in (
                selected_source.get("matched_mapping_parameter_hash"),
                selected_source.get("matched_parameter_hash"),
            ):
                if value:
                    selected_mapping_hashes.add(str(value))
            for value in (
                selected_source.get("matched_search_policy_candidate_id"),
                selected_source.get("matched_search_policy_id"),
            ):
                if value:
                    selected_search_ids.add(str(value))
            for value in (
                selected_source.get("matched_search_policy_parameter_hash"),
                selected_source.get("matched_search_policy_hash"),
            ):
                if value:
                    selected_search_hashes.add(str(value))
        if (
            requested_mapping_id
            and requested_mapping_id not in entry_mapping_ids
            and not requested_mapping_id_resolved_by_selected_source
        ):
            row_blockers.append("authorized_queue_entry_mapping_id_mismatch")
        if requested_mapping_hash and requested_mapping_hash not in entry_mapping_hashes:
            row_blockers.append("materialization_provenance_mapping_hash_mismatch")
        if requested_mapping_hash and requested_mapping_hash not in selected_mapping_hashes:
            row_blockers.append("selected_mapping_source_mapping_hash_mismatch")
        if requested_search_id and requested_search_id not in entry_search_ids:
            row_blockers.append("materialization_provenance_search_policy_id_mismatch")
        selected_expected_search_id = requested_parent_search_id or requested_search_id
        selected_expected_search_hash = requested_parent_search_hash or requested_search_hash
        if selected_expected_search_id and selected_expected_search_id not in selected_search_ids:
            row_blockers.append("selected_mapping_source_search_policy_id_mismatch")
        if requested_search_hash and requested_search_hash not in entry_search_hashes:
            row_blockers.append("materialization_provenance_search_policy_hash_mismatch")
        if selected_expected_search_hash and selected_expected_search_hash not in selected_search_hashes:
            row_blockers.append("selected_mapping_source_search_policy_hash_mismatch")

        if (
            request_id in request_by_id
            and record.get("materialization_status") == "materialized_by_step2_writer"
        ):
            materialized_request_ids.add(request_id)
        authorized_queue_entry_count += len(authorized_entries)
        if not unexpected_execution_artifacts:
            no_execution_artifact_count += 1
        for reason_id in sorted(set(row_blockers)):
            blockers.append({
                "reason_id": reason_id,
                "request_id": request_id,
                "materialized_dir": str(record.get("materialized_dir") or ""),
            })
        rows.append({
            "request_id": request_id,
            "materialized_dir": str(record.get("materialized_dir") or ""),
            "materialization_status": str(record.get("materialization_status") or ""),
            "canonical_step3_queue_written": bool(record.get("canonical_step3_queue_written", False)),
            "step3_simulation_queue_ref": _rel_to(queue_path, out_dir),
            "queue_entry_count": len(entries),
            "authorized_queue_entry_count": len(authorized_entries),
            "requested_mapping_candidate_id": requested_mapping_id,
            "requested_mapping_parameter_hash": requested_mapping_hash,
            "requested_search_policy_candidate_id": requested_search_id,
            "requested_search_policy_parameter_hash": requested_search_hash,
            "requested_parent_search_policy_candidate_id": requested_parent_search_id,
            "requested_parent_search_policy_parameter_hash": requested_parent_search_hash,
            "queue_mapping_candidate_ids": sorted(entry_mapping_ids),
            "queue_mapping_parameter_hashes": sorted(entry_mapping_hashes),
            "queue_search_policy_candidate_ids": sorted(entry_search_ids),
            "queue_search_policy_parameter_hashes": sorted(entry_search_hashes),
            "selected_mapping_source_mapping_candidate_ids": sorted(selected_mapping_candidate_ids),
            "requested_mapping_candidate_resolved_by_selected_source": bool(
                requested_mapping_id_resolved_by_selected_source
            ),
            "selected_mapping_source_mapping_parameter_hashes": sorted(selected_mapping_hashes),
            "selected_mapping_source_search_policy_candidate_ids": sorted(selected_search_ids),
            "selected_mapping_source_search_policy_parameter_hashes": sorted(selected_search_hashes),
            "unexpected_execution_artifacts": unexpected_execution_artifacts,
            "coverage_blockers": sorted(set(row_blockers)),
        })

    for request_id, request in request_by_id.items():
        if request_id in record_ids:
            continue
        reason_id = "materialization_request_missing_record"
        blockers.append({
            "reason_id": reason_id,
            "request_id": request_id,
            "materialized_dir": "",
        })
        rows.append({
            "request_id": request_id,
            "materialized_dir": "",
            "materialization_status": "missing_materialization_record",
            "canonical_step3_queue_written": False,
            "step3_simulation_queue_ref": "",
            "queue_entry_count": 0,
            "authorized_queue_entry_count": 0,
            "requested_mapping_candidate_id": _requested_mapping_candidate_id(request),
            "requested_mapping_parameter_hash": _request_identity_field(request, "mapping_parameter_hash"),
            "requested_search_policy_candidate_id": _request_identity_field(request, "search_policy_candidate_id"),
            "requested_search_policy_parameter_hash": _request_identity_field(request, "search_policy_parameter_hash"),
            "requested_parent_search_policy_candidate_id": _request_identity_field(request, "parent_search_policy_candidate_id"),
            "requested_parent_search_policy_parameter_hash": _request_identity_field(request, "parent_search_policy_parameter_hash"),
            "queue_mapping_candidate_ids": [],
            "queue_mapping_parameter_hashes": [],
            "queue_search_policy_candidate_ids": [],
            "queue_search_policy_parameter_hashes": [],
            "selected_mapping_source_mapping_candidate_ids": [],
            "requested_mapping_candidate_resolved_by_selected_source": False,
            "selected_mapping_source_mapping_parameter_hashes": [],
            "selected_mapping_source_search_policy_candidate_ids": [],
            "selected_mapping_source_search_policy_parameter_hashes": [],
            "unexpected_execution_artifacts": [],
            "coverage_blockers": [reason_id],
        })

    request_count = len(requests)
    materialized_request_count = len(materialized_request_ids)
    coverage_closed = bool(
        request_count > 0
        and not blockers
        and materialized_request_count == request_count
        and authorized_queue_entry_count == request_count
        and no_execution_artifact_count == request_count
    )
    return {
        "schema_version": "dse.campaign.materialization_coverage_audit.v1",
        "status": "closed_for_step3_queue_handoff" if coverage_closed else (
            "no_requests_to_materialize" if request_count == 0 else "partial_blocked_not_complete"
        ),
        "coverage_closed": coverage_closed,
        "request_count": request_count,
        "materialized_request_count": materialized_request_count,
        "authorized_step3_queue_entry_count": authorized_queue_entry_count,
        "all_requests_materialized": bool(request_count > 0 and materialized_request_count == request_count),
        "all_materialized_have_authorized_step3_queue": bool(
            request_count > 0 and authorized_queue_entry_count == request_count
        ),
        "no_step3_execution_artifacts_written": bool(
            request_count > 0 and no_execution_artifact_count == request_count
        ),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "rows": rows,
        "claim_boundary": (
            "Materialization coverage audits prove Step2 request-to-queue coverage only. "
            "They do not execute Step3, prove simulator evidence, or establish final ranking."
        ),
    }
