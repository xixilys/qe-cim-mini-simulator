#!/usr/bin/env python3
"""Search-policy contracts for Step2 architecture/mapping exploration.

This module is intentionally domain-neutral.  It gives Step2 code a small,
testable interface for parameterized candidate generation without pretending
that a fixed candidate list is a real search system.  Policies must emit
candidate records with parameters, provenance, generation reasons, and explicit
promotion/blocker reasons so downstream Step3 admission can be audited.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
import math
from dataclasses import dataclass, field
from random import Random
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


STEP2_SCREENABLE = "step2_screenable"
STEP3_EVALUABLE = "step3_evaluable"
SIMULATION_ELIGIBLE = "simulation_eligible"
SIMULATION_BLOCKERS = "simulation_blockers"
NON_CANDIDATE_ALIAS_PARAMETER_KEYS = frozenset((
    "campaign_id",
    "workload_run_id",
    "workload_id",
    "trial_id",
    "run_id",
))
IDENTITY_ALIAS_PARAMETER_KEYS = frozenset((
    "architecture_id",
    "candidate_id",
    "candidate_record_hash",
    "cdse_candidate_id",
    "compile_schedule_id",
    "complete_dse_candidate_id",
    "design_point_id",
    "mapping_candidate_id",
    "mapping_id",
    "mapping_parameter_hash",
    "parameter_hash",
    "parameter_profile_id",
    "queue_entry_id",
    "release_subset_hash",
    "runtime_schedule_id",
    "search_policy_candidate_id",
    "search_policy_parameter_hash",
    "taxonomy_id",
    "top_k_entry_id",
    "trial_candidate_id",
))
RUNTIME_SCHEDULING_PROVENANCE_KEYS = (
    "runtime_schedule_id",
    "co_scheduling_policy_id",
    "queue_policy",
    "engine_assignment",
    "queue_depth",
    "overlap_window",
)


@dataclass(frozen=True)
class CapabilityDecision:
    """Deterministic legality result for one component/query pair."""

    supported: bool
    blockers: Tuple[str, ...] = ()
    reasons: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supported": self.supported,
            "blockers": list(self.blockers),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ComponentCapability:
    """Domain-neutral component capability model.

    `op_semantics` are generic operation classes (for example `fft`, `gemm`,
    `reduction`); DFT-specific intent must be translated by a profile before it
    reaches this contract.
    """

    component_id: str
    op_semantics: Tuple[str, ...]
    dtypes: Tuple[str, ...] = ("fp64",)
    schedules: Tuple[str, ...] = ("batch", "streaming")
    placements: Tuple[str, ...] = ("host",)
    precision_policies: Tuple[str, ...] = ("strict",)

    def supports(
        self,
        op_semantics: str,
        dtype: str,
        schedule: str,
        placement: str,
        precision_policy: str,
    ) -> CapabilityDecision:
        blockers: List[str] = []
        reasons: List[str] = []
        checks = [
            (op_semantics in self.op_semantics, f"unsupported_op:{op_semantics}", f"op_supported:{op_semantics}"),
            (dtype.lower() in {item.lower() for item in self.dtypes}, f"unsupported_dtype:{dtype}", f"dtype_supported:{dtype}"),
            (schedule in self.schedules, f"unsupported_schedule:{schedule}", f"schedule_supported:{schedule}"),
            (placement in self.placements, f"unsupported_placement:{placement}", f"placement_supported:{placement}"),
            (
                precision_policy in self.precision_policies,
                f"unsupported_precision_policy:{precision_policy}",
                f"precision_policy_supported:{precision_policy}",
            ),
        ]
        for ok, blocker, reason in checks:
            if ok:
                reasons.append(reason)
            else:
                blockers.append(blocker)
        return CapabilityDecision(not blockers, tuple(blockers), tuple(reasons))


@dataclass(frozen=True)
class SearchProblem:
    """Serializable Step2 search input."""

    problem_id: str
    workload_run_id: str
    objective: str
    parameters: Mapping[str, Sequence[Any]]
    constraints: Mapping[str, Any] = field(default_factory=dict)
    seed_candidates: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    def parameter_grid_size(self) -> int:
        """Return the exact Cartesian-grid size without materializing records."""

        size = 1
        for values in self.parameters.values():
            size *= len(tuple(values))
        return size

    def parameter_grid(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        keys = list(self.parameters.keys())
        records: List[Dict[str, Any]] = []

        def visit(index: int, current: Dict[str, Any]) -> None:
            if limit is not None and len(records) >= limit:
                return
            if index == len(keys):
                records.append(dict(current))
                return
            key = keys[index]
            for value in self.parameters[key]:
                current[key] = value
                visit(index + 1, current)
            current.pop(key, None)

        visit(0, {})
        return records

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "workload_run_id": self.workload_run_id,
            "objective": self.objective,
            "parameters": {key: list(values) for key, values in self.parameters.items()},
            "constraints": dict(self.constraints),
            "seed_candidate_count": len(self.seed_candidates),
            "seed_candidates": [dict(seed) for seed in self.seed_candidates],
            "parameter_grid_size": self.parameter_grid_size(),
        }


@dataclass
class SearchCandidateRecord:
    """Auditable output from a SearchPolicy."""

    candidate_id: str
    parameters: Dict[str, Any]
    provenance: Dict[str, Any]
    generation_reason: str
    parameter_hash: str = ""
    score: float = 0.0
    promotion_reasons: List[str] = field(default_factory=list)
    blocker_reasons: List[str] = field(default_factory=list)
    observed_metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def step2_screenable(self) -> bool:
        return bool(self.parameters) and not self.blocker_reasons

    @property
    def step3_evaluable(self) -> bool:
        return self.step2_screenable and "promoted_for_simulation" in self.promotion_reasons

    @property
    def simulation_eligible(self) -> bool:
        return self.step3_evaluable

    @property
    def simulation_blockers(self) -> List[str]:
        if self.simulation_eligible:
            return []
        return list(self.blocker_reasons or ["not_promoted_for_simulation"])

    def to_dict(self) -> Dict[str, Any]:
        parameter_hash = self.parameter_hash or _parameter_hash(self.parameters)
        provenance = dict(self.provenance)
        raw_identity = self.parameters.get("candidate_identity")
        if not isinstance(raw_identity, Mapping):
            raw_identity = provenance.get("candidate_identity")
        candidate_identity = (
            dict(raw_identity)
            if isinstance(raw_identity, Mapping)
            else {"search_parameters": dict(self.parameters)}
        )
        candidate_identity_policy = str(
            self.parameters.get("candidate_identity_policy")
            or provenance.get("candidate_identity_policy")
            or "stable_problem_policy_parameter_hash"
        )
        complete_dse_candidate_id = str(
            self.parameters.get("complete_dse_candidate_id")
            or self.parameters.get("cdse_candidate_id")
            or provenance.get("complete_dse_candidate_id")
            or ""
        )
        promoted_for_simulation = self.step3_evaluable
        payload = {
            "candidate_id": self.candidate_id,
            "search_policy_candidate_id": self.candidate_id,
            "complete_dse_candidate_id": complete_dse_candidate_id,
            "parameters": dict(self.parameters),
            "parameter_hash": parameter_hash,
            "provenance": provenance,
            "generation_reason": self.generation_reason,
            "score": float(self.score),
            "promotion_reasons": list(self.promotion_reasons),
            "blocker_reasons": list(self.blocker_reasons),
            "candidate_identity": candidate_identity,
            "candidate_identity_policy": candidate_identity_policy,
            STEP2_SCREENABLE: self.step2_screenable,
            STEP3_EVALUABLE: self.step3_evaluable,
            SIMULATION_ELIGIBLE: self.simulation_eligible,
            "promoted_for_simulation": promoted_for_simulation,
            SIMULATION_BLOCKERS: self.simulation_blockers,
            "queue_state": (
                "scheduled_for_simulation"
                if promoted_for_simulation
                else "blocked_before_step3"
            ),
            "observed_metrics": dict(self.observed_metrics),
            "claim_status": "step2_proposal_only",
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
            "claim_boundary": (
                "SearchPolicy candidate records are Step2 proposal/admission "
                "provenance only; downstream Step4/Step5 evidence gates own "
                "trusted final claims and deliverable completion."
            ),
        }
        runtime_provenance = _runtime_scheduling_provenance(
            parameters=self.parameters,
            provenance=provenance,
            candidate_identity=candidate_identity,
        )
        if runtime_provenance:
            payload["runtime_scheduling_provenance"] = runtime_provenance
        artifact_provenance = _candidate_artifact_provenance(
            parameters=self.parameters,
            provenance=provenance,
            candidate_id=self.candidate_id,
            parameter_hash=parameter_hash,
            candidate_identity=candidate_identity,
        )
        if artifact_provenance:
            payload["artifact_provenance"] = artifact_provenance
        return payload


@dataclass(frozen=True)
class SearchCheckpoint:
    policy_name: str
    problem_id: str
    proposed_count: int
    observed_count: int
    best_candidate_id: Optional[str]
    candidates: Tuple[SearchCandidateRecord, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "dse.step2.search_checkpoint.v1",
            "policy_name": self.policy_name,
            "problem_id": self.problem_id,
            "proposed_count": self.proposed_count,
            "observed_count": self.observed_count,
            "best_candidate_id": self.best_candidate_id,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class SearchPolicy(ABC):
    """Minimal plugin interface for Step2 search policies."""

    policy_name: str

    @abstractmethod
    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        """Return at most `budget` candidate records."""

    @abstractmethod
    def observe(self, candidate_id: str, metrics: Mapping[str, Any]) -> None:
        """Record feedback from Step3/Step4 or lower-fidelity screening."""

    @abstractmethod
    def checkpoint(self, problem: SearchProblem) -> SearchCheckpoint:
        """Return a replayable state snapshot."""


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _unique_domain_values(values: Iterable[Any]) -> List[Any]:
    ordered: List[Any] = []
    seen: Set[str] = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _payload_hash(payload: Mapping[str, Any]) -> str:
    data = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def _source_artifact_provenance(
    *,
    role: str,
    ref: str,
    payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    payload_dict = _as_mapping(payload)
    return {
        "role": role,
        "ref": ref,
        "payload_hash": _payload_hash(payload_dict),
        "schema_version": str(payload_dict.get("schema_version") or ""),
        "status": str(payload_dict.get("status") or ("present" if payload_dict else "absent")),
    }


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _recommendation_input_provenance(
    *,
    parameters: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> Dict[str, Any]:
    for source in (
        parameters.get("recommendation_input_provenance"),
        provenance.get("recommendation_input_provenance"),
    ):
        if isinstance(source, Mapping):
            return dict(source)
    return {}


def _runtime_from_candidate_identity(candidate_identity: Mapping[str, Any]) -> Dict[str, Any]:
    identity = _as_mapping(candidate_identity)
    identity_layers = _as_mapping(identity.get("identity_layers"))
    if not identity_layers and "runtime_scheduling_parameters" in identity:
        identity_layers = identity
    return _as_mapping(identity_layers.get("runtime_scheduling_parameters"))


def _runtime_scheduling_provenance(
    *,
    parameters: Mapping[str, Any],
    provenance: Mapping[str, Any],
    candidate_identity: Mapping[str, Any],
) -> Dict[str, Any]:
    recommendation = _recommendation_input_provenance(
        parameters=parameters,
        provenance=provenance,
    )
    runtime = _as_mapping(recommendation.get("runtime_scheduling_provenance"))
    if not runtime:
        runtime = _runtime_from_candidate_identity(candidate_identity)
    direct_runtime = {
        key: parameters.get(key)
        for key in RUNTIME_SCHEDULING_PROVENANCE_KEYS
        if _has_value(parameters.get(key))
    }
    runtime.update(direct_runtime)
    payload = {
        key: runtime.get(key)
        for key in RUNTIME_SCHEDULING_PROVENANCE_KEYS
        if _has_value(runtime.get(key))
    }
    if not payload:
        return {}
    payload.update({
        "source": (
            "recommendation_input_provenance.runtime_scheduling_provenance"
            if recommendation.get("runtime_scheduling_provenance")
            else "candidate_parameters_or_identity.runtime_scheduling_parameters"
        ),
        "runtime_schedule_affects_candidate_identity": bool(
            _runtime_from_candidate_identity(candidate_identity)
        ),
        "claim_status": "step2_proposal_only",
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
    })
    return payload


def _candidate_artifact_provenance(
    *,
    parameters: Mapping[str, Any],
    provenance: Mapping[str, Any],
    candidate_id: str,
    parameter_hash: str,
    candidate_identity: Mapping[str, Any],
) -> Dict[str, Any]:
    recommendation = _recommendation_input_provenance(
        parameters=parameters,
        provenance=provenance,
    )
    payload = _as_mapping(recommendation.get("artifact_provenance"))
    if not payload:
        for key in (
            "release_subset_hash",
            "candidate_record_hash",
            "candidate_identity_hash",
        ):
            if _has_value(parameters.get(key)):
                payload[key] = parameters.get(key)
    identity_hash = ""
    if isinstance(candidate_identity, Mapping):
        identity_hash = str(
            candidate_identity.get("identity_hash")
            or candidate_identity.get("candidate_identity_hash")
            or ""
        )
    payload.setdefault("candidate_id", candidate_id)
    payload.setdefault("search_policy_candidate_id", candidate_id)
    payload.setdefault("search_policy_parameter_hash", parameter_hash)
    payload.setdefault("parameter_hash", parameter_hash)
    if _has_value(parameters.get("candidate_record_hash")):
        payload.setdefault("candidate_record_hash", parameters.get("candidate_record_hash"))
    if identity_hash:
        payload.setdefault("candidate_identity_hash", identity_hash)
    has_external_artifact_binding = any(
        _has_value(payload.get(key))
        for key in (
            "release_subset_hash",
            "candidate_workflow_deployment_target_matrix_hash",
            "release_pruning_rationale_hash",
            "candidate_record_hash",
            "candidate_identity_hash",
        )
    )
    if not has_external_artifact_binding:
        return {}
    payload.update({
        "search_policy_provenance_only": True,
        "claim_status": "step2_proposal_only",
        "trusted_final_claim": False,
        "release_completion_eligible": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Candidate artifact provenance binds Step2 proposals to their "
            "source release/search artifacts only; it is not evidence closure."
        ),
    })
    return payload


def _parameter_domains_from_candidates(candidates: Iterable[Mapping[str, Any]]) -> Dict[str, List[Any]]:
    domains: Dict[str, List[Any]] = {}
    for candidate in candidates:
        parameters = candidate.get("parameters", candidate) if isinstance(candidate, Mapping) else {}
        if not isinstance(parameters, Mapping):
            continue
        for key, value in parameters.items():
            domains.setdefault(str(key), []).append(value)
    return {key: _unique_domain_values(values) for key, values in domains.items()}


def search_problem_from_dict(
    payload: Mapping[str, Any],
    *,
    fallback_candidates: Sequence[Mapping[str, Any]] = (),
) -> SearchProblem:
    """Rebuild a SearchProblem from persisted Step2 search metadata.

    Older checkpoints may not carry seed candidates.  In that case, the
    persisted candidate parameter records become replay seeds so feedback can
    still produce a deterministic next-iteration ordering without inventing a
    new search space.
    """

    fallback_seeds = [
        dict(candidate.get("parameters", candidate))
        for candidate in fallback_candidates
        if isinstance(candidate, Mapping)
    ]
    raw_seeds = payload.get("seed_candidates", fallback_seeds)
    seed_candidates = tuple(
        dict(seed)
        for seed in (raw_seeds or fallback_seeds)
        if isinstance(seed, Mapping)
    )
    raw_parameters = payload.get("parameters", {}) if isinstance(payload.get("parameters", {}), Mapping) else {}
    parameters = {
        str(key): list(values) if isinstance(values, (list, tuple)) else [values]
        for key, values in raw_parameters.items()
    }
    if not parameters:
        parameters = _parameter_domains_from_candidates(seed_candidates or fallback_seeds)
    return SearchProblem(
        problem_id=str(payload.get("problem_id") or "restored_search_problem"),
        workload_run_id=str(payload.get("workload_run_id") or payload.get("workload_id") or "unknown_workload_run"),
        objective=str(payload.get("objective") or "rank_step2_mapping_candidates"),
        parameters=parameters,
        constraints=_as_mapping(payload.get("constraints")),
        seed_candidates=seed_candidates,
    )


def candidate_observation_id_lookup(candidates: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    """Return stable aliases that can route Step4 feedback to policy records.

    Step4 artifacts often know a selected mapping id or a parameter hash rather
    than the internal SearchPolicy candidate id.  This lookup is intentionally
    generic: it indexes the canonical `candidate_id`, `parameter_hash`, and
    explicit identity-bearing `parameters.*` values without granting those
    aliases Step3 admission authority.  Generic tuning scalars such as
    `pe_count`, `release_lane`, or nested mapping placements are intentionally
    excluded so feedback cannot bind to a candidate through a non-identity
    value.
    """

    lookup: Dict[str, str] = {}
    ambiguous: Set[str] = set()

    def add_alias(value: Any, candidate_id: str) -> None:
        alias = str(value or "")
        if not alias or alias in ambiguous:
            return
        previous = lookup.get(alias)
        if previous is None:
            lookup[alias] = candidate_id
        elif previous != candidate_id:
            lookup.pop(alias, None)
            ambiguous.add(alias)

    def add_candidate_aliases(candidate: Mapping[str, Any], candidate_id: str) -> None:
        add_alias(candidate.get("candidate_id"), candidate_id)
        add_alias(candidate.get("search_policy_candidate_id"), candidate_id)
        add_alias(candidate.get("complete_dse_candidate_id"), candidate_id)
        add_alias(candidate.get("mapping_candidate_id"), candidate_id)
        add_alias(candidate.get("search_policy_parameter_hash"), candidate_id)
        add_alias(candidate.get("mapping_parameter_hash"), candidate_id)
        add_alias(candidate.get("parameter_hash"), candidate_id)
        add_alias(candidate.get("architecture_id"), candidate_id)
        add_alias(candidate.get("mapping_id"), candidate_id)
        add_alias(candidate.get("design_point_id"), candidate_id)
        add_alias(candidate.get("top_k_entry_id"), candidate_id)
        add_alias(candidate.get("queue_entry_id"), candidate_id)
        provenance = candidate.get("provenance", {})
        if isinstance(provenance, Mapping):
            add_alias(provenance.get("parameter_hash"), candidate_id)
            add_alias(provenance.get("search_policy_candidate_id"), candidate_id)
            add_alias(provenance.get("complete_dse_candidate_id"), candidate_id)
            add_alias(provenance.get("mapping_candidate_id"), candidate_id)
            add_alias(provenance.get("architecture_id"), candidate_id)
        candidate_refs = candidate.get("candidate_refs", {})
        if isinstance(candidate_refs, Mapping):
            add_alias(candidate_refs.get("search_policy_candidate_id"), candidate_id)
            add_alias(candidate_refs.get("complete_dse_candidate_id"), candidate_id)
            add_alias(candidate_refs.get("candidate_id"), candidate_id)
            add_alias(candidate_refs.get("mapping_candidate_id"), candidate_id)
            add_alias(candidate_refs.get("mapping_parameter_hash"), candidate_id)
            add_alias(candidate_refs.get("parameter_hash"), candidate_id)
            add_alias(candidate_refs.get("architecture_id"), candidate_id)

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        add_candidate_aliases(candidate, candidate_id)
        parameters = candidate.get("parameters", {})
        if isinstance(parameters, Mapping):
            for key, value in parameters.items():
                if isinstance(value, Mapping):
                    for nested_key, nested_value in value.items():
                        if (
                            nested_key in NON_CANDIDATE_ALIAS_PARAMETER_KEYS
                            or nested_key not in IDENTITY_ALIAS_PARAMETER_KEYS
                        ):
                            continue
                        if isinstance(nested_value, (str, int, float, bool)) and nested_value not in (None, ""):
                            add_alias(nested_value, candidate_id)
                    continue
                if key in NON_CANDIDATE_ALIAS_PARAMETER_KEYS or key not in IDENTITY_ALIAS_PARAMETER_KEYS:
                    continue
                if isinstance(value, (str, int, float, bool)) and value not in (None, ""):
                    add_alias(value, candidate_id)
    return lookup


def _candidate_aliases_from_feedback(update: Mapping[str, Any]) -> List[str]:
    candidate_refs = _as_mapping(update.get("candidate_refs"))
    aliases: List[str] = []

    def append_alias(value: Any) -> None:
        alias = str(value or "")
        if alias and alias not in aliases:
            aliases.append(alias)

    append_alias(update.get("search_policy_candidate_id"))
    append_alias(candidate_refs.get("search_policy_candidate_id"))
    append_alias(update.get("complete_dse_candidate_id"))
    append_alias(candidate_refs.get("complete_dse_candidate_id"))
    append_alias(update.get("search_policy_parameter_hash"))
    append_alias(candidate_refs.get("search_policy_parameter_hash"))
    append_alias(update.get("candidate_id"))
    append_alias(candidate_refs.get("candidate_id"))
    append_alias(update.get("mapping_candidate_id"))
    append_alias(candidate_refs.get("mapping_candidate_id"))
    append_alias(update.get("mapping_parameter_hash"))
    append_alias(candidate_refs.get("mapping_parameter_hash"))
    append_alias(update.get("parameter_hash"))
    append_alias(candidate_refs.get("parameter_hash"))
    append_alias(candidate_refs.get("architecture_id"))
    append_alias(candidate_refs.get("design_point_id"))
    append_alias(candidate_refs.get("mapping_id"))
    append_alias(candidate_refs.get("top_k_entry_id"))
    append_alias(candidate_refs.get("queue_entry_id"))
    return aliases


def step4_feedback_observations(
    feedback_update: Mapping[str, Any],
    calibration_record: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Normalize Step4 feedback/calibration artifacts into policy observations.

    The feedback contract stays domain-neutral: each observation resolves a
    candidate-like id plus a metrics map suitable for `SearchPolicy.observe()`.
    Callers may use `candidate_observation_id_lookup()` when Step4 reports a
    mapping id or parameter hash instead of the policy candidate id.
    """

    calibration = _as_mapping(calibration_record)
    calibration_confidence = calibration.get("confidence")
    calibration_errors = _as_mapping(calibration.get("error_metrics"))
    observations: List[Dict[str, Any]] = []
    for index, update in enumerate(feedback_update.get("updates", []) or []):
        if not isinstance(update, Mapping):
            continue
        candidate_refs = _as_mapping(update.get("candidate_refs"))
        metrics = _as_mapping(update.get("metrics"))
        if "trusted_sample" in update:
            metrics.setdefault("trusted_sample", bool(update.get("trusted_sample")))
            metrics.setdefault("promoted", bool(update.get("trusted_sample")))
        if "trusted_sample" in metrics:
            metrics.setdefault("promoted", bool(metrics.get("trusted_sample")))
        if "step4_verdict" not in metrics:
            if metrics.get("trusted_sample") or update.get("trusted_sample"):
                metrics["step4_verdict"] = "trusted_pass"
            elif update.get("status") in {"blocked", "failed", "rejected"}:
                metrics["step4_verdict"] = str(update.get("status"))
            else:
                metrics["step4_verdict"] = str(update.get("status") or "available")
        if isinstance(calibration_confidence, (int, float)):
            metrics.setdefault("calibration_confidence", float(calibration_confidence))
            metrics.setdefault("step4_quality_score", float(calibration_confidence) * 100.0)
        if calibration_errors:
            metrics.setdefault("calibration_error_metrics", dict(calibration_errors))
        candidate_aliases = _candidate_aliases_from_feedback(update)
        if not candidate_aliases:
            continue
        observations.append({
            "observation_id": f"step4-feedback::{feedback_update.get('trial_id', 'trial')}::{index}",
            "candidate_id": candidate_aliases[0],
            "candidate_aliases": candidate_aliases,
            "candidate_refs": candidate_refs,
            "metrics": metrics,
            "source_update_index": index,
            "source_artifacts": list(update.get("source_artifacts", []) or []),
        })
    return observations


