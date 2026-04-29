from __future__ import annotations

from dataclasses import dataclass
from itertools import islice, product
import random
from typing import Any, Mapping, Sequence


SEARCH_BOUNDED_CARTESIAN = "bounded_cartesian"
SEARCH_BOUNDED_CARTESIAN_PREFIX = "bounded_cartesian_prefix"
SEARCH_STRATIFIED_CARTESIAN = "stratified_cartesian"
SEARCH_ROUND_ROBIN_BY_FAMILY = "round_robin_by_family"
SEARCH_RANDOM_LATIN_HYPERCUBE = "random_latin_hypercube"
SEARCH_AX_BAYESIAN = "ax_bayesian"
SEARCH_BACKENDS = (
    SEARCH_BOUNDED_CARTESIAN,
    SEARCH_BOUNDED_CARTESIAN_PREFIX,
    SEARCH_STRATIFIED_CARTESIAN,
    SEARCH_ROUND_ROBIN_BY_FAMILY,
    SEARCH_RANDOM_LATIN_HYPERCUBE,
    SEARCH_AX_BAYESIAN,
)


@dataclass(frozen=True)
class SearchResult:
    candidates: list[dict[str, Any]]
    metadata: dict[str, Any]


def bounded_cartesian_product(axes: Mapping[str, Sequence[Any]], limit: int) -> list[dict[str, Any]]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    keys = tuple(axes)
    value_sets = tuple(tuple(axes[key]) for key in keys)
    return [dict(zip(keys, values)) for values in islice(product(*value_sets), limit)]


def stratified_cartesian_product(axes: Mapping[str, Sequence[Any]], limit: int) -> list[dict[str, Any]]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    families = list(axes.get("family", []))
    if not families or limit == 0:
        return []
    per_family_axes = {key: value for key, value in axes.items() if key != "family"}
    buckets: list[list[dict[str, Any]]] = []
    for family in families:
        rows = bounded_cartesian_product(per_family_axes, limit)
        buckets.append([{**row, "family": family} for row in rows])
    candidates: list[dict[str, Any]] = []
    index = 0
    while len(candidates) < limit and any(index < len(bucket) for bucket in buckets):
        for bucket in buckets:
            if index < len(bucket):
                candidates.append(bucket[index])
                if len(candidates) >= limit:
                    break
        index += 1
    # Preserve original axis order in the dictionaries for deterministic make_design_point callers.
    ordered = []
    for candidate in candidates:
        ordered.append({key: candidate[key] for key in axes if key in candidate})
    return ordered


def _ax_available() -> bool:
    try:
        __import__("ax")
    except Exception:
        return False
    return True


def random_latin_hypercube_product(
    axes: Mapping[str, Sequence[Any]],
    limit: int,
    seed: int = 0,
) -> list[dict[str, Any]]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    if limit == 0:
        return []
    keys = tuple(axes)
    value_sets = {key: tuple(axes[key]) for key in keys}
    if any(len(values) == 0 for values in value_sets.values()):
        return []
    rng = random.Random(seed)
    candidates = []
    seen: set[tuple[Any, ...]] = set()
    attempts = 0
    max_attempts = max(100, limit * 20)
    while len(candidates) < limit and attempts < max_attempts:
        attempts += 1
        row = {}
        for axis_index, key in enumerate(keys):
            values = value_sets[key]
            # Deterministic Latin-hypercube-like coverage for categorical axes:
            # every axis is permuted with a phase shift, then occasional random
            # retries fill collisions for small spaces.
            row[key] = values[(len(candidates) + axis_index + rng.randrange(len(values))) % len(values)]
        identity = tuple(row[key] for key in keys)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(row)
    if len(candidates) < limit:
        for row in bounded_cartesian_product(axes, limit * 2):
            identity = tuple(row[key] for key in keys)
            if identity in seen:
                continue
            candidates.append(row)
            seen.add(identity)
            if len(candidates) >= limit:
                break
    return candidates[:limit]


