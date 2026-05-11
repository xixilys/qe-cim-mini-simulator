## ADDED Requirements

### Requirement: Step2 consumes profile mapping preferences generically
Step2 SHALL consume mapping preferences from the resolved workload profile and translate them into legality-matrix-aware seed mappings. Step2 SHALL NOT define workload-family-specific preferred targets or seed names in core code.

#### Scenario: Profile seed generates mapping candidate
- **WHEN** a profile declares a mapping preference compatible with the architecture catalog
- **THEN** Step2 records a seed mapping labeled by profile id and applies legality checks before promotion

#### Scenario: QE seed is not a core default
- **WHEN** the QE reference profile declares a diagonalization or operator-sweep preference
- **THEN** Step2 treats it as profile data and does not expose it as a global default for other profiles

## MODIFIED Requirements

### Requirement: Step2 seed mappings are generic and workflow-aware
Step2 SHALL generate seed mappings from core generic policies and optional workload profile mapping preferences. Core seeds SHALL include host baseline, capability-greedy, memory-locality, communication-aware, all-offload, streaming, batch, fallback-mixed, and debug-observable where applicable. Profile seeds SHALL be labeled with profile id and SHALL operate over generic node ids/op types rather than hardcoded core-domain node names.

#### Scenario: DFT/QE seed is adapter scoped
- **WHEN** a QE reference profile supplies a hardware-diagonalization or operator-sweep mapping preference
- **THEN** Step2 records it as profile-owned metadata and SHALL NOT expose it as a global default for non-QE workloads

#### Scenario: Non-QE workflow seed uses generic operators
- **WHEN** a sparse, stencil, graph analytics, ML/tensor, database/vector-search, or custom profile supplies default mapping preferences
- **THEN** Step2 translates those preferences into legal placements using generic op types, tensor sizes, and architecture capabilities
