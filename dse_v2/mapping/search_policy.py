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
from dataclasses import dataclass, field
from random import Random
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


STEP2_SCREENABLE = "step2_screenable"
STEP3_EVALUABLE = "step3_evaluable"
SIMULATION_ELIGIBLE = "simulation_eligible"
SIMULATION_BLOCKERS = "simulation_blockers"


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
        return {
            "candidate_id": self.candidate_id,
            "parameters": dict(self.parameters),
            "parameter_hash": self.parameter_hash or _parameter_hash(self.parameters),
            "provenance": dict(self.provenance),
            "generation_reason": self.generation_reason,
            "score": float(self.score),
            "promotion_reasons": list(self.promotion_reasons),
            "blocker_reasons": list(self.blocker_reasons),
            STEP2_SCREENABLE: self.step2_screenable,
            STEP3_EVALUABLE: self.step3_evaluable,
            SIMULATION_ELIGIBLE: self.simulation_eligible,
            SIMULATION_BLOCKERS: self.simulation_blockers,
            "observed_metrics": dict(self.observed_metrics),
        }


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
    generic: it indexes the canonical `candidate_id`, `parameter_hash`, and any
    scalar `parameters.*` values without granting those aliases Step3 admission
    authority.
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
            add_alias(provenance.get("mapping_candidate_id"), candidate_id)
            add_alias(provenance.get("architecture_id"), candidate_id)
        candidate_refs = candidate.get("candidate_refs", {})
        if isinstance(candidate_refs, Mapping):
            add_alias(candidate_refs.get("search_policy_candidate_id"), candidate_id)
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
                if isinstance(value, (str, int, float, bool)) and value not in (None, ""):
                    add_alias(value, candidate_id)
                if isinstance(value, Mapping):
                    for nested_value in value.values():
                        if isinstance(nested_value, (str, int, float, bool)) and nested_value not in (None, ""):
                            add_alias(nested_value, candidate_id)
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

    aliases = dict(candidate_id_lookup or {})
    require_alias_match = candidate_id_lookup is not None
    observed = 0
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
        for source_id in candidate_aliases:
            if require_alias_match and source_id not in aliases:
                continue
            candidate_id = aliases.get(source_id, source_id)
            if candidate_id:
                matched_alias = source_id
                break
        if not candidate_id:
            continue
        metrics = _as_mapping(observation.get("metrics"))
        metrics.setdefault("step4_feedback_source_candidate_id", str(observation.get("candidate_id") or ""))
        if matched_alias:
            metrics.setdefault("step4_feedback_matched_candidate_alias", matched_alias)
        policy.observe(candidate_id, metrics)
        observed += 1
    return observed


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
    applied_feedback_count = observe_step4_feedback(
        policy,
        feedback_update,
        calibration_record,
        candidate_id_lookup=alias_lookup,
    )
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
    next_records = policy.propose(problem, budget=next_budget)
    next_candidates: List[Dict[str, Any]] = []
    for rank, record in enumerate(next_records, start=1):
        payload = record.to_dict()
        payload["search_policy_rank"] = rank
        payload["not_a_step3_queue_entry"] = True
        payload["provenance_only"] = True
        payload["trusted_final_claim"] = False
        next_candidates.append(payload)
    next_checkpoint = policy.checkpoint(problem).to_dict()
    next_checkpoint["candidate_count"] = len(next_checkpoint.get("candidates", []) or [])
    next_checkpoint["proposal_budget"] = next_budget
    output_observed_count = int(next_checkpoint.get("observed_count", 0) or 0)
    return {
        "schema_version": "dse.step2.search_iteration_plan.v1",
        "policy_name": next_checkpoint.get("policy_name"),
        "problem_id": next_checkpoint.get("problem_id"),
        "search_policy_problem": problem.to_dict(),
        "input_search_checkpoint_ref": refs_payload.get("search_checkpoint", "step2/search_checkpoint.json"),
        "feedback_update_ref": refs_payload.get("feedback_update", "feedback_update.json"),
        "calibration_record_ref": refs_payload.get("calibration_record", "calibration_record.json"),
        "input_observed_count": input_observed_count,
        "applied_feedback_count": applied_feedback_count,
        "output_observed_count": output_observed_count,
        "candidate_alias_count": len(alias_lookup),
        "next_proposal_budget": next_budget,
        "next_proposed_count": len(next_candidates),
        "next_best_candidate_id": next_checkpoint.get("best_candidate_id"),
        "next_candidates": next_candidates,
        "next_checkpoint": next_checkpoint,
        "top_k_queue_role": "provenance_only_not_step3_admission",
        "step3_admission_queue": "step3_simulation_queue.json",
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
            candidate_id=_stable_candidate_id(problem, self.policy_name, parameters),
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

    def __init__(self, bottleneck_keys: Iterable[str] = ()) -> None:
        super().__init__()
        self.bottleneck_keys = tuple(bottleneck_keys)
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
                candidate_id=_stable_candidate_id(problem, self.policy_name, parameters),
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
    "search_policy_from_checkpoint",
    "search_problem_from_dict",
    "step4_feedback_observations",
]
