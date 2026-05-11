# AGENTS Guide - Architecture Directory

## Purpose

System architecture specifications, module interfaces, design contracts, and component/graph definitions for the DFT acceleration system.

**Core Content:**
- Master system specification (1507 lines)
- 4-Cluster FPGA architecture specifications
- Component catalog and graph topology definitions
- SystemC model contracts and transaction semantics
- DSE advisor pack and confidence rubrics

## Directory Contents

- **51 files total**: 6 JSON, 45 Markdown
- **Master spec**: `system_design_master_spec_v0.md` (1507 lines)
- **Component catalog**: `qe_ic_component_catalog_system_level_v1.json` (955 lines, 16 components)
- **Graph topology**: `qe_ic_graph_seed_system_level_v1.json` (F2 balanced architecture)
- **Cluster specs**: 10+ detailed cluster-level specifications
- **DSE advisor pack**: 10+ templates and rubrics

## Key Documents

### Master Specification
**`system_design_master_spec_v0.md`** - System-level master specification

**Purpose:** Unified system design document defining:
- System object: Host + FPGA + Chip
- Six-domain partition
- QE mainline integration
- LCW (Long Control Word) role
- Object semantics and terminology

**Status:**
- **Stable**: System object, six-domain partition, QE integration, LCW role, BODY catalog
- **Partially stable**: Phase A-E/Bx flow, QE/VASP → replay lowering
- **Unfrozen**: Precise encoding, clock/reset/power, buffer capacity, QoS arbitration

**Read first for:** System boundaries, module responsibilities, control contracts

### Component and Graph Definitions

**`qe_ic_component_catalog_system_level_v1.json`** - Component catalog (16 components)

**Components:**
- **System-level**: system_container, host_controller, chip_execution_facade
- **Cluster-level**: cluster_flow_executor, episode_controller
- **On-chip**: command_scheduler, near_memory_domain, reduction_closure_engine
- **Leaf**: CIM array, GEMM engines, SRAM buffers, merge trees

**`qe_ic_graph_seed_system_level_v1.json`** - Graph topology seed

**Architecture:** F2 balanced 4-cluster pipeline
- Cluster A: Operator sweep (h_psi, s_psi)
- Cluster B: Reduced build (H_sub, S_sub)
- Cluster C: Hardware diag (eigensolver)
- Cluster D: Refresh/residual

**`qe_ic_component_graph_input_template_v1.md`** - Template specification

**Purpose:** Defines component/graph template format for DSE framework

### SystemC Model Specifications

**`qe_band_solver_systemc_overview_20260325.md`** - SystemC model overview

**Purpose:** SystemC skeleton structure and module hierarchy

**`qe_band_solver_transaction_semantics_20260326.md`** - Transaction semantics

**Purpose:** Host-FPGA-Chip transaction boundaries and control flow

**`qe_full_dft_systemc_extension_outline_v0.md`** - Full-SCF extension

**Purpose:** Roadmap for extending band-solver to full-SCF simulation

### 4-Cluster FPGA Architecture

**Cluster A (Operator Sweep) - 68% execution time:**
- `qe_fpga_clustered_v1_cluster_ab_operator_build_spec_20260402.md`
- CIM Array + Ozaki-II GEMM or Traditional FPGA GEMM
- h_psi and s_psi operator application

**Cluster B (Reduced Build) - 4% execution time:**
- `qe_fpga_clustered_v1_cluster_ab_operator_build_spec_20260402.md`
- Reduction tree for H_sub/S_sub construction
- Vector accumulation and merge

**Cluster C (Hardware Diag) - 23% execution time:**
- `qe_fpga_clustered_v1_cluster_c_cdiaghg_spec_20260402.md`
- Generalized Hermitian eigensolver
- Eigenvalue/eigenvector computation

**Cluster D (Refresh/Residual) - 5% execution time:**
- `qe_fpga_clustered_v1_cluster_d_refresh_spec_20260402.md`
- Residual computation
- Context refresh and update

