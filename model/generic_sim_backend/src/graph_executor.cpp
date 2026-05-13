#include "graph_executor.hpp"
#include <algorithm>
#include <queue>

namespace gsim {

GraphExecutor::GraphExecutor(const SimulationRequest& req, const OpModelRegistry& registry)
    : req_(req), registry_(registry) {
    // Initialize device availability
    for (const auto& accel : req_.architecture.accelerators) {
        device_available_at_[accel.accel_id] = 0.0;
        device_compute_time_[accel.accel_id] = 0.0;
        device_dma_time_[accel.accel_id] = 0.0;
    }
    device_available_at_["host"] = 0.0;
    device_compute_time_["host"] = 0.0;
    device_dma_time_["host"] = 0.0;

    // Initialize microarchitecture simulators
    initialize_microarchitecture_simulators();
}

std::vector<std::string> GraphExecutor::topological_sort() const {
    std::map<std::string, int> in_degree;
    std::map<std::string, std::vector<std::string>> adjacency;
    
    // Initialize
    for (const auto& [id, node] : req_.workload.nodes) {
        in_degree[id] = 0;
    }
    
    // Build adjacency and count in-degrees
    for (const auto& edge : req_.workload.edges) {
        adjacency[edge.source].push_back(edge.target);
        in_degree[edge.target]++;
    }
    
    // Kahn's algorithm
    std::queue<std::string> q;
    for (const auto& [id, degree] : in_degree) {
        if (degree == 0) {
            q.push(id);
        }
    }
    
    std::vector<std::string> result;
    while (!q.empty()) {
        std::string node = q.front();
        q.pop();
        result.push_back(node);
        
        for (const auto& neighbor : adjacency[node]) {
            in_degree[neighbor]--;
            if (in_degree[neighbor] == 0) {
                q.push(neighbor);
            }
        }
    }
    
    return result;
}

double GraphExecutor::estimate_transfer_time(const DataEdge& edge, const std::string& src_device, const std::string& dst_device) const {
    if (src_device == dst_device) {
        return 0.0;  // No transfer needed
    }
    
    const double tensor_size_bytes = tensor_payload_bytes(edge);
    
    // Get bandwidth
    double bandwidth_gbps = get_interconnect_bandwidth();
    
    // Transfer time = size / bandwidth + latency
    double transfer_time_ns = (tensor_size_bytes * 8.0 / bandwidth_gbps) + 800.0;  // 800ns latency
    
    return transfer_time_ns;
}

const AcceleratorDesc* GraphExecutor::find_accelerator(const std::string& accel_id) const {
    for (const auto& accel : req_.architecture.accelerators) {
        if (accel.accel_id == accel_id) {
            return &accel;
        }
    }
    return nullptr;
}

double GraphExecutor::get_interconnect_bandwidth() const {
    if (req_.architecture.interconnect) {
        return req_.architecture.interconnect->bandwidth_gbps;
    }
    return 64.0;  // Default PCIe bandwidth
}

SimulationResult GraphExecutor::execute() {
    SimulationResult result;
    result.run_id = req_.run_id;
    result.schema_version = "gsim.result.v1";
    
    try {
        // Get topological order
        std::vector<std::string> exec_order = topological_sort();
        
        if (exec_order.size() != req_.workload.nodes.size()) {
            result.status = "error";
            result.error_message = "Cycle detected in workload graph";
            return result;
        }
        
        // Execute each node
        for (const auto& node_id : exec_order) {
            auto node_it = req_.workload.nodes.find(node_id);
            if (node_it == req_.workload.nodes.end()) continue;
            
            const ComputeNode& node = node_it->second;
            
            // Find mapped accelerator
            std::string accel_id = "host";
            auto map_it = req_.mapping.find(node_id);
            if (map_it != req_.mapping.end()) {
                accel_id = map_it->second;
            }
            
            const AcceleratorDesc* accel = find_accelerator(accel_id);
            if (!accel) {
                accel_id = "host";  // Fallback to host
                accel = nullptr;
            }
            
            // Find operation model
            const OpModel* op_model = registry_.find_model(node.op_type);
            if (!op_model) {
                op_model = registry_.find_model("generic_op");
            }
            
            // Calculate earliest start time based on dependencies
            double earliest_start = 0.0;
            for (const auto& edge : req_.workload.edges) {
                if (edge.target == node_id) {
                    auto dep_end_it = node_end_times_.find(edge.source);
                    if (dep_end_it != node_end_times_.end()) {
                        double dep_end = dep_end_it->second;
                        std::string src_device = "host";
                        auto src_map_it = req_.mapping.find(edge.source);
                        if (src_map_it != req_.mapping.end()) {
                            src_device = src_map_it->second;
                        }
                        double transfer_time = estimate_transfer_time(edge, src_device, accel_id);
                        if (transfer_time > 0.0) {
                            device_dma_time_[accel_id] += transfer_time;
                        }
                        earliest_start = std::max(earliest_start, dep_end + transfer_time);
                    }
                }
            }
            
            // Wait for device availability
            double device_ready = device_available_at_[accel_id];
            double start_time = std::max(earliest_start, device_ready);
            
            // Estimate compute cycles using microarchitecture simulator
            double compute_cycles = 0.0;
            if (accel) {
                compute_cycles = simulate_compute_with_microarchitecture(node, accel);
            } else {
                // Host execution fallback
                double host_clock_mhz = req_.architecture.host.clock_mhz;
                double peak_gflops = host_clock_mhz * 1e6 * 4 / 1e9;
                compute_cycles = node.estimated_flops / (peak_gflops * 1e9) * host_clock_mhz * 1e6;
            }
            
            // Convert cycles to nanoseconds
            double clock_mhz = accel ? accel->clock_mhz : req_.architecture.host.clock_mhz;
            double compute_time_ns = compute_cycles / clock_mhz * 1000.0;
            
            double end_time = start_time + compute_time_ns;
            
            // Record execution
            node_start_times_[node_id] = start_time;
            node_end_times_[node_id] = end_time;
            device_available_at_[accel_id] = end_time;
            device_compute_time_[accel_id] += compute_time_ns;
            
            // Create event
            TraceEvent event;
            event.node_id = node_id;
            event.device = accel_id;
            event.start_ns = start_time;
            event.end_ns = end_time;
            event.op_type = node.op_type;
            events_.push_back(event);
        }
        
        // Calculate total latency
        double total_latency_ns = 0.0;
        for (const auto& [id, end_time] : node_end_times_) {
            total_latency_ns = std::max(total_latency_ns, end_time);
        }
        
        // Calculate metrics
        result.metrics.latency_ms = total_latency_ns / 1e6;
        result.metrics.device_time_ms = 0.0;
        result.metrics.dma_time_ms = 0.0;
        
        for (const auto& [device, time] : device_compute_time_) {
            result.metrics.device_time_ms += time / 1e6;
        }
        
        for (const auto& [device, time] : device_dma_time_) {
            result.metrics.dma_time_ms += time / 1e6;
        }
        
        // Calculate throughput
        double total_flops = 0.0;
        for (const auto& [id, node] : req_.workload.nodes) {
            total_flops += node.estimated_flops;
        }
        result.metrics.throughput_gops = total_flops / result.metrics.latency_ms / 1e6;
        
        // Estimate power and energy
        double total_power = 0.0;
        for (const auto& accel : req_.architecture.accelerators) {
            total_power += accel.power.static_w;
        }
        result.metrics.power_w = total_power;
        result.metrics.energy_j = total_power * result.metrics.latency_ms / 1000.0;
        
        // Calculate data movement
        double total_data_mb = 0.0;
        for (const auto& edge : req_.workload.edges) {
            auto src_it = req_.mapping.find(edge.source);
            auto dst_it = req_.mapping.find(edge.target);
            if (src_it != req_.mapping.end() && dst_it != req_.mapping.end() && src_it->second != dst_it->second) {
                double tensor_size = tensor_payload_bytes(edge);
                total_data_mb += tensor_size / (1024.0 * 1024.0);
            }
        }
        result.metrics.total_data_movement_mb = total_data_mb;
        
        // Resource utilization
        for (const auto& accel : req_.architecture.accelerators) {
            ResourceUtilization util;
            double compute_time = device_compute_time_[accel.accel_id];
            util.compute_percent = (compute_time / total_latency_ns) * 100.0;
            util.compute_percent = std::min(util.compute_percent, 100.0);
            result.resource_utilization[accel.accel_id] = util;
        }
        
        result.events = events_;
        result.status = "passed";
        
    } catch (const std::exception& e) {
        result.status = "error";
        result.error_message = e.what();
    }
    
    return result;
}

void GraphExecutor::initialize_microarchitecture_simulators() {
    for (const auto& accel : req_.architecture.accelerators) {
        const auto& ma = accel.microarchitecture;
        const bool has_microarchitecture_config =
            ma.array_size > 0 ||
            ma.crossbar_rows > 0 || ma.crossbar_cols > 0 ||
            ma.sm_count > 0 ||
            ma.pipeline_stages > 0 ||
            ma.memory_bandwidth_gbps > 0.0 ||
            ma.memory_ports > 0;
        if (!has_microarchitecture_config) {
            continue;
        }
        auto sim = MicroarchitectureSimulatorFactory::create_simulator(accel.accel_type);
        if (sim) {
            micro_simulators_[accel.accel_id] = std::move(sim);
        }
    }
}

double GraphExecutor::simulate_compute_with_microarchitecture(
    const ComputeNode& node,
    const AcceleratorDesc* accel
) {
    if (!accel) return 0.0;

    auto it = micro_simulators_.find(accel->accel_id);
    if (it != micro_simulators_.end() && it->second) {
        return it->second->simulate_compute_cycles(node, *accel);
    }

    const OpModel* op_model = registry_.find_model(node.op_type);
    if (!op_model) {
        op_model = registry_.find_model("generic_op");
    }
    if (op_model) {
        return op_model->estimate_compute_cycles(node, *accel, 0.0);
    }

    double peak_gflops = accel->clock_mhz * 1e6 * 16 / 1e9;
    return node.estimated_flops / (peak_gflops * 1e9) * accel->clock_mhz * 1e6;
}

} // namespace gsim
