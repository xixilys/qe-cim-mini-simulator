#pragma once

#include <string>
#include <vector>
#include <map>
#include <memory>
#include <optional>

namespace gsim {

// Forward declarations
struct ComputeNode;
struct DataEdge;
struct ComputeGraph;
struct AcceleratorDesc;
struct SystemArchitecture;
struct SimulationRequest;
struct SimulationResult;

// Compute node in workload graph
struct ComputeNode {
    std::string node_id;
    std::string op_type;
    std::vector<std::string> inputs;
    std::vector<std::string> outputs;
    double estimated_flops = 0.0;
    double estimated_memory_bytes = 0.0;
    std::map<std::string, std::string> attributes;
};

// Data dependency edge
struct DataEdge {
    std::string source;
    std::string target;
    std::string tensor_name;
    std::vector<int> tensor_shape;
    std::string tensor_dtype = "FP64";
};

// Complete workload graph
struct ComputeGraph {
    std::string graph_id;
    std::map<std::string, ComputeNode> nodes;
    std::vector<DataEdge> edges;
    std::map<std::string, std::string> metadata;
};

// Accelerator capability for specific operation
struct OpCapability {
    double peak_gops = 0.0;
    double efficiency = 0.5;
};

// Accelerator description
struct AcceleratorDesc {
    std::string accel_id;
    std::string accel_type;  // "gpu", "fpga", "cim", "asic", "cpu"
    double clock_mhz = 250.0;
    double local_memory_kb = 2048.0;
    struct {
        double static_w = 0.0;
        double max_w = 100.0;
    } power;
    std::map<std::string, OpCapability> capabilities;
};

// Host description
struct HostDesc {
    std::string cpu_model = "abstract";
    double clock_mhz = 3000.0;
    double memory_bw_gbps = 100.0;
    int cores = 1;
};

// Interconnect description
struct InterconnectDesc {
    std::string type = "pcie";  // "pcie", "nvlink", "cxl", "custom"
    double bandwidth_gbps = 64.0;
    double latency_ns = 800.0;
};

// System architecture
struct SystemArchitecture {
    HostDesc host;
    std::optional<InterconnectDesc> interconnect;
    std::vector<AcceleratorDesc> accelerators;
};

// Task mapping
using MappingDesc = std::map<std::string, std::string>;  // node_id -> accel_id

// Scheduling policy
struct SchedulingDesc {
    std::string policy = "static";  // "static", "dynamic", "pipeline"
    bool allow_overlap_dma_compute = true;
    bool double_buffer = true;
};

// Output configuration
struct OutputConfig {
    std::string result_json;
    std::string trace_json;
};

// Complete simulation request
struct SimulationRequest {
    std::string schema_version = "gsim.request.v1";
    std::string run_id;
    std::string mode = "standalone_systemc";
    ComputeGraph workload;
    SystemArchitecture architecture;
    MappingDesc mapping;
    SchedulingDesc scheduling;
    OutputConfig output;
};

// Event in execution trace
struct TraceEvent {
    std::string node_id;
    std::string device;
    double start_ns = 0.0;
    double end_ns = 0.0;
    std::string op_type;
};

// Resource utilization for a device
struct ResourceUtilization {
    double compute_percent = 0.0;
    double memory_percent = 0.0;
    double bandwidth_percent = 0.0;
};

// Uncertainty metrics
struct UncertaintyMetrics {
    std::string fidelity_level = "L3";
    double confidence_level = 0.85;
    double mape_percent = 15.0;
};

// Complete simulation result
struct SimulationResult {
    std::string schema_version = "gsim.result.v1";
    std::string run_id;
    std::string status = "passed";  // "passed", "failed", "timeout", "error"
    std::string error_message;
    
    struct {
        double latency_ms = 0.0;
        double host_time_ms = 0.0;
        double device_time_ms = 0.0;
        double dma_time_ms = 0.0;
        double throughput_gops = 0.0;
        double power_w = 0.0;
        double energy_j = 0.0;
        double area_mm2 = 0.0;
        double total_data_movement_mb = 0.0;
    } metrics;
    
    std::map<std::string, ResourceUtilization> resource_utilization;
    std::vector<TraceEvent> events;
    UncertaintyMetrics uncertainty;
};

} // namespace gsim
