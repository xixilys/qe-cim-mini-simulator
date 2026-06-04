#!/usr/bin/env python3
"""Default QE-IC Layer-1 workload-suite builder."""

from __future__ import annotations

import copy
from typing import Any

from dse_v2.workloads.qe_ic.registry import (
    EXCLUDED_WORKFLOW_REGISTRY,
    MOTIF_REGISTRY,
    SCENARIO_REGISTRY,
    WORKLOAD_FAMILY_REGISTRY,
)
from dse_v2.workloads.qe_ic.schema import (
    CLAIM_BOUNDARY,
    DOWNSTREAM_CONSUMERS,
    QE_IC_PRIMARY_SCENARIO_ID,
    QE_IC_WORKLOAD_SUITE_ID,
    QE_IC_WORKLOAD_SUITE_SCHEMA_VERSION,
)


def build_default_qe_ic_workload_suite() -> dict[str, Any]:
    """Build the default QE-IC workload-suite contract."""

    return {
        "schema_version": QE_IC_WORKLOAD_SUITE_SCHEMA_VERSION,
        "suite_id": QE_IC_WORKLOAD_SUITE_ID,
        "suite_scope": "IC-device-oriented DFT workload suite",
        "primary_scenario_id": QE_IC_PRIMARY_SCENARIO_ID,
        "workload_families": copy.deepcopy(list(WORKLOAD_FAMILY_REGISTRY.values())),
        "scenarios": copy.deepcopy(list(SCENARIO_REGISTRY.values())),
        "motif_registry": copy.deepcopy(MOTIF_REGISTRY),
        "excluded_workflows": copy.deepcopy(EXCLUDED_WORKFLOW_REGISTRY),
        "downstream_contract": {
            "next_layer": "motif_profiling",
            "required_consumers": list(DOWNSTREAM_CONSUMERS),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }

