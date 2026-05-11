## ADDED Requirements

### Requirement: Step2 mapping search separates generation, screening, and promotion
The multi-fidelity DSE layer SHALL treat Step2 mapping generation, low-fidelity screening, and high-fidelity promotion as separate lifecycle stages with persisted artifacts. L1/L2/surrogate metrics MAY prioritize candidates, but final trusted ranking SHALL wait for SystemC or gem5+SystemC evidence.

#### Scenario: Screening is candidate generation only
- **WHEN** L1, L2, or surrogate screening ranks architecture/mapping candidates
- **THEN** Step2 records predicted metrics, uncertainty, and promotion priority without marking any candidate as a trusted winner

#### Scenario: Promotion queue is budgeted
- **WHEN** Step2 selects candidates for SystemC or gem5+SystemC simulation
- **THEN** it records the promotion budget, selected candidate ids, required backend, evidence mode, and reason for each promotion

### Requirement: Step2 feedback handoff is explicit
Step2 SHALL initialize or update mapping feedback artifacts with screened, promoted, attempted, completed, trusted, blocked, and remaining sample counts. Feedback artifacts SHALL indicate whether the current run is awaiting simulation, has trusted samples integrated, is blocked, or stopped by budget.

#### Scenario: Awaiting simulation remains non-final
- **WHEN** Step2 has promoted candidates but Step3+ simulation has not completed
- **THEN** feedback state marks the run awaiting high-fidelity samples and final reports SHALL treat candidates as non-final

#### Scenario: Blocked sample preserves search history
- **WHEN** a promoted simulation attempt fails or lacks proof
- **THEN** feedback state records the blocked attempt and Step2/Step3 SHALL not silently replace it with a trusted prediction
