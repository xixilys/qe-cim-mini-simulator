#include <iostream>
#include <fstream>
#include <sstream>
#include <cstring>
#include "json_parser.hpp"
#include "graph_executor.hpp"
#include "op_model_registry.hpp"

using namespace gsim;

namespace {

bool is_supported_schema_version(const std::string& schema_version) {
    return schema_version == "gsim.request.v1";
}

bool is_supported_mode(const std::string& mode) {
    return mode == "standalone_systemc" ||
           mode == "gem5_cosim" ||
           mode == "gem5_systemc_blocked" ||
           mode == "analytical";
}

bool validate_request_contract(const SimulationRequest& req, std::string& error) {
    if (!is_supported_schema_version(req.schema_version)) {
        error = "unsupported schema_version: " + req.schema_version;
        return false;
    }
    if (!is_supported_mode(req.mode)) {
        error = "unsupported mode: " + req.mode;
        return false;
    }
    if (req.run_id.empty()) {
        error = "missing run_id";
        return false;
    }
    for (const auto& edge : req.workload.edges) {
        if (edge.size_bytes < 0.0) {
            error = "negative size_bytes for edge: " + edge.tensor_name;
            return false;
        }
        if (edge.element_size < 0.0) {
            error = "negative element_size for edge: " + edge.tensor_name;
            return false;
        }
    }
    return true;
}

} // namespace

void print_usage(const char* program) {
    std::cerr << "Usage: " << program << " --request <request.json> --result <result.json>\n";
}

int main(int argc, char* argv[]) {
    std::string request_path;
    std::string result_path;
    
    // Parse command line arguments
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], "--request") == 0 && i + 1 < argc) {
            request_path = argv[++i];
        } else if (std::strcmp(argv[i], "--result") == 0 && i + 1 < argc) {
            result_path = argv[++i];
        } else if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return 0;
        }
    }
    
    if (request_path.empty() || result_path.empty()) {
        print_usage(argv[0]);
        return 1;
    }
    
    try {
        // Read request file
        std::ifstream request_file(request_path);
        if (!request_file.is_open()) {
            std::cerr << "Error: Cannot open request file: " << request_path << "\n";
            return 1;
        }
        
        std::stringstream request_buffer;
        request_buffer << request_file.rdbuf();
        std::string request_json = request_buffer.str();
        request_file.close();
        
        // Parse request
        SimulationRequest req = JsonParser::parse_request(request_json);
        
        std::string validation_error;
        if (!validate_request_contract(req, validation_error)) {
            std::cerr << "Error: Invalid request contract: " << validation_error << "\n";
            return 1;
        }
        
        // Create operation model registry
        OpModelRegistry registry;
        
        // Execute simulation
        GraphExecutor executor(req, registry);
        SimulationResult result = executor.execute();
        
        // Serialize result
        std::string result_json = JsonParser::serialize_result(result);
        
        // Write result file
        std::ofstream result_file(result_path);
        if (!result_file.is_open()) {
            std::cerr << "Error: Cannot open result file: " << result_path << "\n";
            return 1;
        }
        
        result_file << result_json;
        result_file.close();
        
        std::cout << "Simulation complete: " << result.run_id << "\n";
        std::cout << "Status: " << result.status << "\n";
        std::cout << "Latency: " << result.metrics.latency_ms << " ms\n";
        
        return (result.status == "passed") ? 0 : 1;
        
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << "\n";
        return 1;
    }
}
