## ADDED Requirements

### Requirement: Step2 artifacts reference generic IR identities
Step2 artifacts SHALL reference workload package id, source graph id, executable graph id where present, node ids, region ids, tensor ids where available, architecture id, component ids, mapping id, candidate id, and evidence ids using stable serialized identifiers from the generic IR and architecture contracts.

#### Scenario: Mapping record resolves to graph and architecture entities
- **WHEN** a selected mapping record is written
- **THEN** every mapped node id resolves to an executable graph node or declared summarized region, and every target id resolves to host fallback or an architecture component/resource id

#### Scenario: Unknown entity reference fails validation
- **WHEN** a Step2 artifact references a node, region, tensor, architecture resource, or candidate id that is absent from the relevant persisted artifact
- **THEN** validation reports the unresolved reference before the candidate can be promoted as trusted-final eligible

### Requirement: Step2 preserves claim boundary and coverage metadata
Step2 SHALL carry forward workload claim boundary, workflow family, required coverage, unsupported constructs, approximation labels, and adapter-domain validation boundary from Step1 into DesignPoint, mapping, promotion, and feedback artifacts. Step2 SHALL NOT widen a reduced, diagnostic, trace-only, smoke, or unsupported workload into a full-workload claim.

#### Scenario: Reduced workload stays non-final through Step2
- **WHEN** Step1 labels a workload reduced, diagnostic-only, synthetic, trace-only, smoke-only, or unsupported
- **THEN** Step2 propagates that boundary to candidate and mapping artifacts and prevents trusted full-workload promotion

#### Scenario: Required coverage is available for later simulation
- **WHEN** Step2 promotes a candidate to Step3+ simulation
- **THEN** the promoted candidate record includes or references the required coverage items that Step3+ evidence must emit
