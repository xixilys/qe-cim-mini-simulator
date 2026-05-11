# AGENTS Guide - Benchmarks Directory

## Purpose

DSE (Design Space Exploration) contracts, runbooks, schemas, validation artifacts, and historical evidence for the DFT acceleration system. Runnable Python tools live under `tools/benchmarks/`.

**Core Functions:**
- Architecture family DSE sweep orchestration
- CPU/GPU/FPGA baseline acquisition and validation
- Workload group contracts and correctness validation
- Evidence closure assessment for thesis claims
- Component/graph projection and validation

## Directory Contents

- **Python tools**: Moved to `tools/benchmarks/`; keep command examples pointing there
- **20+ JSON files**: Templates, schemas, results, case packs
- **20+ Markdown files**: Contracts, runbooks, reports
- **Results subdirectories**: Baseline data, DSE outputs, validation artifacts

## Key Entry Points

### DSE Framework
Start with the DSE framework manual:

- `qe_dse_framework_user_manual_v0.md` - Complete user manual for DSE inputs, commands, outputs, validation, artifact reading order, and claim boundaries
- `generic_dse_simulation_system_handbook_v1.md` - New primary handbook for the generic DSE + SystemC/gem5+SystemC simulation evidence loop. It frames QE as a reference adapter / legacy lane and uses Step1/Step2/Step3, feedback, final report, and claim validation as the main workflow.
- `qe_unified_dse_framework_v0.md` - Unified DSE v0 architecture and implementation plan. This is an additive Stage-A evidence-only, adjudicator-ready wrapper plan, not a replacement for the canonical sweep runner or adjudicator.

```bash
# Current main/canonical Stage-A family sweep orchestrator (3478 lines)
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json \
  --output-dir tmp/dse_results
```

```bash
# Additive bounded Unified DSE v0 CLI wrapper, evidence package only
python3 tools/benchmarks/run_unified_dse_v0.py \
  --design-space-spec docs/benchmarks/qe_architecture_family_design_space_spec_v0.json \
  --workload tmp/workload_descriptor.json \
  --output-dir tmp/unified_dse_results \
  --dry-run
```

### Baseline Acquisition
```bash
# Initialize phase-1 artifact bundle
python3 tools/benchmarks/init_qe_phase1_artifact_bundle.py \
  --output-dir tmp/phase1_bundle

# Assess CPU+GPU baseline readiness
python3 tools/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py \
  --baseline-dir tmp/cpu_gpu_baselines
```

### Evidence Closure
```bash
# Run complete phase-1 closure pipeline
python3 tools/benchmarks/run_qe_phase1_closure_pipeline.py \
  --output-dir tmp/closure_results
```

### Contract Validation (`tools/benchmarks/`)
```bash
# Validate phase-1 artifact contracts
python3 tools/benchmarks/check_qe_phase1_artifact_contracts.py

# Validate component/graph v1 contracts
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py
```

## Core Tool Entry Points

### DSE and Architecture Exploration (`tools/benchmarks/`)
- `run_systemc_architecture_family_dse_sweep.py` - Main DSE orchestrator, invokes SystemC model
- `run_unified_dse_v0.py` - Additive bounded v0 wrapper over existing DSE evidence concepts. It writes Stage-A evidence-only, adjudicator-ready results; `SystemC` execution remains opt-in and implementation backend support is stub/reserved/projection-only.
- `qe_ic_graph_projection_utils.py` - Component/graph → design point projection
- `evaluate_qe_ic_graph_frontdoor.py` - Graph frontdoor evaluation
- `build_qe_ic_component_registry.py` - Component registry builder
- `build_qe_ic_case_pack.py` - Case pack builder

### Baseline Acquisition and Validation (`tools/benchmarks/`)
- `init_qe_phase1_artifact_bundle.py` - Initialize artifact bundle scaffold
- `assess_qe_cpu_gpu_baseline_readiness.py` - Assess baseline readiness
- `normalize_qe_gold_baseline.py` - Normalize gold baseline format
- `compare_qe_gold_correctness.py` - Compare against gold baseline
- `extract_qe_shell_cpu_baseline.py` - Extract CPU shell baseline

### Evidence Closure and Reporting (`tools/benchmarks/`)
- `assess_qe_phase1_evidence_closure.py` - Assess evidence closure status
- `render_qe_phase1_evidence_closure_md.py` - Render closure report
- `run_qe_phase1_closure_pipeline.py` - Complete closure pipeline

