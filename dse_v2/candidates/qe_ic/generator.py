#!/usr/bin/env python3
"""Candidate generation for QE-IC Layer-4 plans."""

from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from dse_v2.candidates.qe_ic.schema import (
    SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
    SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
)
from dse_v2.candidates.qe_ic.template_registry import select_templates_for_record


def _slug(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    chars = [char if char.isalnum() else "_" for char in text]
    collapsed = "_".join(part for part in "".join(chars).split("_") if part)
    return collapsed or "unknown"


def viability_record_id(record: Mapping[str, Any]) -> str:
    """Build a stable Layer-3 source record ID from existing viability fields."""

    parts = [
        record.get("workload_family_id"),
        record.get("motif_id"),
        record.get("target_id"),
        record.get("target_type"),
        record.get("decision"),
    ]
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:10]
    return "l3vr_" + "_".join(_slug(part) for part in parts[:4]) + f"_{digest}"


def source_viability_record_index(target_viability: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return source viability records keyed by generated record ID."""

    index: dict[str, dict[str, Any]] = {}
    for record in target_viability.get("viability_records", []):
        if not isinstance(record, Mapping):
            continue
        record_id = viability_record_id(record)
        enriched = copy.deepcopy(dict(record))
        enriched["source_viability_record_id"] = record_id
        index[record_id] = enriched
    return index


def _motif_registry(suite: Mapping[str, Any]) -> Mapping[str, Any]:
    registry = suite.get("motif_registry")
    return registry if isinstance(registry, Mapping) else {}


def _template_allowed(candidate: Mapping[str, Any], campaign_config: Mapping[str, Any]) -> bool:
    allowed_target_types = set(campaign_config.get("allowed_target_types", []))
    allowed_template_families = set(campaign_config.get("allowed_candidate_template_families", []))
    if candidate.get("target_type") not in allowed_target_types:
        return False
    template_family = candidate.get("candidate_parameters", {}).get("template_family")
    return template_family in allowed_template_families


def _candidate_parameters(
    *,
    template: Mapping[str, Any],
    record: Mapping[str, Any],
    motif_registry: Mapping[str, Any],
) -> dict[str, Any]:
    motif = motif_registry.get(record.get("motif_id"), {})
    category = motif.get("category") if isinstance(motif, Mapping) else None
    upper_bound = record.get("upper_bound") if isinstance(record.get("upper_bound"), Mapping) else {}
    risk = record.get("risk") if isinstance(record.get("risk"), Mapping) else {}
    evidence_inputs = record.get("evidence_inputs") if isinstance(record.get("evidence_inputs"), Mapping) else {}
    return {
        **copy.deepcopy(template.get("default_parameters", {})),
        "template_family": template.get("template_family"),
        "motif_category": category,
        "source_target_id": record.get("target_id"),
        "source_profile_target": record.get("source_profile_target"),
        "estimated_net_gain_ratio": upper_bound.get("estimated_net_gain_ratio", 0.0),
        "runtime_ratio": upper_bound.get("runtime_ratio", evidence_inputs.get("runtime_ratio", 0.0)),
        "risk_score": risk.get("overall_risk_score", 0.0),
        "profile_quality_risk": risk.get("profile_quality_risk", 0.0),
        "generation_boundary": "candidate_spec_only_no_execution",
    }


def _candidate_id(
    *,
    candidate_type: str,
    record: Mapping[str, Any],
    template_id: str,
) -> str:
    source_id = str(record.get("source_viability_record_id") or viability_record_id(record))
    raw = "|".join(
        [
            candidate_type,
            str(record.get("workload_family_id", "")),
            str(record.get("motif_id", "")),
            str(record.get("target_type", "")),
            template_id,
            source_id,
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return (
        "qeic_l4_"
        + "_".join(
            _slug(part)
            for part in (
                candidate_type,
                record.get("workload_family_id"),
                record.get("motif_id"),
                record.get("target_type"),
                template_id,
            )
        )
        + f"_{digest}"
    )


def _build_candidate(
    *,
    suite: Mapping[str, Any],
    record: Mapping[str, Any],
    template: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_type = str(template.get("candidate_type"))
    source_decision = "baseline" if candidate_type == "baseline" else str(record.get("decision"))
    return {
        "candidate_id": _candidate_id(
            candidate_type=candidate_type,
            record=record,
            template_id=str(template.get("template_id")),
        ),
        "candidate_type": candidate_type,
        "target_type": record.get("target_type"),
        "workload_family_id": record.get("workload_family_id"),
        "motif_id": record.get("motif_id"),
        "source_viability_record_id": record.get("source_viability_record_id"),
        "source_viability_decision": source_decision,
        "template_id": template.get("template_id"),
        "candidate_parameters": _candidate_parameters(
            template=template,
            record=record,
            motif_registry=_motif_registry(suite),
        ),
        "traceability": {
            "layer1_suite_id": suite.get("suite_id"),
            "layer2_profile_artifact": SOURCE_LAYER2_MOTIF_PROFILE_ARTIFACT,
            "layer3_viability_artifact": SOURCE_LAYER3_TARGET_VIABILITY_ARTIFACT,
        },
    }


def generate_qe_ic_candidates(
    suite: Mapping[str, Any],
    target_viability: Mapping[str, Any],
    campaign_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Generate candidate specs from Layer-3 viability records."""

    generation = campaign_config.get("candidate_generation", {})
    generation = generation if isinstance(generation, Mapping) else {}
    allowed_generation_decisions = set(generation.get("generate_from_decisions", []))
    allowed_template_families = set(campaign_config.get("allowed_candidate_template_families", []))
    max_per_motif = int(generation.get("max_candidates_per_motif", 1))
    max_per_target = int(generation.get("max_candidates_per_target_type", 1))
    include_baseline = generation.get("include_baseline_gpu") is True
    motif_registry = _motif_registry(suite)

    candidates: list[dict[str, Any]] = []
    counts_by_motif: dict[tuple[str, str], int] = defaultdict(int)
    counts_by_target: dict[str, int] = defaultdict(int)

    records = [
        {
            **copy.deepcopy(dict(record)),
            "source_viability_record_id": viability_record_id(record),
        }
        for record in target_viability.get("viability_records", [])
        if isinstance(record, Mapping)
    ]
    records.sort(
        key=lambda record: (
            str(record.get("workload_family_id")),
            str(record.get("motif_id")),
            str(record.get("target_type")),
            str(record.get("target_id")),
        )
    )

    for record in records:
        target_type = str(record.get("target_type", ""))
        decision = str(record.get("decision", ""))
        if target_type == "gpu_only":
            if not include_baseline or decision != "baseline":
                continue
            templates = select_templates_for_record(
                record,
                motif_registry=motif_registry,
                allowed_template_families=allowed_template_families,
                max_templates=1,
            )
        else:
            if decision == "reject" and generation.get("ignore_reject_records") is True:
                continue
            if decision not in allowed_generation_decisions:
                continue
            if counts_by_target[target_type] >= max_per_target:
                continue
            if counts_by_motif[(target_type, str(record.get("motif_id")))] >= max_per_motif:
                continue
            templates = select_templates_for_record(
                record,
                motif_registry=motif_registry,
                allowed_template_families=allowed_template_families,
                max_templates=max(1, max_per_motif - counts_by_motif[(target_type, str(record.get("motif_id")))]),
            )
        for template in templates:
            candidate = _build_candidate(suite=suite, record=record, template=template)
            if not _template_allowed(candidate, campaign_config):
                continue
            candidates.append(candidate)
            if candidate["candidate_type"] != "baseline":
                counts_by_target[str(candidate["target_type"])] += 1
                counts_by_motif[(str(candidate["target_type"]), str(candidate["motif_id"]))] += 1

    return candidates

