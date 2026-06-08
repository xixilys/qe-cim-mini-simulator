#!/usr/bin/env python3
"""Generate ACM/DAC LaTeX result tables from QE-FPGA experiment summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dse_v2.mapping.multifidelity_validation import build_multifidelity_algorithm_validation_report


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True, help="paper_ready_experiment_summary.json")
    parser.add_argument("--out", type=Path, required=True, help="Output .tex include file")
    return parser.parse_args(list(argv))


def _load_json_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _tex_escape(value: Any) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _fmt_float(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _tex_escape(value)
    if not math.isfinite(number):
        return "--"
    if abs(number) >= 1000.0:
        return f"{number:.2e}"
    if abs(number) >= 10.0:
        return f"{number:.1f}"
    return f"{number:.3f}"


def _fmt_ratio(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _tex_escape(value)
    if not math.isfinite(number):
        return "--"
    return f"{number:.2f}"


def _fmt_rank(value: Any) -> str:
    if value is None:
        return "--"
    return _tex_escape(value)


def _fmt_delta(value: Any) -> str:
    if value is None:
        return "--"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return _tex_escape(value)
    return f"{number:+d}" if number < 0 else str(number)


def _fmt_bool(value: Any) -> str:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "passed"}:
            return "Y"
        if lowered in {"0", "false", "no", "n", "blocked", "failed"}:
            return "N"
    return "Y" if bool(value) else "N"


def _list_text(values: Sequence[Any], *, limit: int = 4, separator: str = ", ") -> str:
    items = [str(item) for item in values]
    if len(items) > limit:
        items = items[:limit] + ["..."]
    return separator.join(items)


def _compact_unknown_label(identifier: Any) -> str:
    tokens = [token for token in str(identifier).split("_") if token]
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    return "-".join(tokens[:2]).title()


def _candidate_display_label(candidate_id: Any, index: int) -> str:
    text = str(candidate_id)
    if len(text) <= 18 and ":" not in text:
        return text
    return f"A{index}"


def _workflow_class_label(values: Sequence[Any]) -> str:
    return _list_text(values, separator=",")


def _material_label(material: Any) -> str:
    labels = {
        "Si_slab": "Si slab",
    }
    return labels.get(str(material), str(material))


def _size_label(size_class: Any) -> str:
    labels = {
        "large_fft_fixture": "large-fft",
    }
    return labels.get(str(size_class), str(size_class))


def _policy_label(policy_id: Any) -> str:
    labels = {
        "workflow_aware_pareto_funnel": "Funnel",
        "single_fidelity_l1_edp": "L1-only",
        "kernel_level_hotspot_only": "Kernel-only",
        "random_seeded": "Random",
        "random_seeded_multi_seed": "Random",
        "manual_hbm_streaming_heuristic": "Manual",
        "nsga2_lite_multi_objective": "NSGA-II",
        "neuromf_trained_surrogate": "NeuroMF-trained",
        "neuromf_unguided_bootstrap": "NMF-boot",
        "wamf_generic_active_pareto": "WAMF-kernel",
        "wamf_constrained_active_pareto": "WAMF",
        "wamf_dse": "WAMF-DSE",
        "wamf_selected_candidates": "WAMF",
        "cheap_l1_edp": "L1-only",
        "manual_hbm_streaming": "Manual",
        "sequential_surrogate_expected_improvement": "Surrogate-EI",
        "nsga2_ea_l1_multi_objective": "NSGA-II-EA",
        "kernel_histogram_only": "K-hist",
        "kernel_hotspot_only": "Kernel-only",
    }
    return labels.get(str(policy_id), _compact_unknown_label(policy_id))


def _ablation_label(ablation_id: Any) -> str:
    labels = {
        "full_workflow_structural_features": "Full",
        "remove_data_object_lifetime": "No lifetime",
        "remove_host_control_events": "No host",
        "remove_correctness_gate_pressure": "No gate",
        "kernel_histogram_only": "No workflow",
        "no_workflow_abstraction": "No workflow",
        "no_multifidelity_feedback": "No multi-fid.",
        "no_active_pareto_selection": "No active sel.",
        "kernel_level_only": "Kernel-only",
        "uncalibrated_surrogate": "Uncal. surrogate",
    }
    return labels.get(str(ablation_id), _compact_unknown_label(ablation_id))


def _component_label(component_id: Any) -> str:
    labels = {
        "full_method": "Full method",
        "no_multifidelity_feedback": "No multi-fid.",
        "no_pareto_active_selection": "No active sel.",
        "kernel_only_search": "Kernel-only",
        "manual_heuristic": "Manual",
        "nsga2_lite": "NSGA-II",
    }
    return labels.get(str(component_id), _compact_unknown_label(component_id))


def _removed_component_label(component_id: Any) -> str:
    labels = {
        "none": "none",
        "multi_fidelity_feedback": "multi-fid.",
        "pareto_active_selection": "active sel.",
        "active_pareto_selection": "active sel.",
        "workflow_abstraction": "workflow",
        "workflow_level_mapping_and_scheduling": "workflow",
        "learned_or_pareto_search": "search",
        "workflow_risk_active_selection": "risk-active",
        "trained_surrogate_calibration": "surrogate",
    }
    return labels.get(str(component_id), _compact_unknown_label(component_id))


def _feature_group_label(feature_group: Any) -> str:
    labels = {
        "data_object_lifetime": "lifetime",
        "host_control_event_counts": "host",
        "correctness_observables": "gate",
        "stage_repetition": "repeat",
    }
    return labels.get(str(feature_group), _compact_unknown_label(feature_group))


def _table_workloads(summary: Mapping[str, Any]) -> str:
    rows = []
    workloads = summary.get("paper_table_rows", {}).get("workloads", []) if isinstance(summary.get("paper_table_rows"), Mapping) else []
    for index, row in enumerate(workloads[:6], start=1):
        if not isinstance(row, Mapping):
            continue
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(f"W{index}"),
                _tex_escape(_material_label(row.get("material", ""))),
                _tex_escape(_size_label(row.get("size_class", ""))),
                _tex_escape(_workflow_class_label(row.get("workflow_classes", []) or [])),
                str(int(row.get("stage_count", 0))),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- \\")
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Fixture QE workflow corpus used by the replayable generic-sim feedback experiment.}",
        r"  \label{tab:generated-workloads}",
        r"  \small",
        r"  \begin{tabular}{@{}llllr@{}}",
        r"    \toprule",
        r"    Workload & Material & Size & Classes & Stages \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"\end{table}",
    ])


def _table_search_quality(summary: Mapping[str, Any]) -> str:
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    curves = [row for row in paper_rows.get("baseline_budget_curves", []) or [] if isinstance(row, Mapping)]
    policy_validation = {
        str(row.get("policy_id", "")): row
        for row in paper_rows.get("policy_validation", []) or []
        if isinstance(row, Mapping)
    }
    rows = []
    for row in curves[:8]:
        policy_id = str(row.get("policy_id", ""))
        feedback = policy_validation.get(policy_id, {})
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_policy_label(policy_id)),
                str(int(row.get("final_budget", 0))),
                _fmt_float(row.get("final_best_edp")),
                _fmt_rank(row.get("final_oracle_rank")),
                str(int(feedback.get("feedback_overlap_count", 0))) if feedback else "0",
                _fmt_rank(feedback.get("feedback_rank_of_best") if feedback else None),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- \\")
    fidelity = _tex_escape(summary.get("search_quality", {}).get("baseline_oracle_fidelity", ""))
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Search-quality table generated from the replayable fixture experiment. Lower EDP is better; GS columns report generic-sim overlap and rank.}",
        r"  \label{tab:generated-search-quality}",
        r"  \small",
        r"  \begin{tabular}{@{}lrrrrr@{}}",
        r"    \toprule",
        r"    Policy & Bgt. & EDP & L2 & GS ov. & GS \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        rf"  \par\smallskip\noindent\footnotesize Oracle fidelity: {fidelity}; fixture corpus; generic\_sim timing projection; no HLS/Vivado/bitstream.",
        r"\end{table}",
    ])


def _multi_workload_search_quality(summary: Mapping[str, Any]) -> Dict[str, Any]:
    direct = summary.get("multi_workload_search_quality")
    if isinstance(direct, Mapping):
        return dict(direct)
    experiment = summary.get("multi_workload_experiment")
    if not isinstance(experiment, Mapping):
        return {}
    aggregate = experiment.get("aggregate")
    if not isinstance(aggregate, Mapping):
        return {}
    quality = aggregate.get("search_quality_summary")
    return dict(quality) if isinstance(quality, Mapping) else {}


def _table_multi_workload_search_quality(summary: Mapping[str, Any]) -> str:
    quality = _multi_workload_search_quality(summary)
    rows_src = [row for row in quality.get("policy_rows", []) or [] if isinstance(row, Mapping)]
    rows = []
    for row in rows_src[:8]:
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_policy_label(row.get("policy_id", ""))),
                str(int(row.get("workload_count", quality.get("workload_count", 0)) or 0)),
                str(int(row.get("selection_count_mean", quality.get("budget", 0)) or 0)),
                _fmt_float(row.get("final_simple_regret_mean")),
                _fmt_float(row.get("final_simple_regret_std")),
                _fmt_float(row.get("final_oracle_rank_mean")),
                _fmt_ratio(row.get("top_k_hit_rate")),
                _fmt_float(row.get("evaluations_to_top_5_hit_mean")),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- & -- & -- \\")
    protocol = _tex_escape(quality.get("evaluation_protocol", ""))
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Multi-workload search quality for the WAMF-DSE method and baselines. Lower regret and rank are better; Top-k reports final-budget recovery rate across workloads.}",
        r"  \label{tab:generated-multi-workload-search-quality}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{2.5pt}",
        r"  \begin{tabular}{@{}lrrrrrrr@{}}",
        r"    \toprule",
        r"    Policy & W & B & Reg. & Std & Rnk & Top-k & E@5 \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        rf"  \par\smallskip\noindent\footnotesize Protocol: {protocol}; model oracle; not measured QE, HLS, Vivado, bitstream, or board result.",
        r"\end{table}",
    ])


def _table_neuromf_policy_evaluation(summary: Mapping[str, Any]) -> str:
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    policies = [row for row in paper_rows.get("neuromf_policy_evaluation", []) or [] if isinstance(row, Mapping)]
    neuromf_summary = summary.get("neuromf_policy_evaluation", {}) if isinstance(summary.get("neuromf_policy_evaluation"), Mapping) else {}
    rows = []
    for row in policies[:8]:
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_policy_label(row.get("policy_id", ""))),
                str(int(row.get("final_budget", 0))),
                _fmt_float(row.get("final_best_edp")),
                _fmt_rank(row.get("final_oracle_rank")),
                "Y" if row.get("closed_loop_feedback") is True else "N",
                str(int(row.get("feedback_observation_count", 0) or 0)),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- \\")
    return "\n".join([
        r"\begin{table}",
        r"  \caption{WAMF-DSE policy component evaluation over the replayable candidate pool. Lower EDP is better; WAMF-kernel is the domain-neutral constrained active-Pareto acquisition policy.}",
        r"  \label{tab:generated-neuromf-policy-evaluation}",
        r"  \small",
        r"  \begin{tabular}{@{}lrrrrr@{}}",
        r"    \toprule",
        r"    Policy & Bgt. & EDP & L2 & CL & FB \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        rf"  \par\smallskip\noindent\footnotesize Policy count: {int(neuromf_summary.get('policy_count', 0))}; CL marks closed-loop active feedback; FB is the closed-loop WAMF feedback count; artifact: qe\_fpga\_neuromf\_policy\_evaluation\_report.json; WAMF-kernel is model-oracle policy evidence, not final hardware evidence.",
        r"\end{table}",
    ])


def _table_independent_algorithm_benchmark(summary: Mapping[str, Any]) -> str:
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    benchmark_rows = [
        row for row in paper_rows.get("independent_algorithm_benchmark", []) or []
        if isinstance(row, Mapping)
    ]
    benchmark = (
        summary.get("independent_algorithm_benchmark", {})
        if isinstance(summary.get("independent_algorithm_benchmark"), Mapping)
        else {}
    )
    rows = []
    for row in benchmark_rows[:8]:
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_policy_label(row.get("policy_id", ""))),
                str(int(row.get("final_budget", 0))),
                _fmt_float(row.get("final_simple_regret")),
                _fmt_rank(row.get("final_oracle_rank")),
                _fmt_ratio(row.get("final_hypervolume_ratio")),
                _fmt_ratio(row.get("final_feasibility_weighted_hv_ratio")),
                _fmt_ratio(row.get("final_cost_normalized_hv_gain")),
                _fmt_ratio(row.get("final_pareto_coverage")),
                "Y" if row.get("top_k_hit") is True else "N",
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- & -- & -- & -- \\")
    scenario = _tex_escape(benchmark.get("scenario_id", ""))
    oracle = _tex_escape(benchmark.get("oracle_kind", "independent_synthetic_workflow_mismatch"))
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Independent algorithm benchmark under synthetic workflow/model mismatch. Lower regret is better.}",
        r"  \label{tab:generated-independent-benchmark}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{2.5pt}",
        r"  \begin{tabular}{@{}lrrrrrrrc@{}}",
        r"    \toprule",
        r"    Policy & Bgt. & Regret & Rank & HV & FHV & C-HV & Pcov & Top-k \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        rf"  \par\smallskip\noindent\footnotesize Scenario: {scenario}; oracle: {oracle}; independent synthetic oracle; not HLS/Vivado/bitstream or QE measurement.",
        r"\end{table}",
    ])


def _table_independent_algorithm_benchmark_suite(summary: Mapping[str, Any]) -> str:
    suite = (
        summary.get("independent_algorithm_benchmark_suite", {})
        if isinstance(summary.get("independent_algorithm_benchmark_suite"), Mapping)
        else {}
    )
    stats = [
        row for row in suite.get("policy_statistics", []) or []
        if isinstance(row, Mapping)
    ]
    rows = []
    for row in stats[:8]:
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_policy_label(row.get("policy_id", ""))),
                str(int(row.get("scenario_count", 0))),
                str(int(row.get("final_budget", suite.get("final_budget", 0) or 0))),
                _fmt_float(row.get("mean_simple_regret")),
                _fmt_float(row.get("std_simple_regret")),
                _fmt_ratio(row.get("mean_hypervolume_ratio")),
                _fmt_ratio(row.get("top_k_hit_rate")),
                _fmt_ratio(row.get("win_rate_by_simple_regret")),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- & -- & -- \\")
    best = suite.get("best_policy_by_mean_regret", {}) if isinstance(suite.get("best_policy_by_mean_regret"), Mapping) else {}
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Multi-scenario algorithm robustness benchmark under synthetic workflow/model mismatch. Lower regret is better.}",
        r"  \label{tab:generated-independent-benchmark-suite}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{2.5pt}",
        r"  \begin{tabular}{@{}lrrrrrrr@{}}",
        r"    \toprule",
        r"    Policy & Scen. & Bgt. & Regret & Std & HV & Top-k & Win \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        rf"  \par\smallskip\noindent\footnotesize Scenarios: {int(suite.get('scenario_count', 0))}; best mean-regret policy: {_tex_escape(best.get('policy_id', ''))}; synthetic oracle only, not HLS/Vivado/bitstream or QE measurement.",
        r"\end{table}",
    ])


def _table_wamf_dse(summary: Mapping[str, Any]) -> str:
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    rows_src = [row for row in paper_rows.get("wamf_dse", []) or [] if isinstance(row, Mapping)]
    wamf = summary.get("wamf_dse", {}) if isinstance(summary.get("wamf_dse"), Mapping) else {}
    rows = []
    for row in rows_src[:6]:
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(row.get("label", _policy_label(row.get("policy_id", "")))),
                str(int(row.get("final_budget", 0))),
                _fmt_float(row.get("final_best_edp")),
                _fmt_rank(row.get("final_oracle_rank")),
                str(int(row.get("selected_candidate_count", 0))),
                _tex_escape(row.get("method_name", "")),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- \\")
    return "\n".join([
        r"\begin{table}",
        r"  \caption{WAMF-DSE unified method summary for the replayable QE-to-FPGA search prototype. Lower EDP is better; the unified method centers on a domain-neutral constrained active-Pareto acquisition kernel with workflow-aware priors and surrogate feedback.}",
        r"  \label{tab:generated-wamf-dse}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{2.5pt}",
        r"  \begin{tabular}{@{}lrrrrl@{}}",
        r"    \toprule",
        r"    Variant & Bgt. & EDP & L2 & Sel. & Method \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        rf"  \par\smallskip\noindent\footnotesize Frontier count: {int(wamf.get('selected_final_candidates', {}).get('candidate_count', 0) if isinstance(wamf.get('selected_final_candidates'), Mapping) else 0)}; surrogate backend: {_tex_escape(wamf.get('model_stack', {}).get('surrogate', {}).get('backend', '') if isinstance(wamf.get('model_stack'), Mapping) and isinstance(wamf.get('model_stack', {}).get('surrogate'), Mapping) else '')}; hardware generation path is downstream validation only.",
        r"\end{table}",
    ])


def _algorithm_validation_report(summary: Mapping[str, Any]) -> Dict[str, Any]:
    explicit = (
        summary.get("algorithm_validation", {})
        if isinstance(summary.get("algorithm_validation"), Mapping)
        else {}
    )
    if explicit.get("schema_version") == "dse.multifidelity_algorithm_validation.v1":
        return dict(explicit)
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    policy_rows = [
        row for row in paper_rows.get("baseline_budget_curves", []) or []
        if isinstance(row, Mapping)
    ]
    wamf_rows = [
        row for row in paper_rows.get("wamf_dse", []) or []
        if isinstance(row, Mapping)
    ]
    by_policy: Dict[str, Dict[str, Any]] = {
        str(row.get("policy_id", "")): dict(row)
        for row in policy_rows
        if str(row.get("policy_id", ""))
    }
    for row in wamf_rows:
        policy_id = str(row.get("policy_id", ""))
        if policy_id and policy_id != "selected_final_candidates":
            by_policy.setdefault(policy_id, dict(row))
    return build_multifidelity_algorithm_validation_report(
        proposed_policy_id="wamf_generic_active_pareto",
        policy_results=list(by_policy.values()),
        independent_feedback=(
            summary.get("l3_validation_metrics", {})
            if isinstance(summary.get("l3_validation_metrics"), Mapping)
            else {}
        ),
    )


def _table_algorithm_validation(summary: Mapping[str, Any]) -> str:
    report = _algorithm_validation_report(summary)
    blockers = [str(item) for item in report.get("blockers", []) or []]
    rows = [
        ("Status", _tex_escape(report.get("status", ""))),
        ("Proposed", _tex_escape(_policy_label(report.get("proposed_policy_id", "")))),
        (
            "Best EDP policy",
            _tex_escape(_policy_label(
                report.get("best_policy_by_edp", {}).get("policy_id", "")
                if isinstance(report.get("best_policy_by_edp"), Mapping)
                else ""
            )),
        ),
        (
            "Best rank policy",
            _tex_escape(_policy_label(
                report.get("best_policy_by_rank", {}).get("policy_id", "")
                if isinstance(report.get("best_policy_by_rank"), Mapping)
                else ""
            )),
        ),
        (
            "Rank corr.",
            _fmt_float(
                report.get("independent_feedback", {}).get("rank_correlation")
                if isinstance(report.get("independent_feedback"), Mapping)
                else None
            ),
        ),
        ("Blocker count", str(len(blockers))),
        ("Next", _tex_escape(_compact_unknown_label(report.get("recommended_next_action", "")))),
    ]
    tex_rows = [
        "    " + " & ".join([_tex_escape(label), value]) + r" \\"
        for label, value in rows
    ]
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Algorithm quality gate for the replayable model-level experiment.}",
        r"  \label{tab:generated-algorithm-validation}",
        r"  \small",
        r"  \begin{tabular}{@{}ll@{}}",
        r"    \toprule",
        r"    Item & Value \\",
        r"    \midrule",
        *tex_rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"  \par\smallskip\noindent\footnotesize This gate reports method-validation status only. A failed gate requires model recalibration or exploration fallback before presenting WAMF-DSE as superior.",
        r"\end{table}",
    ])


def _table_search_control(summary: Mapping[str, Any]) -> str:
    control = (
        summary.get("search_control", {})
        if isinstance(summary.get("search_control"), Mapping)
        else {}
    )
    selected = control.get("selected_candidate_ids", [])
    selected_count = len(selected) if isinstance(selected, list) else 0
    rows = [
        ("Mode", _tex_escape(control.get("mode", ""))),
        ("Reason", _tex_escape(control.get("control_reason", ""))),
        ("Selected", str(selected_count)),
        ("Next", _tex_escape(_compact_unknown_label(control.get("recommended_next_action", "")))),
    ]
    tex_rows = [
        "    " + " & ".join([_tex_escape(label), value]) + r" \\"
        for label, value in rows
    ]
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Search-control decision for the next multi-fidelity iteration.}",
        r"  \label{tab:generated-search-control}",
        r"  \small",
        r"  \begin{tabular}{@{}ll@{}}",
        r"    \toprule",
        r"    Item & Value \\",
        r"    \midrule",
        *tex_rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"  \par\smallskip\noindent\footnotesize Search control changes the next sampling mode after method-validation failure; it is not hardware evidence.",
        r"\end{table}",
    ])


def _table_next_evaluation_actions(summary: Mapping[str, Any]) -> str:
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    actions = [row for row in paper_rows.get("next_evaluation_actions", []) or [] if isinstance(row, Mapping)]
    rows = []
    for index, row in enumerate(actions[:6], start=1):
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_candidate_display_label(row.get("candidate_id", ""), index)),
                _tex_escape(str(row.get("fidelity", "")).replace("_", "-")),
                _fmt_float(row.get("action_cost")),
                _fmt_float(row.get("action_score")),
                _fmt_float(row.get("constrained_pareto_gain")),
                _fmt_float(row.get("workflow_risk_coverage")),
                _fmt_float(row.get("fidelity_information_gain")),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- & -- \\")
    return "\n".join([
        r"\begin{table}",
        r"  \caption{WAMF-DSE next candidate--fidelity actions.}",
        r"  \label{tab:generated-next-actions}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{2.5pt}",
        r"  \begin{tabular}{@{}llrrrrr@{}}",
        r"    \toprule",
        r"    Cand & Fidelity & Cost & Score & P-gain & Risk & IG \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"  \par\smallskip\noindent\footnotesize These rows are the algorithm decision queue; they request feedback and are not an evidence-closure matrix.",
        r"\end{table}",
    ])


def _table_corpus_readiness(summary: Mapping[str, Any]) -> str:
    corpus = summary.get("workload_corpus", {}) if isinstance(summary.get("workload_corpus"), Mapping) else {}
    readiness = (
        corpus.get("measured_qe_corpus_readiness", {})
        if isinstance(corpus.get("measured_qe_corpus_readiness"), Mapping)
        else {}
    )
    status = str(readiness.get("status", "unknown") or "unknown")
    workload_count = int(readiness.get("workload_count", corpus.get("workload_count", 0)) or 0)
    measured_ready_count = int(
        readiness.get(
            "measured_ready_workload_count",
            corpus.get("measured_qe_ready_workload_count", 0),
        )
        or 0
    )
    rows = [
        ("Corpus readiness", _tex_escape(status)),
        ("Measured-ready workloads", _tex_escape(f"{measured_ready_count}/{workload_count}")),
    ]
    tex_rows = ["    " + " & ".join([_tex_escape(label), value]) + r" \\" for label, value in rows]
    return "\n".join([
        r"\begin{table}",
        r"  \caption{QE workload-corpus readiness gate for interpreting generated fixture tables.}",
        r"  \label{tab:generated-corpus-readiness}",
        r"  \small",
        r"  \begin{tabular}{@{}ll@{}}",
        r"    \toprule",
        r"    Item & Status \\",
        r"    \midrule",
        *tex_rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"  \par\smallskip\noindent\footnotesize QE corpus readiness is an input-quality gate only; it does not provide hardware performance or QE correctness evidence.",
        r"\end{table}",
    ])


def _table_ablations(summary: Mapping[str, Any]) -> str:
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    ablations = [row for row in paper_rows.get("feature_ablations", []) or [] if isinstance(row, Mapping)]
    rows = []
    for row in ablations[:8]:
        removed = row.get("removed_feature_groups", []) or []
        removed_labels = [_feature_group_label(group) for group in removed]
        comparison = row.get("comparison_to_full", {}) if isinstance(row.get("comparison_to_full"), Mapping) else {}
        changed = "Y" if comparison.get("decision_changed") else "N"
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_ablation_label(row.get("ablation_id", ""))),
                _tex_escape(_list_text(removed_labels, limit=2, separator=",") if removed_labels else "none"),
                _fmt_float(row.get("best_tlm_edp")),
                _fmt_rank(row.get("oracle_rank_of_best")),
                _fmt_delta(comparison.get("rank_delta_vs_full")),
                _fmt_ratio(comparison.get("best_edp_ratio_vs_full")),
                changed,
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- & -- \\")
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Feature-ablation rows extracted from the same candidate pool and L2 model oracle.}",
        r"  \label{tab:generated-ablations}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{2.5pt}",
        r"  \begin{tabular}{@{}llrrrrc@{}}",
        r"    \toprule",
        r"    Var. & Removed & EDP & L2 & $\Delta$ & Ratio & Chg. \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"\end{table}",
    ])


def _table_method_ablations(summary: Mapping[str, Any]) -> str:
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    ablations = [row for row in paper_rows.get("method_component_ablations", []) or [] if isinstance(row, Mapping)]
    rows = []
    for row in ablations[:6]:
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_component_label(row.get("component_id", ""))),
                _tex_escape(_policy_label(row.get("policy_id", ""))),
                _tex_escape(_removed_component_label(row.get("removed_component", ""))),
                _fmt_float(row.get("final_best_edp")),
                _fmt_rank(row.get("final_oracle_rank")),
                _fmt_ratio(row.get("edp_ratio_vs_full")),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- \\")
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Method-component ablations derived from the same final-budget policy rows. Lower EDP is better.}",
        r"  \label{tab:generated-method-ablations}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{2.5pt}",
        r"  \begin{tabular}{@{}lllrrr@{}}",
        r"    \toprule",
        r"    Comp. & Policy & Removed & EDP & L2 & Ratio \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"\end{table}",
    ])


def _table_wamf_required_ablations(summary: Mapping[str, Any]) -> str:
    paper_rows = summary.get("paper_table_rows", {}) if isinstance(summary.get("paper_table_rows"), Mapping) else {}
    ablations = [row for row in paper_rows.get("wamf_required_ablations", []) or [] if isinstance(row, Mapping)]
    rows = []
    for row in ablations[:6]:
        rows.append(
            "    "
            + " & ".join([
                _tex_escape(_ablation_label(row.get("ablation_id", ""))),
                _tex_escape(_removed_component_label(row.get("removed_component", ""))),
                _tex_escape(_policy_label(row.get("maps_to", ""))),
                _fmt_rank(row.get("final_budget")),
                _fmt_float(row.get("final_best_edp")),
                _fmt_rank(row.get("final_oracle_rank")),
                _fmt_ratio(row.get("edp_ratio_vs_method")),
                _fmt_rank(row.get("rank_delta_vs_method")),
            ])
            + r" \\"
        )
    if not rows:
        rows.append(r"    -- & -- & -- & -- & -- & -- & -- & -- \\")
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Required WAMF-DSE ablations exposed by the formal method contract. Rows use the same candidate pool and budget as WAMF-kernel when the summary contract records them; E/W is the EDP ratio versus WAMF-kernel.}",
        r"  \label{tab:generated-wamf-required-ablations}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{2.5pt}",
        r"  \begin{tabular}{@{}lllrrrrr@{}}",
        r"    \toprule",
        r"    Abl. & Rem. & Pol. & B & EDP & L2 & E/W & $\Delta$L2 \\",
        r"    \midrule",
        *rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"\end{table}",
    ])


def _table_l3_validation(summary: Mapping[str, Any]) -> str:
    metrics = summary.get("l3_validation_metrics", {}) if isinstance(summary.get("l3_validation_metrics"), Mapping) else {}
    rank = metrics.get("rank_correlation", {}) if isinstance(metrics.get("rank_correlation"), Mapping) else {}
    top_k = metrics.get("top_k_overlap", {}) if isinstance(metrics.get("top_k_overlap"), Mapping) else {}
    promotion = metrics.get("promotion_quality", {}) if isinstance(metrics.get("promotion_quality"), Mapping) else {}
    k = int(top_k.get("k", promotion.get("k", 0)) or 0)
    rows = [
        ("Spearman L1--GS", _fmt_float(rank.get("l1_estimated_edp_vs_l3_edp_spearman"))),
        (f"Top-{k} overlap" if k else "Top-k overlap", _fmt_rank(top_k.get("overlap_count"))),
        (f"Top-{k} Jaccard" if k else "Top-k Jaccard", _fmt_ratio(top_k.get("jaccard"))),
        (
            "Promotion P/R",
            f"{_fmt_ratio(promotion.get('precision_at_k'))}/{_fmt_ratio(promotion.get('recall_at_k'))}",
        ),
    ]
    tex_rows = [
        "    " + " & ".join([_tex_escape(label), value]) + r" \\"
        for label, value in rows
    ]
    return "\n".join([
        r"\begin{table}",
        r"  \caption{Sampled L3/generic-sim validation metrics for the promoted plus holdout candidates.}",
        r"  \label{tab:generated-l3-validation}",
        r"  \small",
        r"  \begin{tabular}{@{}lr@{}}",
        r"    \toprule",
        r"    Metric & Value \\",
        r"    \midrule",
        *tex_rows,
        r"    \bottomrule",
        r"  \end{tabular}",
        r"  \par\smallskip\noindent\footnotesize L3 validation uses sampled generic\_sim timing projection only; no HLS/Vivado/bitstream or QE correctness.",
        r"\end{table}",
    ])


def build_latex(summary: Mapping[str, Any], *, source_path: Path | None = None, source_sha256: str = "") -> str:
    provenance = [
        "% Auto-generated by build_qe_fpga_paper_results_tables.py.",
        "% Source: dse.qe_fpga_paper_ready_experiment_summary.v1.",
    ]
    if source_path is not None:
        provenance.append(f"% Source file: {source_path}")
    if source_sha256:
        provenance.append(f"% Source sha256: {source_sha256}")
    return "\n\n".join([
        "\n".join(provenance),
        _table_workloads(summary),
        _table_corpus_readiness(summary),
        _table_wamf_dse(summary),
        _table_next_evaluation_actions(summary),
        _table_algorithm_validation(summary),
        _table_search_control(summary),
        _table_search_quality(summary),
        _table_multi_workload_search_quality(summary),
        _table_neuromf_policy_evaluation(summary),
        _table_independent_algorithm_benchmark(summary),
        _table_independent_algorithm_benchmark_suite(summary),
        _table_l3_validation(summary),
        _table_ablations(summary),
        _table_method_ablations(summary),
        _table_wamf_required_ablations(summary),
        "",
    ])


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    summary = _load_json_object(args.summary)
    if summary.get("schema_version") != "dse.qe_fpga_paper_ready_experiment_summary.v1":
        raise ValueError("unexpected paper-ready experiment summary schema")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        build_latex(summary, source_path=args.summary, source_sha256=_file_sha256(args.summary)),
        encoding="utf-8",
    )
    print(json.dumps({"status": "written", "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