def _ax_bayesian_candidates(
    axes: Mapping[str, Sequence[Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], str] | None:
    try:
        from ax.service.ax_client import AxClient  # type: ignore
        from ax.service.utils.instantiation import ObjectiveProperties  # type: ignore
    except Exception:
        return None
    if limit <= 0:
        return [], "ax_available_no_candidates_requested"
    parameters = []
    for key, values in axes.items():
        parameters.append(
            {
                "name": key,
                "type": "choice",
                "values": list(values),
                "is_ordered": False,
            }
        )
    try:
        ax_client = AxClient(verbose_logging=False)
        ax_client.create_experiment(
            name="frontend_dse_candidate_proposal",
            parameters=parameters,
            objectives={"screening_objective": ObjectiveProperties(minimize=True)},
        )
        candidates = []
        seen: set[tuple[Any, ...]] = set()
        keys = tuple(axes)
        for index in range(limit):
            params, trial_index = ax_client.get_next_trial()
            row = {key: params[key] for key in keys}
            identity = tuple(row[key] for key in keys)
            if identity not in seen:
                candidates.append(row)
                seen.add(identity)
            # Complete the trial with a deterministic synthetic objective so Ax can
            # leave pure Sobol initialization when available, without claiming this
            # frontend has executed a backend.
            ax_client.complete_trial(
                trial_index=trial_index,
                raw_data={"screening_objective": float(index + 1)},
            )
            if len(candidates) >= limit:
                break
        return candidates, "ax_client_proposals_generated"
    except Exception:
        return None


def search_candidates(
    axes: Mapping[str, Sequence[Any]],
    limit: int,
    backend: str = SEARCH_BOUNDED_CARTESIAN,
) -> SearchResult:
    if backend in {SEARCH_BOUNDED_CARTESIAN, SEARCH_BOUNDED_CARTESIAN_PREFIX}:
        candidates = bounded_cartesian_product(axes, limit)
        return SearchResult(
            candidates=candidates,
            metadata={
                "schema_version": "search_metadata_v0",
                "backend": backend,
                "available": True,
                "generated_count": len(candidates),
                "skipped_reason": None,
            },
        )
    if backend in {SEARCH_STRATIFIED_CARTESIAN, SEARCH_ROUND_ROBIN_BY_FAMILY}:
        candidates = stratified_cartesian_product(axes, limit)
        return SearchResult(
            candidates=candidates,
            metadata={
                "schema_version": "search_metadata_v0",
                "backend": backend,
                "available": True,
                "generated_count": len(candidates),
                "skipped_reason": None,
            },
        )
    if backend == SEARCH_RANDOM_LATIN_HYPERCUBE:
        candidates = random_latin_hypercube_product(axes, limit)
        return SearchResult(
            candidates=candidates,
            metadata={
                "schema_version": "search_metadata_v0",
                "backend": backend,
                "available": True,
                "generated_count": len(candidates),
                "skipped_reason": None,
                "coverage_strategy": "deterministic_categorical_latin_hypercube",
            },
        )
    if backend == SEARCH_AX_BAYESIAN:
        available = _ax_available()
        if not available:
            return SearchResult(
                candidates=[],
                metadata={
                    "schema_version": "search_metadata_v0",
                    "backend": backend,
                    "available": False,
                    "unavailable_optional_dependency": "ax",
                    "generated_count": 0,
                    "skipped_reason": "optional_ax_dependency_not_installed",
                },
            )
        ax_result = _ax_bayesian_candidates(axes, limit)
        if ax_result is None:
            candidates = stratified_cartesian_product(axes, limit)
            adapter_status = "ax_available_adapter_failed_stdlib_fallback_used"
        else:
            candidates, adapter_status = ax_result
        return SearchResult(
            candidates=candidates,
            metadata={
                "schema_version": "search_metadata_v0",
                "backend": backend,
                "available": True,
                "adapter_status": adapter_status,
                "generated_count": len(candidates),
                "skipped_reason": None,
                "claim_ceiling": "candidate_generation_only",
            },
        )
    raise ValueError(f"unsupported search backend: {backend}")


def generate_candidates(
    axes: Mapping[str, Sequence[Any]],
    limit: int,
    backend: str = SEARCH_BOUNDED_CARTESIAN,
) -> list[dict[str, Any]]:
    result = search_candidates(axes, limit, backend=backend)
    if not result.metadata.get("available", True):
        raise ValueError(
            f"search backend {backend} unavailable: {result.metadata.get('skipped_reason')}"
        )
    return result.candidates
