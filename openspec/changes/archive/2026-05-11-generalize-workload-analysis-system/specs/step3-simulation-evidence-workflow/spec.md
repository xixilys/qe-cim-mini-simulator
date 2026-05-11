## ADDED Requirements

### Requirement: Step3 evidence is broad-workload aware
Step3 SHALL reconstruct simulation requests, evidence requirements, verdicts, claim validation, and final reports from generic Step2 artifacts for every supported workload family. Step3 SHALL apply adapter-specific coverage only when it is declared by the selected workload package or workflow metadata.

#### Scenario: Non-QE Step3 request has no QE required fields
- **WHEN** Step3 reconstructs a simulation request for an ML/tensor, sparse, stencil, graph analytics, database/vector-search, or custom workload
- **THEN** the request is valid without QE-only fields such as `npw`, `nkb`, `h_psi`, `s_psi`, `mix_rho`, or `veff`

#### Scenario: Adapter validation controls domain claims
- **WHEN** Step3 has complete generic simulation evidence but missing adapter-domain validation for a workload family
- **THEN** trusted timing/resource claims may pass while domain correctness claims remain blocked or unavailable
