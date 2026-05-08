#!/usr/bin/env python3
"""
QE Architecture Family Quick Evaluator

快速评估架构家族，不需要完整 SystemC 仿真。
基于 workload 特征和架构参数，输出定量评分和推荐。

Usage:
    python3 qe_architecture_family_quick_evaluator.py \
        --workload-characterization docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md \
        --architecture-taxonomy docs/architecture/architecture_comparison/architecture_taxonomy.md \
        --output-dir tmp/architecture_family_evaluation
"""

import json
import argparse
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple
import math


@dataclass
class WorkloadProfile:
    """Workload characterization data"""
    gemm_ratio: float  # GEMM operations percentage
    operator_sweep_ratio: float  # h_psi/s_psi percentage
    reduced_build_ratio: float  # build H_sub/S_sub percentage
    diag_ratio: float  # cdiaghg percentage
    refresh_ratio: float  # refresh/residual percentage
    algorithm_stability: str  # stable, evolving, experimental
    target_design_time_months: int


@dataclass
class ArchitectureSpec:
    """Architecture family specification"""
    name: str
    compute_units: int
    memory_hierarchy: str
    interconnect: str
    control_model: str
    peak_flops: float  # GFLOPS
    peak_bw: float  # GB/s
    area_mm2: float
    power_w: float
    flexibility_score: int  # 0-100
    complexity_score: int  # 0-100 (lower is simpler)


@dataclass
class EvaluationResult:
    """Evaluation result for one architecture"""
    architecture: str
    performance_score: float
    utilization_score: float
    energy_score: float
    flexibility_score: float
    complexity_score: float
    weighted_total: float
    is_pareto: bool
    rationale: str


def parse_workload_characterization(workload_text: str) -> WorkloadProfile:
    """Parse workload characterization from text"""
    # Simplified parsing - in real implementation, would parse actual markdown
    return WorkloadProfile(
        gemm_ratio=0.83,
        operator_sweep_ratio=0.68,
        reduced_build_ratio=0.04,
        diag_ratio=0.23,
        refresh_ratio=0.05,
        algorithm_stability="evolving",
        target_design_time_months=6
    )


def get_architecture_specs() -> List[ArchitectureSpec]:
    """Define architecture specifications"""
    return [
        ArchitectureSpec(
            name="4-Cluster Pipeline",
            compute_units=4,
            memory_hierarchy="distributed",
            interconnect="FIFO",
            control_model="distributed",
            peak_flops=512.0,
            peak_bw=200.0,
            area_mm2=100.0,
            power_w=50.0,
            flexibility_score=50,
            complexity_score=85  # high complexity due to distributed control
        ),
        ArchitectureSpec(
            name="Unified Systolic Array",
            compute_units=1,  # one big array
            memory_hierarchy="unified",
            interconnect="crossbar",
            control_model="centralized",
            peak_flops=1024.0,
            peak_bw=400.0,
            area_mm2=80.0,
            power_w=60.0,
            flexibility_score=60,
            complexity_score=70
        ),
        ArchitectureSpec(
            name="Dataflow Fabric",
            compute_units=16,
            memory_hierarchy="distributed",
            interconnect="2D_mesh",
            control_model="dataflow_tokens",
            peak_flops=768.0,
            peak_bw=300.0,
            area_mm2=120.0,
            power_w=70.0,
            flexibility_score=90,
            complexity_score=45  # very complex
        ),
        ArchitectureSpec(
            name="Heterogeneous Tiles",
            compute_units=6,
            memory_hierarchy="distributed",
            interconnect="2D_mesh",
            control_model="hybrid",
            peak_flops=896.0,
            peak_bw=350.0,
            area_mm2=90.0,
            power_w=55.0,
            flexibility_score=75,
            complexity_score=65
        ),
        ArchitectureSpec(
            name="CGRA",
            compute_units=128,
            memory_hierarchy="distributed",
            interconnect="reconfigurable",
            control_model="configuration",
            peak_flops=640.0,
            peak_bw=250.0,
            area_mm2=110.0,
            power_w=65.0,
            flexibility_score=95,
            complexity_score=35  # most complex
        )
    ]


def calculate_performance_score(arch: ArchitectureSpec, workload: WorkloadProfile) -> float:
    """
    Calculate performance score using Roofline model
    
    Score 0-100 based on:
    - Compute bound vs memory bound
    - Peak FLOPS utilization
    """
    # Arithmetic intensity for GEMM operations
    # Typical GEMM AI: 10-50 FLOPs/byte
    gemm_ai = 20.0
    
    # Ridge point
    ridge_point = arch.peak_flops / arch.peak_bw
    
    if gemm_ai > ridge_point:
        # Compute bound
        achievable_flops = arch.peak_flops
    else:
        # Memory bound
        achievable_flops = gemm_ai * arch.peak_bw
    
    # Score relative to best possible (1024 GFLOPS)
    max_flops = 1024.0
    score = (achievable_flops / max_flops) * 100
    
    # Penalty for workload mismatch
    if workload.gemm_ratio < 0.5:
        score *= 0.8  # Not GEMM-heavy, systolic/CGRA less effective
    
    return min(score, 100)


