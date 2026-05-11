# distributed-mapping-contract Specification

## Purpose
Define the distributed mapping contract for data-parallel, model-parallel, pipeline-parallel, and hybrid strategies across multi-node systems. This spec extends the single-node mapping search to support distributed placement, communication pattern modeling, and cost decomposition for parallel workloads.

## Requirements

### Requirement: Distributed mapping strategies are explicit and typed
The system SHALL support distributed mapping strategies: `data-parallel`, `model-parallel`, `pipeline-parallel`, and `hybrid`. Each strategy SHALL declare its communication pattern, placement constraints, and cost decomposition. The strategy SHALL be recorded in the DesignPoint and validated by the mapping search.

#### Scenario: Data parallel strategy is declared
- **WHEN** a workload is marked `data-parallel` with `replication_factor=4`
- **THEN** the DesignPoint records the strategy, the mapping places identical copies on 4 nodes, and the evaluator models gradient synchronization via `all-reduce`

#### Scenario: Model parallel strategy is declared
- **WHEN** a workload is marked `model-parallel` with `shard_count=2`
- **THEN** the DesignPoint records the strategy, the mapping splits layers/tensors across 2 nodes, and the evaluator models activation/gradient transfer between shards

#### Scenario: Pipeline parallel strategy is declared
- **WHEN** a workload is marked `pipeline-parallel` with `stage_count=4`
- **THEN** the DesignPoint records the strategy, the mapping assigns pipeline stages to 4 nodes, and the evaluator models stage-to-stage activation transfer

#### Scenario: Hybrid strategy combines approaches
- **WHEN** a workload is marked `hybrid` with `data-parallel=2` and `model-parallel=2`
- **THEN** the DesignPoint records both strategies, the mapping creates 2 model-parallel groups each with 2 data-parallel replicas, and the evaluator models both intra-group all-reduce and inter-group tensor transfers

#### Scenario: Unknown strategy is rejected
- **WHEN** a workload declares an unsupported distributed strategy
- **THEN** validation fails with `unsupported_distributed_strategy` error

### Requirement: Data parallel placement enforces replication consistency
Data-parallel mapping SHALL place identical workload copies on different nodes. The legality matrix SHALL ensure that each replica can execute the full workload and that replicas are placed in distinct failure domains when fault tolerance is required.

#### Scenario: Replicas are placed on different nodes
- **WHEN** `data-parallel` with `replication_factor=4` is requested on a 4-node system
- **THEN** each replica is placed on a different node; placing two replicas on the same node is illegal unless `allow_intra_node_replication=true`

#### Scenario: Replicas avoid shared failure domain
- **WHEN** fault tolerance requires rack-level isolation and `replication_factor=2`
- **THEN** replicas are placed in different racks; shared-rack placement is recorded as a `failure_domain_violation`

#### Scenario: Gradient synchronization is modeled
- **WHEN** `data-parallel` is evaluated
- **THEN** the evaluator adds an `all-reduce` communication cost proportional to `model_size * (replication_factor - 1) / replication_factor` per training step

### Requirement: Model parallel placement respects tensor dependencies
Model-parallel mapping SHALL split tensors or layers across nodes while preserving data dependencies. The legality matrix SHALL ensure that producer-consumer relationships across shards are supported by inter-node links.

#### Scenario: Layer sharding preserves dependencies
- **WHEN** a neural network with 8 layers is sharded across 2 nodes with `shard_count=2`
- **THEN** layers 0-3 are on node-0 and layers 4-7 are on node-1; the dependency between layer 3 and layer 4 is modeled as an inter-node transfer

#### Scenario: Tensor sharding respects communication bandwidth
- **WHEN** a tensor is sharded across nodes with insufficient inter-node bandwidth
- **THEN** the design point is marked `infeasible` with `insufficient_shard_communication_bandwidth` violation

#### Scenario: Model parallel adds inter-shard traffic
- **WHEN** `model-parallel` is evaluated
- **THEN** the evaluator adds communication costs for activations (forward pass) and gradients (backward pass) between adjacent shards

### Requirement: Pipeline parallel placement models stage throughput
Pipeline-parallel mapping SHALL assign stages to nodes such that stage throughput is balanced. The evaluator SHALL model pipeline bubble overhead, stage-to-stage transfer latency, and pipeline fill/drain time.