def route_step4_feedback_observations(
    feedback_update: Mapping[str, Any],
    calibration_record: Optional[Mapping[str, Any]] = None,
    *,
    candidate_id_lookup: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Return auditable Step4-feedback routing rows before policy observation.

    Unknown aliases are preserved as blocked routing rows instead of being
    silently dropped from the durable Step2 replay artifact.  The rows are still
    proposal-only metadata: they may reorder Step2 proposals when resolved, but
    they do not admit Step3 work or upgrade final claims.
    """

    aliases = dict(candidate_id_lookup or {})
    require_alias_match = candidate_id_lookup is not None
    routes: List[Dict[str, Any]] = []
    for observation in step4_feedback_observations(feedback_update, calibration_record):
        candidate_aliases = [
            str(alias)
            for alias in observation.get("candidate_aliases", []) or []
            if str(alias)
        ]
        if not candidate_aliases:
            candidate_aliases = [str(observation.get("candidate_id") or "")]
        matched_alias = ""
        candidate_id = ""
        checked_aliases: List[str] = []
        for source_id in candidate_aliases:
            checked_aliases.append(source_id)
            if require_alias_match and source_id not in aliases:
                continue
            candidate_id = aliases.get(source_id, source_id)
            if candidate_id:
                matched_alias = source_id
                break
        routed = bool(candidate_id)
        metrics = _as_mapping(observation.get("metrics"))
        metrics.setdefault("step4_feedback_source_candidate_id", str(observation.get("candidate_id") or ""))
        if matched_alias:
            metrics.setdefault("step4_feedback_matched_candidate_alias", matched_alias)
        blockers = [] if routed else [
            "candidate_alias_not_found_in_search_checkpoint"
            if require_alias_match
            else "candidate_alias_missing"
        ]
        routes.append({
            "schema_version": "dse.step2.feedback_observation_route.v1",
            "observation_id": str(observation.get("observation_id") or ""),
            "source_update_index": observation.get("source_update_index"),
            "source_candidate_id": str(observation.get("candidate_id") or ""),
            "candidate_aliases": candidate_aliases,
            "checked_candidate_aliases": checked_aliases,
            "matched_candidate_alias": matched_alias,
            "matched_candidate_id": candidate_id,
            "routing_status": (
                "resolved_to_search_policy"
                if routed
                else "unresolved_candidate_alias"
            ),
            "routed_to_search_policy": routed,
            "routing_blockers": blockers,
            "candidate_refs": _as_mapping(observation.get("candidate_refs")),
            "metrics": metrics,
            "source_artifacts": list(observation.get("source_artifacts", []) or []),
            "claim_status": "step4_feedback_routing_only",
            "not_a_step3_queue_entry": True,
            "provenance_only": True,
            "execution_allowed": False,
            "trusted_final_claim": False,
            "release_completion_eligible": False,
            "deliverable_complete": False,
        })
    return routes


def _apply_feedback_routes(policy: SearchPolicy, routes: Sequence[Mapping[str, Any]]) -> int:
    observed = 0
    for route in routes:
        if route.get("routed_to_search_policy") is not True:
            continue
        candidate_id = str(route.get("matched_candidate_id") or "")
        if not candidate_id:
            continue
        metrics = _as_mapping(route.get("metrics"))
        policy.observe(candidate_id, metrics)
        observed += 1
    return observed


def observe_step4_feedback(
    policy: SearchPolicy,
    feedback_update: Mapping[str, Any],
    calibration_record: Optional[Mapping[str, Any]] = None,
    *,
    candidate_id_lookup: Optional[Mapping[str, str]] = None,
) -> int:
    """Apply Step4 observations to a live SearchPolicy instance.

    Returns the number of feedback rows routed to `policy.observe()`.  Unknown
    ids remain fail-closed inside policy implementations; the optional lookup is
    the canonical way to bridge mapping ids/parameter hashes to policy ids.
    """

    return _apply_feedback_routes(
        policy,
        route_step4_feedback_observations(
            feedback_update,
            calibration_record,
            candidate_id_lookup=candidate_id_lookup,
        ),
    )


def _candidate_record_from_dict(payload: Mapping[str, Any]) -> SearchCandidateRecord:
    parameters = _as_mapping(payload.get("parameters"))
    provenance = _as_mapping(payload.get("provenance"))
    return SearchCandidateRecord(
        candidate_id=str(payload.get("candidate_id") or _stable_candidate_id(
            SearchProblem("restored", "restored", "rank", {}),
            str(provenance.get("policy_name") or "restored_policy"),
            parameters,
        )),
        parameters=parameters,
        provenance=provenance,
        generation_reason=str(payload.get("generation_reason") or "restored_checkpoint_candidate"),
        parameter_hash=str(payload.get("parameter_hash") or _parameter_hash(parameters)),
        score=float(payload.get("score", 0.0) or 0.0),
        promotion_reasons=[str(reason) for reason in payload.get("promotion_reasons", []) or []],
        blocker_reasons=[str(reason) for reason in payload.get("blocker_reasons", []) or []],
        observed_metrics={},
    )


def _policy_for_name(policy_name: str) -> SearchPolicy:
    if policy_name == HierarchicalFunnelSearchPolicy.policy_name:
        return HierarchicalFunnelSearchPolicy(bottleneck_keys=("step2_candidate_rank_score",))
    if policy_name == SeededBeamSearchPolicy.policy_name:
        return SeededBeamSearchPolicy()
    if policy_name == BottleneckGuidedPolicy.policy_name:
        return BottleneckGuidedPolicy()
    if policy_name == RandomBaselinePolicy.policy_name:
        return RandomBaselinePolicy(seed=0)
    return HierarchicalFunnelSearchPolicy(bottleneck_keys=("step2_candidate_rank_score",))


def search_policy_from_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    policy_name: Optional[str] = None,
) -> SearchPolicy:
    """Restore a SearchPolicy's proposed records and feedback bias."""

    resolved_policy_name = str(policy_name or checkpoint.get("policy_name") or HierarchicalFunnelSearchPolicy.policy_name)
    policy = _policy_for_name(resolved_policy_name)
    if not isinstance(policy, _BasePolicy):
        return policy
    policy._proposed = {}
    policy._observed_count = 0
    for candidate in checkpoint.get("candidates", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        observed_metrics = _as_mapping(candidate.get("observed_metrics"))
        record = _candidate_record_from_dict(candidate)
        policy._remember_record(record)
        if observed_metrics:
            policy.observe(record.candidate_id, observed_metrics)
    policy._observed_count = int(checkpoint.get("observed_count", policy._observed_count) or 0)
    return policy


def build_search_iteration_plan(
    *,
    search_checkpoint: Mapping[str, Any],
    feedback_update: Mapping[str, Any],
    calibration_record: Optional[Mapping[str, Any]] = None,
    proposal_budget: Optional[int] = None,
    refs: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Build a replayable next-iteration search plan from persisted artifacts.

    This closes the durable loop: Step2 checkpoint + Step4 feedback become a
    refreshed proposal ordering, while Step3 admission remains external and
    fail-closed through `step3_simulation_queue.json`.
    """

    refs_payload = dict(refs or {})
    checkpoint_payload = (
        _as_mapping(search_checkpoint.get("search_policy_checkpoint"))
        if isinstance(search_checkpoint.get("search_policy_checkpoint"), Mapping)
        else _as_mapping(search_checkpoint)
    )
    checkpoint_candidates = [
        dict(candidate)
        for candidate in checkpoint_payload.get("candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    problem_payload = (
        _as_mapping(search_checkpoint.get("search_policy_problem"))
        or _as_mapping(search_checkpoint.get("problem"))
    )
    problem = search_problem_from_dict(
        problem_payload,
        fallback_candidates=checkpoint_candidates,
    )
    policy = search_policy_from_checkpoint(
        checkpoint_payload,
        policy_name=str(
            search_checkpoint.get("search_policy_name")
            or checkpoint_payload.get("policy_name")
            or HierarchicalFunnelSearchPolicy.policy_name
        ),
    )
    alias_source_candidates = list(checkpoint_candidates)
    alias_source_candidates.extend(
        dict(candidate)
        for candidate in search_checkpoint.get("search_policy_candidates", []) or []
        if isinstance(candidate, Mapping)
    )
    alias_lookup = candidate_observation_id_lookup(
        candidate.to_dict() if isinstance(candidate, SearchCandidateRecord) else candidate
        for candidate in alias_source_candidates
    )
    input_observed_count = int(checkpoint_payload.get("observed_count", 0) or 0)
    feedback_observation_routes = route_step4_feedback_observations(
        feedback_update,
        calibration_record,
        candidate_id_lookup=alias_lookup,
    )
    applied_feedback_count = _apply_feedback_routes(policy, feedback_observation_routes)
    unresolved_feedback_count = len([
        route
        for route in feedback_observation_routes
        if route.get("routed_to_search_policy") is not True
    ])
    next_budget = max(
        1,
        int(
            proposal_budget
            or search_checkpoint.get("search_policy_proposal_budget")
            or checkpoint_payload.get("proposal_budget")
            or checkpoint_payload.get("proposed_count")
            or len(checkpoint_candidates)
            or len(problem.seed_candidates)
            or 1
        ),
    )
    step3_queue_ref = (
        refs_payload.get("step3_simulation_queue")
        or refs_payload.get("step3_admission_queue")
        or "step2/step3_simulation_queue.json"
    )
    input_search_checkpoint_ref = refs_payload.get("search_checkpoint", "step2/search_checkpoint.json")
    feedback_update_ref = refs_payload.get("feedback_update", "feedback_update.json")
    calibration_record_ref = refs_payload.get("calibration_record", "calibration_record.json")
    campaign_id = str(
        search_checkpoint.get("campaign_id")
        or problem_payload.get("campaign_id")
        or feedback_update.get("campaign_id")
        or ""
    )
    workload_run_id = str(
        search_checkpoint.get("workload_run_id")
        or problem_payload.get("workload_run_id")
        or problem.workload_run_id
        or feedback_update.get("workload_run_id")
        or ""
    )
    trial_id = str(
        search_checkpoint.get("trial_id")
        or problem_payload.get("trial_id")
        or feedback_update.get("trial_id")
        or ""
    )
    next_records = policy.propose(problem, budget=next_budget)
    next_candidates: List[Dict[str, Any]] = []
    next_step3_admission_candidates: List[Dict[str, Any]] = []
    for rank, record in enumerate(next_records, start=1):
        payload = record.to_dict()
        parameters = _as_mapping(payload.get("parameters"))
        payload["search_policy_candidate_id"] = payload["candidate_id"]
        payload["search_policy_parameter_hash"] = payload["parameter_hash"]
        for key in (
            "architecture_id",
            "complete_dse_candidate_id",
            "taxonomy_id",
            "design_point_id",
            "mapping_id",
            "mapping_candidate_id",
            "mapping_parameter_hash",
            "compile_schedule_id",
            "runtime_schedule_id",
            "parameter_profile_id",
            "candidate_record_hash",
            "release_subset_hash",
            "top_k_entry_id",
            "queue_entry_id",
            "trial_id",
            "trial_candidate_id",
        ):
            if key in parameters and parameters.get(key) not in (None, ""):
                payload.setdefault(key, parameters.get(key))
        payload["search_policy_rank"] = rank
        payload.setdefault("promoted_for_simulation", bool(payload.get(STEP3_EVALUABLE, False)))
        payload.setdefault(
            "queue_state",
            "scheduled_for_simulation"
            if payload["promoted_for_simulation"]
            else "blocked_before_step3",
        )
        payload.setdefault("claim_status", "step2_proposal_only")
        payload["not_a_step3_queue_entry"] = True
        payload["provenance_only"] = True
        payload["execution_allowed"] = False
        payload["admission_required_before_execution"] = step3_queue_ref
        payload["release_completion_eligible"] = False
        payload["trusted_final_claim"] = False
        next_candidates.append(payload)
        if bool(payload.get(SIMULATION_ELIGIBLE, payload.get(STEP3_EVALUABLE, False))):
            next_step3_admission_candidates.append({
                "candidate_id": payload["candidate_id"],
                "search_policy_candidate_id": payload["candidate_id"],
                "complete_dse_candidate_id": str(payload.get("complete_dse_candidate_id") or ""),
                "architecture_id": str(payload.get("architecture_id") or ""),
                "taxonomy_id": str(payload.get("taxonomy_id") or ""),
                "design_point_id": str(payload.get("design_point_id") or ""),
                "mapping_id": str(payload.get("mapping_id") or ""),
                "mapping_candidate_id": str(payload.get("mapping_candidate_id") or ""),
                "compile_schedule_id": str(payload.get("compile_schedule_id") or ""),
                "runtime_schedule_id": str(payload.get("runtime_schedule_id") or ""),
                "parameter_profile_id": str(payload.get("parameter_profile_id") or ""),
                "parameter_hash": str(payload.get("parameter_hash") or ""),
                "search_policy_parameter_hash": str(payload.get("parameter_hash") or ""),
                "mapping_parameter_hash": str(payload.get("mapping_parameter_hash") or ""),
                "candidate_record_hash": str(payload.get("candidate_record_hash") or ""),
                "release_subset_hash": str(payload.get("release_subset_hash") or ""),
                "runtime_scheduling_provenance": dict(
                    payload.get("runtime_scheduling_provenance", {})
                )
                if isinstance(payload.get("runtime_scheduling_provenance", {}), Mapping)
                else {},
                "artifact_provenance": dict(
                    payload.get("artifact_provenance", {})
                )
                if isinstance(payload.get("artifact_provenance", {}), Mapping)
                else {},
                "candidate_identity": (
                    dict(payload.get("candidate_identity", {}))
                    if isinstance(payload.get("candidate_identity", {}), Mapping)
                    else {}
                ),
                "candidate_identity_policy": str(payload.get("candidate_identity_policy") or ""),
                "search_policy_rank": rank,
                "score": float(payload.get("score", 0.0) or 0.0),
                SIMULATION_ELIGIBLE: bool(payload.get(SIMULATION_ELIGIBLE, False)),
                STEP3_EVALUABLE: bool(payload.get(STEP3_EVALUABLE, False)),
                STEP2_SCREENABLE: bool(payload.get(STEP2_SCREENABLE, False)),
                "promoted_for_simulation": bool(payload.get("promoted_for_simulation", False)),
                SIMULATION_BLOCKERS: list(payload.get(SIMULATION_BLOCKERS, []) or []),
                "queue_state": payload.get("queue_state", "blocked_before_step3"),
                "admission_status": "requires_step3_queue_materialization",
                "admission_required_before_execution": step3_queue_ref,
                "not_a_step3_queue_entry": True,
                "provenance_only": True,
                "execution_allowed": False,
                "claim_status": "step2_materialization_candidate_only",
                "trusted_final_claim": False,
                "release_completion_eligible": False,
                "claim_boundary": (
                    "This is a Step2 materialization/admission candidate derived from "
                    "search feedback. It is not a Step3 queue entry and cannot execute "
                    "until written into the canonical step3_simulation_queue artifact."
                ),
            })
    next_checkpoint = policy.checkpoint(problem).to_dict()
    next_checkpoint["candidate_count"] = len(next_checkpoint.get("candidates", []) or [])
    next_checkpoint["proposal_budget"] = next_budget
    output_observed_count = int(next_checkpoint.get("observed_count", 0) or 0)
    return {
        "schema_version": "dse.step2.search_iteration_plan.v1",
        "policy_name": next_checkpoint.get("policy_name"),
        "problem_id": next_checkpoint.get("problem_id"),
        "campaign_id": campaign_id,
        "workload_run_id": workload_run_id,
        "trial_id": trial_id,
        "search_policy_problem": problem.to_dict(),
        "input_search_checkpoint_ref": input_search_checkpoint_ref,
        "feedback_update_ref": feedback_update_ref,
        "calibration_record_ref": calibration_record_ref,
        "source_artifact_provenance": {
            "input_search_checkpoint": _source_artifact_provenance(
                role="input_search_checkpoint",
                ref=input_search_checkpoint_ref,
                payload=search_checkpoint,
            ),
            "feedback_update": _source_artifact_provenance(
                role="feedback_update",
                ref=feedback_update_ref,
                payload=feedback_update,
            ),
            "calibration_record": _source_artifact_provenance(
                role="calibration_record",
                ref=calibration_record_ref,
                payload=calibration_record,
            ),
        },
        "input_observed_count": input_observed_count,
        "applied_feedback_count": applied_feedback_count,
        "feedback_observation_count": len(feedback_observation_routes),
        "feedback_unresolved_observation_count": unresolved_feedback_count,
        "feedback_routing_status": (
            "no_feedback_observations"
            if not feedback_observation_routes
            else "all_feedback_observations_routed"
            if unresolved_feedback_count == 0
            else "partial_unresolved_feedback_observations"
        ),
        "feedback_observation_routing": feedback_observation_routes,
        "output_observed_count": output_observed_count,
        "candidate_alias_count": len(alias_lookup),
        "next_proposal_budget": next_budget,
        "next_proposed_count": len(next_candidates),
        "next_best_candidate_id": next_checkpoint.get("best_candidate_id"),
        "next_candidates": next_candidates,
        "next_step3_admission_queue_ref": step3_queue_ref,
        "next_step3_admission_candidate_count": len(next_step3_admission_candidates),
        "next_step3_admission_candidates": next_step3_admission_candidates,
        "next_checkpoint": next_checkpoint,
        "feedback_informed_proposal_ordering": applied_feedback_count > 0,
        "top_k_queue_role": "provenance_only_not_step3_admission",
        "step3_admission_queue": step3_queue_ref,
        "top_k_queue_provenance_only": True,
        "hidden_evidence_fanout_allowed": False,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Search iteration plans are feedback-informed proposal provenance. "
            "They cannot schedule Step3 evidence until a Campaign materializes "
            "entries in step3_simulation_queue.json."
        ),
    }


def search_checkpoint_from_iteration_plan(
    search_iteration_plan: Mapping[str, Any],
    *,
    campaign_id: str = "",
    workload_run_id: str = "",
    trial_id: str = "",
    refs: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Build a fail-closed Step2 checkpoint summary from an iteration plan.

    The checkpoint is replay state for the next Step2/Campaign wave.  It mirrors
    the SearchPolicy checkpoint and proposal candidates from
    ``build_search_iteration_plan`` without turning those proposals into Step3
    execution authority or release-completion evidence.
    """

    plan = _as_mapping(search_iteration_plan)
    refs_payload = dict(refs or {})
    next_checkpoint = _as_mapping(plan.get("next_checkpoint"))
    problem = _as_mapping(plan.get("search_policy_problem"))
    next_candidates = [
        dict(candidate)
        for candidate in plan.get("next_candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    checkpoint_candidates = [
        dict(candidate)
        for candidate in next_checkpoint.get("candidates", []) or []
        if isinstance(candidate, Mapping)
    ]
    if not next_candidates:
        next_candidates = checkpoint_candidates

    policy_name = str(
        plan.get("policy_name")
        or next_checkpoint.get("policy_name")
        or "unknown_search_policy"
    )
    resolved_campaign_id = str(campaign_id or plan.get("campaign_id") or "")
    resolved_workload_run_id = str(
        workload_run_id
        or plan.get("workload_run_id")
        or problem.get("workload_run_id")
        or ""
    )
    resolved_trial_id = str(trial_id or plan.get("trial_id") or "")
    step3_queue = str(
        plan.get("next_step3_admission_queue_ref")
        or plan.get("step3_admission_queue")
        or refs_payload.get("step3_simulation_queue")
        or "step3_simulation_queue.json"
    )
    candidate_count = len(next_candidates)
    proposed_count = int(
        plan.get("next_proposed_count")
        or next_checkpoint.get("proposed_count")
        or candidate_count
        or 0
    )
    observed_count = int(
        plan.get("output_observed_count")
        or next_checkpoint.get("observed_count")
        or 0
    )

    checkpoint_payload = dict(next_checkpoint)
    checkpoint_payload.setdefault("schema_version", "dse.step2.search_checkpoint.v1")
    checkpoint_payload.setdefault("policy_name", policy_name)
    checkpoint_payload.setdefault("problem_id", str(plan.get("problem_id") or problem.get("problem_id") or ""))
    checkpoint_payload["candidate_count"] = len(checkpoint_candidates)
    checkpoint_payload.setdefault(
        "proposal_budget",
        int(plan.get("next_proposal_budget") or proposed_count or candidate_count or 0),
    )
    checkpoint_payload["trusted_final_claim"] = False
    checkpoint_payload["release_completion_eligible"] = False
    for candidate in checkpoint_payload.get("candidates", []) or []:
        if isinstance(candidate, dict):
            candidate["trusted_final_claim"] = False
            candidate["release_completion_eligible"] = False
            candidate["deliverable_complete"] = False
    search_iteration_plan_ref = str(
        refs_payload.get("search_iteration_plan")
        or plan.get("search_iteration_plan_ref")
        or "search_iteration_plan.json"
    )
    source_artifact_provenance = _as_mapping(plan.get("source_artifact_provenance"))
    source_artifact_provenance["search_iteration_plan"] = _source_artifact_provenance(
        role="search_iteration_plan",
        ref=search_iteration_plan_ref,
        payload=plan,
    )
    checkpoint_artifact_provenance = {
        "search_iteration_plan_ref": search_iteration_plan_ref,
        "input_search_checkpoint_ref": (
            refs_payload.get("source_search_checkpoint")
            or refs_payload.get("input_search_checkpoint")
            or plan.get("input_search_checkpoint_ref")
            or "step2/search_checkpoint.json"
        ),
        "feedback_update_ref": (
            refs_payload.get("feedback_update")
            or plan.get("feedback_update_ref")
            or "feedback_update.json"
        ),
        "calibration_record_ref": (
            refs_payload.get("calibration_record")
            or plan.get("calibration_record_ref")
            or "calibration_record.json"
        ),
        "candidate_count": candidate_count,
        "proposed_count": proposed_count,
        "observed_count": observed_count,
        "top_k_queue_provenance_only": True,
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "deliverable_complete": False,
        "claim_boundary": (
            "Search checkpoint summary artifact provenance records replay "
            "inputs only; Step3 admission and final claims remain external."
        ),
    }

    return {
        "schema_version": "dse.step2.search_checkpoint_summary.v1",
        "campaign_id": resolved_campaign_id,
        "workload_run_id": resolved_workload_run_id,
        "trial_id": resolved_trial_id,
        "workload_id": str(problem.get("workload_run_id") or resolved_workload_run_id),
        "workload_family": str(problem.get("workload_family") or "generic_workload"),
        "policy_scope": str(problem.get("policy_scope") or "search_iteration_plan_replay"),
        "policy_name": policy_name,
        "search_policy_name": policy_name,
        "search_policy_problem_id": str(plan.get("problem_id") or problem.get("problem_id") or ""),
        "search_policy_proposal_budget": int(plan.get("next_proposal_budget") or proposed_count or 0),
        "search_policy_proposed_count": proposed_count,
        "search_policy_observed_count": observed_count,
        "search_policy_candidates": next_candidates,
        "search_policy_checkpoint": checkpoint_payload,
        "search_policy_problem": problem,
        "search_iteration_plan_ref": search_iteration_plan_ref,
        "input_search_checkpoint_ref": (
            refs_payload.get("source_search_checkpoint")
            or refs_payload.get("input_search_checkpoint")
            or plan.get("input_search_checkpoint_ref")
            or "step2/search_checkpoint.json"
        ),
        "feedback_update_ref": refs_payload.get("feedback_update") or plan.get("feedback_update_ref") or "feedback_update.json",
        "calibration_record_ref": refs_payload.get("calibration_record") or plan.get("calibration_record_ref") or "calibration_record.json",
        "search_space_artifact": refs_payload.get("architecture_search_space", "architecture_search_space.json"),
        "search_space_hash": str(plan.get("search_space_hash") or ""),
        "candidate_identity_policy": "stable_parameter_hash_sidecar",
        "candidate_count": candidate_count,
        "proposed_count": proposed_count,
        "observed_count": observed_count,
        "best_candidate_id": str(plan.get("next_best_candidate_id") or next_checkpoint.get("best_candidate_id") or ""),
        "top_k_candidate_queue_artifact": refs_payload.get("top_k_candidate_queue", "top_k_candidate_queue.json"),
        "step3_simulation_queue_artifact": step3_queue,
        "top_k_queue_provenance_only": True,
        "source_artifact_provenance": source_artifact_provenance,
        "artifact_provenance": checkpoint_artifact_provenance,
        "execution_allowed": False,
        "hidden_evidence_fanout_allowed": False,
        "release_completion_eligible": False,
        "trusted_final_claim": False,
        "claim_boundary": (
            "Search checkpoints generated from iteration plans are replay state "
            "only. They preserve SearchPolicy proposals for the next Campaign "
            "wave but do not authorize Step3 execution or final claims."
        ),
    }


def _score_candidate(parameters: Mapping[str, Any], objective: str) -> float:
    score = 0.0
    for key, value in sorted(parameters.items()):
        if isinstance(value, bool):
            score += 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            score += float(value)
        else:
            score += (sum(ord(ch) for ch in f"{key}:{value}") % 100) / 100.0
    if "min" in objective.lower():
        return -score
    return score


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, str):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except ValueError:
            return None
    return None


def _objective_metric_feedback_bias(metrics: Mapping[str, Any]) -> float:
    """Return a domain-neutral score bias from an explicitly named metric.

    Step4 feedback may carry a workload-specific measured metric such as an
    end-to-end runtime.  The core policy stays domain-neutral by requiring the
    feedback row to identify the metric name/direction instead of baking any
    workload-family key into Step2.  Example:

    ``{"objective_metric_name": "end_to_end_time_s",
       "objective_direction": "minimize",
       "end_to_end_time_s": 42.0}``
    """

    metric_name = str(
        metrics.get("objective_metric_name")
        or metrics.get("objective_key")
        or metrics.get("rank_metric_name")
        or ""
    )
    if not metric_name:
        return 0.0
    value = _coerce_float(metrics.get("objective_metric_value"))
    if value is None and metric_name:
        value = _coerce_float(metrics.get(metric_name))
    if value is None:
        return 0.0
    weight = _coerce_float(metrics.get("objective_metric_weight"))
    if weight is None:
        weight = 1.0
    direction = str(
        metrics.get("objective_direction")
        or metrics.get("objective_metric_direction")
        or metrics.get("rank_metric_direction")
        or ""
    ).strip().lower()
    lower_is_better_value = metrics.get("lower_is_better")
    if not direction and not isinstance(lower_is_better_value, bool):
        return 0.0
    lower_is_better = lower_is_better_value is True
    if direction in {"min", "minimize", "minimise", "lower_is_better"}:
        lower_is_better = True
    elif direction in {"max", "maximize", "maximise", "higher_is_better"}:
        lower_is_better = False
    elif direction:
        return 0.0
    return (-value if lower_is_better else value) * weight


def _parameter_hash(parameters: Mapping[str, Any]) -> str:
    data = json.dumps(dict(parameters), sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def _stable_candidate_id(problem: SearchProblem, policy_name: str, parameters: Mapping[str, Any]) -> str:
    identity_payload = {
        "problem_id": problem.problem_id,
        "policy_name": policy_name,
        "parameter_hash": _parameter_hash(parameters),
    }
    digest = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return f"{problem.problem_id}:{policy_name}:{digest[:16]}"


class _BasePolicy(SearchPolicy):
    policy_name = "base"

    def __init__(self) -> None:
        self._proposed: Dict[str, SearchCandidateRecord] = {}
        self._observed_count = 0

    def _candidate_provenance(
        self,
        problem: SearchProblem,
        *,
        candidate_index: int,
        parameters: Mapping[str, Any],
    ) -> Dict[str, Any]:
        parameter_hash = _parameter_hash(parameters)
        return {
            "policy_name": self.policy_name,
            "problem_id": problem.problem_id,
            "workload_run_id": problem.workload_run_id,
            "candidate_index": candidate_index,
            "parameter_hash": parameter_hash,
            "candidate_identity_policy": "stable_problem_policy_parameter_hash",
            "candidate_identity_excludes": [
                "proposal_order",
                "budget",
                "feedback_order",
                "transient_rank",
            ],
        }

    def _remember_record(self, record: SearchCandidateRecord) -> SearchCandidateRecord:
        previous = self._proposed.get(record.candidate_id)
        if previous is not None:
            record.observed_metrics.update(previous.observed_metrics)
            for reason in previous.promotion_reasons:
                if reason not in record.promotion_reasons:
                    record.promotion_reasons.append(reason)
            for blocker in previous.blocker_reasons:
                if blocker not in record.blocker_reasons:
                    record.blocker_reasons.append(blocker)
        self._proposed[record.candidate_id] = record
        return record

    def _candidate_id_for_parameters(
        self,
        problem: SearchProblem,
        parameters: Mapping[str, Any],
    ) -> str:
        """Preserve restored candidate IDs for identical parameter points."""

        parameter_hash = _parameter_hash(parameters)
        for record in self._proposed.values():
            existing_hash = record.parameter_hash or _parameter_hash(record.parameters)
            if existing_hash == parameter_hash or dict(record.parameters) == dict(parameters):
                return record.candidate_id
        return _stable_candidate_id(problem, self.policy_name, parameters)

    def observe(self, candidate_id: str, metrics: Mapping[str, Any]) -> None:
        record = self._proposed.get(candidate_id)
        if record is None:
            return
        record.observed_metrics.update(dict(metrics))
        if "promoted" in metrics:
            if metrics["promoted"] and "promoted_for_simulation" not in record.promotion_reasons:
                record.promotion_reasons.append("promoted_for_simulation")
            if not metrics["promoted"] and "feedback_rejected" not in record.blocker_reasons:
                record.blocker_reasons.append("feedback_rejected")
        self._observed_count += 1

    def checkpoint(self, problem: SearchProblem) -> SearchCheckpoint:
        candidates = tuple(self._proposed.values())
        best = max(candidates, key=lambda item: item.score, default=None)
        return SearchCheckpoint(
            policy_name=self.policy_name,
            problem_id=problem.problem_id,
            proposed_count=len(candidates),
            observed_count=self._observed_count,
            best_candidate_id=best.candidate_id if best else None,
            candidates=candidates,
        )

    def _record(self, problem: SearchProblem, index: int, parameters: Mapping[str, Any], reason: str) -> SearchCandidateRecord:
        blockers = [] if parameters else ["empty_parameter_record"]
        promotions = ["promoted_for_simulation"] if not blockers else []
        parameter_hash = _parameter_hash(parameters)
        record = SearchCandidateRecord(
            candidate_id=self._candidate_id_for_parameters(problem, parameters),
            parameters=dict(parameters),
            provenance=self._candidate_provenance(problem, candidate_index=index, parameters=parameters),
            generation_reason=reason,
            parameter_hash=parameter_hash,
            score=_score_candidate(parameters, problem.objective),
            promotion_reasons=promotions,
            blocker_reasons=blockers,
        )
        return self._remember_record(record)


class SeededBeamSearchPolicy(_BasePolicy):
    """Deterministic beam policy that prefers explicit seeds, then grid records."""

    policy_name = "seeded_beam"

    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        if budget <= 0:
            return []
        raw: List[Tuple[str, Mapping[str, Any]]] = []
        raw.extend(("seed_candidate", seed) for seed in problem.seed_candidates)
        raw.extend(("parameter_grid", item) for item in problem.parameter_grid(limit=max(budget * 2, budget)))
        scored = sorted(raw, key=lambda item: _score_candidate(item[1], problem.objective), reverse=True)
        return [self._record(problem, index, params, reason) for index, (reason, params) in enumerate(scored[:budget])]


class RandomBaselinePolicy(_BasePolicy):
    """Deterministic random baseline for comparing guided search policies."""

    policy_name = "random_baseline"

    def __init__(self, seed: int = 0) -> None:
        super().__init__()
        self._random = Random(seed)

    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        grid = problem.parameter_grid()
        self._random.shuffle(grid)
        return [self._record(problem, index, params, "seeded_random_baseline") for index, params in enumerate(grid[:max(0, budget)])]


class BottleneckGuidedPolicy(_BasePolicy):
    """Simple guided policy that prioritizes records touching bottleneck keys."""

    policy_name = "bottleneck_guided"

    def __init__(self, bottleneck_keys: Iterable[str] = ()) -> None:
        super().__init__()
        self.bottleneck_keys = tuple(bottleneck_keys)

    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        if budget <= 0:
            return []
        grid = problem.parameter_grid()

        def priority(params: Mapping[str, Any]) -> Tuple[int, float]:
            touched = sum(1 for key in self.bottleneck_keys if key in params)
            return touched, _score_candidate(params, problem.objective)

        ordered = sorted(grid, key=priority, reverse=True)
        return [self._record(problem, index, params, "bottleneck_guided_parameter_grid") for index, params in enumerate(ordered[:budget])]


HIERARCHICAL_FUNNEL_STAGES: Tuple[str, ...] = (
    "template_legality_enumeration",
    "analytic_screen",
    "bottleneck_guided_refinement",
    "hls_rtl_ppa_calibration",
    "evidence_eligible_pareto",
)


def _stable_parameter_key(parameters: Mapping[str, Any]) -> str:
    return json.dumps(dict(parameters), sort_keys=True, separators=(",", ":"), default=str)


class HierarchicalFunnelSearchPolicy(_BasePolicy):
    """Replayable staged search policy for expensive multi-fidelity funnels.

    The policy is domain-neutral: callers provide generic parameter records,
    release-lane names, and constraint metadata.  Workload plugins may map any
    domain-specific semantics into those parameters, but this class only enforces
    two generic invariants:

    * every proposal records the same staged funnel in provenance;
    * exploratory/wide-space rows are prevented from contaminating formal
      release/Pareto promotion unless the caller explicitly changes the release
      lane constraint.
    """

    policy_name = "hierarchical_funnel"

    def __init__(
        self,
        bottleneck_keys: Iterable[str] = (),
        *,
        maximize_metric_keys: Iterable[str] = (),
        minimize_metric_keys: Iterable[str] = (),
    ) -> None:
        super().__init__()
        self.bottleneck_keys = tuple(bottleneck_keys)
        self.maximize_metric_keys = tuple(str(key) for key in maximize_metric_keys)
        self.minimize_metric_keys = tuple(str(key) for key in minimize_metric_keys)
        self._feedback_bias: Dict[str, float] = {}
        self._enumeration_by_problem: Dict[str, Dict[str, Any]] = {}

    def observe(self, candidate_id: str, metrics: Mapping[str, Any]) -> None:
        record = self._proposed.get(candidate_id)
        super().observe(candidate_id, metrics)
        if record is None:
            return
        bias = 0.0
        if isinstance(metrics.get("calibrated_score_delta"), (int, float)):
            bias += float(metrics["calibrated_score_delta"])
        if isinstance(metrics.get("step4_quality_score"), (int, float)):
            bias += float(metrics["step4_quality_score"]) / 100.0
        if metrics.get("step4_verdict") in {"trusted_pass", "passed", "promoted"}:
            bias += 1.0
        if metrics.get("step4_verdict") in {"failed", "blocked", "rejected"}:
            bias -= 1.0
        if "latency_ms" in metrics and isinstance(metrics["latency_ms"], (int, float)):
            bias -= float(metrics["latency_ms"]) / 1000.0
        bias += _objective_metric_feedback_bias(metrics)
        for key in self.maximize_metric_keys:
            value = _coerce_float(metrics.get(key))
            if value is not None:
                bias += value
        for key in self.minimize_metric_keys:
            value = _coerce_float(metrics.get(key))
            if value is not None:
                bias -= value
        key = _stable_parameter_key(record.parameters)
        self._feedback_bias[key] = self._feedback_bias.get(key, 0.0) + bias

    def _constraint_blockers(self, problem: SearchProblem, parameters: Mapping[str, Any]) -> List[str]:
        constraints = dict(problem.constraints or {})
        blockers: List[str] = []
        for key in constraints.get("required_parameters", ()) or ():
            if key not in parameters:
                blockers.append(f"missing_required_parameter:{key}")

        lane_policy = self._release_lane_policy(problem)
        lane_field = str(lane_policy.get("formal_pareto_lane_field") or "")
        release_lane = str(lane_policy.get("release_lane", "release"))
        if lane_field in parameters and str(parameters[lane_field]) != release_lane:
            blockers.append(f"non_release_lane:{parameters[lane_field]}")

        legal_values = constraints.get("legal_values", {}) or {}
        if isinstance(legal_values, Mapping):
            for key, values in legal_values.items():
                if key in parameters and parameters[key] not in set(values or ()):
                    blockers.append(f"illegal_value:{key}:{parameters[key]}")
        return blockers

    def _release_lane_policy(self, problem: SearchProblem) -> Dict[str, Any]:
        constraints = dict(problem.constraints or {})
        preferred_lane_field = constraints.get("formal_pareto_lane_field")
        legacy_tier_field = constraints.get("formal_pareto_tier_field")
        preferred_release_lane = constraints.get("release_lane")
        legacy_release_tier = constraints.get("release_tier")

        if preferred_lane_field:
            lane_field = str(preferred_lane_field)
            lane_field_source = "formal_pareto_lane_field"
        elif legacy_tier_field:
            lane_field = str(legacy_tier_field)
            lane_field_source = "legacy_formal_pareto_tier_field"
        else:
            lane_field = None
            lane_field_source = "none"

        release_lane = str(
            preferred_release_lane
            if preferred_release_lane is not None
            else legacy_release_tier
            if legacy_release_tier is not None
            else "release"
        )
        legacy_policy = {
            "formal_pareto_tier_field": str(legacy_tier_field) if legacy_tier_field else None,
            "release_tier": str(legacy_release_tier) if legacy_release_tier is not None else None,
            "legacy_tier_constraints_authoritative": False,
            "deprecated": True,
        }
        return {
            "formal_pareto_lane_field": lane_field,
            "release_policy_field": str(
                constraints.get("release_policy_field", "release_policy.lane")
            ),
            "release_lane": release_lane,
            "lane_field_source": lane_field_source,
            "exploratory_rows_can_order_search": True,
            "exploratory_rows_can_enter_formal_pareto": False,
            "legacy_compatibility": legacy_policy,
        }

    def _stage_trace(
        self,
        problem: SearchProblem,
        parameters: Mapping[str, Any],
        blockers: Sequence[str],
    ) -> List[Dict[str, Any]]:
        constraints = dict(problem.constraints or {})
        required_stages = tuple(
            str(stage)
            for stage in constraints.get("hierarchical_funnel_stages", HIERARCHICAL_FUNNEL_STAGES)
        )
        active_stages = required_stages or HIERARCHICAL_FUNNEL_STAGES
        stage_trace: List[Dict[str, Any]] = []
        first_blocked = blockers[0] if blockers else ""
        for index, stage_id in enumerate(active_stages):
            status = "passed"
            reasons: List[str] = [f"stage_order:{index}"]
            if first_blocked and stage_id in {"template_legality_enumeration", "evidence_eligible_pareto"}:
                status = "blocked"
                reasons.append(first_blocked)
            elif stage_id == "hls_rtl_ppa_calibration" and constraints.get("requires_physical_evidence"):
                reasons.append("physical_evidence_required_before_trusted_claim")
            elif stage_id == "evidence_eligible_pareto":
                reasons.append("formal_pareto_candidate" if not blockers else "formal_pareto_blocked")
            else:
                reasons.append("replayable_funnel_stage")
            stage_trace.append({"stage_id": stage_id, "status": status, "reasons": reasons})
        return stage_trace

    def _score(self, problem: SearchProblem, parameters: Mapping[str, Any]) -> float:
        base = _score_candidate(parameters, problem.objective)
        touched = sum(1 for key in self.bottleneck_keys if key in parameters)
        return base + touched + self._feedback_bias.get(_stable_parameter_key(parameters), 0.0)

    def _max_candidate_enumeration(self, problem: SearchProblem) -> Optional[int]:
        raw_limit = (problem.constraints or {}).get("max_candidate_enumeration")
        if raw_limit in (None, "", False):
            return None
        try:
            return max(0, int(raw_limit))
        except (TypeError, ValueError):
            return None

    def _raw_candidates(self, problem: SearchProblem, budget: int) -> List[Mapping[str, Any]]:
        grid_size = problem.parameter_grid_size()
        max_enumeration = self._max_candidate_enumeration(problem)
        grid_limit = grid_size if max_enumeration is None else min(grid_size, max_enumeration)
        raw: List[Mapping[str, Any]] = [dict(seed) for seed in problem.seed_candidates]
        raw.extend(problem.parameter_grid(limit=grid_limit))
        deduped: Dict[str, Mapping[str, Any]] = {}
        for params in raw:
            deduped.setdefault(_stable_parameter_key(params), dict(params))
        self._enumeration_by_problem[problem.problem_id] = {
            "schema_version": "dse.step2.search_space_enumeration.v1",
            "grid_candidate_count": grid_size,
            "grid_candidate_enumerated_count": grid_limit,
            "seed_candidate_count": len(problem.seed_candidates),
            "deduped_candidate_count": len(deduped),
            "complete_grid_enumeration": grid_limit >= grid_size,
            "max_candidate_enumeration": max_enumeration,
            "output_budget": int(budget),
            "claim_boundary": (
                "Search-space enumeration is Step2 candidate-generation provenance only; "
                "it is not Step3 evidence or a trusted final ranking."
            ),
        }
        return list(deduped.values())

    def propose(self, problem: SearchProblem, budget: int) -> List[SearchCandidateRecord]:
        if budget <= 0:
            return []
        ordered = sorted(
            self._raw_candidates(problem, budget),
            key=lambda params: self._score(problem, params),
            reverse=True,
        )
        records: List[SearchCandidateRecord] = []
        for index, parameters in enumerate(ordered[:budget]):
            blockers = self._constraint_blockers(problem, parameters)
            stage_trace = self._stage_trace(problem, parameters, blockers)
            release_lane_policy = self._release_lane_policy(problem)
            parameter_hash = _parameter_hash(parameters)
            provenance = self._candidate_provenance(
                problem,
                candidate_index=index,
                parameters=parameters,
            )
            provenance.update({
                "funnel_stage_order": list(HIERARCHICAL_FUNNEL_STAGES),
                "funnel_stages": stage_trace,
                "release_lane_policy": release_lane_policy,
                "release_tier_policy": {
                    **release_lane_policy["legacy_compatibility"],
                    "compatibility_alias_for": "release_lane_policy",
                },
                "search_space_enumeration": dict(self._enumeration_by_problem.get(problem.problem_id, {})),
            })
            promotions = [] if blockers else [
                "promoted_for_simulation",
                "formal_release_pareto_eligible",
            ]
            record = SearchCandidateRecord(
                candidate_id=self._candidate_id_for_parameters(problem, parameters),
                parameters=dict(parameters),
                provenance=provenance,
                generation_reason="hierarchical_funnel_search",
                parameter_hash=parameter_hash,
                score=self._score(problem, parameters),
                promotion_reasons=promotions,
                blocker_reasons=list(blockers),
            )
            records.append(self._remember_record(record))
        return records


__all__ = [
    "BottleneckGuidedPolicy",
    "CapabilityDecision",
    "ComponentCapability",
    "HIERARCHICAL_FUNNEL_STAGES",
    "HierarchicalFunnelSearchPolicy",
    "RandomBaselinePolicy",
    "SearchCandidateRecord",
    "SearchCheckpoint",
    "SearchPolicy",
    "SearchProblem",
    "SeededBeamSearchPolicy",
    "SIMULATION_BLOCKERS",
    "SIMULATION_ELIGIBLE",
    "STEP2_SCREENABLE",
    "STEP3_EVALUABLE",
    "build_search_iteration_plan",
    "candidate_observation_id_lookup",
    "observe_step4_feedback",
    "route_step4_feedback_observations",
    "search_checkpoint_from_iteration_plan",
    "search_policy_from_checkpoint",
    "search_problem_from_dict",
    "step4_feedback_observations",
]
