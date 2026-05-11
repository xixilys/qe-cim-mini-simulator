## ADDED Requirements

### Requirement: Generic backend L4 proof is derived from real descriptor/request closure
The generic simulation backend integration SHALL mark gem5+SystemC evidence as trusted L4 only when the real gem5 path submits a descriptor or equivalent request to the SystemC backend and observes completion/result writeback through the guest-visible path.

#### Scenario: GenericAccel descriptor path drives SystemC request
- **WHEN** `Gem5SystemCClosureAdapter` runs the real L4 harness
- **THEN** the generated proof records gem5 descriptor/request ingestion and SystemC backend submission for the selected generic heterogeneous workload
- **AND** standalone TLM/MMIO compatibility output alone is not accepted as generic L4 closure

#### Scenario: SystemC status is included in L4 proof
- **WHEN** the SystemC backend returns a failed or malformed result during a real L4 run
- **THEN** the L4 proof fails and records the SystemC result status as the blocker
