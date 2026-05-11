## ADDED Requirements

### Requirement: Architecture catalog supports Step2 candidate generation
The architecture catalog SHALL provide Step2 with versioned architecture families, component types, parameter schemas, architecture instances, constraint sets, simulation bindings, status labels, and trusted-final eligibility metadata. The catalog SHALL support multiple extensible families rather than a single fixed reference architecture.

#### Scenario: Catalog emits concrete architecture instance
- **WHEN** Step2 selects a family and valid parameter assignment
- **THEN** the catalog emits an architecture instance with resolved components, memory hierarchy, interconnect, constraints, binding metadata, and validation status

#### Scenario: Multiple architecture families are reviewable
- **WHEN** a reviewer inspects the seed architecture catalog
- **THEN** the catalog distinguishes baseline, balanced, memory-rich, streaming-heavy, low-power, debug, future/custom, and legacy/reference families where present

### Requirement: Architecture validation gates Step2 trusted eligibility
Architecture validation SHALL check duplicate identifiers, units, required component fields, operator and precision support, memory capacity, communication routes, power/area/cost budgets, fallback policy compatibility, and simulation binding coverage before Step2 marks an instance eligible for trusted high-fidelity sampling.

#### Scenario: Validation failure downgrades candidate
- **WHEN** an architecture instance violates constraints or lacks required binding coverage
- **THEN** Step2 records structured validation reasons and marks the instance candidate-only or blocked rather than trusted-final eligible

#### Scenario: Valid binding enables simulation promotion
- **WHEN** an architecture instance has a compatible SystemC or gem5+SystemC binding for the selected workload and mapping
- **THEN** Step2 can promote a candidate using that instance to the simulation queue subject to mapping legality and budget
