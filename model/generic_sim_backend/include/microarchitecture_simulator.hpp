#pragma once

#include "simulation_types.hpp"
#include <cmath>

namespace gsim {

inline double tensor_dtype_bytes(const std::string& dtype) {
    if (dtype == "FP64" || dtype == "fp64" || dtype == "float64" || dtype == "double") return 8.0;
    if (dtype == "FP32" || dtype == "fp32" || dtype == "float32" || dtype == "single") return 4.0;
    if (dtype == "FP16" || dtype == "fp16" || dtype == "float16" || dtype == "BF16" || dtype == "bf16") return 2.0;
    if (dtype == "INT8" || dtype == "int8" || dtype == "UINT8" || dtype == "uint8") return 1.0;
    return 8.0;
}

inline double tensor_payload_bytes(const DataEdge& edge) {
    if (edge.size_bytes > 0.0) {
        return edge.size_bytes;
    }
    double tensor_size_bytes = tensor_dtype_bytes(edge.tensor_dtype);
    if (edge.element_size > 0.0) {
        tensor_size_bytes = edge.element_size;
    }
    for (int dim : edge.tensor_shape) {
        tensor_size_bytes *= dim;
    }
    return tensor_size_bytes;
}

// Microarchitecture simulator interface
// Each accelerator type implements this to provide true cycle-level simulation
class MicroarchitectureSimulator {
public:
    virtual ~MicroarchitectureSimulator() = default;
    
