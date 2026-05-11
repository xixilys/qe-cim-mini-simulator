# distributed-system-contract Specification

## Purpose
Define the distributed system contract for multi-node DSE, including network topology modeling, link quality attributes, collective communication primitives, hierarchical failure domains, routing algorithms, and distributed mapping strategies. This spec extends the single-node `SystemArchitecture` to support clusters, datacenters, and geographically distributed systems.

## Requirements

### Requirement: Distributed topology is explicit and typed
DistributedSystem SHALL model the network topology as one of `fat-tree`, `torus`, `dragonfly`, `mesh`, or `custom`. Custom topologies SHALL carry enough structural metadata to reconstruct node adjacency and hierarchy. The topology type SHALL constrain validation and communication cost modeling.

#### Scenario: Topology type constrains validation
- **WHEN** a design point declares `topology_type="torus"`
- **THEN** the system validates torus-consistent adjacency (wrap-around links) and rejects incompatible link layouts

#### Scenario: Fat-tree topology is validated
- **WHEN** a design point declares `topology_type="fat-tree"`
- **THEN** the system validates that link bandwidth increases toward the root and that oversubscription ratios are consistent

#### Scenario: Custom topology is serializable
- **WHEN** a design point uses `topology_type="custom"`
- **THEN** the topology metadata preserves node adjacency, hierarchy, and topology parameters for later analysis and replay

#### Scenario: Unknown topology type is rejected
- **WHEN** a design point declares an unsupported topology type
- **THEN** validation fails with `unsupported_topology_type` error

### Requirement: Network links model full transport quality
NetworkLink SHALL model `bandwidth_gbps`, `latency_us`, `jitter_us`, `reliability` (0.0-1.0), and `congestion_model` in addition to endpoints and link type. Communication cost SHALL incorporate these attributes when estimating transfer time, uncertainty, and feasibility.

#### Scenario: Jitter increases transfer uncertainty
- **WHEN** a transfer traverses a link with `jitter_us=10.0`
- **THEN** the evaluator reports a latency interval `[base_latency, base_latency + jitter]` rather than a single point estimate

#### Scenario: Low reliability marks risky communication
- **WHEN** a path includes links with `reliability < 0.99` and the workload requires high availability
- **THEN** the design point is marked `degraded` or `infeasible` with a `low_reliability_path` violation

#### Scenario: Congestion model affects bandwidth
- **WHEN** multiple transfers share a link and the congestion model is `fifo`
- **THEN** the effective bandwidth per transfer is reduced proportionally to the number of concurrent flows

#### Scenario: Link type determines default properties
- **WHEN** a link has `link_type="infiniband"`
- **THEN** default properties are bandwidth=200 Gbps, latency=1.0 us, jitter=0.5 us, reliability=0.9999 unless explicitly overridden

### Requirement: Collective communication primitives are first-class
DistributedSystem SHALL declare support for collective primitives: `all-reduce`, `broadcast`, `gather`, `scatter`, `all-gather`, `reduce-scatter`. Primitive cost SHALL be topology-aware and SHALL differ from naive point-to-point cost aggregation.

#### Scenario: All-reduce uses collective cost model
- **WHEN** a workload requests `all-reduce` across N nodes with total data size D
- **THEN** the evaluator uses the declared collective primitive cost (e.g., `2*(N-1)/N * D * bandwidth` for ring all-reduce) rather than summing pairwise sends

#### Scenario: Broadcast uses tree-based cost
- **WHEN** a workload requests `broadcast` in a fat-tree topology
- **THEN** the evaluator models tree-based broadcast cost with logarithmic depth rather than linear pairwise sends

#### Scenario: Unsupported collective is rejected
- **WHEN** a mapping requires `reduce-scatter` on a system that does not declare it in `supported_collectives`
- **THEN** the design point is infeasible with `unsupported_collective_primitive` violation

#### Scenario: Collective primitive list is validated
- **WHEN** a DistributedSystem is instantiated
- **THEN** validation checks that declared collectives are a subset of the standard primitive set and that topology supports them

### Requirement: Failure domains are hierarchical and preserved
DistributedSystem SHALL represent failure domains at `node`, `rack`, `cluster`, `datacenter`, and `region` levels. Failure-domain metadata SHALL be preserved in serialization and used for placement and resilience checks.

#### Scenario: Placement avoids shared failure domain
- **WHEN** two redundant replicas are mapped for fault tolerance
- **THEN** the mapper places them in different failure domains at the requested level or reports a `shared_failure_domain` violation