### Contract Validation (`tools/benchmarks/`)
- `check_qe_phase1_artifact_contracts.py` - Validate phase-1 contracts
- `check_qe_ic_component_graph_v1.py` - Validate component/graph v1
- `check_qe_next_stage_dse_simulator_contracts.py` - Validate DSE contracts
- `check_qe_next_stage_release_bundle.py` - Validate release bundle
- `check_qe_gold_contract_regression.py` - Gold contract regression

### Workload Analysis (`tools/benchmarks/`)
- `analyze_qe_scf_operator_load.py` - SCF operator load analysis
- `analyze_qe_workload_revalidation.py` - Workload revalidation analysis
- `run_qe_workload_matrix.py` - Run workload matrix
- `summarize_qe_subspace_trace.py` - Summarize subspace trace

### Utilities (`tools/benchmarks/`)
- `compute_qe_clustered_cycle_proxy.py` - Compute cycle proxy
- `derive_qe_cpu_speedup_envelope.py` - Derive speedup envelope

## Key Contracts and Specifications

### Frozen Contracts
- `qe_fpga_workload_group_and_correctness_contract_v0.md` - Workload group admission
- `qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` - Fairness and power boundaries
- `qe_algorithm_rewrite_manifest_contract_v0.md` - Algorithm rewrite classification
- `qe_simulator_board_observability_contract_v0.md` - Simulator/board observability
- `qe_ic_adjudicator_authority_contract_v0.md` - Authority hierarchy

### Runbooks
- `qe_cpu_gpu_baseline_acquisition_runbook_v0.md` - Baseline acquisition procedures
- `generic_dse_simulation_system_handbook_v1.md` - Generic DSE + simulation evidence loop handbook and primary broad-workload DSE reading entry
- `qe_dse_framework_user_manual_v0.md` - DSE framework user manual and evidence/claim-boundary guide
- `qe_unified_dse_framework_v0.md` - Unified DSE v0 architecture/plan for an additive stdlib package and thin CLI wrapper
- `qe_next_stage_release_delivery_spec_v0.md` - Release delivery specification
- `qe_next_stage_dse_strategy_v0.md` - DSE strategy specification

### Templates and Schemas
- `qe_algorithm_rewrite_manifest_template_v0.json` - Rewrite manifest template
- `qe_cpu_gpu_baseline_manifest_template_v0.json` - Baseline manifest template
- `systemc_architecture_family_dse_result_schema_v0.json` - DSE result schema

## Authority Hierarchy

**Critical Rule:** Only adjudicator memo has decision authority.

### Stage A (Current)
- **Allowed**: Bounded/guarded/projection-grade conclusions
- **Forbidden**: Thesis-grade final authority claims
- **Evidence sources**: DSE results, projection helpers, GPU annex

### Stage B (Future)
- **Activation gates**: GPU baseline closure, phase closure, board closure, ranking stability
- **Allowed**: Thesis-grade public claims
- **Requirements**: All closure gates satisfied

## Common Workflows

### Run Complete DSE Sweep
```bash
# 1. Prepare component catalog and graph spec
# (Already exists: docs/architecture/qe_ic_component_catalog_system_level_v1.json)

# 2. Run DSE sweep
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json \
  --output-dir tmp/dse_sweep_results \
  --workloads si4,si8,graphene

# 3. Results in tmp/dse_sweep_results/
# - systemc_architecture_family_dse_bootstrap_v0.csv
# - compare/speedup_summary.json
# - logs/
```

### Acquire and Validate CPU+GPU Baseline
```bash
# 1. Initialize artifact bundle
python3 tools/benchmarks/init_qe_phase1_artifact_bundle.py \
  --output-dir tmp/phase1_artifacts

# 2. Run QE workloads and collect data
# (Follow qe_cpu_gpu_baseline_acquisition_runbook_v0.md)

# 3. Assess baseline readiness
python3 tools/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py \
  --baseline-dir tmp/cpu_gpu_baselines \
  --output tmp/baseline_readiness.json

# 4. Validate contracts
python3 tools/benchmarks/check_qe_phase1_artifact_contracts.py
```

### Assess Evidence Closure
```bash
# Run complete closure pipeline
python3 tools/benchmarks/run_qe_phase1_closure_pipeline.py \
  --gpu-baseline-dir tmp/cpu_gpu_baselines \
  --board-bundle-dir tmp/board_artifacts \
  --output-dir tmp/closure_results

# Outputs:
# - tmp/closure_results/phase1_evidence_closure.json
# - tmp/closure_results/phase1_evidence_closure.md
```