    // Simulate execution of a compute node on this microarchitecture
    // Returns cycle count (not time)
    virtual double simulate_compute_cycles(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const = 0;
    
    // Simulate data transfer through this accelerator's memory system
    // Returns cycle count for DMA/memory operations
    virtual double simulate_transfer_cycles(
        const DataEdge& edge,
        const AcceleratorDesc& accel,
        const std::string& src_device,
        const std::string& dst_device
    ) const = 0;
    
    // Calculate power consumption for this operation
    virtual double estimate_power_w(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const = 0;
    
    // Get accelerator type this simulator supports
    virtual AccelType get_supported_type() const = 0;
};

// FPGA Systolic Array Simulator
// Models a 2D systolic array with local SRAM and DMA engine
class FPGASystolicArraySimulator : public MicroarchitectureSimulator {
public:
    AccelType get_supported_type() const override { return AccelType::FPGA; }
    
    double simulate_compute_cycles(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const override {
        const auto& ma = accel.microarchitecture;
        if (ma.array_size <= 0) {
            // Fallback to simple model if no microarchitecture configured
            return fallback_cycles(node, accel);
        }
        
        // Systolic array execution model:
        // For GEMM: C[i][j] += A[i][k] * B[k][j]
        // Array size = N x N processing elements
        // Each PE performs one multiply-accumulate per cycle
        // Data flows in from top and left, results flow out to bottom/right
        
        double array_size = static_cast<double>(ma.array_size);
        double pes = array_size * array_size;  // Total processing elements
        
        // Calculate workload dimensions from FLOPS
        // For matrix multiply: flops = 2 * M * N * K
        // Assume square matrices for simplicity: M = N = K = sqrt(flops/2)
        double total_flops = node.estimated_flops;
        double matrix_dim = std::pow(total_flops / 2.0, 1.0 / 3.0);
        
        // Systolic array execution:
        // - Wavefront propagation: 2*N-1 cycles to fill array
        // - Compute: (M*N*K) / PEs cycles
        // - Drain: 2*N-1 cycles
        double fill_drain_cycles = 2.0 * array_size - 1.0;
        double compute_cycles = total_flops / pes;
        
        // Memory bandwidth limitation:
        // Need to feed array_size elements per cycle from SRAM
        double sram_bandwidth_bytes_per_cycle = 
            (ma.memory_bandwidth_gbps * 1e9) / (accel.clock_mhz * 1e6);
        double data_size_bytes = node.estimated_memory_bytes;
        double memory_cycles = data_size_bytes / sram_bandwidth_bytes_per_cycle;
        
        // Total cycles = max(compute, memory) + fill/drain overhead
        return std::max(compute_cycles, memory_cycles) + fill_drain_cycles;
    }
    
    double simulate_transfer_cycles(
        const DataEdge& edge,
        const AcceleratorDesc& accel,
        const std::string& src_device,
        const std::string& dst_device
    ) const override {
        if (src_device == dst_device) return 0.0;
        
        double tensor_size_bytes = tensor_payload_bytes(edge);
        
        // DMA transfer: setup + transfer time
        const auto& ma = accel.microarchitecture;
        double dma_channels = std::max(1, ma.dma_channels);
        double bandwidth_per_channel = (ma.memory_bandwidth_gbps * 1e9) / dma_channels;
        
        double setup_cycles = 10.0;  // DMA setup overhead
        double transfer_cycles = tensor_size_bytes / bandwidth_per_channel * (accel.clock_mhz * 1e6);
        
        return setup_cycles + transfer_cycles;
    }
    
    double estimate_power_w(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const override {
        const auto& ma = accel.microarchitecture;
        double static_power = accel.power.static_w;
        
        // Dynamic power based on array utilization
        double array_size = static_cast<double>(ma.array_size);
        double pes = array_size * array_size;
        double utilization = std::min(1.0, node.estimated_flops / (pes * accel.clock_mhz * 1e6));
        
        double dynamic_power = (accel.power.max_w - static_power) * utilization;
        return static_power + dynamic_power;
    }

private:
    double fallback_cycles(const ComputeNode& node, const AcceleratorDesc& accel) const {
        auto it = accel.capabilities.find(node.op_type);
        if (it != accel.capabilities.end()) {
            double peak_gops = it->second.peak_gops;
            double efficiency = it->second.efficiency;
            double actual_gops = peak_gops * efficiency;
            double ops_per_cycle = actual_gops * 1e9 / (accel.clock_mhz * 1e6);
            return node.estimated_flops / ops_per_cycle;
        }
        // Ultimate fallback
        double peak_gflops = accel.clock_mhz * 1e6 * 16 / 1e9;
        return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
    }
};

// CIM Crossbar Array Simulator
// Models compute-in-memory crossbar with ADC/DAC and peripheral digital logic
class CIMCrossbarSimulator : public MicroarchitectureSimulator {
public:
    AccelType get_supported_type() const override { return AccelType::CIM; }
    
    double simulate_compute_cycles(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const override {
        const auto& ma = accel.microarchitecture;
        if (ma.crossbar_rows <= 0 || ma.crossbar_cols <= 0) {
            return fallback_cycles(node, accel);
        }
        
        // CIM execution model:
        // Crossbar performs matrix-vector multiplication in analog domain
        // Each crossbar cell stores one weight value
        // Input vector is converted by DAC, multiplied in parallel, sensed by ADC
        
        double crossbar_size = static_cast<double>(ma.crossbar_rows);
        double total_cells = static_cast<double>(ma.crossbar_rows * ma.crossbar_cols);
        
        // For matrix-vector: output[j] = sum_i(input[i] * weight[i][j])
        // Each column computes one output element in parallel
        // Multiple columns can be processed in parallel
        double parallel_outputs = static_cast<double>(ma.crossbar_cols);
        
        // Calculate workload
        double total_flops = node.estimated_flops;
        // Assume vector-matrix operations: flops = 2 * M * N
        double matrix_dim = std::sqrt(total_flops / 2.0);
        
        // CIM execution cycles:
        // 1. DAC conversion: input vector elements -> analog voltages
        // 2. Crossbar multiplication: parallel across all cells (1 cycle in analog)
        // 3. ADC conversion: sense and digitize output
        // 4. Peripheral digital: post-processing (activation, pooling, etc.)
        
        double dac_cycles = static_cast<double>(ma.dac_resolution) * 0.5;  // ~0.5 cycle per bit
        double adc_cycles = static_cast<double>(ma.adc_resolution) * 2.0;  // ~2 cycles per bit
        double analog_compute_cycles = 1.0;  // Parallel analog multiplication
        double peripheral_cycles = static_cast<double>(ma.peripheral_digital_units) * 0.5;
        
        // Number of crossbar operations needed
        double num_operations = std::ceil(matrix_dim / crossbar_size);
        double cycles_per_operation = dac_cycles + analog_compute_cycles + adc_cycles + peripheral_cycles;
        
        return num_operations * cycles_per_operation;
    }
    
    double simulate_transfer_cycles(
        const DataEdge& edge,
        const AcceleratorDesc& accel,
        const std::string& src_device,
        const std::string& dst_device
    ) const override {
        if (src_device == dst_device) return 0.0;
        
        double tensor_size_bytes = tensor_payload_bytes(edge);
        
        // CIM data transfer: typically on-chip, lower bandwidth than FPGA
        const auto& ma = accel.microarchitecture;
        double bandwidth = ma.memory_bandwidth_gbps * 1e9;
        if (bandwidth <= 0) bandwidth = 50.0 * 1e9;  // Default 50 GB/s for on-chip
        
        return tensor_size_bytes / bandwidth * (accel.clock_mhz * 1e6);
    }
    
    double estimate_power_w(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const override {
        const auto& ma = accel.microarchitecture;
        double static_power = accel.power.static_w;
        
        // CIM power: ADC/DAC dominate
        double crossbar_size = static_cast<double>(ma.crossbar_rows * ma.crossbar_cols);
        double utilization = std::min(1.0, node.estimated_flops / crossbar_size);
        
        // ADC power scales with resolution and sample rate
        double adc_power = static_cast<double>(ma.adc_resolution) * 0.1 * utilization;
        double dac_power = static_cast<double>(ma.dac_resolution) * 0.05 * utilization;
        double crossbar_power = (accel.power.max_w - static_power) * utilization * 0.3;  // CIM array is efficient
        
        return static_power + adc_power + dac_power + crossbar_power;
    }

private:
    double fallback_cycles(const ComputeNode& node, const AcceleratorDesc& accel) const {
        auto it = accel.capabilities.find(node.op_type);
        if (it != accel.capabilities.end()) {
            double peak_gops = it->second.peak_gops;
            double efficiency = it->second.efficiency;
            double actual_gops = peak_gops * efficiency;
            double ops_per_cycle = actual_gops * 1e9 / (accel.clock_mhz * 1e6);
            return node.estimated_flops / ops_per_cycle;
        }
        double peak_gflops = accel.clock_mhz * 1e6 * 8 / 1e9;
        return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
    }
};

// GPU SM (Streaming Multiprocessor) Simulator
// Simplified model: SMs execute warps in SIMD fashion
class GPUSMSimulator : public MicroarchitectureSimulator {
public:
    AccelType get_supported_type() const override { return AccelType::GPU; }
    
    double simulate_compute_cycles(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const override {
        const auto& ma = accel.microarchitecture;
        if (ma.sm_count <= 0) {
            return fallback_cycles(node, accel);
        }
        
        // GPU execution model:
        // - Workload is divided into thread blocks
        // - Each SM executes warps (groups of threads)
        // - Warps are scheduled round-robin to hide latency
        
        double sm_count = static_cast<double>(ma.sm_count);
        double warp_size = static_cast<double>(ma.warp_size > 0 ? ma.warp_size : 32);
        double max_warps_per_sm = static_cast<double>(ma.max_warps_per_sm > 0 ? ma.max_warps_per_sm : 64);
        
        // Total parallel threads
        double total_threads = sm_count * max_warps_per_sm * warp_size;
        
        // Calculate workload
        double total_flops = node.estimated_flops;
        
        // GPU cycles:
        // - Each warp executes the same instruction on multiple data (SIMD)
        // - Throughput = total_threads * ops_per_cycle
        // - ops_per_cycle depends on operation type (FMA = 2 ops)
        double ops_per_cycle = 2.0;  // FMA = multiply + add
        double total_ops_per_cycle = total_threads * ops_per_cycle;
        
        // Memory latency hiding: assume 80% utilization due to warp scheduling
        double utilization = 0.8;
        double compute_cycles = total_flops / (total_ops_per_cycle * utilization);
        
        // Memory bandwidth limitation
        double shared_memory_bw = ma.shared_memory_kb * 1024.0 * sm_count * (accel.clock_mhz * 1e6) / 1e9;
        double data_size = node.estimated_memory_bytes;
        double memory_cycles = data_size / (shared_memory_bw * 1e9 / (accel.clock_mhz * 1e6));
        
        return std::max(compute_cycles, memory_cycles);
    }
    
    double simulate_transfer_cycles(
        const DataEdge& edge,
        const AcceleratorDesc& accel,
        const std::string& src_device,
        const std::string& dst_device
    ) const override {
        if (src_device == dst_device) return 0.0;
        
        double tensor_size_bytes = tensor_payload_bytes(edge);
        
        // GPU memory transfer: HBM/GDDR bandwidth
        const auto& ma = accel.microarchitecture;
        double bandwidth = ma.memory_bandwidth_gbps * 1e9;
        if (bandwidth <= 0) bandwidth = 900.0 * 1e9;  // Default 900 GB/s (HBM2)
        
        return tensor_size_bytes / bandwidth * (accel.clock_mhz * 1e6);
    }
    
    double estimate_power_w(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const override {
        const auto& ma = accel.microarchitecture;
        double static_power = accel.power.static_w;
        
        // GPU power scales with SM utilization
        double sm_count = static_cast<double>(ma.sm_count);
        double max_warps = static_cast<double>(ma.max_warps_per_sm > 0 ? ma.max_warps_per_sm : 64);
        double total_threads = sm_count * max_warps * (ma.warp_size > 0 ? ma.warp_size : 32);
        
        double utilization = std::min(1.0, node.estimated_flops / (total_threads * accel.clock_mhz * 1e6));
        double dynamic_power = (accel.power.max_w - static_power) * utilization;
        
        return static_power + dynamic_power;
    }

private:
    double fallback_cycles(const ComputeNode& node, const AcceleratorDesc& accel) const {
        auto it = accel.capabilities.find(node.op_type);
        if (it != accel.capabilities.end()) {
            double peak_gops = it->second.peak_gops;
            double efficiency = it->second.efficiency;
            double actual_gops = peak_gops * efficiency;
            double ops_per_cycle = actual_gops * 1e9 / (accel.clock_mhz * 1e6);
            return node.estimated_flops / ops_per_cycle;
        }
        double peak_gflops = accel.clock_mhz * 1e6 * 32 / 1e9;  // GPU: 32 ops/cycle per SM
        return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
    }
};

// ASIC Pipeline Simulator
// Models custom datapath with configurable pipeline stages
class ASICPipelineSimulator : public MicroarchitectureSimulator {
public:
    AccelType get_supported_type() const override { return AccelType::ASIC; }
    
    double simulate_compute_cycles(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const override {
        const auto& ma = accel.microarchitecture;
        if (ma.pipeline_stages <= 0) {
            return fallback_cycles(node, accel);
        }
        
        // ASIC execution model:
        // - Custom pipeline with N stages
        // - Each stage performs one operation
        // - Throughput = 1 result per cycle (fully pipelined)
        // - Latency = pipeline_stages cycles
        
        double pipeline_stages = static_cast<double>(ma.pipeline_stages);
        double vector_width = static_cast<double>(ma.vector_width > 0 ? ma.vector_width : 1);
        
        // Total elements to process
        double total_flops = node.estimated_flops;
        double elements = total_flops / 2.0;  // Assume 2 FLOPs per element (FMA)
        
        // Pipelined execution:
        // - First result after pipeline_stages cycles
        // - Then 1 result per cycle
        // - Vector width processes multiple elements in parallel
        double cycles = pipeline_stages + (elements / vector_width);
        
        return cycles;
    }
    
    double simulate_transfer_cycles(
        const DataEdge& edge,
        const AcceleratorDesc& accel,
        const std::string& src_device,
        const std::string& dst_device
    ) const override {
        if (src_device == dst_device) return 0.0;
        
        double tensor_size_bytes = tensor_payload_bytes(edge);
        
        const auto& ma = accel.microarchitecture;
        double bandwidth = ma.memory_bandwidth_gbps * 1e9;
        if (bandwidth <= 0) bandwidth = 100.0 * 1e9;  // Default 100 GB/s
        
        return tensor_size_bytes / bandwidth * (accel.clock_mhz * 1e6);
    }
    
    double estimate_power_w(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const override {
        const auto& ma = accel.microarchitecture;
        double static_power = accel.power.static_w;
        
        // ASIC power: scales with pipeline utilization
        double pipeline_stages = static_cast<double>(ma.pipeline_stages);
        double vector_width = static_cast<double>(ma.vector_width > 0 ? ma.vector_width : 1);
        double throughput_per_cycle = vector_width;
        
        double total_elements = node.estimated_flops / 2.0;
        double cycles_needed = pipeline_stages + (total_elements / throughput_per_cycle);
        double utilization = std::min(1.0, total_elements / (cycles_needed * throughput_per_cycle));
        
        double dynamic_power = (accel.power.max_w - static_power) * utilization;
        return static_power + dynamic_power;
    }

private:
    double fallback_cycles(const ComputeNode& node, const AcceleratorDesc& accel) const {
        auto it = accel.capabilities.find(node.op_type);
        if (it != accel.capabilities.end()) {
            double peak_gops = it->second.peak_gops;
            double efficiency = it->second.efficiency;
            double actual_gops = peak_gops * efficiency;
            double ops_per_cycle = actual_gops * 1e9 / (accel.clock_mhz * 1e6);
            return node.estimated_flops / ops_per_cycle;
        }
        double peak_gflops = accel.clock_mhz * 1e6 * 8 / 1e9;
        return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
    }
};

// Factory to create the appropriate simulator for an accelerator type
class MicroarchitectureSimulatorFactory {
public:
    static std::unique_ptr<MicroarchitectureSimulator> create_simulator(AccelType type) {
        switch (type) {
            case AccelType::FPGA:
                return std::make_unique<FPGASystolicArraySimulator>();
            case AccelType::CIM:
                return std::make_unique<CIMCrossbarSimulator>();
            case AccelType::GPU:
                return std::make_unique<GPUSMSimulator>();
            case AccelType::ASIC:
                return std::make_unique<ASICPipelineSimulator>();
            default:
                return nullptr;
        }
    }
    
    static std::unique_ptr<MicroarchitectureSimulator> create_simulator(const std::string& type_str) {
        return create_simulator(string_to_accel_type(type_str));
    }
};

} // namespace gsim