#### Scenario: Rack failure domain is preserved
- **WHEN** a distributed design point is serialized
- **THEN** each node's `rack_id`, `cluster_id`, `datacenter_id`, and `region_id` remain available to downstream analysis

#### Scenario: Failure domain hierarchy is validated
- **WHEN** a node declares `rack_id="rack-0"` and `cluster_id="cluster-0"`
- **THEN** validation checks that the rack belongs to the declared cluster; mismatches are reported as `invalid_failure_domain_hierarchy`

### Requirement: Routing algorithm is selectable
DistributedSystem SHALL support `shortest-path`, `adaptive`, and `oblivious` routing modes. Route selection SHALL affect estimated communication cost and congestion exposure.

#### Scenario: Shortest-path routing is deterministic
- **WHEN** routing mode is `shortest-path`
- **THEN** the evaluator chooses the minimum-hop or minimum-cost path according to declared link weights; the same source-destination pair always uses the same path

#### Scenario: Adaptive routing mitigates congestion
- **WHEN** a path is congested and routing mode is `adaptive`
- **THEN** the evaluator considers an alternate valid route with lower congestion if one exists

#### Scenario: Oblivious routing provides worst-case bounds
- **WHEN** routing mode is `oblivious`
- **THEN** the evaluator uses Valiant-style randomization or predetermined multi-path to provide worst-case congestion bounds

#### Scenario: Invalid routing mode is rejected
- **WHEN** a design point declares an unsupported routing mode
- **THEN** validation fails with `unsupported_routing_mode` error

### Requirement: Distributed mapping strategy is explicit
DistributedSystem SHALL record the distributed mapping strategy used by the workload, including `data-parallel`, `model-parallel`, `pipeline-parallel`, and `hybrid`. The mapping strategy SHALL determine communication pattern, placement constraints, and cost decomposition.

#### Scenario: Data parallel uses gradient collective
- **WHEN** a workload is marked `data-parallel`
- **THEN** the evaluator includes gradient synchronization traffic, typically via `all-reduce`, proportional to model size and node count

#### Scenario: Model parallel adds tensor sharding traffic
- **WHEN** a workload is marked `model-parallel`
- **THEN** the evaluator models activation/gradient transfer between shards as explicit inter-node flows with sizes derived from tensor specs

#### Scenario: Pipeline parallel adds stage-to-stage traffic
- **WHEN** a workload is marked `pipeline-parallel`
- **THEN** the evaluator models activation transfer between adjacent pipeline stages as an explicit inter-node flow

#### Scenario: Hybrid strategy combines patterns
- **WHEN** a workload is marked `hybrid` with `data-parallel=4` and `model-parallel=2`
- **THEN** the evaluator models both intra-group data-parallel all-reduce and inter-group model-parallel tensor transfers

### Requirement: Inter-node communication cost is distinguishable from intra-node
DistributedSystem SHALL distinguish intra-node communication (within the same Node) from inter-node communication. Intra-node communication SHALL use the local SystemArchitecture interconnect; inter-node communication SHALL use NetworkLink attributes.

#### Scenario: Same-node transfer uses local bandwidth
- **WHEN** a producer and consumer are on the same node
- **THEN** transfer cost uses the node's local interconnect bandwidth (e.g., NVLink, shared memory) rather than inter-node network bandwidth

#### Scenario: Cross-node transfer uses network link
- **WHEN** a producer and consumer are on different nodes
- **THEN** transfer cost uses the NetworkLink bandwidth, latency, and congestion model along the selected route

#### Scenario: Multi-hop transfer accumulates cost
- **WHEN** nodes are not directly connected and routing requires multiple hops
- **THEN** total transfer cost is the sum of per-hop latency plus the bottleneck bandwidth along the path

### Requirement: Distributed system supports single-node degeneracy
DistributedSystem SHALL support single-node systems as a degenerate case. A single-node DistributedSystem SHALL behave identically to a standalone SystemArchitecture for backward compatibility.

#### Scenario: Single-node system has zero inter-node cost
- **WHEN** a DistributedSystem contains exactly one node
- **THEN** all inter-node communication costs are zero and the system behaves as a single-node architecture

#### Scenario: Single-node system omits network links
- **WHEN** a DistributedSystem contains exactly one node
- **THEN** validation permits empty `network_links` and ignores routing mode and collective primitives
