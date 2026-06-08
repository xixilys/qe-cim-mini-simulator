#!/usr/bin/env python3
"""Public API for QE-IC real GPU-baseline opportunity analysis."""

from __future__ import annotations

from dse_v2.evidence.qe_ic.artifacts import (
    load_qe_ic_real_baseline_opportunity_report,
    write_qe_ic_real_baseline_opportunity_artifacts,
)
from dse_v2.evidence.qe_ic.candidate_result import validate_qe_ic_candidate_high_fidelity_results
from dse_v2.evidence.qe_ic.gpu_baseline import validate_qe_ic_gpu_baseline_measurements
from dse_v2.evidence.qe_ic.opportunity import analyze_qe_ic_real_baseline_opportunity
from dse_v2.evidence.qe_ic.preliminary_classifier import classify_preliminary_opportunity
from dse_v2.evidence.qe_ic.validation import (
    validate_qe_ic_opportunity_input_artifacts,
    validate_qe_ic_real_baseline_opportunity_report,
)

__all__ = [
    "analyze_qe_ic_real_baseline_opportunity",
    "classify_preliminary_opportunity",
    "load_qe_ic_real_baseline_opportunity_report",
    "validate_qe_ic_candidate_high_fidelity_results",
    "validate_qe_ic_gpu_baseline_measurements",
    "validate_qe_ic_opportunity_input_artifacts",
    "validate_qe_ic_real_baseline_opportunity_report",
    "write_qe_ic_real_baseline_opportunity_artifacts",
]
