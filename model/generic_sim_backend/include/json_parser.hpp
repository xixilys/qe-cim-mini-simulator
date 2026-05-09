#pragma once

#include "simulation_types.hpp"
#include <string>
#include <vector>

namespace gsim {

class JsonParser {
public:
    static SimulationRequest parse_request(const std::string& json_str);
    static SimulationResult parse_result(const std::string& json_str);
    static std::string serialize_result(const SimulationResult& result);
    
private:
    static ComputeGraph parse_workload(const std::string& json_str);
    static SystemArchitecture parse_architecture(const std::string& json_str);
};

} // namespace gsim
