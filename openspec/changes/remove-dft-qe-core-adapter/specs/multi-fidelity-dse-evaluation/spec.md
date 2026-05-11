## ADDED Requirements

### Requirement: Trust gates use profile/importer metadata without privileged exceptions
Multi-fidelity promotion, trusted-final eligibility, and claim validation SHALL use profile/importer metadata, claim boundary, coverage status, simulator evidence, and domain validation status. Trust gates SHALL NOT include privileged exceptions for DFT/QE or any other workload family.

#### Scenario: Profile claim boundary controls eligibility
- **WHEN** a workload profile or package declares a diagnostic, reduced, synthetic, trace-only, or smoke claim boundary
- **THEN** trust gates block trusted final ranking regardless of workload family

#### Scenario: Domain correctness requires profile-declared evidence
- **WHEN** a report claims domain correctness for any workload profile
- **THEN** trust gates require the domain validation evidence declared by that profile or importer plugin

## MODIFIED Requirements

### Requirement: Promotion policy is explicit, budgeted, and evidence-driven
MultiFidelityEvaluator SHALL define when to promote from L1 to L2 and from L2 to L3/L4 using confidence, uncertainty, resource margins, Pareto-front proximity, workload profile metadata, and simulation budget constraints.

#### Scenario: Low-confidence L1 promotes
- **WHEN** L1 confidence is below the configured threshold and promotion budget remains
- **THEN** the evaluator promotes the design point to L2 and records the promotion reason

#### Scenario: Budget exhaustion is visible
- **WHEN** promotion would be beneficial but the configured budget is exhausted
- **THEN** the result remains at the current fidelity and records a budget-exhausted reason
