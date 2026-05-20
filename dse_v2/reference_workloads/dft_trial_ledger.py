#!/usr/bin/env python3
"""DFT-profile trial state ledger for full-SCF hardware DSE runs.

This module intentionally lives in ``reference_workloads``: it binds DFT/QE
candidate-search artifacts to the generic registry's Campaign/WorkloadRun/Trial
state machine without adding DFT fields to generic control-plane schemas.  The
ledger is orchestration evidence only.  It can prove ID propagation, transition
provenance, artifact refs, and fail-closed blocker accounting; it cannot upgrade
DFT numerical correctness, FPGA/ASIC PPA, trusted Pareto, or deliverable claims.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dse_v2.codesign.evidence_ledger import sha256_file, write_json
from dse_v2.registry.experiment_registry import ExperimentRegistry, TRIAL_TRANSITIONS

DFT_TRIAL_STATE_LEDGER_SCHEMA = "dse.dft.trial_state_ledger.v1"
DFT_TRIAL_STATE_LEDGER_VALIDATION_SCHEMA = "dse.dft.trial_state_ledger_validation.v1"
DFT_TRIAL_TRANSITION_REPORT_SCHEMA = "dse.dft.trial_transition_report.v1"
DFT_TRIAL_ARTIFACT_REFS_SCHEMA = "dse.dft.trial_artifact_refs.v1"

DFT_TRIAL_LEDGER_ARTIFACT_NAMES = (
    "dft_trial_state_ledger.json",
    "dft_trial_transition_report.json",
    "dft_trial_artifact_refs.json",
    "dft_trial_state_ledger_validation.json",
    "dft_trial_ledger.sqlite",
)

_REQUIRED_SOURCE_REFS = ("hierarchical_funnel_search_report",)
_CLAIM_BOUNDARY = (
    "dft_trial_state_ledger.json is a DFT-profile orchestration and audit "
    "artifact. It ties search candidates, DFT evidence rows, Step5 report "
    "citations, and goal-audit checklist items to a Campaign/WorkloadRun/Trial "
    "lifecycle, but it does not replace generic campaign ledgers, Step4 "
    "adjudication, claim_validation.json, final_report.json, or independent "
    "numerical/FPGA/ASIC hard gates. Trial state transitions are provenance, "
    "not proof."
)


def _load_json(path: Path | None) -> Dict[str, Any]:
    if path is None or not Path(path).exists():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _display_path(path: Path, *, base_dir: Path | None = None) -> str:
    resolved = Path(path)
    if base_dir is not None:
        try:
            return str(resolved.resolve().relative_to(base_dir.resolve()))
        except ValueError:
            pass
    try:
        return str(resolved.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def _resolve_ref_path(path_text: object, *, base_dir: Path) -> Path:
    raw = Path(str(path_text))
    if raw.is_absolute():
        return raw
    candidates = [base_dir / raw, Path.cwd() / raw, raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _artifact_ref(
    path: Path | None,
    *,
    artifact_id: str,
    canonical_name: str,
    schema_id: str,
    required: bool,
    base_dir: Path,
    producer_step: str,
    hash_required: bool = True,
) -> Dict[str, Any]:
    if path is None:
        return {
            "artifact_id": artifact_id,
            "canonical_name": canonical_name,
            "path": None,
            "exists": False,
            "required": required,
            "status": "missing_required" if required else "not_attached",
            "schema_id": schema_id,
            "schema_version": "v1",
            "hash_algorithm": "sha256",
            "sha256": None,
            "producer_step": producer_step,
        }
    candidate = Path(path)
    exists = candidate.exists() and candidate.is_file()
    digest = sha256_file(candidate) if exists and hash_required else None
    return {
        "artifact_id": artifact_id,
        "canonical_name": canonical_name,
        "path": _display_path(candidate, base_dir=base_dir if candidate.exists() else None),
        "exists": exists,
        "required": required,
        "status": (
            "present_hash_valid"
            if exists and hash_required
            else "present_mutable_self_reference"
            if exists
            else "missing_required"
            if required
            else "not_attached"
        ),
        "schema_id": schema_id,
        "schema_version": "v1",
        "hash_algorithm": "sha256",
        "sha256": digest,
        "producer_step": producer_step,
    }


def _iter_candidate_records(report: Mapping[str, Any]) -> list[Dict[str, Any]]:
    records = report.get("all_records")
    if not isinstance(records, list) or not records:
        records = list(report.get("formal_pareto_records", []) or []) + list(
            report.get("exploratory_records", []) or []
        )
    result: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in records or []:
        if not isinstance(item, Mapping):
            continue
        candidate_id = str(item.get("candidate_id", ""))
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        result.append(dict(item))
    return result


def _evidence_rows_by_candidate(ledger: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = ledger.get("rows", [])
    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if isinstance(row, Mapping) and row.get("candidate_id"):
            result[str(row["candidate_id"])] = dict(row)
    return result


def _binding_rows_by_search_candidate(binding_map: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = binding_map.get("binding_rows", [])
    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if isinstance(row, Mapping) and row.get("search_candidate_id"):
            result[str(row["search_candidate_id"])] = dict(row)
    return result


def _row_claim_completion(row: Mapping[str, Any] | None) -> bool:
    if not row:
        return False
    claim = row.get("claim_eligibility", {})
    if isinstance(claim, Mapping):
        return bool(claim.get("deliverable_complete", False))
    return False


def _evidence_blockers(
    *,
    candidate: Mapping[str, Any],
    evidence_row: Mapping[str, Any] | None,
    ledger: Mapping[str, Any],
    eda: Mapping[str, Any],
    final_report_present: bool,
    goal_audit_present: bool,
) -> list[str]:
    blockers: list[str] = []
    if evidence_row is None:
        blockers.append("no_matching_per_candidate_evidence_row_for_search_candidate")
    elif not _row_claim_completion(evidence_row):
        blockers.append("per_candidate_evidence_row_not_deliverable_complete")
    release_gate = ledger.get("release_claim_gate", {})
    if isinstance(release_gate, Mapping) and release_gate.get("deliverable_complete") is not True:
        blockers.append("release_claim_gate.deliverable_complete=false")
    if eda and eda.get("hardware_completion_eligible") is not True:
        blockers.append("eda_all_candidate_evidence.hardware_completion_eligible=false")
    if not final_report_present:
        blockers.append("step5_final_report_not_attached")
    if not goal_audit_present:
        blockers.append("goal_audit_not_attached")
    if candidate.get("simulation_eligible") is not True:
        blockers.extend(str(item) for item in candidate.get("simulation_blockers", []) or [])
    return sorted(set(blockers))


def _candidate_policy_metadata(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = candidate.get("policy_metadata", {})
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _candidate_release_policy(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    """Return authoritative DFT release/exploratory policy metadata."""

    metadata = _candidate_policy_metadata(candidate)
    for policy in (
        candidate.get("release_policy"),
        metadata.get("release_policy"),
        (metadata.get("template_policy", {}) if isinstance(metadata.get("template_policy"), Mapping) else {}).get("release_policy"),
    ):
        if isinstance(policy, Mapping):
            lane = str(policy.get("lane") or "exploratory").strip().lower()
            formal_allowed = bool(policy.get("formal_pareto_allowed", lane == "release"))
            return {
                "lane": "release" if lane == "release" and formal_allowed else "exploratory",
                "formal_pareto_allowed": lane == "release" and formal_allowed,
                "exploratory_only": not (lane == "release" and formal_allowed),
                "authority": str(policy.get("authority") or "policy_metadata.release_policy"),
                "legacy_candidate_tier_authoritative": False,
            }
    if metadata.get("formal_pareto_eligible") is True or metadata.get("release_queue_eligible") is True:
        return {
            "lane": "release",
            "formal_pareto_allowed": True,
            "exploratory_only": False,
            "authority": "policy_metadata.formal_pareto_eligible",
            "legacy_candidate_tier_authoritative": False,
        }
    return {
        "lane": "exploratory",
        "formal_pareto_allowed": False,
        "exploratory_only": True,
        "authority": "default_fail_closed_release_policy",
        "legacy_candidate_tier_authoritative": False,
    }


def _next_actions(blockers: Sequence[str]) -> list[str]:
    actions: list[str] = []
    if "no_matching_per_candidate_evidence_row_for_search_candidate" in blockers:
        actions.append("bind Step2 search candidate ids to per-candidate DFT release evidence rows")
    if "per_candidate_evidence_row_not_deliverable_complete" in blockers:
        actions.append("produce missing per-candidate SystemC/gem5/EDA/formal/numerical/runtime evidence")
    if "eda_all_candidate_evidence.hardware_completion_eligible=false" in blockers:
        actions.append("run real per-kernel/per-candidate Vivado FPGA and DC ASIC closure gates")
    if "step5_final_report_not_attached" in blockers:
        actions.append("regenerate Step5 final_report.json with this ledger indexed")
    if "goal_audit_not_attached" in blockers:
        actions.append("rerun DFT hardware goal audit after Step5 report regeneration")
    if not actions:
        actions.append("continue Step4/Step5 adjudication without claim upgrade")
    return actions


def _provenance(reason: str) -> Dict[str, object]:
    return {"actor": "dft_trial_ledger", "reason": reason}


def _transition_trial(
    registry: ExperimentRegistry,
    trial_id: int,
    target: str,
    *,
    history: list[Dict[str, Any]],
    reason: str,
    artifacts: Mapping[str, object] | None = None,
    blockers: Sequence[str] = (),
) -> None:
    before = registry.resume_trial(trial_id).trial
    if before is None:
        raise RuntimeError(f"trial not found while transitioning: {trial_id}")
    updated = registry.transition_trial(
        trial_id,
        target,
        provenance=_provenance(reason),
        artifacts=artifacts,
        resume={"blockers": list(blockers), "resume_allowed": bool(blockers)},
    )
    history.append({
        "from_state": before.status,
        "to_state": updated.status,
        "reason": reason,
        "blockers": list(blockers),
        "artifact_refs": list((artifacts or {}).keys()),
    })


def _register_ref_if_present(
    registry: ExperimentRegistry,
    *,
    campaign_row_id: int,
    workload_row_id: int,
    trial_row_id: int | None,
    ref: Mapping[str, Any],
    scope: str,
    producing_activity_id: int | None,
    metadata: Mapping[str, object],
) -> Dict[str, Any] | None:
    if ref.get("exists") is not True or not ref.get("path") or not ref.get("sha256"):
        return None
    artifact = registry.register_artifact_ref(
        campaign_id=campaign_row_id,
        workload_run_id=workload_row_id if scope in {"workload_run", "trial"} else None,
        trial_id=trial_row_id if scope == "trial" else None,
        scope=scope,
        path=str(ref["path"]),
        schema_id=str(ref.get("schema_id", "unknown")),
        schema_version=str(ref.get("schema_version", "v1")),
        content_hash=str(ref["sha256"]),
        content_hash_alg=str(ref.get("hash_algorithm", "sha256")),
        producing_activity_id=producing_activity_id,
        metadata=dict(metadata),
    )
    return {
        "artifact_ref_id": artifact.artifact_ref_id,
        "campaign_row_id": artifact.campaign_id,
        "workload_run_row_id": artifact.workload_run_id,
        "trial_row_id": artifact.trial_id,
        "path": artifact.path,
        "schema_id": artifact.schema_id,
        "sha256": artifact.content_hash,
        "metadata": artifact.metadata,
    }


def build_dft_trial_state_ledger(
    *,
    out_dir: Path,
    hierarchical_search_report_path: Path,
    per_candidate_evidence_ledger_path: Path | None = None,
    eda_all_candidate_evidence_path: Path | None = None,
    candidate_binding_map_path: Path | None = None,
    final_report_path: Path | None = None,
    goal_audit_path: Path | None = None,
    dft_hardware_evidence_matrix_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    campaign_id: str = "dft_scf_hardware_dse_campaign_v1",
    workload_run_id: str | None = None,
) -> Dict[str, Any]:
    """Build an in-memory DFT trial ledger payload and backing registry.

    The returned payload is structurally pass/fail audited, but it keeps
    ``deliverable_complete=false`` unless every independent evidence source is
    already claim-eligible.  Current DFT/QE runs are therefore expected to be
    structurally ``passed`` while trial rows remain ``blocked``.
    """

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    search_report = _load_json(hierarchical_search_report_path)
    evidence_ledger = _load_json(per_candidate_evidence_ledger_path)
    eda = _load_json(eda_all_candidate_evidence_path)
    candidate_binding_map = _load_json(candidate_binding_map_path)
    final_report = _load_json(final_report_path)
    goal_audit = _load_json(goal_audit_path)
    candidate_records = _iter_candidate_records(search_report)
    evidence_rows = _evidence_rows_by_candidate(evidence_ledger)
    binding_rows = _binding_rows_by_search_candidate(candidate_binding_map)
    binding_map_validated = bool(
        candidate_binding_map
        and candidate_binding_map.get("schema_version") == "dse.dft.candidate_binding_map.v1"
        and candidate_binding_map.get("completion_eligible") is not True
        and candidate_binding_map.get("deliverable_complete") is not True
        and int(candidate_binding_map.get("unmatched_candidate_count", 0) or 0) == 0
    )
    workload_suite_id = str(
        workload_run_id
        or search_report.get("workload_suite_id")
        or search_report.get("workload_run_id")
        or "dft_scf_workload_suite"
    )

    source_refs = {
        "hierarchical_funnel_search_report": _artifact_ref(
            hierarchical_search_report_path,
            artifact_id="source.step2.hierarchical_funnel_search_report",
            canonical_name="hierarchical_funnel_search_report.json",
            schema_id="dse.dft.step2.hierarchical_funnel_search_report.v1",
            required=True,
            base_dir=out_dir,
            producer_step="step2",
        ),
        "per_candidate_evidence_ledger": _artifact_ref(
            per_candidate_evidence_ledger_path,
            artifact_id="source.dft.per_candidate_evidence_ledger",
            canonical_name="per_candidate_evidence_ledger.json",
            schema_id="dse.codesign.per_candidate_evidence_ledger.v1",
            required=False,
            base_dir=out_dir,
            producer_step="dft_evidence_ledger",
        ),
        "candidate_binding_map": _artifact_ref(
            candidate_binding_map_path,
            artifact_id="source.dft.candidate_binding_map",
            canonical_name="dft_candidate_binding_map.json",
            schema_id="dse.dft.candidate_binding_map.v1",
            required=False,
            base_dir=out_dir,
            producer_step="dft_candidate_binding",
        ),
        "eda_all_candidate_evidence": _artifact_ref(
            eda_all_candidate_evidence_path,
            artifact_id="source.dft.eda_all_candidate_evidence",
            canonical_name="eda_all_candidate_evidence.json",
            schema_id="dse.dft.eda_all_candidate_evidence.v1",
            required=False,
            base_dir=out_dir,
            producer_step="dft_evidence_ledger",
        ),
        "dft_hardware_evidence_matrix": _artifact_ref(
            dft_hardware_evidence_matrix_path,
            artifact_id="source.dft.hardware_evidence_matrix",
            canonical_name="dft_hardware_evidence_matrix.json",
            schema_id="dse.dft.hardware_evidence_matrix.v1",
            required=False,
            base_dir=out_dir,
            producer_step="dft_kernel_evidence",
        ),
        "ic_eda_tool_availability": _artifact_ref(
            ic_eda_tool_availability_path,
            artifact_id="source.dft.ic_eda_tool_availability",
            canonical_name="ic_eda_tool_availability.json",
            schema_id="dse.dft.ic_eda_tool_availability.v1",
            required=False,
            base_dir=out_dir,
            producer_step="dft_tool_probe",
        ),
        "final_report": _artifact_ref(
            final_report_path,
            artifact_id="source.step5.final_report",
            canonical_name="final_report.json",
            schema_id="dse.final_report.v1",
            required=False,
            base_dir=out_dir,
            producer_step="step5",
            hash_required=False,
        ),
        "goal_audit": _artifact_ref(
            goal_audit_path,
            artifact_id="source.goal.dft_scf_hardware_goal_completion_audit",
            canonical_name="dft_scf_hardware_goal_completion_audit.json",
            schema_id="dse.dft_scf_hardware.goal_completion_audit.v1",
            required=False,
            base_dir=out_dir,
            producer_step="goal_audit",
            hash_required=False,
        ),
    }

    registry_path = out_dir / "dft_trial_ledger.sqlite"
    if registry_path.exists():
        registry_path.unlink()
    registry = ExperimentRegistry(registry_path)
    campaign = registry.create_campaign(
        campaign_id,
        metadata={
            "profile": "dft_qe_full_scf_hardware_dse",
            "workload_suite_id": workload_suite_id,
            "claim_boundary": _CLAIM_BOUNDARY,
        },
    )
    campaign = registry.transition_campaign(campaign.campaign_id, "running", provenance=_provenance("start DFT trial-ledger campaign"))
    workload = registry.create_workload_run(
        campaign.campaign_id,
        {
            "workload_suite_id": workload_suite_id,
            "hierarchical_funnel_search_report": source_refs["hierarchical_funnel_search_report"].get("path"),
        },
        provenance=_provenance("create workload run for DFT trial ledger"),
    )
    for status, reason in [
        ("ingesting", "load DFT search/evidence artifacts"),
        ("lowered", "normalize DFT search candidates into trial rows"),
        ("validated", "validate required source artifact refs"),
        ("ready_for_step2", "handoff to DFT Step2 trial generation"),
    ]:
        workload = registry.transition_workload_run(workload.workload_run_id, status, provenance=_provenance(reason))

    build_activity = registry.create_activity(
        campaign.campaign_id,
        "dft_trial_state_ledger_build",
        workload_run_id=workload.workload_run_id,
        status="succeeded",
        command={"module": "dse_v2.reference_workloads.dft_trial_ledger"},
        inputs={key: ref for key, ref in source_refs.items()},
        outputs={"dft_trial_state_ledger": "dft_trial_state_ledger.json"},
        provenance=_provenance("build DFT trial state ledger"),
    )

    campaign_artifact_refs: list[Dict[str, Any]] = []
    for key, ref in source_refs.items():
        registered = _register_ref_if_present(
            registry,
            campaign_row_id=campaign.campaign_id,
            workload_row_id=workload.workload_run_id,
            trial_row_id=None,
            ref=ref,
            scope="campaign",
            producing_activity_id=build_activity.activity_id,
            metadata={"artifact_role": key, "logical_campaign_id": campaign_id},
        )
        if registered:
            campaign_artifact_refs.append(registered)

    release_gate = evidence_ledger.get("release_claim_gate", {})
    release_deliverable_complete = bool(
        release_gate.get("deliverable_complete", evidence_ledger.get("deliverable_complete", False))
    ) if isinstance(release_gate, Mapping) else False
    final_report_present = bool(source_refs["final_report"].get("exists"))
    goal_audit_present = bool(source_refs["goal_audit"].get("exists"))

    trial_rows: list[Dict[str, Any]] = []
    transition_rows: list[Dict[str, Any]] = []
    trial_artifact_refs: list[Dict[str, Any]] = []
    for index, candidate in enumerate(candidate_records):
        candidate_id = str(candidate["candidate_id"])
        params = dict(candidate.get("parameters", {}) or {})
        release_policy = _candidate_release_policy(candidate)
        release_lane = str(release_policy.get("lane", "exploratory"))
        policy_metadata = _candidate_policy_metadata(candidate)
        params.pop("candidate_tier", None)
        trial_logical_id = _stable_id("trial", candidate_id)
        design_point_id = _stable_id("design_point", candidate_id)
        generation_reasons = [str(candidate.get("generation_reason", "hierarchical_funnel_search"))]
        trial = registry.create_trial(
            workload.workload_run_id,
            {
                "candidate_id": candidate_id,
                "design_point_id": design_point_id,
                "template_family": params.get("template_family"),
                "policy_metadata": policy_metadata,
                "parameters": params,
            },
            "DFT_STEP2_TO_STEP5",
            generation_reasons=generation_reasons,
            provenance=_provenance(f"create DFT trial for search candidate {candidate_id}"),
            artifacts={"hierarchical_funnel_search_report": source_refs["hierarchical_funnel_search_report"].get("path")},
        )
        history: list[Dict[str, Any]] = []
        row_refs = {
            "search_refs": {"hierarchical_funnel_search_report": source_refs["hierarchical_funnel_search_report"]},
            "binding_refs": {"candidate_binding_map": source_refs["candidate_binding_map"]},
            "evidence_refs": {
                key: source_refs[key]
                for key in [
                    "per_candidate_evidence_ledger",
                    "eda_all_candidate_evidence",
                    "dft_hardware_evidence_matrix",
                    "ic_eda_tool_availability",
                ]
            },
            "step5_refs": {"final_report": source_refs["final_report"]},
            "goal_audit_refs": {"goal_audit": source_refs["goal_audit"]},
        }
        row_registry_refs: list[Dict[str, Any]] = []
        for group_name, refs in row_refs.items():
            for key, ref in refs.items():
                registered = _register_ref_if_present(
                    registry,
                    campaign_row_id=campaign.campaign_id,
                    workload_row_id=workload.workload_run_id,
                    trial_row_id=trial.trial_id,
                    ref=ref,
                    scope="trial",
                    producing_activity_id=build_activity.activity_id,
                    metadata={
                        "artifact_role": key,
                        "artifact_group": group_name,
                        "candidate_id": candidate_id,
                        "logical_trial_id": trial_logical_id,
                    },
                )
                if registered:
                    row_registry_refs.append(registered)
                    trial_artifact_refs.append(registered)

        binding_row = binding_rows.get(candidate_id, {})
        release_candidate_id = (
            str(binding_row["release_candidate_id"])
            if isinstance(binding_row, Mapping) and binding_row.get("release_candidate_id")
            else None
        )
        evidence_candidate_id = release_candidate_id or candidate_id
        evidence_row = evidence_rows.get(evidence_candidate_id)
        if evidence_row is None and not release_candidate_id:
            evidence_row = evidence_rows.get(candidate_id)
        blockers = _evidence_blockers(
            candidate=candidate,
            evidence_row=evidence_row,
            ledger=evidence_ledger,
            eda=eda,
            final_report_present=final_report_present,
            goal_audit_present=goal_audit_present,
        )
        _transition_trial(
            registry,
            trial.trial_id,
            "screened",
            history=history,
            reason="candidate entered DFT hierarchical screening",
            artifacts={"hierarchical_funnel_search_report": source_refs["hierarchical_funnel_search_report"].get("path")},
        )
        if release_policy.get("formal_pareto_allowed") is not True:
            _transition_trial(
                registry,
                trial.trial_id,
                "rejected",
                history=history,
                reason="exploratory candidate cannot enter formal Pareto/frontier",
                blockers=["exploratory_candidate_excluded_from_formal_pareto"],
            )
        elif candidate.get("simulation_eligible") is not True:
            _transition_trial(
                registry,
                trial.trial_id,
                "blocked",
                history=history,
                reason="release candidate is not Step3 evaluable",
                blockers=blockers or ["simulation_eligible=false"],
            )
        else:
            for target, reason in [
                ("promoted", "release-tier candidate promoted for evidence scheduling"),
                ("scheduled_for_sim", "Step3/EDA evidence scheduling recorded"),
                ("simulated", "Step3/EDA evidence artifact refs attached or blocker recorded"),
                ("adjudicated", "Step4/Step5/goal-audit refs considered for claim gate"),
            ]:
                _transition_trial(
                    registry,
                    trial.trial_id,
                    target,
                    history=history,
                    reason=reason,
                    artifacts={key: ref.get("path") for key, ref in source_refs.items() if ref.get("exists")},
                    blockers=blockers,
                )
            if blockers or not release_deliverable_complete:
                _transition_trial(
                    registry,
                    trial.trial_id,
                    "blocked",
                    history=history,
                    reason="hard evidence gates remain incomplete; withhold final promotion",
                    blockers=blockers or ["release_claim_gate.deliverable_complete=false"],
                )
            else:
                _transition_trial(
                    registry,
                    trial.trial_id,
                    "reported",
                    history=history,
                    reason="all attached hard evidence gates are claim eligible",
                )
                _transition_trial(
                    registry,
                    trial.trial_id,
                    "finalist",
                    history=history,
                    reason="candidate can enter trusted finalist review",
                )
                if index == 0:
                    _transition_trial(
                        registry,
                        trial.trial_id,
                        "selected",
                        history=history,
                        reason="first trusted finalist selected by deterministic replay order",
                    )

        final_trial = registry.resume_trial(trial.trial_id).trial
        if final_trial is None:
            raise RuntimeError(f"failed to resume trial {trial.trial_id}")
        completion_eligible = bool(
            release_policy.get("formal_pareto_allowed") is True
            and _row_claim_completion(evidence_row)
            and release_deliverable_complete
            and not blockers
        )
        deliverable_complete = bool(completion_eligible and final_trial.status == "selected")
        evidence_binding_status = (
            "matched_bound_release_candidate_row"
            if evidence_row is not None and release_candidate_id
            else "matched_search_candidate_row"
            if evidence_row is not None
            else "release_scope_artifact_only_no_candidate_id_match"
        )
        binding_release_policy = release_policy
        if isinstance(binding_row, Mapping) and isinstance(binding_row.get("release_policy"), Mapping):
            binding_release_policy = dict(binding_row["release_policy"])
        candidate_binding = {
            "status": (
                "binding_map_row_present"
                if binding_row
                else "binding_map_not_attached"
                if not candidate_binding_map
                else "missing_binding_map_row"
            ),
            "search_candidate_id": candidate_id,
            "release_candidate_id": release_candidate_id,
            "binding_status": binding_row.get("binding_status") if isinstance(binding_row, Mapping) else None,
            "binding_confidence": binding_row.get("confidence") if isinstance(binding_row, Mapping) else None,
            "template_family": binding_row.get("template_family") if isinstance(binding_row, Mapping) else params.get("template_family"),
            "release_policy": binding_release_policy,
            "release_lane": str(binding_release_policy.get("lane", release_lane)),
            "release_assignments": dict(binding_row.get("release_assignments", {}) or {}) if isinstance(binding_row, Mapping) else {},
            "evidence_row_present": evidence_row is not None,
            "reasons": list(binding_row.get("reasons", []) or []) if isinstance(binding_row, Mapping) else [],
            "binding_map_present": bool(candidate_binding_map),
            "binding_map_validated": binding_map_validated,
            "completion_eligible": False,
            "claim_boundary": (
                binding_row.get("claim_boundary")
                if isinstance(binding_row, Mapping) and binding_row.get("claim_boundary")
                else "Candidate binding is heuristic ID provenance only and cannot upgrade hardware, numerical, Pareto, or completion claims."
            ),
        }
        row = {
            "trial_id": trial_logical_id,
            "registry_trial_id": final_trial.trial_id,
            "campaign_id": campaign_id,
            "registry_campaign_id": campaign.campaign_id,
            "workload_run_id": workload_suite_id,
            "registry_workload_run_id": workload.workload_run_id,
            "design_point_id": design_point_id,
            "candidate_id": candidate_id,
            "release_policy": release_policy,
            "release_lane": release_lane,
            "template_family": params.get("template_family"),
            "policy_metadata": policy_metadata,
            "state": final_trial.status,
            "transition_history": history,
            "search_state": {
                "score": candidate.get("score"),
                "step2_screenable": candidate.get("step2_screenable"),
                "step3_evaluable": candidate.get("step3_evaluable"),
                "simulation_eligible": candidate.get("simulation_eligible"),
                "promotion_reasons": list(candidate.get("promotion_reasons", []) or []),
                "simulation_blockers": list(candidate.get("simulation_blockers", []) or []),
            },
            "evidence_binding": {
                "status": evidence_binding_status,
                "search_candidate_id": candidate_id,
                "release_candidate_id": release_candidate_id,
                "evidence_candidate_id": evidence_candidate_id if evidence_row is not None else None,
                "evidence_row_present": evidence_row is not None,
                "release_scope_artifact_present": bool(evidence_ledger),
                "binding_map_present": bool(candidate_binding_map),
                "binding_map_validated": binding_map_validated,
                "binding_source": "candidate_binding_map" if release_candidate_id else "same_id_fallback",
                "claim_eligible_from_evidence_row": _row_claim_completion(evidence_row),
            },
            "candidate_binding": candidate_binding,
            **row_refs,
            "registry_artifact_refs": row_registry_refs,
            "completion_eligible": completion_eligible,
            "deliverable_complete": deliverable_complete,
            "blocked_reasons": blockers if blockers else ([] if deliverable_complete else ["release_claim_gate.deliverable_complete=false"]),
            "next_actions": _next_actions(blockers),
            "claim_boundary": _CLAIM_BOUNDARY,
        }
        trial_rows.append(row)
        transition_rows.append({
            "trial_id": trial_logical_id,
            "candidate_id": candidate_id,
            "state": final_trial.status,
            "transition_history": history,
        })

    any_deliverable = any(row["deliverable_complete"] is True for row in trial_rows)
    blocked_rows = [row for row in trial_rows if row["state"] == "blocked"]
    rejected_rows = [row for row in trial_rows if row["state"] == "rejected"]
    selected_rows = [row for row in trial_rows if row["state"] == "selected"]
    campaign = registry.transition_campaign(
        campaign.campaign_id,
        "deliverable_complete" if any_deliverable else "partial_blocked_not_complete",
        provenance=_provenance("close DFT trial ledger campaign without claim upgrade"),
    )
    registry.close()

    payload: Dict[str, Any] = {
        "schema_version": DFT_TRIAL_STATE_LEDGER_SCHEMA,
        "status": "passed",
        "campaign_id": campaign_id,
        "registry_campaign_id": campaign.campaign_id,
        "campaign_status": campaign.status,
        "workload_run_id": workload_suite_id,
        "registry_workload_run_id": workload.workload_run_id,
        "workload_suite_id": workload_suite_id,
        "candidate_count": len(trial_rows),
        "release_trial_count": sum(1 for row in trial_rows if row.get("release_policy", {}).get("formal_pareto_allowed") is True),
        "exploratory_trial_count": sum(1 for row in trial_rows if row.get("release_policy", {}).get("formal_pareto_allowed") is not True),
        "blocked_trial_count": len(blocked_rows),
        "rejected_trial_count": len(rejected_rows),
        "selected_trial_count": len(selected_rows),
        "completion_eligible": any(row["completion_eligible"] for row in trial_rows),
        "deliverable_complete": any_deliverable,
        "candidate_binding_map_present": bool(candidate_binding_map),
        "candidate_binding_map_validated": binding_map_validated,
        "candidate_binding_map_bound_candidate_count": candidate_binding_map.get("bound_candidate_count") if candidate_binding_map else None,
        "candidate_binding_map_unmatched_candidate_count": candidate_binding_map.get("unmatched_candidate_count") if candidate_binding_map else None,
        "source_artifacts": source_refs,
        "registry": {
            "path": "dft_trial_ledger.sqlite",
            "campaign_row_id": campaign.campaign_id,
            "workload_run_row_id": workload.workload_run_id,
            "artifact_ref_count": len(campaign_artifact_refs) + len(trial_artifact_refs),
        },
        "campaign_artifact_refs": campaign_artifact_refs,
        "trial_rows": trial_rows,
        "blocked_reasons": sorted({reason for row in trial_rows for reason in row.get("blocked_reasons", [])}),
        "next_actions": sorted({action for row in trial_rows for action in row.get("next_actions", [])}),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return payload


def _iter_ref_objects(value: object) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if "canonical_name" in value and "path" in value and "exists" in value:
            yield value
        for nested in value.values():
            yield from _iter_ref_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_ref_objects(nested)


def _validate_ref(ref: Mapping[str, Any], *, base_dir: Path, errors: list[Dict[str, Any]], context: str) -> None:
    required = bool(ref.get("required", False))
    exists = bool(ref.get("exists", False))
    path_text = ref.get("path")
    if required and not exists:
        errors.append({"field": context, "message": "required artifact ref is missing", "artifact": ref.get("canonical_name")})
        return
    if not exists:
        return
    if not path_text:
        errors.append({"field": context, "message": "present artifact ref has no path", "artifact": ref.get("canonical_name")})
        return
    resolved = _resolve_ref_path(path_text, base_dir=base_dir)
    if not resolved.exists() or not resolved.is_file():
        errors.append({"field": context, "message": "artifact ref path does not exist", "path": str(path_text)})
        return
    expected_hash = ref.get("sha256")
    if expected_hash and sha256_file(resolved) != expected_hash:
        errors.append({"field": context, "message": "artifact ref hash mismatch", "path": str(path_text)})


def validate_dft_trial_state_ledger(
    ledger: Mapping[str, Any] | Path,
    *,
    base_dir: Path | None = None,
) -> Dict[str, Any]:
    """Validate DFT trial-ledger structure, hashes, transitions, and claim gates."""

    if isinstance(ledger, Path):
        ledger_path = ledger
        payload = _load_json(ledger_path)
        root = base_dir or ledger_path.parent
    else:
        payload = dict(ledger)
        root = base_dir or Path(".")

    errors: list[Dict[str, Any]] = []
    warnings: list[Dict[str, Any]] = []
    if payload.get("schema_version") != DFT_TRIAL_STATE_LEDGER_SCHEMA:
        errors.append({"field": "schema_version", "message": "unexpected DFT trial ledger schema"})
    source_artifacts = payload.get("source_artifacts", {})
    if not isinstance(source_artifacts, Mapping):
        errors.append({"field": "source_artifacts", "message": "source_artifacts must be an object"})
        source_artifacts = {}
    for key in _REQUIRED_SOURCE_REFS:
        ref = source_artifacts.get(key)
        if not isinstance(ref, Mapping):
            errors.append({"field": f"source_artifacts.{key}", "message": "required source artifact ref missing"})
        else:
            _validate_ref(ref, base_dir=root, errors=errors, context=f"source_artifacts.{key}")

    rows = payload.get("trial_rows", [])
    if not isinstance(rows, list) or not rows:
        errors.append({"field": "trial_rows", "message": "non-empty trial_rows are required"})
        rows = []
    seen: set[str] = set()
    selected_rows = 0
    for index, row_obj in enumerate(rows):
        if not isinstance(row_obj, Mapping):
            errors.append({"field": f"trial_rows[{index}]", "message": "trial row must be an object"})
            continue
        row = row_obj
        for field in ["trial_id", "campaign_id", "workload_run_id", "candidate_id", "state", "transition_history"]:
            if not row.get(field):
                errors.append({"field": f"trial_rows[{index}].{field}", "message": "required field missing"})
        trial_id = str(row.get("trial_id", ""))
        if trial_id in seen:
            errors.append({"field": f"trial_rows[{index}].trial_id", "message": "duplicate trial_id", "trial_id": trial_id})
        seen.add(trial_id)
        state = str(row.get("state", ""))
        if state == "selected":
            selected_rows += 1
        history = row.get("transition_history", [])
        if not isinstance(history, list):
            errors.append({"field": f"trial_rows[{index}].transition_history", "message": "transition_history must be a list"})
            history = []
        current = "generated"
        for hist_index, item in enumerate(history):
            if not isinstance(item, Mapping):
                errors.append({"field": f"trial_rows[{index}].transition_history[{hist_index}]", "message": "transition entry must be an object"})
                continue
            from_state = str(item.get("from_state", ""))
            to_state = str(item.get("to_state", ""))
            if from_state != current:
                errors.append({
                    "field": f"trial_rows[{index}].transition_history[{hist_index}].from_state",
                    "message": "transition history is not contiguous",
                    "expected": current,
                    "actual": from_state,
                })
            if to_state not in TRIAL_TRANSITIONS.get(from_state, frozenset()):
                errors.append({
                    "field": f"trial_rows[{index}].transition_history[{hist_index}]",
                    "message": "invalid trial transition",
                    "transition": f"{from_state}->{to_state}",
                })
            current = to_state
        if history and current != state:
            errors.append({"field": f"trial_rows[{index}].state", "message": "final state does not match transition history", "expected": current, "actual": state})
        if row.get("deliverable_complete") is True and row.get("completion_eligible") is not True:
            errors.append({"field": f"trial_rows[{index}].deliverable_complete", "message": "deliverable_complete requires completion_eligible"})
        if row.get("release_policy", {}).get("formal_pareto_allowed") is not True and state in {"finalist", "selected"}:
            errors.append({"field": f"trial_rows[{index}].state", "message": "non-release-policy row cannot become trusted finalist/selected"})
        for group_name in ["search_refs", "binding_refs", "evidence_refs", "step5_refs", "goal_audit_refs"]:
            group = row.get(group_name, {})
            if not isinstance(group, Mapping):
                errors.append({"field": f"trial_rows[{index}].{group_name}", "message": "artifact ref group must be an object"})
                continue
            for key, ref in group.items():
                if isinstance(ref, Mapping):
                    _validate_ref(ref, base_dir=root, errors=errors, context=f"trial_rows[{index}].{group_name}.{key}")
        candidate_binding = row.get("candidate_binding", {})
        if isinstance(candidate_binding, Mapping):
            if candidate_binding.get("completion_eligible") is True:
                errors.append({"field": f"trial_rows[{index}].candidate_binding.completion_eligible", "message": "candidate binding cannot be completion eligible"})
            if candidate_binding.get("binding_map_present") and not candidate_binding.get("release_candidate_id"):
                errors.append({"field": f"trial_rows[{index}].candidate_binding.release_candidate_id", "message": "binding map row must provide release_candidate_id"})
        else:
            errors.append({"field": f"trial_rows[{index}].candidate_binding", "message": "candidate_binding must be an object"})
    if payload.get("deliverable_complete") is False and selected_rows:
        errors.append({"field": "trial_rows", "message": "selected trial rows cannot exist while ledger deliverable_complete=false"})
    if payload.get("deliverable_complete") is True and payload.get("completion_eligible") is not True:
        errors.append({"field": "deliverable_complete", "message": "ledger deliverable_complete requires completion_eligible"})
    if payload.get("blocked_trial_count", 0) and payload.get("deliverable_complete") is True:
        errors.append({"field": "blocked_trial_count", "message": "blocked trials prevent deliverable_complete"})
    registry_path = root / "dft_trial_ledger.sqlite"
    if not registry_path.exists():
        warnings.append({"field": "registry.path", "message": "registry sqlite artifact not found beside ledger"})

    return {
        "schema_version": DFT_TRIAL_STATE_LEDGER_VALIDATION_SCHEMA,
        "valid": not errors,
        "row_count": len(rows),
        "errors": errors,
        "warnings": warnings,
        "claim_boundary": (
            "Validation proves DFT trial-ledger structure, artifact-hash refs, "
            "and legal state transitions. It does not turn blocked/rejected rows "
            "into numerical correctness, PPA, trusted Pareto, or completion evidence."
        ),
    }


def write_dft_trial_state_ledger(
    out_dir: Path,
    *,
    hierarchical_search_report_path: Path,
    per_candidate_evidence_ledger_path: Path | None = None,
    eda_all_candidate_evidence_path: Path | None = None,
    candidate_binding_map_path: Path | None = None,
    final_report_path: Path | None = None,
    goal_audit_path: Path | None = None,
    dft_hardware_evidence_matrix_path: Path | None = None,
    ic_eda_tool_availability_path: Path | None = None,
    campaign_id: str = "dft_scf_hardware_dse_campaign_v1",
    workload_run_id: str | None = None,
) -> Dict[str, Any]:
    """Write DFT trial-ledger JSON, registry, transition report, and validation."""

    out_dir = Path(out_dir)
    payload = build_dft_trial_state_ledger(
        out_dir=out_dir,
        hierarchical_search_report_path=hierarchical_search_report_path,
        per_candidate_evidence_ledger_path=per_candidate_evidence_ledger_path,
        eda_all_candidate_evidence_path=eda_all_candidate_evidence_path,
        candidate_binding_map_path=candidate_binding_map_path,
        final_report_path=final_report_path,
        goal_audit_path=goal_audit_path,
        dft_hardware_evidence_matrix_path=dft_hardware_evidence_matrix_path,
        ic_eda_tool_availability_path=ic_eda_tool_availability_path,
        campaign_id=campaign_id,
        workload_run_id=workload_run_id,
    )
    ledger_path = out_dir / "dft_trial_state_ledger.json"
    write_json(ledger_path, payload)

    transition_report = {
        "schema_version": DFT_TRIAL_TRANSITION_REPORT_SCHEMA,
        "status": "passed",
        "campaign_id": payload["campaign_id"],
        "workload_run_id": payload["workload_run_id"],
        "trial_count": payload["candidate_count"],
        "transition_rows": [
            {
                "trial_id": row["trial_id"],
                "candidate_id": row["candidate_id"],
                "state": row["state"],
                "transition_history": row["transition_history"],
            }
            for row in payload["trial_rows"]
        ],
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_trial_transition_report.json", transition_report)
    artifact_refs = {
        "schema_version": DFT_TRIAL_ARTIFACT_REFS_SCHEMA,
        "status": "passed",
        "campaign_id": payload["campaign_id"],
        "workload_run_id": payload["workload_run_id"],
        "registry": payload["registry"],
        "source_artifacts": payload["source_artifacts"],
        "campaign_artifact_refs": payload["campaign_artifact_refs"],
        "trial_artifact_refs": [
            ref
            for row in payload["trial_rows"]
            for ref in row.get("registry_artifact_refs", [])
        ],
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_trial_artifact_refs.json", artifact_refs)
    validation = validate_dft_trial_state_ledger(ledger_path, base_dir=out_dir)
    write_json(out_dir / "dft_trial_state_ledger_validation.json", validation)
    status = {
        "schema_version": "dse.dft.trial_state_ledger_status.v1",
        "status": "passed" if validation["valid"] else "failed",
        "ledger": "dft_trial_state_ledger.json",
        "validation": "dft_trial_state_ledger_validation.json",
        "registry": "dft_trial_ledger.sqlite",
        "candidate_count": payload["candidate_count"],
        "blocked_trial_count": payload["blocked_trial_count"],
        "rejected_trial_count": payload["rejected_trial_count"],
        "deliverable_complete": payload["deliverable_complete"],
        "completion_eligible": payload["completion_eligible"],
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    write_json(out_dir / "dft_trial_ledger_status.json", status)
    return status


__all__ = [
    "DFT_TRIAL_ARTIFACT_REFS_SCHEMA",
    "DFT_TRIAL_LEDGER_ARTIFACT_NAMES",
    "DFT_TRIAL_STATE_LEDGER_SCHEMA",
    "DFT_TRIAL_STATE_LEDGER_VALIDATION_SCHEMA",
    "DFT_TRIAL_TRANSITION_REPORT_SCHEMA",
    "build_dft_trial_state_ledger",
    "validate_dft_trial_state_ledger",
    "write_dft_trial_state_ledger",
]
