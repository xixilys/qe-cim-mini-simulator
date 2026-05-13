#pragma once

#include "simulation_types.hpp"
#include "op_model_registry.hpp"
#include "microarchitecture_simulator.hpp"
#include <vector>
#include <map>
#include <set>
#include <memory>

namespace gsim {

class GraphExecutor {
public:
    GraphExecutor(const SimulationRequest& req, const OpModelRegistry& registry);
    
    SimulationResult execute();
    
private:
    SimulationRequest req_;
    const OpModelRegistry& registry_;
    
    // Execution state
    std::map<std::string, double> node_start_times_;
    std::map<std::string, double> node_end_times_;
    std::map<std::string, double> device_available_at_;
    std::map<std::string, double> device_compute_time_;
    std::map<std::string, double> device_dma_time_;
    std::vector<TraceEvent> events_;
    
    // Microarchitecture simulators per accelerator
    std::map<std::string, std::unique_ptr<MicroarchitectureSimulator>> micro_simulators_;
    
    // Helper methods
    std::vector<std::string> topological_sort() const;
    double estimate_transfer_time(const DataEdge& edge, const std::string& src_device, const std::string& dst_device) const;
    const AcceleratorDesc* find_accelerator(const std::string& accel_id) const;
    double get_interconnect_bandwidth() const;
    void initialize_microarchitecture_simulators();
    double simulate_compute_with_microarchitecture(const ComputeNode& node, const AcceleratorDesc* accel);
};

} // namespace gsim
