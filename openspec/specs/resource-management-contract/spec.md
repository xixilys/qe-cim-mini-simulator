# resource-management-contract Specification

## Purpose
Define the resource management contract for memory, disk, CPU, and network resource limits in the DSE framework. This spec ensures that resource exhaustion is handled gracefully, prevents resource leaks, and maintains system stability under load.

## Requirements

### Requirement: Memory usage is bounded and monitored
The system SHALL enforce memory limits for all components including evaluators, simulators, and the orchestrator. Memory usage SHALL be monitored and bounded to prevent out-of-memory crashes.

#### Scenario: Memory limit prevents OOM crash
- **WHEN** an evaluator process exceeds `max_memory_mb`
- **THEN** the process is terminated with `memory_limit_exceeded` status and resources are reclaimed

#### Scenario: Memory pressure triggers graceful degradation
- **WHEN** system memory usage exceeds `memory_pressure_threshold_percent` (e.g., 85%)
- **THEN** the system reduces concurrent evaluations and writes a `memory_pressure_event` to the log

#### Scenario: Memory leak is detected and contained
- **WHEN** an evaluator's memory grows monotonically without bound
- **THEN** the system detects the leak after `memory_growth_threshold_mb` and terminates the process

### Requirement: Disk usage is bounded and monitored
The system SHALL enforce disk space limits for artifact directories, temporary files, and logs. Disk usage SHALL be monitored to prevent disk-full errors.

#### Scenario: Disk full blocks non-essential writes
- **WHEN** available disk space drops below `min_disk_bytes` (e.g., 1 GB)
- **THEN** the system pauses non-essential artifact generation and alerts the operator

#### Scenario: Artifact size limit prevents disk exhaustion
- **WHEN** a single artifact exceeds `max_artifact_size_mb`
- **THEN** the artifact is truncated or rejected with `artifact_too_large` error

#### Scenario: Temporary files are cleaned up
- **WHEN** a DSE run completes or fails
- **THEN** temporary files in `temp/` are removed while preserving required artifacts in `runs/`

### Requirement: CPU usage is bounded and fair
The system SHALL enforce CPU limits and ensure fair scheduling across concurrent evaluations. CPU-intensive tasks SHALL not starve other tasks.

#### Scenario: CPU limit prevents starvation
- **WHEN** an evaluator process exceeds `max_cpu_percent` for sustained period
- **THEN** the process is throttled or terminated to ensure fair scheduling

#### Scenario: CPU saturation triggers fidelity reduction
- **WHEN** CPU utilization exceeds `cpu_saturation_threshold` (e.g., 90%) for `saturation_duration`
- **THEN** new candidates are temporarily screened at L1/L2 instead of L3 simulation

### Requirement: Network usage is bounded
The system SHALL enforce network bandwidth limits for distributed simulations, data transfers, and remote artifact storage.

#### Scenario: Network bandwidth limit prevents congestion
- **WHEN** a distributed simulation exceeds `max_network_mbps`
- **THEN** the transfer is throttled or queued to prevent network congestion

#### Scenario: Network timeout prevents hung transfers
- **WHEN** a network transfer exceeds `network_timeout_seconds`
- **THEN** the transfer is aborted with `network_timeout` error and retried if configured

### Requirement: Resource limits are configurable per workload
Resource limits SHALL be configurable per workload family, architecture type, and evaluation fidelity level.

#### Scenario: ML workload gets higher memory limit
- **WHEN** an ML workload with large models is evaluated
- **THEN** the system applies `ml_workload_memory_multiplier` to the base memory limit

#### Scenario: L3 simulation gets higher CPU limit
- **WHEN** an L3 SystemC simulation is launched
- **THEN** the system applies `l3_cpu_multiplier` to the base CPU limit

### Requirement: Resource usage is observable
The system SHALL expose resource usage metrics including memory, disk, CPU, and network utilization for monitoring and debugging.

#### Scenario: Resource metrics are emitted
- **WHEN** an evaluation completes
- **THEN** `resource_usage.json` is written with peak memory, disk, CPU, and network usage

#### Scenario: Resource alerts are generated
- **WHEN** resource usage exceeds warning thresholds
- **THEN** the system generates `resource_alert` events with severity and recommended action
