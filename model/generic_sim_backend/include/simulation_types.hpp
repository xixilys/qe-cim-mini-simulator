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

// Accelerator type enumeration for true heterogeneous support
enum class AccelType {
    FPGA = 0,
    CIM = 1,
    GPU = 2,
    ASIC = 3,
    CPU = 4,
    UNKNOWN = 5
};

// Convert string to AccelType (backward compatible with existing string-based code)
inline AccelType string_to_accel_type(const std::string& type_str) {
    if (type_str == "fpga" || type_str == "FPGA") return AccelType::FPGA;
    if (type_str == "cim" || type_str == "CIM") return AccelType::CIM;
    if (type_str == "gpu" || type_str == "GPU") return AccelType::GPU;
    if (type_str == "asic" || type_str == "ASIC") return AccelType::ASIC;
    if (type_str == "cpu" || type_str == "CPU") return AccelType::CPU;
    return AccelType::UNKNOWN;
}

// Convert AccelType to string
inline std::string accel_type_to_string(AccelType type) {
    switch (type) {
        case AccelType::FPGA: return "fpga";
        case AccelType::CIM: return "cim";
        case AccelType::GPU: return "gpu";
        case AccelType::ASIC: return "asic";
        case AccelType::CPU: return "cpu";
        default: return "unknown";
    }
}

// Microarchitecture configuration for true hardware modeling
// Each accelerator type has its own specific parameters
struct MicroarchitectureConfig {
    AccelType accel_type = AccelType::UNKNOWN;
    
    // FPGA-specific parameters
    int array_size = 0;           // Systolic array dimension (e.g., 16x16, 32x32)
    int local_sram_kb = 0;        // Local SRAM size in KB
    int dma_channels = 0;         // DMA channel count
    
    // CIM-specific parameters
    int crossbar_rows = 0;        // Crossbar row count
    int crossbar_cols = 0;        // Crossbar column count
    int adc_resolution = 0;       // ADC bit resolution (e.g., 8)
    int dac_resolution = 0;       // DAC bit resolution (e.g., 8)
    int peripheral_digital_units = 0; // Number of peripheral digital units
    
    // GPU-specific parameters
    int sm_count = 0;             // SM (Streaming Multiprocessor) count
    int shared_memory_kb = 0;     // Shared memory per SM in KB
    int warp_size = 0;            // Warp size (e.g., 32)
    int max_warps_per_sm = 0;     // Maximum warps per SM
    
    // ASIC-specific parameters
    int pipeline_stages = 0;      // Pipeline depth
    std::vector<int> custom_dims; // Custom datapath dimensions
    int vector_width = 0;         // Vector processing width
    
    // Common parameters
    int memory_ports = 0;         // Number of memory ports
    double memory_bandwidth_gbps = 0.0; // Memory bandwidth in GB/s
};

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
    double element_size = 0.0;
    double size_bytes = 0.0;
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

// Accelerator description with microarchitecture support
struct AcceleratorDesc {
    std::string accel_id;
    std::string accel_type_str;  // "gpu", "fpga", "cim", "asic", "cpu" (backward compatible)
    AccelType accel_type = AccelType::UNKNOWN;  // NEW: typed enumeration
    double clock_mhz = 250.0;
    double local_memory_kb = 2048.0;
    struct {
        double static_w = 0.0;
        double max_w = 100.0;
    } power;
    std::map<std::string, OpCapability> capabilities;
    MicroarchitectureConfig microarchitecture;  // NEW: v2 microarchitecture config
    
    // Helper to get AccelType from string (for backward compatibility)
    void resolve_accel_type() {
        if (accel_type == AccelType::UNKNOWN && !accel_type_str.empty()) {
            accel_type = string_to_accel_type(accel_type_str);
        }
    }
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