**Supporting Specifications:**
- `qe_fpga_clustered_v1_architecture_model_v0.md` - Architecture model
- `qe_fpga_clustered_v1_implementation_package_20260402.md` - Implementation package
- `qe_fpga_clustered_v1_cycle_approx_baseline_rows_v0_20260403.md` - Cycle approximation
- `qe_fpga_clustered_v1_cycle_proxy_formula_contract_v0_20260403.md` - Proxy formula contract
- `qe_fpga_clustered_v1_buffer_memory_budget_table_20260402.md` - Memory budget
- `qe_fpga_clustered_v1_module_interface_table_20260402.md` - Module interfaces
- `qe_fpga_clustered_v1_workload_bucket_mapping_20260402.md` - Workload mapping

### System Contracts

**`system_interface_contract_v0.md`** - System interface contract

**Purpose:** Interface definitions and routing contracts

**`system_exception_and_flow_control_contract_v0.md`** - Exception handling

**Purpose:** Exception handling, flow control, and recovery mechanisms

**`qe_system_optimized_delta_20260413.md`** - Optimized system delta

**Purpose:** Recent system-level redesign changes relative to master spec

### Component/Graph Projection

**`qe_ic_component_graph_projection_v1.md`** - Projection specification

**Purpose:** Graph/component → design_point + SystemRunConfig projection rules

**`qe_ic_component_graph_brownfield_binding_v1.md`** - Brownfield binding

**Purpose:** v1 component/graph binding to brownfield simulator and artifact chain

**`qe_ic_component_library_contract_v0.md`** - Component library contract

**Purpose:** Component library interface and usage contracts

### DSE Advisor Pack

**Purpose:** Templates and rubrics for DSE result reporting and confidence assessment

**Key files:**
- `systemc_system_level_dse_advisor_pack_manifest_v0_20260413.md` - Pack manifest
- `systemc_system_level_dse_advisor_pack_assembly_checklist_v0_20260413.md` - Assembly checklist
- `systemc_system_level_dse_confidence_and_claims_rubric_v0_20260413.md` - Confidence rubric
- `systemc_system_level_dse_advisor_report_template_v0_20260413.md` - Report template
- `systemc_system_level_dse_executive_summary_onepager_template_v0_20260413.md` - Executive summary
- `systemc_system_level_dse_advisor_cover_memo_template_v0_20260413.md` - Cover memo
- `systemc_system_level_dse_advisor_qa_cheatsheet_v0_20260413.md` - Q&A cheatsheet
- `systemc_system_level_dse_family_responsibility_matrix_v0_20260413.md` - Responsibility matrix
- `systemc_system_level_dse_why_not_other_families_note_template_v0_20260413.md` - Alternative analysis

### Graph Schema and Examples

**`qe_ic_graph_schema_v0.json`** - Graph schema definition

**Purpose:** JSON schema for graph topology definitions

**`qe_ic_graph_schema_guide_v0.md`** - Schema guide

**Purpose:** Human-readable guide to graph schema

**`qe_ic_graph_export_contract_v0.md`** - Export contract

**Purpose:** Graph export format and contract

**`qe_ic_graph_export_examples_v0.json`** - Export examples

**Purpose:** Example graph exports

**`qe_ic_graph_seed_templates_v0.json`** - Seed templates

**Purpose:** Template library for graph seeds

## Common Workflows

### Design Review Workflow
```bash
# 1. Read master specification
cat docs/architecture/system_design_master_spec_v0.md

# 2. Review system contracts
cat docs/architecture/system_interface_contract_v0.md
cat docs/architecture/system_exception_and_flow_control_contract_v0.md

# 3. Check cluster specifications
cat docs/architecture/qe_fpga_clustered_v1_cluster_*_spec_*.md

# 4. Validate against control ISA
cat docs/control/long_control_word_isa_v0.md
```

### Component/Graph Exploration
```bash
# 1. Inspect component catalog
cat docs/architecture/qe_ic_component_catalog_system_level_v1.json | jq '.components[] | {id: .component_id, role: .role}'

# 2. Inspect graph topology
cat docs/architecture/qe_ic_graph_seed_system_level_v1.json | jq '.graph_topology'

# 3. Validate component/graph contracts
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py

# 4. Preview projection
python3 tools/benchmarks/qe_ic_graph_projection_utils.py --preview
```

