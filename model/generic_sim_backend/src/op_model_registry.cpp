#include "op_model_registry.hpp"
#include <cmath>

namespace gsim {

// OpModelRegistry implementation
OpModelRegistry::OpModelRegistry() {
    // Register default models
    register_model(std::make_unique<GemmModel>());
    register_model(std::make_unique<FftModel>());
    register_model(std::make_unique<EigenModel>());
    register_model(std::make_unique<ReductionModel>());
    register_model(std::make_unique<GenericOpModel>());
}

void OpModelRegistry::register_model(std::unique_ptr<OpModel> model) {
    models_.push_back(std::move(model));
}

const OpModel* OpModelRegistry::find_model(const std::string& op_type) const {
    for (const auto& model : models_) {
        if (model->supports(op_type)) {
            return model.get();
        }
    }
    return nullptr;
}

// GemmModel implementation
bool GemmModel::supports(const std::string& op_type) const {
    return op_type == "gemm" || op_type == "batched_gemm";
}

double GemmModel::estimate_compute_cycles(
    const ComputeNode& node,
    const AcceleratorDesc& accel,
    double context
) const {
    auto it = accel.capabilities.find("gemm");
    if (it == accel.capabilities.end()) {
        // Fallback: use generic FLOPS estimate
        double peak_gflops = accel.clock_mhz * 1e6 * 16 / 1e9;  // Assume 16 ops/cycle
        return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
    }
    
    double peak_gops = it->second.peak_gops;
    double efficiency = it->second.efficiency;
    double actual_gops = peak_gops * efficiency;
    
    // cycles = flops / (ops/cycle)
    double ops_per_cycle = actual_gops * 1e9 / (accel.clock_mhz * 1e6);
    return node.estimated_flops / ops_per_cycle;
}

double GemmModel::estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const {
    return node.estimated_memory_bytes;
}

double GemmModel::estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const {
    double seconds = cycles / (accel.clock_mhz * 1e6);
    double power_w = accel.power.static_w + (accel.power.max_w - accel.power.static_w) * 0.7;
    return seconds * power_w;
}

// FftModel implementation
bool FftModel::supports(const std::string& op_type) const {
    return op_type == "fft";
}

double FftModel::estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const {
    auto it = accel.capabilities.find("fft");
    if (it == accel.capabilities.end()) {
        double peak_gflops = accel.clock_mhz * 1e6 * 8 / 1e9;
        return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
    }
    
    double peak_gops = it->second.peak_gops;
    double efficiency = it->second.efficiency;
    double actual_gops = peak_gops * efficiency;
    double ops_per_cycle = actual_gops * 1e9 / (accel.clock_mhz * 1e6);
    return node.estimated_flops / ops_per_cycle;
}

double FftModel::estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const {
    return node.estimated_memory_bytes;
}

double FftModel::estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const {
    double seconds = cycles / (accel.clock_mhz * 1e6);
    double power_w = accel.power.static_w + (accel.power.max_w - accel.power.static_w) * 0.6;
    return seconds * power_w;
}

// EigenModel implementation
bool EigenModel::supports(const std::string& op_type) const {
    return op_type == "eigen" || op_type == "eigensolver";
}

double EigenModel::estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const {
    auto it = accel.capabilities.find("eigen");
    if (it == accel.capabilities.end()) {
        // Eigensolver is typically much slower than GEMM
        double peak_gflops = accel.clock_mhz * 1e6 * 4 / 1e9;
        return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
    }
    
    double peak_gops = it->second.peak_gops;
    double efficiency = it->second.efficiency;
    double actual_gops = peak_gops * efficiency;
    double ops_per_cycle = actual_gops * 1e9 / (accel.clock_mhz * 1e6);
    return node.estimated_flops / ops_per_cycle;
}

double EigenModel::estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const {
    return node.estimated_memory_bytes;
}

double EigenModel::estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const {
    double seconds = cycles / (accel.clock_mhz * 1e6);
    double power_w = accel.power.static_w + (accel.power.max_w - accel.power.static_w) * 0.5;
    return seconds * power_w;
}

// ReductionModel implementation
bool ReductionModel::supports(const std::string& op_type) const {
    return op_type == "reduction" || op_type == "sum" || op_type == "max";
}

double ReductionModel::estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const {
    auto it = accel.capabilities.find("reduction");
    if (it == accel.capabilities.end()) {
        double peak_gflops = accel.clock_mhz * 1e6 * 8 / 1e9;
        return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
    }
    
    double peak_gops = it->second.peak_gops;
    double efficiency = it->second.efficiency;
    double actual_gops = peak_gops * efficiency;
    double ops_per_cycle = actual_gops * 1e9 / (accel.clock_mhz * 1e6);
    return node.estimated_flops / ops_per_cycle;
}

double ReductionModel::estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const {
    return node.estimated_memory_bytes;
}

double ReductionModel::estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const {
    double seconds = cycles / (accel.clock_mhz * 1e6);
    double power_w = accel.power.static_w + (accel.power.max_w - accel.power.static_w) * 0.5;
    return seconds * power_w;
}

// GenericOpModel implementation
bool GenericOpModel::supports(const std::string& op_type) const {
    return true;  // Catch-all for unknown operations
}

double GenericOpModel::estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const {
    // Use the estimated FLOPS from the node
    double peak_gflops = accel.clock_mhz * 1e6 * 8 / 1e9;  // Conservative estimate
    return node.estimated_flops / (peak_gflops * 1e9) * accel.clock_mhz * 1e6;
}

double GenericOpModel::estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const {
    return node.estimated_memory_bytes;
}

double GenericOpModel::estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const {
    double seconds = cycles / (accel.clock_mhz * 1e6);
    double power_w = accel.power.static_w + (accel.power.max_w - accel.power.static_w) * 0.5;
    return seconds * power_w;
}

} // namespace gsim
