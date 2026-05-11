# AGENTS Guide - Documentation Directory

## Purpose

Project-level design documentation, benchmark runbooks, and validation artifacts for the DFT acceleration system. Runnable Python tools live under `tools/`. This directory contains:

- **Architecture specifications**: System design, module interfaces, transaction semantics
- **Benchmark documentation**: DSE contracts, workload analysis reports, baseline runbooks, schemas, and evidence artifacts
- **CIM design**: Macro block structure, timing models, resident context management
- **Control specifications**: ISA, control word formats, descriptor templates
- **Survey materials**: Industry analysis, tool references, software evolution

## Directory Structure

```
docs/
├── architecture/        # System architecture and module specifications
├── benchmarks/          # DSE contracts, runbooks, schemas, and evidence artifacts
├── cim/                 # CIM macro design and timing models
├── control/             # Control ISA and descriptor specifications
├── overview/            # Project timeline, handoff notes, sampling guides
├── survey/              # Industry surveys and tool references
├── qe_inputs/           # QE input file examples
├── patches/             # QE instrumentation patches
└── README.md            # Documentation index
```

## Quick Navigation

### For Design Review
Start with these canonical documents:
1. `architecture/system_design_master_spec_v0.md` - System-level master specification
2. `overview/project_development_timeline.md` - Complete development timeline
3. `benchmarks/qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` - Fairness contract
4. `cim/cim_macro_block_and_timing_v0.md` - CIM macro structure

### For Implementation
1. `architecture/qe_band_solver_systemc_overview_20260325.md` - SystemC model overview
2. `architecture/qe_band_solver_transaction_semantics_20260326.md` - Transaction semantics
3. `control/long_control_word_isa_v0.md` - Control ISA specification
4. `model/qe_band_solver_model/README.md` - Runnable model entry point

### For Benchmarking
1. `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` - DSE sweep entry point
2. `benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md` - Baseline acquisition guide
3. `benchmarks/qe_fpga_workload_group_and_correctness_contract_v0.md` - Workload contracts
4. `overview/qe_subspace_sampling.md` - QE sampling methodology

## Key Subdirectories

### architecture/
System architecture specifications, module interfaces, and design contracts.

**Key files:**
- `system_design_master_spec_v0.md` - Master system specification
- `qe_band_solver_systemc_overview_20260325.md` - SystemC model overview
- `qe_fpga_clustered_v1_*.md` - Cluster-level specifications
- `qe_ic_component_catalog_system_level_v1.json` - Component catalog
- `qe_ic_graph_seed_system_level_v1.json` - Graph topology seed

**See:** `docs/architecture/AGENTS.md` for detailed guidance

### benchmarks/
DSE contracts, workload-analysis reports, baseline runbooks, schemas, and validation artifacts. Runnable Python tools are in `tools/benchmarks/`.

**Key files:**
- `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py` - DSE sweep orchestrator
- `qe_cpu_gpu_baseline_acquisition_runbook_v0.md` - Baseline acquisition guide
- `qe_fpga_workload_group_and_correctness_contract_v0.md` - Workload contracts
- `qe_cpu_gpu_fpga_fairness_and_power_contract_v0.md` - Fairness contract
- `tools/benchmarks/assess_qe_phase1_evidence_closure.py` - Evidence closure assessment

**See:** `docs/benchmarks/AGENTS.md` for detailed guidance

### cim/
CIM macro block design, timing models, and implementation contracts.

**Key files:**
- `cim_macro_block_and_timing_v0.md` - CIM macro structure and timing
- `cim_resident_context_and_near_sram_contract_v0.md` - Resident context management
- `fused_digit_residue_multiply_flow_v0.md` - Fused digit-residue multiply flow

### control/
Control ISA, long control word formats, and descriptor specifications.

**Key files:**
- `long_control_word_isa_v0.md` - Control ISA specification
- Descriptor templates and replay mechanisms

### overview/
Project timeline, handoff notes, and QE sampling methodology.

**Key files:**
- `project_development_timeline.md` - Complete development timeline and phase conclusions
- `agent_handoff_20260312.md` - Repository handoff and work constraints
- `qe_subspace_sampling.md` - QE sampling methodology and reproduction guide

### survey/
Industry surveys, tool references, and software evolution analysis.

**Key files:**
- `dft_acceleration_industry_survey_20260322.md` - Industry acceleration survey
- `dft_acceleration_vasp_qe_pyscf_survey_20260323.md` - Software-specific survey
- `system_level_modeling_methods_and_tools_reference_20260402.md` - Modeling tools reference

## Documentation Philosophy

### Authority Hierarchy
1. **Adjudicator memo**: Only source of decision authority
2. **DSE/projection/GPU annex**: Evidence inputs only
3. **Stage A**: Bounded/guarded/projection-grade conclusions
4. **Stage B**: Thesis-grade claims (requires closure gates)

