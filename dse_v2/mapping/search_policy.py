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

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        add_alias(candidate_id, candidate_id)
        add_alias(candidate.get("parameter_hash"), candidate_id)
        parameters = candidate.get("parameters", {})
        if isinstance(parameters, Mapping):
            for value in parameters.values():
                if isinstance(value, (str, int, float, bool)) and value not in (None, ""):
                    add_alias(value, candidate_id)
    return lookup


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
        candidate_id = str(
            update.get("search_policy_candidate_id")
            or candidate_refs.get("search_policy_candidate_id")
            or update.get("candidate_id")
            or candidate_refs.get("candidate_id")
            or candidate_refs.get("mapping_candidate_id")
            or candidate_refs.get("mapping_parameter_hash")
            or candidate_refs.get("parameter_hash")
            or ""
        )
        if not candidate_id:
            continue
        observations.append({
            "observation_id": f"step4-feedback::{feedback_update.get('trial_id', 'trial')}::{index}",
            "candidate_id": candidate_id,
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
    observed = 0
    for observation in step4_feedback_observations(feedback_update, calibration_record):
        source_id = str(observation.get("candidate_id") or "")
        candidate_id = aliases.get(source_id, source_id)
        if not candidate_id:
            continue
        metrics = _as_mapping(observation.get("metrics"))
        metrics.setdefault("step4_feedback_source_candidate_id", source_id)
        policy.observe(candidate_id, metrics)
        observed += 1
    return observed


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
    "candidate_observation_id_lookup",
    "observe_step4_feedback",
    "step4_feedback_observations",
]
