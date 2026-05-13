#!/usr/bin/env python3
"""Compatibility layer for workload workflow terminology.

New code should use :mod:`dse_v2.core.workload.profiles`.  The workflow names
remain as aliases so older generic tests/scripts can keep importing them while
policy is sourced from WorkloadProfile data.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from dse_v2.core.workload.profiles import (
    DEFAULT_WORKLOAD_PROFILES,
    DIAGNOSTIC_CLAIM_BOUNDARIES,
    FAMILY_ALIASES,
    FULL_CLAIM_BOUNDARIES,
    ProfileRegistry,
    WorkloadProfile,
    canonical_workload_family,
    default_profile_dict,
    default_profile_registry,
    get_workload_profile,
    required_coverage_from_profile,
    resolve_profile_metadata,
)

WorkloadWorkflow = WorkloadProfile
DEFAULT_WORKLOAD_WORKFLOWS = DEFAULT_WORKLOAD_PROFILES


def get_workload_workflow(workload_family: str) -> WorkloadWorkflow:
    return get_workload_profile(workload_family)


def default_workflow_registry() -> Dict[str, Dict[str, Any]]:
    return default_profile_dict()


def resolve_workflow_metadata(workload_family: str, override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    return resolve_profile_metadata(workload_family, override)


def required_coverage_from_workflow(
    workload_family: str,
    workflow: Optional[Mapping[str, Any]],
    graph_nodes: Iterable[str],
    topological_order: Optional[Iterable[str]] = None,
) -> List[str]:
    return required_coverage_from_profile(workload_family, workflow, graph_nodes, topological_order)