### Document Types
- **Contracts**: Frozen specifications (e.g., fairness_contract, workload_contract)
- **Specifications**: Design documents (e.g., system_design_master_spec)
- **Runbooks**: Operational procedures (e.g., baseline_acquisition_runbook)
- **Evidence**: Analysis results (e.g., workload_revalidation_report)

### Naming Conventions
- `*_contract_v0.md`: Frozen contracts
- `*_spec_v0.md`: Specifications
- `*_runbook_v0.md`: Operational procedures
- `*_YYYYMMDD.md`: Timestamped snapshots
- `*_template_v0.json`: Machine-readable templates

## Common Workflows

### Design Review Workflow
1. Read `architecture/system_design_master_spec_v0.md`
2. Check `benchmarks/qe_ic_adjudicator_authority_contract_v0.md` for authority boundaries
3. Review relevant cluster specifications in `architecture/`
4. Validate against `control/long_control_word_isa_v0.md`

### Benchmark Workflow
1. Extract QE traces using `overview/qe_subspace_sampling.md`
2. Run DSE sweep: `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`
3. Assess evidence closure: `tools/benchmarks/assess_qe_phase1_evidence_closure.py`
4. Generate reports: `tools/benchmarks/render_qe_phase1_evidence_closure_md.py`

### Baseline Acquisition Workflow
1. Follow `benchmarks/qe_cpu_gpu_baseline_acquisition_runbook_v0.md`
2. Initialize artifact bundle: `tools/benchmarks/init_qe_phase1_artifact_bundle.py`
3. Assess readiness: `tools/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py`
4. Validate contracts: `tools/benchmarks/check_qe_phase1_artifact_contracts.py`

### Architecture Exploration Workflow
1. Define component catalog: `architecture/qe_ic_component_catalog_system_level_v1.json`
2. Define graph topology: `architecture/qe_ic_graph_seed_system_level_v1.json`
3. Run projection: `tools/benchmarks/qe_ic_graph_projection_utils.py`
4. Execute DSE sweep: `tools/benchmarks/run_systemc_architecture_family_dse_sweep.py`

## Critical Rules

### Documentation Updates
- Update `project_development_timeline.md` when major phases complete
- Update contracts when system boundaries change
- Update runbooks when procedures change
- Preserve timestamped snapshots (do not modify)

### Authority Boundaries
- Only adjudicator memo can make final decisions
- DSE results are evidence, not authority
- Stage A conclusions must be bounded/guarded
- Stage B requires closure gate satisfaction

### File Management
- Do not delete timestamped snapshots
- Preserve QE trace data and dumps
- Keep machine-readable templates in sync with documentation
- Update README.md when adding new canonical documents

## Integration Points

### With Model Directory
- Architecture specs → SystemC implementation in `model/qe_band_solver_model/`
- Algorithm validation in `model/ozaki_subspace_model/` → architecture assumptions
- DSE framework invokes SystemC model for performance estimation

### With Benchmark Tools
- Python tools in `tools/benchmarks/` consume architecture specs
- DSE sweep generates results validated against contracts
- Baseline acquisition follows runbook procedures

### With QE Workspace
- QE sampling methodology in `overview/qe_subspace_sampling.md`
- Patches in `patches/` applied to `soft/qe-7.5/`
- Input files in `qe_inputs/` used for trace extraction

## Testing and Validation

### Contract Validation
```bash
# Validate phase-1 artifact contracts
python3 tools/benchmarks/check_qe_phase1_artifact_contracts.py

# Validate component/graph v1 contracts
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py

# Run contract regression tests
python3 tools/benchmarks/test_qe_phase1_artifact_contracts.py
```

### Evidence Closure Assessment
```bash
# Assess phase-1 evidence closure
python3 tools/benchmarks/assess_qe_phase1_evidence_closure.py

# Generate closure report
python3 tools/benchmarks/run_qe_phase1_closure_pipeline.py
```

### Baseline Readiness
```bash
# Assess CPU+GPU baseline readiness
python3 tools/benchmarks/assess_qe_cpu_gpu_baseline_readiness.py
```

## Documentation Style

- **Markdown**: Use standard markdown with code blocks
- **JSON**: Machine-readable templates and schemas
- **Python**: Validation scripts and DSE framework live under `tools/`; docs reference their commands
- **Diagrams**: ASCII art or external tools (not embedded images)

## Next Steps

- For architecture details: see `docs/architecture/AGENTS.md`
- For benchmark infrastructure: see `docs/benchmarks/AGENTS.md`
- For model implementation: see `model/qe_band_solver_model/AGENTS.md`
- For algorithm validation: see `model/ozaki_subspace_model/AGENTS.md`
