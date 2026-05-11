from __future__ import annotations

from typing import Iterable, Sequence


SURVEY_CATALOG = "survey-catalog"
PROJECTION_SCREENED = "projection-screened"
SYSTEMC_CYCLE_ACCOUNTED = "systemc-cycle-accounted"
FINAL_BEST_ELIGIBLE = "final-best-eligible"

EVIDENCE_TIER_LABELS: tuple[str, ...] = (
    SURVEY_CATALOG,
    PROJECTION_SCREENED,
    SYSTEMC_CYCLE_ACCOUNTED,
    FINAL_BEST_ELIGIBLE,
)


class EvidenceTierError(ValueError):
    pass


def validate_evidence_tier(label: str) -> str:
    if label not in EVIDENCE_TIER_LABELS:
        raise EvidenceTierError(f"unknown evidence tier label: {label}")
    return label


def _unique(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _has_prefix(items: Sequence[str], prefixes: tuple[str, ...]) -> bool:
    return any(item.startswith(prefix) for item in items for prefix in prefixes)


def _append_if_no_related_reason(
    reasons: list[str],
    reason: str,
    *,
    prefixes: tuple[str, ...],
) -> None:
    if not _has_prefix(reasons, prefixes):
        reasons.append(reason)


def classify_candidate_evidence(
    *,
    same_candidate_evidence_only: bool,
    stage_c_correct: bool,
    strict_b4_evidence: bool,
    stage_d_policy_satisfied: bool,
    systemc_cycle_evidence: bool,
    projection_screened: bool = False,
    catalog_provenance: bool = False,
    existing_blockers: Iterable[str] = (),
) -> tuple[str, list[str]]:
    """Classify a DSE candidate into the exact Evidence-Plane v1 tiers.

    The four labels are intentionally narrow:
    - ``survey-catalog``: researched/catalog presence only.
    - ``projection-screened``: any executable/proxy/projection screening exists,
      but generated SystemC cycle-accounted evidence is absent.
    - ``systemc-cycle-accounted``: generated/configured SystemC cycle-accounted
      evidence exists, but final-best closure is incomplete.
    - ``final-best-eligible``: exact same candidate has Stage C correctness,
      strict B4 evidence, Stage D implementation evidence satisfying policy,
      and generated SystemC cycle-accounted evidence.
    """

    reasons = _unique(str(item) for item in existing_blockers if item)
    if not same_candidate_evidence_only:
        _append_if_no_related_reason(
            reasons,
            "candidate_evidence_alignment_mismatch",
            prefixes=("candidate_evidence_alignment_",),
        )
    if not stage_c_correct:
        _append_if_no_related_reason(
            reasons,
            "missing_stage_c_qe_correctness_report",
            prefixes=("missing_stage_c", "stage_c_"),
        )
    if not strict_b4_evidence:
        _append_if_no_related_reason(
            reasons,
            "strict_b4_evidence_missing",
            prefixes=("missing_b4", "b4_", "strict_b4_"),
        )
    if not stage_d_policy_satisfied:
        _append_if_no_related_reason(
            reasons,
            "missing_stage_d_implementation_evidence",
            prefixes=("missing_stage_d", "stage_d_", "implementation_projection_"),
        )
    if not systemc_cycle_evidence:
        _append_if_no_related_reason(
            reasons,
            "missing_systemc_cycle_evidence",
            prefixes=("missing_systemc_cycle_evidence", "systemc_cycle_evidence_"),
        )

    if not reasons:
        return FINAL_BEST_ELIGIBLE, []
    if systemc_cycle_evidence:
        return SYSTEMC_CYCLE_ACCOUNTED, reasons
    if projection_screened or stage_c_correct or strict_b4_evidence or stage_d_policy_satisfied:
        return PROJECTION_SCREENED, reasons
    if catalog_provenance:
        return SURVEY_CATALOG, reasons
    return SURVEY_CATALOG, reasons