def calculate_utilization_score(arch: ArchitectureSpec, workload: WorkloadProfile) -> float:
    """
    Calculate utilization score based on workload balance
    
    Score 0-100 based on:
    - How well workload maps to architecture
    - Load balancing across compute units
    """
    if arch.name == "4-Cluster Pipeline":
        # Severe load imbalance: 68%, 4%, 23%, 5%
        # Average utilization very low
        avg_util = (workload.operator_sweep_ratio + workload.reduced_build_ratio + 
                   workload.diag_ratio + workload.refresh_ratio) / 4
        # But actual utilization is limited by longest stage
        max_stage = max(workload.operator_sweep_ratio, workload.reduced_build_ratio,
                       workload.diag_ratio, workload.refresh_ratio)
        utilization = avg_util / max_stage if max_stage > 0 else 0
        score = utilization * 100 * 0.6  # Penalty for pipeline bubbles
        
    elif arch.name == "Unified Systolic Array":
        # One big array, can dynamically partition
        # Utilization limited by GEMM ratio
        utilization = workload.gemm_ratio + (1 - workload.gemm_ratio) * 0.3
        score = utilization * 100
        
    elif arch.name == "Dataflow Fabric":
        # Dynamic PE allocation
        # Good load balancing
        utilization = 0.65  # Estimated
        score = utilization * 100
        
    elif arch.name == "Heterogeneous Tiles":
        # Tiles can be sized for workload
        # GEMM tiles handle 83%, eigen tile handles 23%
        utilization = 0.70  # Estimated
        score = utilization * 100
        
    elif arch.name == "CGRA":
        # Reconfigurable, good utilization
        utilization = 0.60  # But reconfiguration overhead
        score = utilization * 100
        
    else:
        score = 50
    
    return min(score, 100)


def calculate_energy_score(arch: ArchitectureSpec, workload: WorkloadProfile) -> float:
    """
    Calculate energy efficiency score
    
    Score 0-100 based on:
    - GFLOPS/W
    - Memory access energy
    """
    # Simple model: energy efficiency = performance / power
    perf = calculate_performance_score(arch, workload)
    power_efficiency = perf / arch.power_w if arch.power_w > 0 else 0
    
    # Normalize to best possible
    max_efficiency = 100 / 50.0  # 100 score / 50W baseline
    score = (power_efficiency / max_efficiency) * 100
    
    # Bonus for unified memory (less data movement)
    if arch.memory_hierarchy == "unified":
        score *= 1.1
    
    # Penalty for complex interconnect
    if arch.interconnect in ["2D_mesh", "reconfigurable"]:
        score *= 0.9
    
    return min(score, 100)


def calculate_flexibility_score(arch: ArchitectureSpec, workload: WorkloadProfile) -> float:
    """
    Calculate flexibility score
    
    Score 0-100 based on:
    - Algorithm support range
    - Reconfiguration capability
    """
    base_score = arch.flexibility_score
    
    # Bonus for evolving workloads
    if workload.algorithm_stability == "evolving":
        if arch.name in ["Dataflow Fabric", "CGRA"]:
            base_score += 10
        elif arch.name == "4-Cluster Pipeline":
            base_score -= 10  # Fixed topology hard to change
    
    return min(max(base_score, 0), 100)


def calculate_complexity_score(arch: ArchitectureSpec, workload: WorkloadProfile) -> float:
    base_score = arch.complexity_score
    
    if workload.target_design_time_months <= 6:
        if arch.name in ["Dataflow Fabric", "CGRA"]:
            base_score -= 30
        elif arch.name == "Unified Systolic Array":
            base_score -= 15
        elif arch.name == "Heterogeneous Tiles":
            base_score -= 5
        elif arch.name == "4-Cluster Pipeline":
            base_score += 5
    
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
    
    total = (result.performance_score * weights['performance'] +
            result.utilization_score * weights['utilization'] +
            result.energy_score * weights['energy'] +
            result.flexibility_score * weights['flexibility'] +
            result.complexity_score * weights['complexity'])
    
    return total


