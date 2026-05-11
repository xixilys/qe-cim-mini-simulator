# observability-contract Specification

## Purpose
Define the observability contract for metrics, logs, traces, and alerts in the DSE framework. This spec ensures that the system is observable, debuggable, and auditable through comprehensive telemetry.

## Requirements

### Requirement: Metrics are emitted for all key operations
The system SHALL emit metrics for all key operations including workload ingestion, mapping search, simulation execution, and report generation. Metrics SHALL include counters, gauges, histograms, and timers.

#### Scenario: Evaluation metrics are emitted
- **WHEN** an evaluation completes
- **THEN** metrics are emitted for `evaluation_duration_ms`, `evaluation_status`, `fidelity_level`, and `resource_usage`

#### Scenario: Mapping search metrics are emitted
- **WHEN** mapping search completes
- **THEN** metrics are emitted for `search_duration_ms`, `candidates_generated`, `candidates_pruned`, and `legality_matrix_size`

#### Scenario: Trust gate metrics are emitted
- **WHEN** the TrustGate evaluates a candidate
- **THEN** metrics are emitted for `trust_gate_decisions_total`, `trust_gate_rejections_total`, and `trust_gate_latency_ms`

### Requirement: Logs are structured and searchable
All logs SHALL be structured (JSON) and include timestamp, severity, component, message, and context. Logs SHALL be searchable and filterable.

#### Scenario: Structured log is written
- **WHEN** an event occurs
- **THEN** a JSON log entry is written with `timestamp`, `severity`, `component`, `message`, and `context`

#### Scenario: Log severity levels are respected
- **WHEN** a log entry has severity `ERROR`
- **THEN** it is written to `error.log` and triggers an alert if configured

#### Scenario: Log rotation prevents disk exhaustion
- **WHEN** a log file exceeds `max_log_size_mb`
- **THEN** the log is rotated and old logs are archived or deleted according to retention policy

### Requirement: Distributed traces track cross-component flows
The system SHALL support distributed tracing to track requests across components including workload ingestion, mapping search, simulation, and reporting.

#### Scenario: Trace spans evaluation pipeline
- **WHEN** a workload is evaluated
- **THEN** a trace spans from workload ingestion through mapping search, simulation, and report generation

#### Scenario: Trace includes error details
- **WHEN** an error occurs during evaluation
- **THEN** the trace includes error details, stack trace, and recovery actions

#### Scenario: Trace sampling is configurable
- **WHEN** trace volume is high
- **THEN** the system supports configurable sampling (e.g., 1% of traces) to reduce overhead

### Requirement: Alerts are generated for critical events
The system SHALL generate alerts for critical events including system failures, resource exhaustion, security violations, and trust gate rejections.

#### Scenario: Critical alert is generated
- **WHEN** a system failure occurs (e.g., simulator crash, disk full)
- **THEN** an alert is generated with severity `CRITICAL`, description, and recommended action

#### Scenario: Warning alert is generated
- **WHEN** a resource approaches its limit (e.g., memory at 80%)
- **THEN** an alert is generated with severity `WARNING` and recommended action

#### Scenario: Alert deduplication prevents spam
- **WHEN** the same alert condition persists
- **THEN** duplicate alerts are suppressed and the original alert is updated with duration

### Requirement: Health checks report system status
The system SHALL support health checks that report the status of all components including orchestrator, evaluators, simulators, and storage.

#### Scenario: Health check returns status
- **WHEN** a health check is requested
- **THEN** the response includes `status` (healthy/degraded/unhealthy), `component_status`, and `last_check_time`

#### Scenario: Degraded health triggers alert
- **WHEN** a component reports degraded status
- **THEN** a `WARNING` alert is generated with component name and degradation reason

### Requirement: Telemetry is configurable and extensible
The system SHALL support configurable telemetry backends including Prometheus, Grafana, Jaeger, and custom exporters. Telemetry configuration SHALL be hot-reloadable.

#### Scenario: Prometheus metrics are exposed
- **WHEN** Prometheus scraping is enabled
- **THEN** metrics are exposed at `/metrics` endpoint in Prometheus format

#### Scenario: Jaeger traces are exported
- **WHEN** Jaeger tracing is enabled
- **THEN** traces are exported to Jaeger collector in OTLP format

#### Scenario: Custom exporter is supported
- **WHEN** a custom telemetry exporter is configured
- **THEN** the system loads and uses the exporter without code changes