### Architecture Modification Workflow
```bash
# 1. Edit component catalog
vim docs/architecture/qe_ic_component_catalog_system_level_v1.json

# 2. Edit graph topology
vim docs/architecture/qe_ic_graph_seed_system_level_v1.json

# 3. Validate changes
python3 tools/benchmarks/check_qe_ic_component_graph_v1.py

# 4. Run DSE sweep with new architecture
python3 tools/benchmarks/run_systemc_architecture_family_dse_sweep.py \
  --component-catalog docs/architecture/qe_ic_component_catalog_system_level_v1.json \
  --graph-spec docs/architecture/qe_ic_graph_seed_system_level_v1.json
```

### SystemC Model Integration
```bash
# 1. Review SystemC overview
cat docs/architecture/qe_band_solver_systemc_overview_20260325.md

# 2. Review transaction semantics
cat docs/architecture/qe_band_solver_transaction_semantics_20260326.md

# 3. Check brownfield binding
cat docs/architecture/qe_ic_component_graph_brownfield_binding_v1.md

# 4. Build and run SystemC model
cd model/qe_band_solver_model/build
cmake .. && make -j4
./qe_band_solver_model
```

## File Naming Conventions

- `system_*_v0.md` - System-level specifications
- `qe_fpga_clustered_v1_*_YYYYMMDD.md` - Timestamped cluster specs
- `qe_ic_*_v0.json` - Component/graph JSON definitions
- `qe_ic_*_v1.json` - Component/graph v1 definitions
- `systemc_system_level_dse_*_v0_YYYYMMDD.md` - DSE advisor templates

## Component Catalog Structure

### System-Level Components
- `system_container` - Top-level host/device/datapath composition
- `host_controller` - Host CPU SCF loop orchestration
- `chip_execution_facade` - FPGA chip-level container

### Cluster-Level Components
- `cluster_flow_executor` - Cluster graph execution engine
- `episode_controller` - Episode-level control flow

### On-Chip Components
- `command_scheduler` - On-chip command scheduling
- `near_memory_domain` - Near-memory compute domain
- `reduction_closure_engine` - Reduction tree for H_sub/S_sub

### Leaf Components
- `cim_array_core` - CIM Array with Ozaki-II GEMM
- `traditional_fpga_gemm_core` - Traditional FPGA GEMM baseline
- `near_sram_coeff_buffer` - Coefficient buffer
- `near_sram_row_buffer` - Row buffer
- `row_merge_tree` - Row merge tree

## Graph Topology Structure

### F2 Balanced Architecture
```
system_container
  ├── host_controller (Host CPU)
  │   ├── rho → Veff computation
  │   └── mix_rho and convergence check
  └── chip_execution_facade (FPGA)
      ├── cluster_flow_executor
      │   ├── Cluster A: operator_sweep (68%)
      │   ├── Cluster B: reduced_build (4%)
      │   ├── Cluster C: hardware_diag (23%)
      │   └── Cluster D: refresh_residual (5%)
      └── near_memory_domain
          ├── CIM Array / Traditional GEMM
          ├── Reduction Engine
          └── SRAM Buffers
```

## Critical Rules

### Documentation Updates
- Update master spec when system boundaries change
- Update cluster specs when module responsibilities change
- Update component catalog when adding/removing components
- Update graph topology when changing architecture
- Preserve timestamped snapshots (do not modify)

### Authority Boundaries
- Master spec is canonical for system-level decisions
- Cluster specs are canonical for module-level decisions
- Component catalog is canonical for DSE framework
- Graph topology is canonical for architecture exploration

### Validation Requirements
- Validate component/graph changes before DSE sweep
- Validate SystemC model against transaction semantics
- Validate cluster specs against master spec
- Validate DSE results against confidence rubric

## Integration Points

### With Benchmarks
- Component catalog consumed by DSE framework
- Graph topology consumed by projection utilities
- Cluster specs inform cycle approximation models

### With SystemC Model
- SystemC overview defines module hierarchy
- Transaction semantics define control flow
- Brownfield binding maps components to code

### With Control Specifications
- Master spec references LCW ISA
- Cluster specs reference control word formats
- Component catalog references descriptor templates

## Next Steps

- For DSE framework: see `docs/benchmarks/AGENTS.md`
- For SystemC model: see `model/qe_band_solver_model/AGENTS.md`
- For control ISA: see `docs/control/long_control_word_isa_v0.md`
- For documentation index: see `docs/AGENTS.md`