def identify_pareto_frontier(results: List[EvaluationResult]) -> List[EvaluationResult]:
    """Identify Pareto-optimal architectures"""
    pareto = []
    
    for i, result_i in enumerate(results):
        is_dominated = False
        for j, result_j in enumerate(results):
            if i == j:
                continue
            
            # Check if j dominates i
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
    """Generate selection rationale for an architecture"""
    rationales = []
    
    if result.performance_score >= 80:
        rationales.append("Excellent performance for GEMM-heavy workload")
    elif result.performance_score >= 60:
        rationales.append("Good performance")
    else:
        rationales.append("Performance bottleneck identified")
    
    if result.utilization_score >= 70:
        rationales.append("High utilization")
    elif result.utilization_score < 50:
        rationales.append("Low utilization due to load imbalance")
    
    if result.flexibility_score >= 80:
        rationales.append("Excellent flexibility for algorithm evolution")
    
    if result.complexity_score < 50:
        rationales.append("High design complexity, may miss time-to-market")
    
    return "; ".join(rationales)


def evaluate_architectures(workload: WorkloadProfile, 
                          architectures: List[ArchitectureSpec]) -> List[EvaluationResult]:
    """Evaluate all architectures"""
    results = []
    
    for arch in architectures:
        result = EvaluationResult(
            architecture=arch.name,
            performance_score=calculate_performance_score(arch, workload),
            utilization_score=calculate_utilization_score(arch, workload),
            energy_score=calculate_energy_score(arch, workload),
            flexibility_score=calculate_flexibility_score(arch, workload),
            complexity_score=calculate_complexity_score(arch, workload),
            weighted_total=0.0,
            is_pareto=False,
            rationale=""
        )
        
        result.weighted_total = calculate_weighted_total(result, workload)
        result.rationale = generate_rationale(result, workload)
        results.append(result)
    
    # Identify Pareto frontier
    pareto = identify_pareto_frontier(results)
    for result in results:
        result.is_pareto = result in pareto
    
    return results


def generate_report(results: List[EvaluationResult], 
                   workload: WorkloadProfile,
                   output_dir: Path) -> None:
    """Generate evaluation report"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # JSON output
    json_output = {
        "workload_profile": asdict(workload),
        "evaluation_results": [asdict(r) for r in results],
        "pareto_architectures": [r.architecture for r in results if r.is_pareto],
        "recommended_architecture": max(results, key=lambda x: x.weighted_total).architecture
    }
    
    with open(output_dir / "architecture_evaluation.json", "w") as f:
        json.dump(json_output, f, indent=2)
    
    # Markdown report
    md_lines = [
        "# Architecture Family Evaluation Report",
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
        "The following architectures are Pareto-optimal (no other architecture dominates them in all dimensions):",
        ""
    ])
    
    for result in results:
        if result.is_pareto:
            md_lines.append(f"- **{result.architecture}**: {result.rationale}")
    
    md_lines.extend([
        "",
        "## Recommendation",
        "",
        f"**Recommended Architecture: {max(results, key=lambda x: x.weighted_total).architecture}**",
        "",
        "### Selection Rationale",
        ""
    ])
    
    best = max(results, key=lambda x: x.weighted_total)
    md_lines.append(f"{best.rationale}")
    
    md_lines.extend([
        "",
        "### Why Not Other Architectures?",
        ""
    ])
    
    for result in results:
        if result.architecture != best.architecture:
            md_lines.append(f"- **{result.architecture}**: {result.rationale}")
    
    with open(output_dir / "architecture_evaluation_report.md", "w") as f:
        f.write("\n".join(md_lines))
    
    print(f"Report generated in {output_dir}")
    print(f"Recommended architecture: {best.architecture}")


def main():
    parser = argparse.ArgumentParser(description="QE Architecture Family Quick Evaluator")
    parser.add_argument("--workload-characterization", type=Path,
                       default=Path("docs/benchmarks/qe_kernel_characterization_matrix_for_system_dse_v0.md"))
    parser.add_argument("--architecture-taxonomy", type=Path,
                       default=Path("docs/architecture/architecture_comparison/architecture_taxonomy.md"))
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/architecture_family_evaluation"))
    args = parser.parse_args()
    
    # Load workload profile (simplified - would parse actual files)
    workload = WorkloadProfile(
        gemm_ratio=0.83,
        operator_sweep_ratio=0.68,
        reduced_build_ratio=0.04,
        diag_ratio=0.23,
        refresh_ratio=0.05,
        algorithm_stability="evolving",
        target_design_time_months=6
    )
    
    # Load architecture specs
    architectures = get_architecture_specs()
    
    # Evaluate
    results = evaluate_architectures(workload, architectures)
    
    # Generate report
    generate_report(results, workload, args.output_dir)
    
    # Print summary
    print("\n" + "="*60)
    print("ARCHITECTURE FAMILY EVALUATION SUMMARY")
    print("="*60)
    for result in sorted(results, key=lambda x: x.weighted_total, reverse=True):
        pareto = " [PARETO]" if result.is_pareto else ""
        print(f"{result.architecture:25s} Score: {result.weighted_total:5.1f}{pareto}")
    print("="*60)


if __name__ == "__main__":
    main()
