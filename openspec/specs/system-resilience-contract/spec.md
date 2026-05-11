# system-resilience-contract Specification

## Purpose
Define the system resilience contract for fault tolerance, error recovery, retry strategies, checkpoint/restart, and graceful degradation in the DSE framework. This spec ensures that DSE runs can survive partial failures, recover from errors, and provide meaningful diagnostics without losing audit trail integrity.

## Requirements

### Requirement: System supports configurable retry policies
The system SHALL support configurable retry policies for transient failures including network timeouts, simulator crashes, and temporary resource unavailability. Retry policies SHALL specify max attempts, backoff strategy, and retryable error types.

#### Scenario: Transient simulator failure triggers retry
- **WHEN** a SystemC simulation fails with `SIGSEGV` or timeout and `retry_policy.max_attempts > 1`
- **THEN** the system waits for `backoff_duration` and retries the simulation up to `max_attempts`

#### Scenario: Permanent failure stops retry
- **WHEN** a simulation fails with a non-retryable error (e.g., `invalid_architecture`, `unsupported_operator`)
- **THEN** the system does not retry and records the failure as permanent

#### Scenario: Exponential backoff prevents thundering herd
- **WHEN** multiple simulations fail simultaneously due to shared resource contention
- **THEN** retry backoff uses exponential jitter to prevent synchronized retry storms

### Requirement: Checkpoint mechanism preserves DSE state
The system SHALL support periodic checkpoints that preserve the complete DSE state including search space, evaluated candidates, feedback state, and ranking. Checkpoints SHALL enable restart from the last consistent state after system failure.

#### Scenario: Checkpoint writes complete state
- **WHEN** a checkpoint is triggered (periodic or on-demand)
- **THEN** the system writes `dse_checkpoint.json` containing all candidate states, evaluation results, feedback state, and random seed

#### Scenario: Restart from checkpoint resumes search
- **WHEN** a DSE run is interrupted and later restarted from a checkpoint
- **THEN** the system resumes from the last checkpoint without re-evaluating already-completed candidates

#### Scenario: Corrupted checkpoint is detected
- **WHEN** a checkpoint file is corrupted or incomplete
- **THEN** the system falls back to the previous valid checkpoint or restarts from scratch with a warning

### Requirement: Graceful degradation handles resource constraints
When resources are constrained (memory, disk, compute), the system SHALL degrade gracefully rather than crashing. Degradation strategies include reducing parallelism, simplifying evaluation fidelity, or pausing non-critical tasks.

#### Scenario: Memory pressure reduces parallelism
- **WHEN** system memory usage exceeds `memory_threshold_percent`
- **THEN** the system reduces concurrent evaluations and writes a `degradation_event` to the log

#### Scenario: Disk full pauses artifact generation
- **WHEN** available disk space drops below `min_disk_bytes`
- **THEN** the system pauses non-essential artifact generation and alerts the operator

#### Scenario: Compute saturation lowers fidelity
- **WHEN** CPU utilization exceeds `cpu_threshold_percent` for sustained period
- **THEN** the system may temporarily switch new candidates to L1/L2 screening instead of L3 simulation

### Requirement: Error isolation prevents cascade failures
Errors in one component SHALL NOT cascade to other components or corrupt shared state. Each evaluation SHALL be isolated such that a crashing simulator does not affect the DSE orchestrator or other concurrent evaluations.

#### Scenario: Simulator crash is isolated
- **WHEN** a single SystemC simulator instance crashes
- **THEN** the DSE orchestrator continues running other candidates and records the crash as a failed evaluation

#### Scenario: Corrupted result is quarantined
- **WHEN** an evaluation produces a result that fails schema validation
- **THEN** the result is quarantined and does not enter ranking or feedback loops

#### Scenario: Memory leak in evaluator is contained
- **WHEN** an evaluator process leaks memory
- **THEN** the process is terminated after `max_memory_mb` and resources are reclaimed

### Requirement: Audit trail survives failures
All audit artifacts SHALL be written durably before being acknowledged. In-flight evaluations SHALL leave sufficient traces to reconstruct what was attempted even if the evaluation itself fails.

#### Scenario: Failed evaluation leaves audit trail
- **WHEN** an evaluation fails after starting but before completing
- **THEN** the system writes `evaluation_attempt.json` with start time, input artifacts, and failure reason

#### Scenario: Partial results are preserved
- **WHEN** an evaluation produces partial results before crashing
- **THEN** the partial results are preserved with `status="partial"` and `completion_percent`

### Requirement: System supports cancellation and cleanup
The system SHALL support graceful cancellation of in-progress DSE runs with proper cleanup of resources, processes, and temporary files.

#### Scenario: Cancel signal stops new evaluations
- **WHEN** a DSE run receives a cancel signal (SIGINT, SIGTERM)
- **THEN** the system stops accepting new candidates, waits for in-flight evaluations to complete or timeout, and writes final state

#### Scenario: Force cancel terminates immediately
- **WHEN** a DSE run receives a force-cancel signal (SIGKILL or second SIGINT)
- **THEN** the system terminates immediately after writing emergency checkpoint

#### Scenario: Cleanup removes temporary files
- **WHEN** a DSE run completes or is cancelled
- **THEN** temporary files in `temp/` are removed while preserving required artifacts in `runs/`
