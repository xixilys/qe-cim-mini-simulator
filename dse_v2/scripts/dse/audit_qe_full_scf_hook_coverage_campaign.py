#!/usr/bin/env python3
"""Summarize fail-closed QE full-SCF hook coverage across a Step5 row root.

This campaign audit is a coordination artifact for the DFT/QE full-SCF
accelerated evidence lane.  It never upgrades call-site, proxy, or timing
diagnostics into strict closure; it only aggregates the per-row blockers emitted
by :mod:`dse_v2.reference_workloads.qe_full_scf_hook_coverage` so parallel lanes
can see which major-kernel hooks, replacement rows, runtime events, and proofs
remain missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.codesign.dft_hardware_evidence import MAJOR_SCF_KERNEL_IDS  # noqa: E402
from dse_v2.reference_workloads.qe_full_scf_hook_coverage import (  # noqa: E402
    QE_FULL_SCF_HOOK_COVERAGE_AUDIT_SCHEMA,
    build_qe_full_scf_hook_coverage_audit,
    write_qe_full_scf_hook_coverage_audit,
)


CAMPAIGN_SCHEMA = "dse.qe.full_scf_hook_coverage_campaign_audit.v1"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _row_status(row_dir: Path) -> Mapping[str, Any]:
    status_path = row_dir / "qe_accelerated_numeric_producer_status.json"
    if not status_path.exists():
        return {}
    try:
        status = _load_json(status_path)
    except Exception:
        return {}
    return status if isinstance(status, Mapping) else {}


def _identity_from_row_dir(row_root: Path, row_dir: Path, status: Mapping[str, Any]) -> tuple[str | None, str | None]:
    candidate_id = str(status.get("candidate_id") or "").strip()
    workload_case_id = str(status.get("workload_case_id") or "").strip()
    if candidate_id and workload_case_id:
        return candidate_id, workload_case_id
    rel_parts = row_dir.relative_to(row_root).parts if row_dir.is_relative_to(row_root) else row_dir.parts
    if not workload_case_id and rel_parts:
        workload_case_id = rel_parts[-1]
    if not candidate_id and len(rel_parts) >= 2:
        candidate_id = rel_parts[-2]
    return candidate_id or None, workload_case_id or None


def _top_blockers(counter: Counter[str], limit: int) -> list[dict[str, Any]]:
    return [
        {"blocker": blocker, "count": count}
        for blocker, count in counter.most_common(limit)
    ]


def _kernel_suffix(blocker: str, prefix: str) -> str | None:
    if not blocker.startswith(prefix):
        return None
    kernel_id = blocker[len(prefix) :].split("::", 1)[0]
    return kernel_id if kernel_id in MAJOR_SCF_KERNEL_IDS else None


def _next_action_for_kernel(
    kernel_id: str,
    *,
    direct_hook_missing_count: int,
    runtime_movement_missing_count: int,
    composite_only_count: int,
    replacement_missing_count: int,
    runtime_event_missing_count: int,
) -> str:
    """Return an action-oriented diagnostic without weakening the hard gate."""

    if kernel_id == "dma_hbm_movement_engine" and runtime_movement_missing_count:
        return (
            "emit a trusted runtime movement event from the offload/runtime bridge "
            "with measured DMA/HBM cost, candidate/workload identity, and passed "
            "runtime proof; do not fake DMA closure with a QE call-site trace"
        )
    if kernel_id == "transpose_layout_conversion" and direct_hook_missing_count:
        return (
            "add an exact transpose/layout conversion observation surface and "
            "trusted replacement/runtime-cost evidence; FFT or h_psi composite "
            "call-sites remain diagnostic only"
        )
    if composite_only_count:
        return (
            "split the composite QE routine into exact major-kernel replacement "
            "rows and runtime-cost events before claiming this kernel"
        )
    if replacement_missing_count:
        return (
            "write trusted kernel_evidence/offload_provenance rows proving full "
            "kernel replacement and QE consumption of accelerated output"
        )
    if runtime_event_missing_count:
        return (
            "attach measured full-SCF runtime events for this exact major-kernel "
            "ID from a trusted runtime/accounting source"
        )
    return "keep row blocked until exact replacement evidence and trusted runtime cost events pass"


def build_campaign_hook_coverage_audit(
    *,
    row_root: Path,
    write_row_audits: bool = False,
    top_limit: int = 25,
) -> dict[str, Any]:
    row_root = row_root.resolve()
    records: list[dict[str, Any]] = []
    blocker_histogram: Counter[str] = Counter()
    kernel_status_histogram: dict[str, Counter[str]] = {
        kernel_id: Counter() for kernel_id in MAJOR_SCF_KERNEL_IDS
    }
    kernel_contract_pass_counts: Counter[str] = Counter()
    kernel_runtime_event_counts: Counter[str] = Counter()
    kernel_trusted_replacement_counts: Counter[str] = Counter()
    kernel_direct_hook_missing_counts: Counter[str] = Counter()
    kernel_runtime_movement_missing_counts: Counter[str] = Counter()
    kernel_composite_only_counts: Counter[str] = Counter()
    kernel_observed_without_replacement_counts: Counter[str] = Counter()
    kernel_replacement_missing_counts: Counter[str] = Counter()
    kernel_runtime_event_missing_counts: Counter[str] = Counter()
    rows_by_missing_contract: dict[str, list[str]] = defaultdict(list)

    for trace_path in sorted(row_root.rglob("qe_offload_callsite_trace.txt")):
        row_dir = trace_path.parent
        status = _row_status(row_dir)
        candidate_id, workload_case_id = _identity_from_row_dir(row_root, row_dir, status)
        audit = build_qe_full_scf_hook_coverage_audit(
            callsite_trace_path=trace_path,
            kernel_evidence_path=row_dir / "kernel_evidence.json",
            offload_provenance_path=row_dir / "offload_provenance.json",
            runtime_trace_path=row_dir / "full_scf_runtime_trace.json",
            runtime_execution_proof_path=row_dir / "runtime_execution_proof.json",
            candidate_id=candidate_id,
            workload_case_id=workload_case_id,
        )
        if write_row_audits:
            write_qe_full_scf_hook_coverage_audit(row_dir / "qe_full_scf_hook_coverage_audit.json", audit)

        for blocker in audit.get("blockers", []) or []:
            blocker_text = str(blocker)
            blocker_histogram[blocker_text] += 1
            if blocker_text.startswith("kernel_replacement_evidence_missing_or_untrusted::"):
                kernel_id = blocker_text.rsplit("::", 1)[-1]
                rows_by_missing_contract[kernel_id].append(str(row_dir))
            kernel_id = _kernel_suffix(blocker_text, "kernel_direct_qe_hook_missing::")
            if kernel_id:
                kernel_direct_hook_missing_counts[kernel_id] += 1
            kernel_id = _kernel_suffix(blocker_text, "kernel_runtime_movement_hook_missing::")
            if kernel_id:
                kernel_runtime_movement_missing_counts[kernel_id] += 1
            kernel_id = _kernel_suffix(blocker_text, "kernel_hook_composite_only::")
            if kernel_id:
                kernel_composite_only_counts[kernel_id] += 1
            kernel_id = _kernel_suffix(blocker_text, "kernel_hook_observed_without_replacement_evidence::")
            if kernel_id:
                kernel_observed_without_replacement_counts[kernel_id] += 1
            kernel_id = _kernel_suffix(blocker_text, "kernel_replacement_evidence_missing_or_untrusted::")
            if kernel_id:
                kernel_replacement_missing_counts[kernel_id] += 1
            kernel_id = _kernel_suffix(blocker_text, "runtime_event::")
            if kernel_id is None and blocker_text.startswith("runtime_event::"):
                # The row-level blocker is shaped as
                # runtime_event::<kernel>::runtime_event_missing_for_kernel.
                parts = blocker_text.split("::")
                kernel_id = parts[1] if len(parts) > 1 and parts[1] in MAJOR_SCF_KERNEL_IDS else None
            if kernel_id and "runtime_event_missing_for_kernel" in blocker_text:
                kernel_runtime_event_missing_counts[kernel_id] += 1
        for kernel_record in audit.get("major_kernel_records", []) or []:
            if not isinstance(kernel_record, Mapping):
                continue
            kernel_id = str(kernel_record.get("kernel_id") or "")
            if kernel_id not in kernel_status_histogram:
                continue
            kernel_status_histogram[kernel_id][str(kernel_record.get("status") or "unknown")] += 1
            if kernel_record.get("runtime_hook_contract_passed") is True:
                kernel_contract_pass_counts[kernel_id] += 1
            if kernel_record.get("trusted_runtime_cost_event_present") is True:
                kernel_runtime_event_counts[kernel_id] += 1
            if kernel_record.get("trusted_replacement_evidence_present") is True:
                kernel_trusted_replacement_counts[kernel_id] += 1

        records.append(
            {
                "row_dir": str(row_dir),
                "candidate_id": candidate_id,
                "workload_case_id": workload_case_id,
                "status": audit.get("status"),
                "passed": audit.get("passed") is True,
                "covered_major_kernel_count_diagnostic": audit.get("covered_major_kernel_count_diagnostic"),
                "runtime_hook_contract_passed_count": audit.get("runtime_hook_contract_passed_count"),
                "trusted_replacement_evidence_count": audit.get("trusted_replacement_evidence_count"),
                "trusted_runtime_cost_event_count": audit.get("trusted_runtime_cost_event_count"),
                "blockers": audit.get("blockers", []),
            }
        )

    row_count = len(records)
    passed_count = sum(1 for record in records if record["passed"])
    blocked_count = row_count - passed_count
    status = "passed" if row_count > 0 and blocked_count == 0 else "blocked_temporary"
    campaign_blockers: list[str] = []
    if row_count == 0:
        campaign_blockers.append("no_qe_callsite_traces_found_under_row_root")
    kernel_next_action_matrix = {
        kernel_id: {
            "kernel_id": kernel_id,
            "status_histogram": dict(sorted(kernel_status_histogram[kernel_id].items())),
            "runtime_hook_contract_pass_count": kernel_contract_pass_counts[kernel_id],
            "trusted_replacement_count": kernel_trusted_replacement_counts[kernel_id],
            "trusted_runtime_event_count": kernel_runtime_event_counts[kernel_id],
            "direct_hook_missing_count": kernel_direct_hook_missing_counts[kernel_id],
            "runtime_movement_missing_count": kernel_runtime_movement_missing_counts[kernel_id],
            "composite_only_count": kernel_composite_only_counts[kernel_id],
            "observed_without_replacement_count": kernel_observed_without_replacement_counts[kernel_id],
            "replacement_missing_or_untrusted_count": kernel_replacement_missing_counts[kernel_id],
            "runtime_event_missing_count": kernel_runtime_event_missing_counts[kernel_id],
            "required_next_action": _next_action_for_kernel(
                kernel_id,
                direct_hook_missing_count=kernel_direct_hook_missing_counts[kernel_id],
                runtime_movement_missing_count=kernel_runtime_movement_missing_counts[kernel_id],
                composite_only_count=kernel_composite_only_counts[kernel_id],
                replacement_missing_count=kernel_replacement_missing_counts[kernel_id],
                runtime_event_missing_count=kernel_runtime_event_missing_counts[kernel_id],
            ),
            "claim_boundary": (
                "Per-kernel campaign diagnostics only; these counters do not "
                "satisfy strict row accounting or numerical comparison."
            ),
        }
        for kernel_id in MAJOR_SCF_KERNEL_IDS
    }
    return {
        "schema_version": CAMPAIGN_SCHEMA,
        "row_audit_schema_version": QE_FULL_SCF_HOOK_COVERAGE_AUDIT_SCHEMA,
        "row_root": str(row_root),
        "status": status,
        "passed": status == "passed",
        "row_count": row_count,
        "passed_row_count": passed_count,
        "blocked_row_count": blocked_count,
        "required_major_kernel_ids": list(MAJOR_SCF_KERNEL_IDS),
        "kernel_status_histogram": {
            kernel_id: dict(sorted(counter.items()))
            for kernel_id, counter in kernel_status_histogram.items()
        },
        "kernel_runtime_hook_contract_pass_counts": dict(sorted(kernel_contract_pass_counts.items())),
        "kernel_trusted_replacement_counts": dict(sorted(kernel_trusted_replacement_counts.items())),
        "kernel_trusted_runtime_event_counts": dict(sorted(kernel_runtime_event_counts.items())),
        "kernel_direct_hook_missing_counts": dict(sorted(kernel_direct_hook_missing_counts.items())),
        "kernel_runtime_movement_missing_counts": dict(sorted(kernel_runtime_movement_missing_counts.items())),
        "kernel_composite_only_counts": dict(sorted(kernel_composite_only_counts.items())),
        "kernel_observed_without_replacement_counts": dict(sorted(kernel_observed_without_replacement_counts.items())),
        "kernel_replacement_missing_or_untrusted_counts": dict(sorted(kernel_replacement_missing_counts.items())),
        "kernel_runtime_event_missing_counts": dict(sorted(kernel_runtime_event_missing_counts.items())),
        "kernel_next_action_matrix": kernel_next_action_matrix,
        "rows_missing_runtime_contract_by_kernel": {
            kernel_id: rows[:top_limit]
            for kernel_id, rows in sorted(rows_by_missing_contract.items())
        },
        "blocker_histogram": dict(sorted(blocker_histogram.items())),
        "campaign_blockers": campaign_blockers,
        "top_blockers": _top_blockers(blocker_histogram, top_limit),
        "records": records,
        "claim_boundary": (
            "Campaign hook audit only. It aggregates fail-closed row diagnostics "
            "and cannot satisfy strict full-SCF row accounting, numerical "
            "comparison, FPGA/ASIC PPA gates, or deliverable-complete claims."
        ),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--row-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--write-row-audits", action="store_true")
    parser.add_argument("--top-limit", type=int, default=25)
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_campaign_hook_coverage_audit(
        row_root=args.row_root,
        write_row_audits=args.write_row_audits,
        top_limit=max(1, int(args.top_limit)),
    )
    _write_json(args.out, payload)
    print(
        json.dumps(
            {
                "artifact": str(args.out),
                "status": payload["status"],
                "passed": payload["passed"],
                "row_count": payload["row_count"],
                "blocked_row_count": payload["blocked_row_count"],
                "top_blockers": payload["top_blockers"][:5],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.fail_on_blocked and payload["passed"] is not True:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
