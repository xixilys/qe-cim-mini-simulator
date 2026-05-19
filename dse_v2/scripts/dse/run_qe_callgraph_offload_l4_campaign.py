#!/usr/bin/env python3
"""Run a bounded QE full-callgraph offload L4 campaign.

The single-opportunity smoke runner proves one selected callsite at a time.  This
campaign runner is the DSE-facing layer: it chooses *which* workload/stage/kernel
/callsite/bundle opportunities to try, defaults away from h_psi-only probing,
runs the selected smoke attempts, and emits a combined blocker/value report.

It is intentionally anti-downgrade.  A campaign may broaden real QE + gem5 L4
coverage, but it never converts a campaign, projection rank, or h_psi-only result
into ``valuable_l4`` or ``deliverable_complete``.
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

from dse_v2.codesign.qe_callgraph_offload_search import (  # noqa: E402
    NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID,
    NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID,
    SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID,
    SPSI_NC_CG_WORKLOAD_VARIANT_ID,
    WORKLOAD_SELECTION_AXES,
    build_offload_bundle_search_space,
    build_workload_variant_search_space,
    offload_artifact_bundle,
)
from dse_v2.scripts.dse.build_qe_callgraph_l4_multi_probe_report import (  # noqa: E402
    build_multi_probe_report,
)

CAMPAIGN_PLAN_SCHEMA = "dse.qe_callgraph_offload_l4_campaign_plan.v1"
CAMPAIGN_STATUS_SCHEMA = "dse.qe_callgraph_offload_l4_campaign_status.v1"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_or_build_artifacts(*, source_root: Path, artifact_root: Path | None) -> dict[str, Any]:
    if artifact_root is None:
        return offload_artifact_bundle(source_root=source_root)
    required = (
        "qe_callgraph_inventory.json",
        "offload_opportunity_manifest.json",
        "offload_bundle_search_space.json",
        "qe_callsite_patch_manifest.json",
    )
    optional = (
        "offload_workload_variant_search_space.json",
        "offload_target_identity_schema.json",
        "l4_offload_attempt_queue.json",
        "offload_value_l4_evidence_matrix.json",
        "offload_value_report.json",
        "callgraph_offload_blocker_report.json",
        "accelerated_replacement_readiness_report.json",
        "offload_selection_search_report.json",
        "prompt_to_artifact_checklist.json",
    )
    artifacts: dict[str, Any] = {}
    missing: list[str] = []
    for name in required:
        path = artifact_root / name
        if path.exists():
            artifacts[name] = _load_json(path)
        else:
            missing.append(str(path))
    if missing:
        raise FileNotFoundError(
            "artifact_root is missing required campaign planning artifacts: "
            + ", ".join(missing)
        )
    for name in optional:
        path = artifact_root / name
        if path.exists():
            artifacts[name] = _load_json(path)
    return artifacts


def _safe_path_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def _dedupe_keep_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _bundle_index(bundle_space: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the best-ranked bundle metadata per opportunity id."""
    best_by_opp: dict[str, dict[str, Any]] = {}
    for rank, bundle in enumerate(bundle_space.get("bundles", []) or [], start=1):
        if not isinstance(bundle, Mapping):
            continue
        priority = bundle.get("selection_priority", {})
        score = 0.0
        if isinstance(priority, Mapping):
            try:
                score = float(priority.get("score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
        summary = {
            "bundle_id": bundle.get("bundle_id"),
            "bundle_rank": rank,
            "bundle_score": score,
            "bundle_granularity": bundle.get("granularity"),
            "bundle_classification": bundle.get("classification"),
        }
        for opportunity_id in bundle.get("opportunity_ids", []) or []:
            key = str(opportunity_id)
            current = best_by_opp.get(key)
            if current is None or (score, -rank) > (
                float(current.get("bundle_score", 0.0) or 0.0),
                -int(current.get("bundle_rank", 10**9) or 10**9),
            ):
                best_by_opp[key] = dict(summary)
    return best_by_opp


def _bundle_metadata_by_id(bundle_space: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for rank, bundle in enumerate(bundle_space.get("bundles", []) or [], start=1):
        if not isinstance(bundle, Mapping) or not bundle.get("bundle_id"):
            continue
        priority = bundle.get("selection_priority", {})
        score = 0.0
        if isinstance(priority, Mapping):
            try:
                score = float(priority.get("score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
        rows[str(bundle["bundle_id"])] = {
            "bundle_id": bundle.get("bundle_id"),
            "bundle_rank": rank,
            "bundle_score": score,
            "bundle_granularity": bundle.get("granularity"),
            "bundle_classification": bundle.get("classification"),
            "bundle_opportunity_ids": list(bundle.get("opportunity_ids") or []),
            "bundle_kernel_list": list(bundle.get("kernel_list") or []),
            "bundle_workload_case_id": bundle.get("workload_case_id"),
            "bundle_stage_type": bundle.get("stage_type"),
            "bundle_execution_policy": bundle.get("bundle_execution_policy"),
            "runnable_as_single_qe_workflow": bundle.get(
                "runnable_as_single_qe_workflow"
            ),
        }
    return rows


def _variant_index(
    workload_variant_search_space: Mapping[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    best_by_opp: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(workload_variant_search_space, Mapping):
        return best_by_opp
    for variant in workload_variant_search_space.get("variants", []) or []:
        if not isinstance(variant, Mapping):
            continue
        summary = {
            "variant_id": variant.get("variant_id"),
            "variant_kind": variant.get("variant_kind"),
            "variant_status": variant.get("variant_status"),
            "pseudopotential_family": variant.get("pseudopotential_family"),
            "offload_target_binding": dict(
                variant.get("offload_target_binding") or {}
            ),
            "input_overrides": dict(variant.get("input_overrides") or {}),
            "replacement_semantics": dict(
                variant.get("replacement_semantics") or {}
            ),
            "selection_reason": (
                "formal_workload_variant_probe"
                if variant.get("variant_status")
                == "formal_workload_variant_candidate"
                else "canonical_workload_variant"
            ),
        }
        for opportunity_id in variant.get("applies_to_opportunity_ids", []) or []:
            best_by_opp.setdefault(str(opportunity_id), []).append(dict(summary))
    for variants in best_by_opp.values():
        preference = {
            SPSI_NC_CG_LARGER_WORKLOAD_VARIANT_ID: 0,
            SPSI_NC_CG_WORKLOAD_VARIANT_ID: 1,
            NSCF_STRESS_BANDGRID_WORKLOAD_VARIANT_ID: 2,
            NSCF_ULTRA_BANDGRID_WORKLOAD_VARIANT_ID: 3,
            NSCF_HEAVY_BANDGRID_WORKLOAD_VARIANT_ID: 4,
            NSCF_AMORTIZED_BANDGRID_WORKLOAD_VARIANT_ID: 5,
        }
        variants.sort(
            key=lambda row: (
                preference.get(str(row.get("variant_id") or ""), 99),
                str(row.get("variant_id") or ""),
            )
        )
    return best_by_opp


def _selected_variant_for_opportunity(
    opportunity: Mapping[str, Any],
    variants_by_opp: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    enable_formal_variants: bool,
) -> dict[str, Any]:
    if not enable_formal_variants:
        return {}
    opportunity_id = str(opportunity.get("opportunity_id") or "")
    kernel = str(opportunity.get("kernel") or "")
    for variant in variants_by_opp.get(opportunity_id, []) or []:
        binding = variant.get("offload_target_binding")
        target_kernel = (
            str(binding.get("target_kernel") or "")
            if isinstance(binding, Mapping)
            else ""
        )
        target_kernels = (
            {
                str(item)
                for item in binding.get("target_kernels", []) or []
            }
            if isinstance(binding, Mapping)
            else set()
        )
        if kernel == "s_psi" and target_kernel == "s_psi":
            return dict(variant)
        if kernel in target_kernels:
            return dict(variant)
    return {}


def _opportunity_score(opportunity: Mapping[str, Any]) -> float:
    priority = opportunity.get("selection_priority", {})
    if not isinstance(priority, Mapping):
        return 0.0
    try:
        return float(priority.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _rank_opportunities(
    opportunities: Sequence[Mapping[str, Any]],
    bundle_by_opp: Mapping[str, Mapping[str, Any]],
    variants_by_opp: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    *,
    include_hpsi: bool,
    enable_formal_variants: bool = True,
) -> list[Mapping[str, Any]]:
    candidates = [dict(row) for row in opportunities if isinstance(row, Mapping)]
    if not include_hpsi:
        candidates = [row for row in candidates if row.get("kernel") != "h_psi"]
    def profile_observed(row: Mapping[str, Any]) -> bool:
        profile = row.get("profile_evidence", {})
        return (
            isinstance(profile, Mapping)
            and profile.get("status") == "fixture_profile_observed"
        )

    def replacement_variant_ready(row: Mapping[str, Any]) -> bool:
        variant = _selected_variant_for_opportunity(
            row,
            variants_by_opp or {},
            enable_formal_variants=enable_formal_variants,
        )
        return bool(variant)

    candidates.sort(
        key=lambda row: (
            row.get("kernel") == "h_psi",
            not (profile_observed(row) or replacement_variant_ready(row)),
            not replacement_variant_ready(row),
            -float(dict(bundle_by_opp.get(str(row.get("opportunity_id")), {})).get("bundle_score", 0.0) or 0.0),
            int(dict(bundle_by_opp.get(str(row.get("opportunity_id")), {})).get("bundle_rank", 10**9) or 10**9),
            -_opportunity_score(row),
            str(row.get("workload_case_id") or ""),
            str(row.get("stage_type") or ""),
            str(row.get("kernel") or ""),
            str(row.get("opportunity_id") or ""),
        )
    )
    return candidates


def _take_campaign_window(
    ranked: Sequence[Mapping[str, Any]],
    *,
    max_attempts: int,
    diversify_kernels: bool,
) -> list[Mapping[str, Any]]:
    if not diversify_kernels:
        return [dict(row) for row in ranked[:max_attempts]]

    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    seen_kernels: set[str] = set()
    # First pass: maximize kernel diversity so a bounded campaign does not
    # collapse into a single dense-subspace/diagonalization-only probe.
    for row in ranked:
        opportunity_id = str(row.get("opportunity_id") or "")
        kernel = str(row.get("kernel") or "")
        if not opportunity_id or opportunity_id in selected_ids:
            continue
        if kernel in seen_kernels:
            continue
        selected.append(dict(row))
        selected_ids.add(opportunity_id)
        seen_kernels.add(kernel)
        if len(selected) >= max_attempts:
            return selected

    # Second pass: fill remaining slots by ranking while preserving duplicates
    # only after all available kernels have had a chance to appear.
    for row in ranked:
        opportunity_id = str(row.get("opportunity_id") or "")
        if not opportunity_id or opportunity_id in selected_ids:
            continue
        selected.append(dict(row))
        selected_ids.add(opportunity_id)
        if len(selected) >= max_attempts:
            return selected
    return selected


def build_campaign_plan(
    opportunity_manifest: Mapping[str, Any],
    bundle_space: Mapping[str, Any] | None = None,
    workload_variant_search_space: Mapping[str, Any] | None = None,
    *,
    max_attempts: int = 4,
    include_hpsi: bool = False,
    explicit_opportunity_ids: Sequence[str] | None = None,
    explicit_bundle_ids: Sequence[str] | None = None,
    require_non_hpsi: bool = True,
    diversify_kernels: bool = True,
    enable_formal_workload_variants: bool = True,
) -> dict[str, Any]:
    """Choose a bounded set of offload opportunities for real L4 attempts."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    opportunities = [
        dict(row)
        for row in opportunity_manifest.get("opportunities", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    ]
    if bundle_space is None:
        bundle_space = build_offload_bundle_search_space(opportunity_manifest)
    if workload_variant_search_space is None:
        workload_variant_search_space = build_workload_variant_search_space(
            opportunity_manifest
        )
    bundle_by_opp = _bundle_index(bundle_space)
    variants_by_opp = _variant_index(workload_variant_search_space)
    by_id = {str(row["opportunity_id"]): row for row in opportunities}

    unknown_ids: list[str] = []
    selected_bundle_ids: list[str] = []
    explicit_bundle_by_opp: dict[str, dict[str, Any]] = {}
    if explicit_opportunity_ids and explicit_bundle_ids:
        raise ValueError("use either explicit_opportunity_ids or explicit_bundle_ids, not both")
    if explicit_opportunity_ids:
        ranked = []
        for opportunity_id in explicit_opportunity_ids:
            row = by_id.get(str(opportunity_id))
            if row is None:
                unknown_ids.append(str(opportunity_id))
                continue
            if include_hpsi or row.get("kernel") != "h_psi":
                ranked.append(row)
    elif explicit_bundle_ids:
        bundle_by_id = _bundle_metadata_by_id(bundle_space)
        ranked = []
        seen_opportunities: set[str] = set()
        for bundle_id in explicit_bundle_ids:
            bundle = bundle_by_id.get(str(bundle_id))
            if bundle is None:
                unknown_ids.append(f"unknown_bundle_id:{bundle_id}")
                continue
            selected_bundle_ids.append(str(bundle_id))
            for opportunity_id in bundle.get("bundle_opportunity_ids", []) or []:
                row = by_id.get(str(opportunity_id))
                if row is None:
                    unknown_ids.append(
                        f"bundle_unknown_opportunity_id:{bundle_id}:{opportunity_id}"
                    )
                    continue
                if not include_hpsi and row.get("kernel") == "h_psi":
                    continue
                if str(opportunity_id) in seen_opportunities:
                    continue
                explicit_bundle_by_opp[str(opportunity_id)] = dict(bundle)
                ranked.append(row)
                seen_opportunities.add(str(opportunity_id))
    else:
        ranked = _rank_opportunities(
            opportunities,
            bundle_by_opp,
            variants_by_opp,
            include_hpsi=include_hpsi,
            enable_formal_variants=enable_formal_workload_variants,
        )

    selected = _take_campaign_window(
        ranked,
        max_attempts=max_attempts,
        diversify_kernels=(
            diversify_kernels
            and not explicit_opportunity_ids
            and not explicit_bundle_ids
        ),
    )
    selected_rows: list[dict[str, Any]] = []
    for attempt_index, opportunity in enumerate(selected, start=1):
        opportunity_id = str(opportunity["opportunity_id"])
        bundle = dict(
            explicit_bundle_by_opp.get(opportunity_id)
            or bundle_by_opp.get(opportunity_id)
            or {}
        )
        variant = _selected_variant_for_opportunity(
            opportunity,
            variants_by_opp,
            enable_formal_variants=enable_formal_workload_variants,
        )
        selected_rows.append(
            {
                "attempt_index": attempt_index,
                "opportunity_id": opportunity_id,
                "workload_case_id": opportunity.get("workload_case_id"),
                "stage_type": opportunity.get("stage_type"),
                "phase": opportunity.get("phase"),
                "kernel": opportunity.get("kernel"),
                "kernel_family": opportunity.get("kernel_family"),
                "callsite_id": opportunity.get("callsite_id"),
                "selected_bundle_id": bundle.get("bundle_id"),
                "selected_bundle_rank": bundle.get("bundle_rank"),
                "selected_bundle_score": bundle.get("bundle_score"),
                "selected_bundle_granularity": bundle.get("bundle_granularity"),
                "selected_bundle_classification": bundle.get(
                    "bundle_classification"
                ),
                "selected_bundle_opportunity_count": len(
                    bundle.get("bundle_opportunity_ids") or []
                ),
                "selected_bundle_kernel_list": list(
                    bundle.get("bundle_kernel_list") or []
                ),
                "selected_bundle_execution_policy": bundle.get(
                    "bundle_execution_policy"
                ),
                "selected_bundle_runnable_as_single_qe_workflow": bundle.get(
                    "runnable_as_single_qe_workflow"
                ),
                "selected_workload_variant_id": variant.get("variant_id"),
                "selected_workload_variant_binding": dict(
                    variant.get("offload_target_binding") or {}
                ),
                "selected_workload_variant_reason": variant.get("selection_reason"),
                "selected_workload_variant_input_overrides": dict(
                    variant.get("input_overrides") or {}
                ),
                "opportunity_score": _opportunity_score(opportunity),
                "workload_selection": dict(opportunity.get("workload_selection") or {}),
                "profile_evidence": dict(opportunity.get("profile_evidence") or {}),
                "selection_reason": (
                    "explicit_bundle_id"
                    if explicit_bundle_ids
                    else (
                        "explicit_opportunity_id"
                        if explicit_opportunity_ids
                        else "ranked_dse_offload_target_search"
                    )
                ),
                "per_opportunity_expansion_only": bool(explicit_bundle_ids),
                "single_qe_workflow_bundle_proof": False,
                "bundle_level_value_claim_allowed": False,
                "claim_boundary": (
                    "campaign selection chooses what to attempt; it is not value evidence"
                ),
            }
        )

    non_hpsi_count = sum(1 for row in selected_rows if row.get("kernel") != "h_psi")
    hpsi_count = sum(1 for row in selected_rows if row.get("kernel") == "h_psi")
    blockers: list[str] = []
    if unknown_ids:
        blockers.extend(f"unknown_opportunity_id:{item}" for item in unknown_ids)
    if not selected_rows:
        blockers.append("no_l4_campaign_opportunity_selected")
    if require_non_hpsi and non_hpsi_count == 0:
        blockers.append("no_non_hpsi_l4_campaign_opportunity_selected")
    explicit_bundle_expansion = bool(explicit_bundle_ids)
    single_workflow_candidate_bundle_ids = _dedupe_keep_order(
        str(row.get("selected_bundle_id"))
        for row in selected_rows
        if row.get("selected_bundle_runnable_as_single_qe_workflow") is True
        and row.get("selected_bundle_id")
    )
    single_workflow_bundle_blockers: list[str] = []
    if explicit_bundle_expansion:
        single_workflow_bundle_blockers.extend(
            [
                "explicit_bundle_campaign_expands_to_per_opportunity_attempts",
                "single_qe_workflow_bundle_runner_not_implemented_in_campaign",
                "bundle_level_value_requires_separate_single_workflow_evidence",
            ]
        )

    payload = {
        "schema_version": CAMPAIGN_PLAN_SCHEMA,
        "status": "blocked" if blockers else "planned",
        "manifest_hash": opportunity_manifest.get("manifest_hash"),
        "bundle_search_space_hash": bundle_space.get("search_space_hash") if isinstance(bundle_space, Mapping) else None,
        "full_callgraph_opportunity_count": len(opportunities),
        "bundle_count": bundle_space.get("bundle_count") if isinstance(bundle_space, Mapping) else None,
        "max_attempts": max_attempts,
        "include_hpsi": include_hpsi,
        "require_non_hpsi": require_non_hpsi,
        "diversify_kernels": (
            diversify_kernels
            and not bool(explicit_opportunity_ids)
            and not bool(explicit_bundle_ids)
        ),
        "enable_formal_workload_variants": enable_formal_workload_variants,
        "workload_variant_search_space_hash": (
            workload_variant_search_space.get("search_space_hash")
            if isinstance(workload_variant_search_space, Mapping)
            else None
        ),
        "selected_attempt_count": len(selected_rows),
        "selected_non_hpsi_attempt_count": non_hpsi_count,
        "selected_hpsi_attempt_count": hpsi_count,
        "selected_bundle_ids": selected_bundle_ids,
        "selected_bundle_count": len(selected_bundle_ids),
        "selected_bundle_expanded_opportunity_count": len(
            {
                str(row.get("opportunity_id"))
                for row in selected_rows
                if row.get("selection_reason") == "explicit_bundle_id"
            }
        ),
        "selected_bundle_single_workflow_candidate_count": len(
            single_workflow_candidate_bundle_ids
        ),
        "selected_bundle_single_workflow_candidate_ids": (
            single_workflow_candidate_bundle_ids
        ),
        "single_qe_workflow_bundle_attempt_planned": False,
        "per_opportunity_expansion_only": explicit_bundle_expansion,
        "bundle_level_value_claim_allowed": False,
        "single_workflow_bundle_blockers": single_workflow_bundle_blockers,
        "selection_axes": list(WORKLOAD_SELECTION_AXES),
        "selected_opportunities": selected_rows,
        "blockers": blockers,
        "hpsi_only_completion_allowed": False,
        "projection_only_value_allowed": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "DSE callgraph campaign plan searches workload/stage/phase/kernel/"
            "callsite/bundle targets for real L4 attempts. The plan itself and "
            "any h_psi-only subset cannot claim value or completion."
        ),
    }
    return payload


def _smoke_command(
    *,
    args: argparse.Namespace,
    smoke_runner: Path,
    artifact_root: Path,
    attempt_dir: Path,
    opportunity_id: str,
    workload_variant_id: str | None = None,
    batched_bridge_override: bool | None = None,
) -> list[str]:
    cmd = [
        sys.executable,
        str(smoke_runner),
        "--out",
        str(attempt_dir),
        "--source-root",
        str(args.source_root),
        "--artifact-root",
        str(artifact_root),
        "--opportunity-id",
        opportunity_id,
        "--baseline-policy",
        args.baseline_policy,
        "--qe-baseline-timeout",
        str(args.qe_baseline_timeout),
        "--gem5-transport-max-ticks",
        str(args.gem5_transport_max_ticks),
        "--gem5-binary",
        str(args.gem5_binary),
        "--gem5-config",
        str(args.gem5_config),
        "--gem5-driver",
        str(args.gem5_driver),
        "--simulator",
        str(args.simulator),
    ]
    if workload_variant_id:
        cmd.extend(["--workload-variant-id", workload_variant_id])
    if args.qe_bin_dir is not None:
        cmd.extend(["--qe-bin-dir", str(args.qe_bin_dir)])
    if args.qe_pseudo_dir is not None:
        cmd.extend(["--qe-pseudo-dir", str(args.qe_pseudo_dir)])
    if args.trace_instrumented_qe:
        cmd.append("--trace-instrumented-qe")
    if args.run_gem5_transport:
        cmd.append("--run-gem5-transport")
    if args.run_patched_qe_bridge:
        cmd.append("--run-patched-qe-bridge")
    evidence_mode = getattr(args, "evidence_mode", "dataflow_smoke")
    if evidence_mode != "dataflow_smoke":
        cmd.extend(["--evidence-mode", str(evidence_mode)])
    batched_bridge = (
        bool(batched_bridge_override)
        if batched_bridge_override is not None
        else bool(getattr(args, "batched_patched_qe_bridge", False))
    )
    if batched_bridge:
        cmd.append("--batched-patched-qe-bridge")
    if getattr(args, "prelaunch_patched_qe_bridge", False):
        cmd.append("--prelaunch-patched-qe-bridge")
    if hasattr(args, "max_batched_bridge_trace_count"):
        cmd.extend(
            [
                "--max-batched-bridge-trace-count",
                str(args.max_batched_bridge_trace_count),
            ]
        )
    return cmd


def _bridge_dispatch_policy_candidates(
    args: argparse.Namespace,
) -> list[tuple[str, bool | None]]:
    """Return DSE dispatch-policy candidates for patched QE bridge attempts.

    The legacy campaign switch, ``--batched-patched-qe-bridge``, still means
    "run the one selected policy".  ``--search-bridge-dispatch-policies``
    intentionally widens DSE to compare the single-launch policy against the
    trace-batched policy for the same offload target.  Both rows remain
    non-smoke value attempts only when ``--evidence-mode actual_compute`` is
    selected; neither policy can claim value without the normal correctness,
    replacement, and positive-speed gates.
    """
    if not (
        getattr(args, "search_bridge_dispatch_policies", False)
        and getattr(args, "run_patched_qe_bridge", False)
    ):
        label = (
            "trace_batched"
            if getattr(args, "batched_patched_qe_bridge", False)
            else "single_launch"
        )
        return [(label, None)]
    return [
        ("single_launch", False),
        ("trace_batched", True),
    ]


def _blocked_attempt_from_failure(
    opportunity: Mapping[str, Any],
    *,
    command: Sequence[str],
    returncode: int | None,
    attempt_dir: Path,
) -> dict[str, Any]:
    blockers = ["campaign_smoke_subprocess_failed"]
    if returncode is not None:
        blockers.append(f"campaign_smoke_returncode:{returncode}")
    return {
        "schema_version": "dse.qe_callgraph_l4_offload_attempt_evidence.v1",
        "opportunity_id": opportunity.get("opportunity_id"),
        "kernel": opportunity.get("kernel"),
        "stage_type": opportunity.get("stage_type"),
        "callsite_id": opportunity.get("callsite_id"),
        "evidence_kind": "real_qe_l4_dataflow_smoke",
        "evidence_scope": "dataflow_smoke_only",
        "actual_compute_evidence": {
            "status": "blocked",
            "smoke_only": True,
            "blockers": ["smoke_dataflow_only_not_actual_compute"],
        },
        "attempt_status": "blocked",
        "real_l4_provenance": {"status": "blocked", "blockers": blockers},
        "correctness": {"status": "blocked", "blockers": blockers},
        "pure_qe_baseline": {"status": "blocked", "blockers": blockers},
        "accelerated_replacement": {
            "status": "missing",
            "accelerated_results_consumed_by_qe": False,
            "software_fallback_on_critical_path": True,
            "blockers": blockers,
        },
        "speed_signal": {"status": "blocked", "speedup_vs_pure_qe": None, "blockers": blockers},
        "commands": {"campaign_smoke_command": list(command)},
        "blockers": blockers,
        "claim_boundary": f"campaign subprocess failed; see {attempt_dir}",
    }


def run_campaign(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = _load_or_build_artifacts(
        source_root=args.source_root,
        artifact_root=args.artifact_root,
    )
    for name, payload in artifacts.items():
        _write_json(out_dir / name, payload)

    manifest = artifacts["offload_opportunity_manifest.json"]
    bundle_space = artifacts.get("offload_bundle_search_space.json") or build_offload_bundle_search_space(manifest)
    workload_variants = artifacts.get(
        "offload_workload_variant_search_space.json"
    ) or build_workload_variant_search_space(manifest)
    explicit_ids: Sequence[str] | None = args.opportunity_id or None
    explicit_bundle_ids: Sequence[str] | None = args.bundle_id or None
    plan = build_campaign_plan(
        manifest,
        bundle_space,
        workload_variants,
        max_attempts=args.max_attempts,
        include_hpsi=args.include_hpsi,
        explicit_opportunity_ids=explicit_ids,
        explicit_bundle_ids=explicit_bundle_ids,
        require_non_hpsi=not args.allow_hpsi_only_campaign,
        diversify_kernels=not args.no_diversify_kernels,
        enable_formal_workload_variants=not args.no_formal_workload_variants,
    )
    _write_json(out_dir / "campaign_plan.json", plan)

    if args.dry_run or plan["status"] == "blocked":
        status = {
            "schema_version": CAMPAIGN_STATUS_SCHEMA,
            "status": "planned_only" if plan["status"] != "blocked" else "blocked",
            "campaign_plan_path": str(out_dir / "campaign_plan.json"),
            "selected_attempt_count": plan["selected_attempt_count"],
            "selected_non_hpsi_attempt_count": plan["selected_non_hpsi_attempt_count"],
            "selected_hpsi_attempt_count": plan["selected_hpsi_attempt_count"],
            "selected_bundle_count": plan.get("selected_bundle_count", 0),
            "selected_bundle_ids": plan.get("selected_bundle_ids", []),
            "selected_bundle_expanded_opportunity_count": plan.get(
                "selected_bundle_expanded_opportunity_count", 0
            ),
            "selected_bundle_single_workflow_candidate_count": plan.get(
                "selected_bundle_single_workflow_candidate_count", 0
            ),
            "selected_bundle_single_workflow_candidate_ids": plan.get(
                "selected_bundle_single_workflow_candidate_ids", []
            ),
            "single_qe_workflow_bundle_attempt_planned": plan.get(
                "single_qe_workflow_bundle_attempt_planned", False
            ),
            "per_opportunity_expansion_only": plan.get(
                "per_opportunity_expansion_only", False
            ),
            "bundle_level_value_claim_allowed": plan.get(
                "bundle_level_value_claim_allowed", False
            ),
            "single_workflow_bundle_blockers": plan.get(
                "single_workflow_bundle_blockers", []
            ),
            "attempted_count": 0,
            "valuable_l4_count": 0,
            "replacement_ready_count": 0,
            "deliverable_complete": False,
            "blockers": plan.get("blockers", []),
            "claim_boundary": "dry-run or blocked campaign planning only; no value claim",
        }
        _write_json(out_dir / "status.json", status)
        return status

    smoke_runner = args.smoke_runner
    opportunity_by_id = {
        str(row.get("opportunity_id")): row
        for row in manifest.get("opportunities", []) or []
        if isinstance(row, Mapping) and row.get("opportunity_id")
    }
    attempt_paths: list[Path] = []
    attempt_statuses: list[dict[str, Any]] = []
    dispatch_policy_candidates = _bridge_dispatch_policy_candidates(args)
    for selected in plan.get("selected_opportunities", []) or []:
        if not isinstance(selected, Mapping):
            continue
        opportunity_id = str(selected.get("opportunity_id"))
        opportunity = opportunity_by_id.get(opportunity_id, selected)
        for dispatch_label, batched_bridge_override in dispatch_policy_candidates:
            base_index = int(selected.get("attempt_index", len(attempt_paths) + 1))
            policy_suffix = (
                ""
                if len(dispatch_policy_candidates) == 1
                else f"_{_safe_path_component(dispatch_label)}"
            )
            attempt_dir = (
                out_dir
                / "attempts"
                / f"{base_index:02d}_{_safe_path_component(opportunity_id)}{policy_suffix}"
            )
            attempt_dir.mkdir(parents=True, exist_ok=True)
            command = _smoke_command(
                args=args,
                smoke_runner=smoke_runner,
                artifact_root=out_dir,
                attempt_dir=attempt_dir,
                opportunity_id=opportunity_id,
                workload_variant_id=(
                    str(selected.get("selected_workload_variant_id"))
                    if selected.get("selected_workload_variant_id")
                    else None
                ),
                batched_bridge_override=batched_bridge_override,
            )
            command_payload = {
                "command": command,
                "bridge_dispatch_policy_candidate": dispatch_label,
                "batched_patched_qe_bridge": (
                    bool(batched_bridge_override)
                    if batched_bridge_override is not None
                    else bool(getattr(args, "batched_patched_qe_bridge", False))
                ),
                "claim_boundary": (
                    "DSE dispatch-policy search metadata only; value remains "
                    "gated by the attempt evidence row"
                ),
            }
            (attempt_dir / "campaign_smoke_command.json").write_text(
                json.dumps(command_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(command, capture_output=True, text=True)
            (attempt_dir / "campaign_smoke_stdout.log").write_text(
                completed.stdout or "", encoding="utf-8"
            )
            (attempt_dir / "campaign_smoke_stderr.log").write_text(
                completed.stderr or "", encoding="utf-8"
            )
            attempt_path = attempt_dir / "l4_offload_attempt_evidence.json"
            if not attempt_path.exists():
                blocked = _blocked_attempt_from_failure(
                    opportunity,
                    command=command,
                    returncode=completed.returncode,
                    attempt_dir=attempt_dir,
                )
                _write_json(attempt_path, blocked)
            attempt_paths.append(attempt_path)
            attempt_statuses.append(
                {
                    "opportunity_id": opportunity_id,
                    "attempt_dir": str(attempt_dir),
                    "attempt_evidence_path": str(attempt_path),
                    "returncode": completed.returncode,
                    "bridge_dispatch_policy_candidate": dispatch_label,
                    "batched_patched_qe_bridge": command_payload[
                        "batched_patched_qe_bridge"
                    ],
                }
            )

    combined_dir = out_dir / "multi_probe_report"
    combined_status = build_multi_probe_report(
        out_dir=combined_dir,
        inventory_path=out_dir / "qe_callgraph_inventory.json",
        manifest_path=out_dir / "offload_opportunity_manifest.json",
        attempt_paths=attempt_paths,
        patch_manifest_path=out_dir / "qe_callsite_patch_manifest.json",
    )
    status = {
        "schema_version": CAMPAIGN_STATUS_SCHEMA,
        "status": "partial_or_blocked",
        "campaign_plan_path": str(out_dir / "campaign_plan.json"),
        "combined_report_dir": str(combined_dir),
        "selected_attempt_count": plan["selected_attempt_count"],
        "selected_non_hpsi_attempt_count": plan["selected_non_hpsi_attempt_count"],
        "selected_hpsi_attempt_count": plan["selected_hpsi_attempt_count"],
        "selected_bundle_count": plan.get("selected_bundle_count", 0),
        "selected_bundle_ids": plan.get("selected_bundle_ids", []),
        "selected_bundle_expanded_opportunity_count": plan.get(
            "selected_bundle_expanded_opportunity_count", 0
        ),
        "attempted_count": len(attempt_paths),
        "attempt_statuses": attempt_statuses,
        "bridge_dispatch_policy_search_enabled": bool(
            getattr(args, "search_bridge_dispatch_policies", False)
            and getattr(args, "run_patched_qe_bridge", False)
        ),
        "bridge_dispatch_policy_candidates": [
            label for label, _ in dispatch_policy_candidates
        ],
        "valuable_l4_count": combined_status.get("valuable_l4_count", 0),
        "replacement_ready_count": combined_status.get("replacement_ready_count", 0),
        "target_kernel_mismatch_count": combined_status.get("target_kernel_mismatch_count", 0),
        "accelerated_results_consumed_by_qe_count": combined_status.get(
            "accelerated_results_consumed_by_qe_count", 0
        ),
        "qe_kernel_work_replaced_on_critical_path_count": combined_status.get(
            "qe_kernel_work_replaced_on_critical_path_count", 0
        ),
        "actual_compute_full_qe_evidence_required": combined_status.get(
            "actual_compute_full_qe_evidence_required"
        ),
        "non_smoke_actual_compute_attempt_count": combined_status.get(
            "non_smoke_actual_compute_attempt_count", 0
        ),
        "actual_compute_attempted_kernels": combined_status.get(
            "actual_compute_attempted_kernels", []
        ),
        "actual_compute_attempted_kernel_count": combined_status.get(
            "actual_compute_attempted_kernel_count", 0
        ),
        "actual_compute_attempted_kernel_counts": combined_status.get(
            "actual_compute_attempted_kernel_counts", {}
        ),
        "non_hpsi_actual_compute_attempt_count": combined_status.get(
            "non_hpsi_actual_compute_attempt_count", 0
        ),
        "non_hpsi_non_spsi_actual_compute_attempt_count": combined_status.get(
            "non_hpsi_non_spsi_actual_compute_attempt_count", 0
        ),
        "non_hpsi_non_spsi_actual_compute_blocked_count": combined_status.get(
            "non_hpsi_non_spsi_actual_compute_blocked_count", 0
        ),
        "actual_compute_full_qe_evidence_passed_count": combined_status.get(
            "actual_compute_full_qe_evidence_passed_count", 0
        ),
        "actual_compute_full_qe_evidence_blocked_count": combined_status.get(
            "actual_compute_full_qe_evidence_blocked_count", 0
        ),
        "hpsi_only_completion_allowed": False,
        "projection_only_value_allowed": False,
        "deliverable_complete": False,
        "blockers": [],
        "claim_boundary": (
            "campaign broadens real callgraph L4 attempts; combined report is "
            "authoritative for value and remains first-pass partial/blocked"
        ),
    }
    _write_json(out_dir / "status.json", status)
    return status


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=REPO_ROOT / "runs" / "dse" / "_tools" / "q-e-src",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help=(
            "Reuse existing QE callgraph/offload artifacts from a previous run "
            "instead of rebuilding the source inventory before planning."
        ),
    )
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--include-hpsi", action="store_true")
    parser.add_argument(
        "--no-diversify-kernels",
        action="store_true",
        help=(
            "Keep strict priority order even if a bounded campaign would "
            "select repeated kernels. Default diversifies selected kernels."
        ),
    )
    parser.add_argument(
        "--no-formal-workload-variants",
        action="store_true",
        help=(
            "Disable formal workload-variant binding during campaign planning. "
            "Default lets DSE pick explicit variants such as NC+CG s_psi when "
            "they improve real replacement-readiness coverage."
        ),
    )
    parser.add_argument(
        "--allow-hpsi-only-campaign",
        action="store_true",
        help="Allow planning a campaign with no non-h_psi attempt. Default blocks h_psi-only campaign plans.",
    )
    parser.add_argument("--opportunity-id", action="append", default=[])
    parser.add_argument(
        "--bundle-id",
        action="append",
        default=[],
        help=(
            "Select a DSE bundle from offload_bundle_search_space.json and "
            "expand its opportunities into real L4 attempts. This chooses a "
            "larger offload granularity; per-opportunity actual-compute rows "
            "still control value."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--smoke-runner",
        type=Path,
        default=Path(__file__).resolve().with_name("run_qe_callgraph_offload_l4_smoke.py"),
    )
    parser.add_argument(
        "--baseline-policy",
        choices=["real_if_ready", "preflight_only"],
        default="real_if_ready",
    )
    parser.add_argument("--qe-bin-dir", type=Path, default=None)
    parser.add_argument("--qe-pseudo-dir", type=Path, default=None)
    parser.add_argument("--qe-baseline-timeout", type=int, default=120)
    parser.add_argument("--trace-instrumented-qe", action="store_true")
    parser.add_argument("--run-gem5-transport", action="store_true")
    parser.add_argument("--run-patched-qe-bridge", action="store_true")
    parser.add_argument(
        "--batched-patched-qe-bridge",
        action="store_true",
        help=(
            "Forward batched bridge mode to each selected L4 attempt so "
            "multiple QE bridge invocations can share one gem5 launch."
        ),
    )
    parser.add_argument(
        "--prelaunch-patched-qe-bridge",
        action="store_true",
        help=(
            "Forward prelaunched persistent bridge mode to each selected L4 "
            "attempt while keeping the full patched-QE wall-clock value gate."
        ),
    )
    parser.add_argument(
        "--search-bridge-dispatch-policies",
        action="store_true",
        help=(
            "When patched QE bridge attempts are enabled, run each selected "
            "offload target under both single-launch and trace-batched bridge "
            "dispatch policies. This lets DSE search dispatch policy as part "
            "of the offload/value attempt; smoke remains dataflow-only and "
            "actual_compute rows still need real correctness, replacement, "
            "and positive speed before any value claim."
        ),
    )
    parser.add_argument(
        "--max-batched-bridge-trace-count",
        type=int,
        default=1024,
        help=(
            "Forwarded cap for shell-script batched bridge trace counts. "
            "Hot paths above this count are blocked instead of launching an "
            "impractical gem5 batch; use a persistent/in-process dispatcher "
            "for those value attempts."
        ),
    )
    parser.add_argument(
        "--evidence-mode",
        choices=["dataflow_smoke", "actual_compute"],
        default="dataflow_smoke",
        help=(
            "Forward the per-attempt evidence contract. Use actual_compute "
            "for non-smoke full-QE value attempts; smoke remains dataflow only."
        ),
    )
    parser.add_argument("--gem5-transport-max-ticks", type=int, default=3_000_000_000)
    parser.add_argument(
        "--gem5-binary",
        type=Path,
        default=REPO_ROOT / "gem5_integration" / "gem5" / "build" / "X86" / "gem5.opt",
    )
    parser.add_argument(
        "--gem5-config",
        type=Path,
        default=REPO_ROOT / "gem5_integration" / "configs" / "generic_accel_l4_test.py",
    )
    parser.add_argument(
        "--gem5-driver",
        type=Path,
        default=REPO_ROOT / "gem5_integration" / "test_programs" / "generic_accel" / "generic_accel_l4_driver",
    )
    parser.add_argument(
        "--simulator",
        type=Path,
        default=REPO_ROOT / "model" / "generic_sim_backend" / "build" / "generic_sim",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    status = run_campaign(args)
    print(json.dumps(status, sort_keys=True))
    return 0 if status.get("status") != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
