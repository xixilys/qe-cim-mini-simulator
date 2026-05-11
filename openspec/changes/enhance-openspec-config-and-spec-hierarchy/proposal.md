## Why

The OpenSpec configuration (`openspec/config.yaml`) is currently at ~20% completeness—containing only the schema declaration with empty context and rules sections. This prevents AI assistants from understanding the project's technical stack, domain constraints, and artifact conventions when creating or reviewing OpenSpec artifacts. Additionally, three completed change-local specs (generic-workload-workflows, step2-architecture-mapping-workflow, step3-simulation-evidence-workflow) need promotion to root-level capabilities to establish a complete spec hierarchy for the DSE framework.

## What Changes

- **Enhance `openspec/config.yaml`** with complete project context including:
  - Tech stack (Python, C++, SystemC, CMake)
  - Domain knowledge (DFT, QE, CIM, FPGA acceleration)
  - Conventions (C++17, Python 3.9+, naming, testing)
  - Artifact rules (proposal, design, spec, tasks formatting requirements)
- **Promote 3 change-local specs to root-level**:
  - `generic-workload-workflows` → `openspec/specs/generic-workload-workflows/spec.md`
  - `step2-architecture-mapping-workflow` → `openspec/specs/step2-architecture-mapping-workflow/spec.md`
  - `step3-simulation-evidence-workflow` → `openspec/specs/step3-simulation-evidence-workflow/spec.md`
- **Update existing root specs** to reference the new capabilities where appropriate
- **Add validation tooling** to verify spec completeness and cross-references

## Capabilities

### New Capabilities
- `openspec-project-config`: Project-level configuration for OpenSpec artifact generation including context, rules, and conventions
- `generic-workload-workflows`: Workload-family workflow definitions, adapter coverage declarations, and domain-neutral ingestion contracts
- `step2-architecture-mapping-workflow`: Architecture catalog, mapping search, DesignPoint generation, and promotion decision contracts
- `step3-simulation-evidence-workflow`: Simulation execution, evidence bundle generation, claim validation, and cross-step handoff contracts

### Modified Capabilities
- `end-to-end-dse-workflow`: Add references to new Step2/Step3 capabilities, clarify feedback-loop artifact requirements
- `multi-fidelity-dse-evaluation`: Add cross-references to Step2 promotion decisions and Step3 evidence gates

## Impact

- **OpenSpec artifact generation**: AI assistants will have full project context when creating proposals, designs, and specs
- **DSE v2 framework**: Complete spec hierarchy enables formal verification of Step1→Step2→Step3 workflow compliance
- **Documentation**: Architecture handbook can reference stable root-level specs instead of change-local artifacts
- **Testing**: New validation tooling ensures spec completeness and detects broken cross-references