#### Scenario: Pipeline stages are balanced
- **WHEN** a workload is divided into 4 pipeline stages
- **THEN** the mapping search attempts to balance stage latency; imbalanced stages are flagged with `pipeline_imbalance` warning

#### Scenario: Pipeline bubble is modeled
- **WHEN** `pipeline-parallel` with `stage_count=4` and `microbatch_count=8` is evaluated
- **THEN** the evaluator adds pipeline bubble overhead: `(stage_count - 1) * max_stage_latency` per macrobatch

#### Scenario: Stage-to-stage transfer is modeled
- **WHEN** adjacent pipeline stages are on different nodes
- **THEN** the evaluator models activation transfer cost using the inter-node NetworkLink attributes

### Requirement: Hybrid strategy decomposes communication patterns
Hybrid mapping SHALL decompose the communication pattern into intra-group and inter-group components. The evaluator SHALL model each component separately and sum them for total communication cost.

#### Scenario: Hybrid data+model parallel decomposes costs
- **WHEN** `hybrid` with `data-parallel=2` and `model-parallel=2` is evaluated
- **THEN** the evaluator models:
  - Intra-group all-reduce for gradient synchronization (2 replicas per group)
  - Inter-group tensor transfers for model-parallel shards

#### Scenario: Hybrid pipeline+data parallel decomposes costs
- **WHEN** `hybrid` with `pipeline-parallel=4` and `data-parallel=2` is evaluated
- **THEN** the evaluator models:
  - Pipeline stage-to-stage transfers within each data-parallel replica
  - All-reduce across data-parallel replicas for each pipeline stage

### Requirement: Distributed legality matrix includes communication feasibility
The legality matrix for distributed systems SHALL include communication feasibility checks in addition to single-node legality checks.

#### Scenario: Inter-node link supports required bandwidth
- **WHEN** a mapping requires 100 Gbps between two nodes
- **THEN** the legality matrix checks that the NetworkLink bandwidth is >= 100 Gbps; insufficient bandwidth marks the placement illegal

#### Scenario: Collective primitive is supported
- **WHEN** a mapping requires `all-reduce` across 4 nodes
- **THEN** the legality matrix checks that all 4 nodes support `all-reduce`; unsupported nodes mark the placement illegal

#### Scenario: Routing path exists
- **WHEN** a mapping requires communication between two nodes with no direct or multi-hop path
- **THEN** the legality matrix marks the placement illegal with `no_route_between_nodes` violation

### Requirement: Distributed mapping artifacts record strategy and decomposition
Distributed mapping artifacts SHALL record the distributed strategy, replication factors, shard counts, stage assignments, and communication pattern decomposition.

#### Scenario: Mapping artifact includes distributed strategy
- **WHEN** a distributed DesignPoint is persisted
- **THEN** `mapping.json` includes `distributed_strategy`, `replication_factor`, `shard_count`, `stage_count`, and `communication_pattern`

#### Scenario: Mapping artifact includes stage assignments
- **WHEN** `pipeline-parallel` is used
- **THEN** `mapping.json` includes `stage_assignments` mapping stage ids to node ids

#### Scenario: Mapping artifact includes shard assignments
- **WHEN** `model-parallel` is used
- **THEN** `mapping.json` includes `shard_assignments` mapping tensor/layer ids to node ids

### Requirement: Distributed mapping supports single-node degeneracy
Distributed mapping SHALL support single-node systems as a degenerate case. On a single node, distributed strategies SHALL reduce to single-node mapping with zero inter-node communication cost.

#### Scenario: Single-node data parallel is single replica
- **WHEN** `data-parallel` is requested on a single-node system
- **THEN** `replication_factor` is capped at 1 and no all-reduce cost is added

#### Scenario: Single-node model parallel is single shard
- **WHEN** `model-parallel` is requested on a single-node system
- **THEN** `shard_count` is capped at 1 and no inter-shard transfer cost is added

#### Scenario: Single-node pipeline parallel is single stage
- **WHEN** `pipeline-parallel` is requested on a single-node system
- **THEN** `stage_count` is capped at 1 and no stage-to-stage transfer cost is added