### Validate Component/Graph Contracts
```bash
# Validate v1 component catalog and graph seed
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json

# Run projection preview
python3 tools/benchmarks/qe_ic_graph_projection_utils.py \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json \
  --preview
```

### Run Workload Analysis
```bash
# Analyze QE trace
python3 tools/benchmarks/summarize_qe_subspace_trace.py \
  docs/benchmarks/results/qe_si8_trace.csv

# Analyze SCF operator load
python3 tools/benchmarks/analyze_qe_scf_operator_load.py \
  --trace-dir docs/benchmarks/results/qe_workload_revalidation
```

## Testing and Validation

### Run All Contract Tests
```bash
# Phase-1 artifact contracts
python3 tools/benchmarks/test_qe_phase1_artifact_contracts.py

# Component/graph v1 contracts
python3 tools/benchmarks/test_check_qe_ic_component_graph_v1.py

# Projection utils
python3 tools/benchmarks/test_qe_ic_graph_projection_utils.py

# Evidence closure
python3 tools/benchmarks/test_assess_qe_phase1_evidence_closure.py

# Baseline readiness
python3 tools/benchmarks/test_assess_qe_cpu_gpu_baseline_readiness.py
```

### Validate Gold Baseline
```bash
# Normalize gold baseline
python3 tools/benchmarks/normalize_qe_gold_baseline.py \
  --input-dir tmp/raw_baselines \
  --output-dir tmp/normalized_baselines

# Compare correctness
python3 tools/benchmarks/compare_qe_gold_correctness.py \
  --gold-dir tmp/normalized_baselines \
  --test-dir tmp/test_results

# Check regression
python3 tools/benchmarks/check_qe_gold_contract_regression.py
```

## Integration with SystemC Model

The DSE framework invokes the SystemC model:

```python
# Simplified flow from run_systemc_architecture_family_dse_sweep.py
1. Load component catalog and graph spec
2. Generate design points via projection
3. For each design point:
   a. Generate SystemC configuration JSON
   b. Invoke: ./model/qe_band_solver_model/build/qe_band_solver_model --config <json>
   c. Parse cycle counts and resource utilization
   d. Compute speedup vs CPU baseline
4. Aggregate results into DSE result bundle
5. Generate speedup summary and Pareto frontier
```

## File Naming Conventions

- `tools/benchmarks/run_*.py` - Executable entry points
- `tools/benchmarks/check_*.py` - Validation scripts
- `tools/benchmarks/test_*.py` - Regression tests
- `tools/benchmarks/assess_*.py` - Assessment tools
- `tools/benchmarks/analyze_*.py` - Analysis scripts
- `tools/benchmarks/build_*.py` - Builder utilities
- `*_contract_v0.md` - Frozen contracts
- `*_runbook_v0.md` - Operational procedures
- `*_template_v0.json` - Machine-readable templates
- `*_schema_v0.json` - JSON schemas

## Critical Rules

### Authority Boundaries
- DSE results are **evidence only**, not decision authority
- Only adjudicator memo can make final claims
- Stage A: bounded/guarded conclusions only
- Stage B: requires closure gate satisfaction

### Contract Compliance
- All baselines must satisfy workload group contract
- All comparisons must follow fairness contract
- All rewrites must be documented in manifest
- All board data must follow observability contract

### Data Preservation
- Never modify timestamped result files
- Preserve QE trace data and dumps
- Keep baseline manifests with results
- Version all templates and schemas

### Validation Requirements
- Run contract validation before release
- Run regression tests after changes
- Validate closure before thesis claims
- Check gold baseline consistency

## Python Tool Patterns

### Standard Imports
```python
from pathlib import Path
import json
import argparse
```

### Standard Argument Parsing
```python
parser = argparse.ArgumentParser(description="...")
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
```

### JSON Template Loading
```python
with open(template_path) as f:
    template = json.load(f)
```

### Result Bundle Writing
```python
result = {
    "schema_version": "v0",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data": {...}
}
with open(output_path, "w") as f:
    json.dump(result, f, indent=2)
```

## Next Steps

- For architecture specs: see `docs/architecture/AGENTS.md`
- For SystemC model: see `model/qe_band_solver_model/AGENTS.md`
- For algorithm validation: see `model/ozaki_subspace_model/AGENTS.md`
- For documentation index: see `docs/AGENTS.md`
