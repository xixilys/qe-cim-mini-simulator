#!/usr/bin/env python3
"""
QE Architecture Family Comprehensive Evaluator v1

扩展版架构评估器，支持15+架构变体，多保真度评估。

Usage:
    python3 qe_architecture_family_comprehensive_evaluator.py \
        --design-space docs/architecture/architecture_comparison/architecture_design_space_v1.json \
        --workload qe_dft \
        --fidelity L0 \
        --output-dir tmp/comprehensive_architecture_evaluation
"""

import json
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional
import math


@dataclass
class WorkloadProfile:
    gemm_ratio: float
    operator_sweep_ratio: float
    reduced_build_ratio: float
    diag_ratio: float
    refresh_ratio: float
    algorithm_stability: str
    target_design_time_months: int
    precision_requirement: str
    memory_footprint_mb: float
    bandwidth_requirement_gbps: float


@dataclass
class ArchitectureVariant:
    variant_id: str
    family_id: str
    name: str
    parameters: Dict
    performance_model: Dict


@dataclass
class EvaluationResult:
    variant_id: str
    family_id: str
    architecture: str
    performance_score: float
    utilization_score: float
    energy_score: float
    flexibility_score: float
    complexity_score: float
    weighted_total: float
    is_pareto: bool
    rationale: str
    fidelity: str


def load_design_space(design_space_path: Path) -> Dict:
    with open(design_space_path) as f:
        return json.load(f)


def get_workload_profile(workload_id: str, design_space: Dict) -> WorkloadProfile:
    workload = design_space["workload_characteristics"][workload_id]
    return WorkloadProfile(
        gemm_ratio=workload["gemm_ratio"],
        operator_sweep_ratio=workload["operator_sweep"],
        reduced_build_ratio=workload["reduced_build"],
        diag_ratio=workload["diagonalization"],
        refresh_ratio=workload["refresh_residual"],
        algorithm_stability=workload["algorithm_stability"],
        target_design_time_months=workload["target_design_time_months"],
        precision_requirement=workload["precision_requirement"],
        memory_footprint_mb=workload["memory_footprint_mb"],
        bandwidth_requirement_gbps=workload["bandwidth_requirement_gbps"]
    )


def extract_variants(design_space: Dict) -> List[ArchitectureVariant]:
    variants = []
    for family_id, family_data in design_space["architecture_families"].items():
        for variant_id, variant_data in family_data["variants"].items():
            variants.append(ArchitectureVariant(
                variant_id=variant_data["variant_id"],
                family_id=family_id,
                name=variant_data["name"],
                parameters=variant_data["parameters"],
                performance_model=variant_data.get("performance_model", {})
            ))
    return variants


