## ADDED Requirements

### Requirement: Step2 mapping is broad-workload aware
Step2 SHALL build legality matrices, seed mappings, candidate records, selected mappings, and promotion decisions from generic executable graph nodes or regions for every supported workload family. Step2 SHALL NOT require QE node ids or SCF phase names to promote a non-QE candidate.

#### Scenario: Sparse workload maps without QE names
- **WHEN** Step2 consumes a sparse linear algebra workload package and executable graph
- **THEN** legality and selected mapping artifacts reference sparse generic op types, tensor sizes, and workflow policies without requiring `h_psi`, `s_psi`, or `diagonalize`

#### Scenario: Adapter seed remains scoped
- **WHEN** a workload adapter supplies domain-specific seed policies
- **THEN** Step2 records the adapter id or workload family for those seeds and applies them only to compatible workload packages