def calculate_performance_score(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    family = variant.family_id
    params = variant.parameters
    
    if family == "pipeline":
        return calculate_pipeline_performance(variant, workload)
    elif family == "systolic":
        return calculate_systolic_performance(variant, workload)
    elif family == "dataflow":
        return calculate_dataflow_performance(variant, workload)
    elif family == "tile":
        return calculate_tile_performance(variant, workload)
    elif family == "reconfigurable":
        return calculate_reconfigurable_performance(variant, workload)
    elif family == "hybrid":
        return calculate_hybrid_performance(variant, workload)
    elif family == "near_memory":
        return calculate_near_memory_performance(variant, workload)
    else:
        return 50.0


def calculate_pipeline_performance(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    params = variant.parameters
    n_clusters = params.get("n_clusters", 4)
    
    workload_shares = [0.68, 0.04, 0.23, 0.05]
    max_share = max(workload_shares)
    avg_share = sum(workload_shares) / len(workload_shares)
    
    imbalance_penalty = 1.0 - (max_share - avg_share)
    base_score = 60.0 * imbalance_penalty
    
    if "fusion_benefit" in params:
        base_score *= 1.2
    
    if params.get("adaptive_load_balancing", False):
        base_score *= 1.15
    
    return min(base_score, 100)


def calculate_systolic_performance(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    params = variant.parameters
    
    if "array_dimensions" in params:
        dims = params["array_dimensions"]
        total_pes = dims[0] * dims[1]
    elif "arrays" in params:
        total_pes = sum(a.get("dimensions", [1, 1])[0] * a.get("dimensions", [1, 1])[1] 
                       for a in params["arrays"])
    else:
        total_pes = 1024
    
    peak_flops = total_pes * 2  # 2 FLOPs per PE per cycle (MAC)
    
    gemm_ai = 20.0
    peak_bw = params.get("interconnect", {}).get("bandwidth_gbps", 256)
    ridge_point = peak_flops / peak_bw
    
    if gemm_ai > ridge_point:
        achievable_flops = peak_flops
    else:
        achievable_flops = gemm_ai * peak_bw
    
    max_flops = 32768  # 256x256 array
    score = (achievable_flops / max_flops) * 100
    
    if workload.gemm_ratio > 0.8:
        score *= 1.1
    
    return min(score, 100)


def calculate_dataflow_performance(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    params = variant.parameters
    
    pe_count = params.get("pe_count", 64)
    if "pe_counts" in params:
        pe_count = sum(params["pe_counts"].values())
    
    peak_flops = pe_count * 2
    max_flops = 512
    score = (peak_flops / max_flops) * 100
    
    if params.get("reconfiguration_granularity") == "cycle":
        score *= 0.9  # Reconfiguration overhead
    
    return min(score, 100)


def calculate_tile_performance(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    params = variant.parameters
    
    if "n_tiles" in params:
        n_tiles = params["n_tiles"]
        pe_per_tile = 1024  # 32x32
        total_pes = n_tiles * pe_per_tile
    elif "tiles" in params:
        total_pes = 0
        for tile in params["tiles"]:
            if "systolic" in tile.get("compute", ""):
                total_pes += 4096 * tile["count"]
            else:
                total_pes += 256 * tile["count"]
    else:
        total_pes = 4096
    
    peak_flops = total_pes * 2
    max_flops = 32768
    score = (peak_flops / max_flops) * 100
    
    if "chiplet_technology" in params:
        score *= 0.95  # Chiplet overhead
    
    return min(score, 100)


def calculate_reconfigurable_performance(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    params = variant.parameters
    
    if "fu_count" in params:
        fu_count = params["fu_count"]
    elif "lut_count" in params:
        fu_count = params["lut_count"] / 1000  # Approximate
    else:
        fu_count = 128
    
    peak_flops = fu_count * 2
    max_flops = 512
    score = (peak_flops / max_flops) * 100
    
    if "reconfiguration_time_cycles" in params:
        if params["reconfiguration_time_cycles"] > 1:
            score *= 0.9
    
    return min(score, 100)


def calculate_hybrid_performance(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    params = variant.parameters
    
    if "accelerator" in params:
        accel = params["accelerator"]
        if "dimensions" in accel:
            pe_count = accel["dimensions"][0] * accel["dimensions"][1]
        else:
            pe_count = 4096
    elif "chips" in params:
        pe_count = 16384  # Multi-chip
    else:
        pe_count = 4096
    
    peak_flops = pe_count * 2
    max_flops = 32768
    score = (peak_flops / max_flops) * 100
    
    if params.get("coupling") == "tight":
        score *= 1.05
    
    return min(score, 100)


def calculate_near_memory_performance(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    params = variant.parameters
    
    bandwidth_advantage = params.get("bandwidth_advantage", 10)
    base_score = 50.0 + bandwidth_advantage * 2
    
    if "precision" in params and params["precision"] == "approximate":
        base_score *= 0.8
    
    if workload.precision_requirement == "FP64":
        base_score *= 0.7  # Near-memory struggles with FP64
    
    return min(base_score, 100)


def calculate_utilization_score(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    family = variant.family_id
    params = variant.parameters
    
    utilization_map = {
        "pipeline": 0.35,
        "systolic": 0.75,
        "dataflow": 0.65,
        "tile": 0.70,
        "reconfigurable": 0.60,
        "hybrid": 0.72,
        "near_memory": 0.55
    }
    
    base_util = utilization_map.get(family, 0.5)
    
    if family == "pipeline":
        workload_shares = [0.68, 0.04, 0.23, 0.05]
        max_share = max(workload_shares)
        avg_share = sum(workload_shares) / len(workload_shares)
        base_util = avg_share / max_share if max_share > 0 else 0
        
        if params.get("adaptive_load_balancing", False):
            base_util *= 1.3
    
    elif family == "systolic":
        if workload.gemm_ratio > 0.8:
            base_util = 0.80
        else:
            base_util = 0.60
    
    return min(base_util * 100, 100)


def calculate_energy_score(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    family = variant.family_id
    params = variant.parameters
    
    perf = calculate_performance_score(variant, workload)
    
    power_map = {
        "pipeline": 50,
        "systolic": 60,
        "dataflow": 70,
        "tile": 55,
        "reconfigurable": 65,
        "hybrid": 75,
        "near_memory": 40
    }
    
    power = power_map.get(family, 60)
    
    if "power_w" in params:
        power = params["power_w"]
    
    power_efficiency = perf / power if power > 0 else 0
    max_efficiency = 100 / 40.0
    score = (power_efficiency / max_efficiency) * 100
    
    if family == "near_memory":
        score *= 1.3  # Bandwidth advantage
    
    if family == "systolic" and params.get("memory_hierarchy", {}).get("l2_scratchpad_kb", 0) > 1024:
        score *= 1.1
    
    return min(score, 100)


def calculate_flexibility_score(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    family = variant.family_id
    params = variant.parameters
    
    flexibility_map = {
        "pipeline": 40,
        "systolic": 55,
        "dataflow": 85,
        "tile": 70,
        "reconfigurable": 90,
        "hybrid": 65,
        "near_memory": 50
    }
    
    base_score = flexibility_map.get(family, 50)
    
    if workload.algorithm_stability == "evolving":
        if family in ["dataflow", "reconfigurable"]:
            base_score += 10
        elif family == "pipeline":
            base_score -= 15
    
    if params.get("reconfiguration_granularity") == "cycle":
        base_score += 5
    
    return min(max(base_score, 0), 100)


def calculate_complexity_score(variant: ArchitectureVariant, workload: WorkloadProfile) -> float:
    family = variant.family_id
    params = variant.parameters
    
    complexity_map = {
        "pipeline": 80,
        "systolic": 70,
        "dataflow": 45,
        "tile": 65,
        "reconfigurable": 40,
        "hybrid": 55,
        "near_memory": 60
    }
    
    base_score = complexity_map.get(family, 50)
    
    if workload.target_design_time_months <= 6:
        if family in ["dataflow", "reconfigurable"]:
            base_score -= 30
        elif family == "hybrid":
            base_score -= 15
        elif family == "near_memory":
            base_score -= 10
        elif family == "systolic":
            base_score -= 5
    
    if "chiplet_technology" in params:
        base_score -= 10
    
    return min(max(base_score, 0), 100)


def calculate_weighted_total(result: EvaluationResult, workload: WorkloadProfile) -> float:
    if workload.target_design_time_months <= 6:
        weights = {
            'performance': 0.25,
            'utilization': 0.20,
            'energy': 0.15,
            'flexibility': 0.20,
            'complexity': 0.20
        }
    else:
        weights = {
            'performance': 0.30,
            'utilization': 0.25,
            'energy': 0.20,
            'flexibility': 0.15,
            'complexity': 0.10
        }
    
    return (result.performance_score * weights['performance'] +
            result.utilization_score * weights['utilization'] +
            result.energy_score * weights['energy'] +
            result.flexibility_score * weights['flexibility'] +
            result.complexity_score * weights['complexity'])


def identify_pareto_frontier(results: List[EvaluationResult]) -> List[EvaluationResult]:
    pareto = []
    
    for i, result_i in enumerate(results):
        is_dominated = False
        for j, result_j in enumerate(results):
            if i == j:
                continue
            
            if (result_j.performance_score >= result_i.performance_score and
                result_j.utilization_score >= result_i.utilization_score and
                result_j.energy_score >= result_i.energy_score and
                result_j.flexibility_score >= result_i.flexibility_score and
                result_j.complexity_score >= result_i.complexity_score and
                (result_j.performance_score > result_i.performance_score or
                 result_j.utilization_score > result_i.utilization_score or
                 result_j.energy_score > result_i.energy_score or
                 result_j.flexibility_score > result_i.flexibility_score or
                 result_j.complexity_score > result_i.complexity_score)):
                is_dominated = True
                break
        
        if not is_dominated:
            pareto.append(result_i)
    
    return pareto


def generate_rationale(result: EvaluationResult, workload: WorkloadProfile) -> str:
    rationales = []
    
    if result.performance_score >= 80:
        rationales.append("Excellent performance")
    elif result.performance_score >= 60:
        rationales.append("Good performance")
    else:
        rationales.append("Performance limitations")
    
    if result.utilization_score >= 70:
        rationales.append("High utilization")
    elif result.utilization_score < 50:
        rationales.append("Low utilization")
    
    if result.flexibility_score >= 80:
        rationales.append("Excellent flexibility")
    
    if result.complexity_score < 50:
        rationales.append("High complexity risk")
    
    return "; ".join(rationales)


def evaluate_architectures(workload: WorkloadProfile, 
                          variants: List[ArchitectureVariant],
                          fidelity: str) -> List[EvaluationResult]:
    results = []
    
    for variant in variants:
        result = EvaluationResult(
            variant_id=variant.variant_id,
            family_id=variant.family_id,
            architecture=variant.name,
            performance_score=calculate_performance_score(variant, workload),
            utilization_score=calculate_utilization_score(variant, workload),
            energy_score=calculate_energy_score(variant, workload),
            flexibility_score=calculate_flexibility_score(variant, workload),
            complexity_score=calculate_complexity_score(variant, workload),
            weighted_total=0.0,
            is_pareto=False,
            rationale="",
            fidelity=fidelity
        )
        
        result.weighted_total = calculate_weighted_total(result, workload)
        result.rationale = generate_rationale(result, workload)
        results.append(result)
    
    pareto = identify_pareto_frontier(results)
    for result in results:
        result.is_pareto = result in pareto
    
    return results


def generate_report(results: List[EvaluationResult], 
                   workload: WorkloadProfile,
                   fidelity: str,
                   output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    
    json_output = {
        "workload_profile": asdict(workload),
        "fidelity": fidelity,
        "evaluation_results": [asdict(r) for r in results],
        "pareto_architectures": [r.architecture for r in results if r.is_pareto],
        "recommended_architecture": max(results, key=lambda x: x.weighted_total).architecture
    }
    
    with open(output_dir / "comprehensive_architecture_evaluation.json", "w") as f:
        json.dump(json_output, f, indent=2)
    
    md_lines = [
        "# Comprehensive Architecture Family Evaluation Report",
        "",
        f"**Fidelity Level**: {fidelity}",
        "",
        "## Workload Profile",
        "",
        f"- GEMM Ratio: {workload.gemm_ratio*100:.0f}%",
        f"- Operator Sweep: {workload.operator_sweep_ratio*100:.0f}%",
        f"- Reduced Build: {workload.reduced_build_ratio*100:.0f}%",
        f"- Diagonalization: {workload.diag_ratio*100:.0f}%",
        f"- Refresh/Residual: {workload.refresh_ratio*100:.0f}%",
        f"- Algorithm Stability: {workload.algorithm_stability}",
        f"- Target Design Time: {workload.target_design_time_months} months",
        f"- Precision Requirement: {workload.precision_requirement}",
        "",
        "## Evaluation Results",
        "",
        "| Architecture | Performance | Utilization | Energy | Flexibility | Complexity | **Weighted Total** | Pareto |",
        "|-------------|-------------|-------------|--------|-------------|------------|-------------------|--------|"
    ]
    
    for result in sorted(results, key=lambda x: x.weighted_total, reverse=True):
        pareto_mark = "✅" if result.is_pareto else ""
        md_lines.append(
            f"| {result.architecture} | {result.performance_score:.0f} | "
            f"{result.utilization_score:.0f} | {result.energy_score:.0f} | "
            f"{result.flexibility_score:.0f} | {result.complexity_score:.0f} | "
            f"**{result.weighted_total:.1f}** | {pareto_mark} |"
        )
    
    md_lines.extend([
        "",
        "## Pareto-Optimal Architectures",
        "",
        "The following architectures are Pareto-optimal:",
        ""
    ])
    
    for result in results:
        if result.is_pareto:
            md_lines.append(f"- **{result.architecture}** ({result.variant_id}): {result.rationale}")
    
    md_lines.extend([
        "",
        "## Top 5 Recommendations",
        "",
    ])
    
    for i, result in enumerate(sorted(results, key=lambda x: x.weighted_total, reverse=True)[:5], 1):
        md_lines.append(f"{i}. **{result.architecture}** ({result.variant_id}): Score {result.weighted_total:.1f} - {result.rationale}")
    
    md_lines.extend([
        "",
        "## Family-Level Analysis",
        ""
    ])
    
    families = {}
    for result in results:
        if result.family_id not in families:
            families[result.family_id] = []
        families[result.family_id].append(result)
    
    for family_id, family_results in families.items():
        avg_score = sum(r.weighted_total for r in family_results) / len(family_results)
        best = max(family_results, key=lambda x: x.weighted_total)
        md_lines.append(f"- **{family_id}**: Average {avg_score:.1f}, Best: {best.architecture} ({best.weighted_total:.1f})")
    
    with open(output_dir / "comprehensive_architecture_evaluation_report.md", "w") as f:
        f.write("\n".join(md_lines))
    
    print(f"Report generated in {output_dir}")
    best = max(results, key=lambda x: x.weighted_total)
    print(f"Recommended architecture: {best.architecture} ({best.variant_id})")


def main():
    parser = argparse.ArgumentParser(description="QE Architecture Family Comprehensive Evaluator")
    parser.add_argument("--design-space", type=Path,
                       default=Path("docs/architecture/architecture_comparison/architecture_design_space_v1.json"))
    parser.add_argument("--workload", type=str, default="qe_dft")
    parser.add_argument("--fidelity", type=str, default="L0", choices=["L0", "L1", "L2", "L3", "L4"])
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/comprehensive_architecture_evaluation"))
    args = parser.parse_args()
    
    design_space = load_design_space(args.design_space)
    workload = get_workload_profile(args.workload, design_space)
    variants = extract_variants(design_space)
    
    print(f"Evaluating {len(variants)} architecture variants...")
    print(f"Workload: {args.workload}")
    print(f"Fidelity: {args.fidelity}")
    print()
    
    results = evaluate_architectures(workload, variants, args.fidelity)
    generate_report(results, workload, args.fidelity, args.output_dir)
    
    print("\n" + "="*80)
    print("COMPREHENSIVE ARCHITECTURE EVALUATION SUMMARY")
    print("="*80)
    print(f"{'Rank':<6} {'Architecture':<40} {'Score':<8} {'Pareto':<8}")
    print("-"*80)
    for i, result in enumerate(sorted(results, key=lambda x: x.weighted_total, reverse=True), 1):
        pareto = "[PARETO]" if result.is_pareto else ""
        print(f"{i:<6} {result.architecture:<40} {result.weighted_total:>6.1f}   {pareto}")
    print("="*80)
    
    print(f"\nTop 3 by family:")
    families = {}
    for result in results:
        if result.family_id not in families:
            families[result.family_id] = []
        families[result.family_id].append(result)
    
    for family_id in sorted(families.keys()):
        best = max(families[family_id], key=lambda x: x.weighted_total)
        print(f"  {family_id}: {best.architecture} ({best.weighted_total:.1f})")


if __name__ == "__main__":
    main()
