#include "json_parser.hpp"
#include <fstream>
#include <sstream>
#include <iostream>
#include <algorithm>

namespace gsim {

// Helper: skip whitespace
static void skip_ws(const std::string& s, size_t& pos) {
    while (pos < s.size() && (s[pos] == ' ' || s[pos] == '\t' || s[pos] == '\n' || s[pos] == '\r'))
        pos++;
}

// Helper: expect a specific character
static bool expect_char(const std::string& s, size_t& pos, char c) {
    skip_ws(s, pos);
    if (pos < s.size() && s[pos] == c) {
        pos++;
        return true;
    }
    return false;
}

// Helper: parse a JSON string value (returns content without quotes)
static std::string parse_json_string(const std::string& s, size_t& pos) {
    skip_ws(s, pos);
    if (pos >= s.size() || s[pos] != '"') return "";
    pos++; // skip opening quote
    std::string result;
    while (pos < s.size() && s[pos] != '"') {
        if (s[pos] == '\\' && pos + 1 < s.size()) {
            pos++;
            switch (s[pos]) {
                case '"': result += '"'; break;
                case '\\': result += '\\'; break;
                case '/': result += '/'; break;
                case 'b': result += '\b'; break;
                case 'f': result += '\f'; break;
                case 'n': result += '\n'; break;
                case 'r': result += '\r'; break;
                case 't': result += '\t'; break;
                default: result += s[pos]; break;
            }
        } else {
            result += s[pos];
        }
        pos++;
    }
    if (pos < s.size() && s[pos] == '"') pos++; // skip closing quote
    return result;
}

// Helper: parse a JSON number
static double parse_json_number(const std::string& s, size_t& pos) {
    skip_ws(s, pos);
    size_t start = pos;
    if (pos < s.size() && (s[pos] == '-' || s[pos] == '+')) pos++;
    while (pos < s.size() && std::isdigit(s[pos])) pos++;
    if (pos < s.size() && s[pos] == '.') {
        pos++;
        while (pos < s.size() && std::isdigit(s[pos])) pos++;
    }
    if (pos < s.size() && (s[pos] == 'e' || s[pos] == 'E')) {
        pos++;
        if (pos < s.size() && (s[pos] == '-' || s[pos] == '+')) pos++;
        while (pos < s.size() && std::isdigit(s[pos])) pos++;
    }
    if (start == pos) return 0.0;
    return std::stod(s.substr(start, pos - start));
}

// Helper: parse a JSON boolean
static bool parse_json_bool(const std::string& s, size_t& pos) {
    skip_ws(s, pos);
    if (s.substr(pos, 4) == "true") {
        pos += 4;
        return true;
    }
    if (s.substr(pos, 5) == "false") {
        pos += 5;
        return false;
    }
    return false;
}

// Helper: skip a JSON value (for advancing past unknown fields)
static void skip_json_value(const std::string& s, size_t& pos);

static void skip_json_object(const std::string& s, size_t& pos) {
    if (!expect_char(s, pos, '{')) return;
    while (true) {
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == '"') {
            parse_json_string(s, pos); // skip key
            expect_char(s, pos, ':');
            skip_json_value(s, pos);
        }
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == ',') {
            pos++;
            continue;
        }
        if (pos < s.size() && s[pos] == '}') {
            pos++;
            break;
        }
        if (pos >= s.size()) break;
    }
}

static void skip_json_array(const std::string& s, size_t& pos) {
    if (!expect_char(s, pos, '[')) return;
    while (true) {
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == ']') {
            pos++;
            break;
        }
        skip_json_value(s, pos);
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == ',') {
            pos++;
            continue;
        }
        if (pos < s.size() && s[pos] == ']') {
            pos++;
            break;
        }
        if (pos >= s.size()) break;
    }
}

static void skip_json_value(const std::string& s, size_t& pos) {
    skip_ws(s, pos);
    if (pos >= s.size()) return;
    if (s[pos] == '"') {
        parse_json_string(s, pos);
    } else if (s[pos] == '{') {
        skip_json_object(s, pos);
    } else if (s[pos] == '[') {
        skip_json_array(s, pos);
    } else {
        // number, bool, null
        while (pos < s.size() && s[pos] != ',' && s[pos] != '}' && s[pos] != ']')
            pos++;
    }
}

static std::string parse_json_scalar_as_string(const std::string& s, size_t& pos) {
    skip_ws(s, pos);
    if (pos >= s.size()) return "";
    if (s[pos] == '"') {
        return parse_json_string(s, pos);
    }
    if (s[pos] == '{' || s[pos] == '[') {
        skip_json_value(s, pos);
        return "";
    }
    size_t start = pos;
    while (pos < s.size() && s[pos] != ',' && s[pos] != '}' && s[pos] != ']') {
        pos++;
    }
    size_t end = pos;
    while (end > start && (s[end - 1] == ' ' || s[end - 1] == '\t' || s[end - 1] == '\n' || s[end - 1] == '\r')) {
        end--;
    }
    return s.substr(start, end - start);
}

// Parse a ComputeNode from JSON object
static ComputeNode parse_compute_node(const std::string& s, size_t& pos) {
    ComputeNode node;
    if (!expect_char(s, pos, '{')) return node;
    
    while (true) {
        skip_ws(s, pos);
        if (pos >= s.size()) break;
        if (s[pos] == '}') {
            pos++;
            break;
        }
        
        std::string key = parse_json_string(s, pos);
        expect_char(s, pos, ':');
        
        if (key == "op_type") {
            node.op_type = parse_json_string(s, pos);
        } else if (key == "inputs") {
            if (expect_char(s, pos, '[')) {
                while (true) {
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ']') {
                        pos++;
                        break;
                    }
                    std::string val = parse_json_string(s, pos);
                    if (!val.empty()) node.inputs.push_back(val);
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ',') pos++;
                }
            }
        } else if (key == "outputs") {
            if (expect_char(s, pos, '[')) {
                while (true) {
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ']') {
                        pos++;
                        break;
                    }
                    std::string val = parse_json_string(s, pos);
                    if (!val.empty()) node.outputs.push_back(val);
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ',') pos++;
                }
            }
        } else if (key == "estimated_flops") {
            node.estimated_flops = parse_json_number(s, pos);
        } else if (key == "estimated_memory_bytes") {
            node.estimated_memory_bytes = parse_json_number(s, pos);
        } else if (key == "attributes") {
            if (expect_char(s, pos, '{')) {
                while (true) {
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string attr_key = parse_json_string(s, pos);
                    expect_char(s, pos, ':');
                    std::string attr_val = parse_json_scalar_as_string(s, pos);
                    node.attributes[attr_key] = attr_val;
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ',') pos++;
                }
            }
        } else {
            skip_json_value(s, pos);
        }
        
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == ',') {
            pos++;
            continue;
        }
        if (pos < s.size() && s[pos] == '}') {
            pos++;
            break;
        }
    }
    
    return node;
}

// Parse a DataEdge from JSON object
static DataEdge parse_data_edge(const std::string& s, size_t& pos) {
    DataEdge edge;
    if (!expect_char(s, pos, '{')) return edge;
    
    while (true) {
        skip_ws(s, pos);
        if (pos >= s.size()) break;
        if (s[pos] == '}') {
            pos++;
            break;
        }
        
        std::string key = parse_json_string(s, pos);
        expect_char(s, pos, ':');
        
        if (key == "source") {
            edge.source = parse_json_string(s, pos);
        } else if (key == "target") {
            edge.target = parse_json_string(s, pos);
        } else if (key == "tensor_name") {
            edge.tensor_name = parse_json_string(s, pos);
        } else if (key == "tensor_shape") {
            if (expect_char(s, pos, '[')) {
                while (true) {
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ']') {
                        pos++;
                        break;
                    }
                    edge.tensor_shape.push_back(static_cast<int>(parse_json_number(s, pos)));
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ',') pos++;
                }
            }
        } else if (key == "tensor_dtype") {
            edge.tensor_dtype = parse_json_string(s, pos);
        } else if (key == "element_size") {
            edge.element_size = parse_json_number(s, pos);
        } else if (key == "size_bytes") {
            edge.size_bytes = parse_json_number(s, pos);
        } else {
            skip_json_value(s, pos);
        }
        
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == ',') {
            pos++;
            continue;
        }
        if (pos < s.size() && s[pos] == '}') {
            pos++;
            break;
        }
    }
    
    return edge;
}

// Parse an AcceleratorDesc from JSON object
static AcceleratorDesc parse_accelerator(const std::string& s, size_t& pos) {
    AcceleratorDesc accel;
    if (!expect_char(s, pos, '{')) return accel;
    
    while (true) {
        skip_ws(s, pos);
        if (pos >= s.size()) break;
        if (s[pos] == '}') {
            pos++;
            break;
        }
        
        std::string key = parse_json_string(s, pos);
        expect_char(s, pos, ':');
        
        if (key == "accel_id") {
            accel.accel_id = parse_json_string(s, pos);
        } else if (key == "accel_type") {
            accel.accel_type_str = parse_json_string(s, pos);
            accel.resolve_accel_type();
        } else if (key == "clock_mhz") {
            accel.clock_mhz = parse_json_number(s, pos);
        } else if (key == "local_memory_kb") {
            accel.local_memory_kb = parse_json_number(s, pos);
        } else if (key == "power") {
            if (expect_char(s, pos, '{')) {
                while (true) {
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string pkey = parse_json_string(s, pos);
                    expect_char(s, pos, ':');
                    if (pkey == "static_w") accel.power.static_w = parse_json_number(s, pos);
                    else if (pkey == "max_w") accel.power.max_w = parse_json_number(s, pos);
                    else skip_json_value(s, pos);
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ',') pos++;
                }
            }
        } else if (key == "capabilities") {
            if (expect_char(s, pos, '{')) {
                while (true) {
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string cap_key = parse_json_string(s, pos);
                    expect_char(s, pos, ':');
                    OpCapability cap;
                    if (expect_char(s, pos, '{')) {
                        while (true) {
                            skip_ws(s, pos);
                            if (pos < s.size() && s[pos] == '}') {
                                pos++;
                                break;
                            }
                            std::string ckey = parse_json_string(s, pos);
                            expect_char(s, pos, ':');
                            if (ckey == "peak_gops") cap.peak_gops = parse_json_number(s, pos);
                            else if (ckey == "efficiency") cap.efficiency = parse_json_number(s, pos);
                            else skip_json_value(s, pos);
                            skip_ws(s, pos);
                            if (pos < s.size() && s[pos] == ',') pos++;
                        }
                    }
                    accel.capabilities[cap_key] = cap;
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ',') pos++;
                }
            }
        } else if (key == "microarchitecture") {
            // Parse microarchitecture configuration (v2 schema)
            if (expect_char(s, pos, '{')) {
                while (true) {
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string mkey = parse_json_string(s, pos);
                    expect_char(s, pos, ':');
                    
                    if (mkey == "fpga") {
                        if (expect_char(s, pos, '{')) {
                            while (true) {
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == '}') { pos++; break; }
                                std::string fkey = parse_json_string(s, pos);
                                expect_char(s, pos, ':');
                                if (fkey == "array_size") accel.microarchitecture.array_size = static_cast<int>(parse_json_number(s, pos));
                                else if (fkey == "local_sram_kb") accel.microarchitecture.local_sram_kb = static_cast<int>(parse_json_number(s, pos));
                                else if (fkey == "dma_channels") accel.microarchitecture.dma_channels = static_cast<int>(parse_json_number(s, pos));
                                else skip_json_value(s, pos);
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == ',') pos++;
                            }
                        }
                    } else if (mkey == "cim") {
                        if (expect_char(s, pos, '{')) {
                            while (true) {
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == '}') { pos++; break; }
                                std::string ckey = parse_json_string(s, pos);
                                expect_char(s, pos, ':');
                                if (ckey == "crossbar_rows") accel.microarchitecture.crossbar_rows = static_cast<int>(parse_json_number(s, pos));
                                else if (ckey == "crossbar_cols") accel.microarchitecture.crossbar_cols = static_cast<int>(parse_json_number(s, pos));
                                else if (ckey == "adc_resolution") accel.microarchitecture.adc_resolution = static_cast<int>(parse_json_number(s, pos));
                                else if (ckey == "dac_resolution") accel.microarchitecture.dac_resolution = static_cast<int>(parse_json_number(s, pos));
                                else if (ckey == "peripheral_digital_units") accel.microarchitecture.peripheral_digital_units = static_cast<int>(parse_json_number(s, pos));
                                else skip_json_value(s, pos);
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == ',') pos++;
                            }
                        }
                    } else if (mkey == "gpu") {
                        if (expect_char(s, pos, '{')) {
                            while (true) {
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == '}') { pos++; break; }
                                std::string gkey = parse_json_string(s, pos);
                                expect_char(s, pos, ':');
                                if (gkey == "sm_count") accel.microarchitecture.sm_count = static_cast<int>(parse_json_number(s, pos));
                                else if (gkey == "shared_memory_kb") accel.microarchitecture.shared_memory_kb = static_cast<int>(parse_json_number(s, pos));
                                else if (gkey == "warp_size") accel.microarchitecture.warp_size = static_cast<int>(parse_json_number(s, pos));
                                else if (gkey == "max_warps_per_sm") accel.microarchitecture.max_warps_per_sm = static_cast<int>(parse_json_number(s, pos));
                                else skip_json_value(s, pos);
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == ',') pos++;
                            }
                        }
                    } else if (mkey == "asic") {
                        if (expect_char(s, pos, '{')) {
                            while (true) {
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == '}') { pos++; break; }
                                std::string akey = parse_json_string(s, pos);
                                expect_char(s, pos, ':');
                                if (akey == "pipeline_stages") accel.microarchitecture.pipeline_stages = static_cast<int>(parse_json_number(s, pos));
                                else if (akey == "vector_width") accel.microarchitecture.vector_width = static_cast<int>(parse_json_number(s, pos));
                                else if (akey == "custom_dims") {
                                    if (expect_char(s, pos, '[')) {
                                        while (true) {
                                            skip_ws(s, pos);
                                            if (pos < s.size() && s[pos] == ']') { pos++; break; }
                                            accel.microarchitecture.custom_dims.push_back(static_cast<int>(parse_json_number(s, pos)));
                                            skip_ws(s, pos);
                                            if (pos < s.size() && s[pos] == ',') pos++;
                                        }
                                    }
                                }
                                else skip_json_value(s, pos);
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == ',') pos++;
                            }
                        }
                    } else if (mkey == "common") {
                        if (expect_char(s, pos, '{')) {
                            while (true) {
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == '}') { pos++; break; }
                                std::string ckey = parse_json_string(s, pos);
                                expect_char(s, pos, ':');
                                if (ckey == "memory_ports") accel.microarchitecture.memory_ports = static_cast<int>(parse_json_number(s, pos));
                                else if (ckey == "memory_bandwidth_gbps") accel.microarchitecture.memory_bandwidth_gbps = parse_json_number(s, pos);
                                else skip_json_value(s, pos);
                                skip_ws(s, pos);
                                if (pos < s.size() && s[pos] == ',') pos++;
                            }
                        }
                    } else {
                        skip_json_value(s, pos);
                    }
                    
                    skip_ws(s, pos);
                    if (pos < s.size() && s[pos] == ',') pos++;
                }
            }
        } else {
            skip_json_value(s, pos);
        }
        
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == ',') {
            pos++;
            continue;
        }
        if (pos < s.size() && s[pos] == '}') {
            pos++;
            break;
        }
    }
    
    return accel;
}

// Parse mapping object
static MappingDesc parse_mapping(const std::string& s, size_t& pos) {
    MappingDesc mapping;
    if (!expect_char(s, pos, '{')) return mapping;
    
    while (true) {
        skip_ws(s, pos);
        if (pos >= s.size()) break;
        if (s[pos] == '}') {
            pos++;
            break;
        }
        
        std::string key = parse_json_string(s, pos);
        expect_char(s, pos, ':');
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == '"') {
            std::string val = parse_json_string(s, pos);
            mapping[key] = val;
        } else {
            skip_json_value(s, pos);
        }
        
        skip_ws(s, pos);
        if (pos < s.size() && s[pos] == ',') {
            pos++;
            continue;
        }
        if (pos < s.size() && s[pos] == '}') {
            pos++;
            break;
        }
    }
    
    return mapping;
}

SimulationRequest JsonParser::parse_request(const std::string& json_str) {
    SimulationRequest req;
    size_t pos = 0;
    
    if (!expect_char(json_str, pos, '{')) return req;
    
    while (true) {
        skip_ws(json_str, pos);
        if (pos >= json_str.size()) break;
        if (json_str[pos] == '}') {
            pos++;
            break;
        }
        
        std::string key = parse_json_string(json_str, pos);
        expect_char(json_str, pos, ':');
        
        if (key == "schema_version") {
            req.schema_version = parse_json_string(json_str, pos);
        } else if (key == "run_id") {
            req.run_id = parse_json_string(json_str, pos);
        } else if (key == "mode") {
            req.mode = parse_json_string(json_str, pos);
        } else if (key == "workload") {
            // Parse workload object
            if (expect_char(json_str, pos, '{')) {
                while (true) {
                    skip_ws(json_str, pos);
                    if (pos >= json_str.size()) break;
                    if (json_str[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string wkey = parse_json_string(json_str, pos);
                    expect_char(json_str, pos, ':');
                    
                    if (wkey == "graph_id") {
                        req.workload.graph_id = parse_json_string(json_str, pos);
                    } else if (wkey == "nodes") {
                        // Parse nodes object
                        if (expect_char(json_str, pos, '{')) {
                            while (true) {
                                skip_ws(json_str, pos);
                                if (pos >= json_str.size()) break;
                                if (json_str[pos] == '}') {
                                    pos++;
                                    break;
                                }
                                std::string node_id = parse_json_string(json_str, pos);
                                expect_char(json_str, pos, ':');
                                ComputeNode node = parse_compute_node(json_str, pos);
                                node.node_id = node_id;
                                req.workload.nodes[node_id] = node;
                                skip_ws(json_str, pos);
                                if (pos < json_str.size() && json_str[pos] == ',') pos++;
                            }
                        }
                    } else if (wkey == "edges") {
                        // Parse edges array
                        if (expect_char(json_str, pos, '[')) {
                            while (true) {
                                skip_ws(json_str, pos);
                                if (pos >= json_str.size()) break;
                                if (json_str[pos] == ']') {
                                    pos++;
                                    break;
                                }
                                DataEdge edge = parse_data_edge(json_str, pos);
                                req.workload.edges.push_back(edge);
                                skip_ws(json_str, pos);
                                if (pos < json_str.size() && json_str[pos] == ',') pos++;
                            }
                        }
                    } else if (wkey == "metadata") {
                        if (expect_char(json_str, pos, '{')) {
                            while (true) {
                                skip_ws(json_str, pos);
                                if (pos >= json_str.size()) break;
                                if (json_str[pos] == '}') {
                                    pos++;
                                    break;
                                }
                                std::string mkey = parse_json_string(json_str, pos);
                                expect_char(json_str, pos, ':');
                                std::string mval = parse_json_scalar_as_string(json_str, pos);
                                req.workload.metadata[mkey] = mval;
                                skip_ws(json_str, pos);
                                if (pos < json_str.size() && json_str[pos] == ',') pos++;
                            }
                        }
                    } else {
                        skip_json_value(json_str, pos);
                    }
                    
                    skip_ws(json_str, pos);
                    if (pos < json_str.size() && json_str[pos] == ',') pos++;
                }
            }
        } else if (key == "architecture") {
            // Parse architecture object
            if (expect_char(json_str, pos, '{')) {
                while (true) {
                    skip_ws(json_str, pos);
                    if (pos >= json_str.size()) break;
                    if (json_str[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string akey = parse_json_string(json_str, pos);
                    expect_char(json_str, pos, ':');
                    
                    if (akey == "host") {
                        if (expect_char(json_str, pos, '{')) {
                            while (true) {
                                skip_ws(json_str, pos);
                                if (pos >= json_str.size()) break;
                                if (json_str[pos] == '}') {
                                    pos++;
                                    break;
                                }
                                std::string hkey = parse_json_string(json_str, pos);
                                expect_char(json_str, pos, ':');
                                if (hkey == "cpu_model") req.architecture.host.cpu_model = parse_json_string(json_str, pos);
                                else if (hkey == "clock_mhz") req.architecture.host.clock_mhz = parse_json_number(json_str, pos);
                                else if (hkey == "memory_bw_gbps") req.architecture.host.memory_bw_gbps = parse_json_number(json_str, pos);
                                else if (hkey == "cores") req.architecture.host.cores = static_cast<int>(parse_json_number(json_str, pos));
                                else skip_json_value(json_str, pos);
                                skip_ws(json_str, pos);
                                if (pos < json_str.size() && json_str[pos] == ',') pos++;
                            }
                        }
                    } else if (akey == "interconnect") {
                        if (expect_char(json_str, pos, '{')) {
                            InterconnectDesc ic;
                            while (true) {
                                skip_ws(json_str, pos);
                                if (pos >= json_str.size()) break;
                                if (json_str[pos] == '}') {
                                    pos++;
                                    break;
                                }
                                std::string ikey = parse_json_string(json_str, pos);
                                expect_char(json_str, pos, ':');
                                if (ikey == "type") ic.type = parse_json_string(json_str, pos);
                                else if (ikey == "bandwidth_gbps") ic.bandwidth_gbps = parse_json_number(json_str, pos);
                                else if (ikey == "latency_ns") ic.latency_ns = parse_json_number(json_str, pos);
                                else skip_json_value(json_str, pos);
                                skip_ws(json_str, pos);
                                if (pos < json_str.size() && json_str[pos] == ',') pos++;
                            }
                            req.architecture.interconnect = ic;
                        }
                    } else if (akey == "accelerators") {
                        // Parse accelerators array
                        if (expect_char(json_str, pos, '[')) {
                            while (true) {
                                skip_ws(json_str, pos);
                                if (pos >= json_str.size()) break;
                                if (json_str[pos] == ']') {
                                    pos++;
                                    break;
                                }
                                AcceleratorDesc accel = parse_accelerator(json_str, pos);
                                req.architecture.accelerators.push_back(accel);
                                skip_ws(json_str, pos);
                                if (pos < json_str.size() && json_str[pos] == ',') pos++;
                            }
                        }
                    } else {
                        skip_json_value(json_str, pos);
                    }
                    
                    skip_ws(json_str, pos);
                    if (pos < json_str.size() && json_str[pos] == ',') pos++;
                }
            }
        } else if (key == "mapping") {
            req.mapping = parse_mapping(json_str, pos);
        } else if (key == "scheduling") {
            if (expect_char(json_str, pos, '{')) {
                while (true) {
                    skip_ws(json_str, pos);
                    if (pos >= json_str.size()) break;
                    if (json_str[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string skey = parse_json_string(json_str, pos);
                    expect_char(json_str, pos, ':');
                    if (skey == "policy") req.scheduling.policy = parse_json_string(json_str, pos);
                    else if (skey == "allow_overlap_dma_compute") req.scheduling.allow_overlap_dma_compute = parse_json_bool(json_str, pos);
                    else if (skey == "double_buffer") req.scheduling.double_buffer = parse_json_bool(json_str, pos);
                    else skip_json_value(json_str, pos);
                    skip_ws(json_str, pos);
                    if (pos < json_str.size() && json_str[pos] == ',') pos++;
                }
            }
        } else if (key == "output") {
            if (expect_char(json_str, pos, '{')) {
                while (true) {
                    skip_ws(json_str, pos);
                    if (pos >= json_str.size()) break;
                    if (json_str[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string okey = parse_json_string(json_str, pos);
                    expect_char(json_str, pos, ':');
                    if (okey == "result_json") req.output.result_json = parse_json_string(json_str, pos);
                    else if (okey == "trace_json") req.output.trace_json = parse_json_string(json_str, pos);
                    else skip_json_value(json_str, pos);
                    skip_ws(json_str, pos);
                    if (pos < json_str.size() && json_str[pos] == ',') pos++;
                }
            }
        } else {
            skip_json_value(json_str, pos);
        }
        
        skip_ws(json_str, pos);
        if (pos < json_str.size() && json_str[pos] == ',') {
            pos++;
            continue;
        }
        if (pos < json_str.size() && json_str[pos] == '}') {
            pos++;
            break;
        }
    }
    
    return req;
}

SimulationResult JsonParser::parse_result(const std::string& json_str) {
    SimulationResult result;
    size_t pos = 0;
    
    if (!expect_char(json_str, pos, '{')) return result;
    
    while (true) {
        skip_ws(json_str, pos);
        if (pos >= json_str.size()) break;
        if (json_str[pos] == '}') {
            pos++;
            break;
        }
        
        std::string key = parse_json_string(json_str, pos);
        expect_char(json_str, pos, ':');
        
        if (key == "schema_version") {
            result.schema_version = parse_json_string(json_str, pos);
        } else if (key == "run_id") {
            result.run_id = parse_json_string(json_str, pos);
        } else if (key == "status") {
            result.status = parse_json_string(json_str, pos);
        } else if (key == "error_message") {
            result.error_message = parse_json_string(json_str, pos);
        } else if (key == "metrics") {
            if (expect_char(json_str, pos, '{')) {
                while (true) {
                    skip_ws(json_str, pos);
                    if (pos >= json_str.size()) break;
                    if (json_str[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string mkey = parse_json_string(json_str, pos);
                    expect_char(json_str, pos, ':');
                    if (mkey == "latency_ms") result.metrics.latency_ms = parse_json_number(json_str, pos);
                    else if (mkey == "host_time_ms") result.metrics.host_time_ms = parse_json_number(json_str, pos);
                    else if (mkey == "device_time_ms") result.metrics.device_time_ms = parse_json_number(json_str, pos);
                    else if (mkey == "dma_time_ms") result.metrics.dma_time_ms = parse_json_number(json_str, pos);
                    else if (mkey == "throughput_gops") result.metrics.throughput_gops = parse_json_number(json_str, pos);
                    else if (mkey == "power_w") result.metrics.power_w = parse_json_number(json_str, pos);
                    else if (mkey == "energy_j") result.metrics.energy_j = parse_json_number(json_str, pos);
                    else if (mkey == "area_mm2") result.metrics.area_mm2 = parse_json_number(json_str, pos);
                    else if (mkey == "total_data_movement_mb") result.metrics.total_data_movement_mb = parse_json_number(json_str, pos);
                    else skip_json_value(json_str, pos);
                    skip_ws(json_str, pos);
                    if (pos < json_str.size() && json_str[pos] == ',') pos++;
                }
            }
        } else if (key == "resource_utilization") {
            if (expect_char(json_str, pos, '{')) {
                while (true) {
                    skip_ws(json_str, pos);
                    if (pos >= json_str.size()) break;
                    if (json_str[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string rkey = parse_json_string(json_str, pos);
                    expect_char(json_str, pos, ':');
                    ResourceUtilization util;
                    if (expect_char(json_str, pos, '{')) {
                        while (true) {
                            skip_ws(json_str, pos);
                            if (pos >= json_str.size()) break;
                            if (json_str[pos] == '}') {
                                pos++;
                                break;
                            }
                            std::string ukey = parse_json_string(json_str, pos);
                            expect_char(json_str, pos, ':');
                            if (ukey == "compute_percent") util.compute_percent = parse_json_number(json_str, pos);
                            else if (ukey == "memory_percent") util.memory_percent = parse_json_number(json_str, pos);
                            else if (ukey == "bandwidth_percent") util.bandwidth_percent = parse_json_number(json_str, pos);
                            else skip_json_value(json_str, pos);
                            skip_ws(json_str, pos);
                            if (pos < json_str.size() && json_str[pos] == ',') pos++;
                        }
                    }
                    result.resource_utilization[rkey] = util;
                    skip_ws(json_str, pos);
                    if (pos < json_str.size() && json_str[pos] == ',') pos++;
                }
            }
        } else if (key == "events") {
            if (expect_char(json_str, pos, '[')) {
                while (true) {
                    skip_ws(json_str, pos);
                    if (pos >= json_str.size()) break;
                    if (json_str[pos] == ']') {
                        pos++;
                        break;
                    }
                    TraceEvent event;
                    if (expect_char(json_str, pos, '{')) {
                        while (true) {
                            skip_ws(json_str, pos);
                            if (pos >= json_str.size()) break;
                            if (json_str[pos] == '}') {
                                pos++;
                                break;
                            }
                            std::string ekey = parse_json_string(json_str, pos);
                            expect_char(json_str, pos, ':');
                            if (ekey == "node_id") event.node_id = parse_json_string(json_str, pos);
                            else if (ekey == "device") event.device = parse_json_string(json_str, pos);
                            else if (ekey == "start_ns") event.start_ns = parse_json_number(json_str, pos);
                            else if (ekey == "end_ns") event.end_ns = parse_json_number(json_str, pos);
                            else if (ekey == "op_type") event.op_type = parse_json_string(json_str, pos);
                            else skip_json_value(json_str, pos);
                            skip_ws(json_str, pos);
                            if (pos < json_str.size() && json_str[pos] == ',') pos++;
                        }
                    }
                    result.events.push_back(event);
                    skip_ws(json_str, pos);
                    if (pos < json_str.size() && json_str[pos] == ',') pos++;
                }
            }
        } else if (key == "uncertainty") {
            if (expect_char(json_str, pos, '{')) {
                while (true) {
                    skip_ws(json_str, pos);
                    if (pos >= json_str.size()) break;
                    if (json_str[pos] == '}') {
                        pos++;
                        break;
                    }
                    std::string ukey = parse_json_string(json_str, pos);
                    expect_char(json_str, pos, ':');
                    if (ukey == "fidelity_level") result.uncertainty.fidelity_level = parse_json_string(json_str, pos);
                    else if (ukey == "confidence_level") result.uncertainty.confidence_level = parse_json_number(json_str, pos);
                    else if (ukey == "mape_percent") result.uncertainty.mape_percent = parse_json_number(json_str, pos);
                    else skip_json_value(json_str, pos);
                    skip_ws(json_str, pos);
                    if (pos < json_str.size() && json_str[pos] == ',') pos++;
                }
            }
        } else {
            skip_json_value(json_str, pos);
        }
        
        skip_ws(json_str, pos);
        if (pos < json_str.size() && json_str[pos] == ',') {
            pos++;
            continue;
        }
        if (pos < json_str.size() && json_str[pos] == '}') {
            pos++;
            break;
        }
    }
    
    return result;
}

std::string JsonParser::serialize_result(const SimulationResult& result) {
    std::ostringstream oss;
    oss << "{\n";
    oss << "  \"schema_version\": \"" << result.schema_version << "\",\n";
    oss << "  \"run_id\": \"" << result.run_id << "\",\n";
    oss << "  \"status\": \"" << result.status << "\",\n";
    
    if (!result.error_message.empty()) {
        oss << "  \"error_message\": \"" << result.error_message << "\",\n";
    }
    
    oss << "  \"metrics\": {\n";
    oss << "    \"latency_ms\": " << result.metrics.latency_ms << ",\n";
    oss << "    \"host_time_ms\": " << result.metrics.host_time_ms << ",\n";
    oss << "    \"device_time_ms\": " << result.metrics.device_time_ms << ",\n";
    oss << "    \"dma_time_ms\": " << result.metrics.dma_time_ms << ",\n";
    oss << "    \"throughput_gops\": " << result.metrics.throughput_gops << ",\n";
    oss << "    \"power_w\": " << result.metrics.power_w << ",\n";
    oss << "    \"energy_j\": " << result.metrics.energy_j << ",\n";
    oss << "    \"area_mm2\": " << result.metrics.area_mm2 << ",\n";
    oss << "    \"total_data_movement_mb\": " << result.metrics.total_data_movement_mb << "\n";
    oss << "  },\n";
    
    oss << "  \"resource_utilization\": {\n";
    bool first = true;
    for (const auto& [device, util] : result.resource_utilization) {
        if (!first) oss << ",\n";
        first = false;
        oss << "    \"" << device << "\": {\n";
        oss << "      \"compute_percent\": " << util.compute_percent << ",\n";
        oss << "      \"memory_percent\": " << util.memory_percent << ",\n";
        oss << "      \"bandwidth_percent\": " << util.bandwidth_percent << "\n";
        oss << "    }";
    }
    oss << "\n  },\n";
    
    oss << "  \"events\": [\n";
    first = true;
    for (const auto& event : result.events) {
        if (!first) oss << ",\n";
        first = false;
        oss << "    {\n";
        oss << "      \"node_id\": \"" << event.node_id << "\",\n";
        oss << "      \"device\": \"" << event.device << "\",\n";
        oss << "      \"start_ns\": " << event.start_ns << ",\n";
        oss << "      \"end_ns\": " << event.end_ns << ",\n";
        oss << "      \"op_type\": \"" << event.op_type << "\"\n";
        oss << "    }";
    }
    oss << "\n  ],\n";
    
    oss << "  \"uncertainty\": {\n";
    oss << "    \"fidelity_level\": \"" << result.uncertainty.fidelity_level << "\",\n";
    oss << "    \"confidence_level\": " << result.uncertainty.confidence_level << ",\n";
    oss << "    \"mape_percent\": " << result.uncertainty.mape_percent << "\n";
    oss << "  }\n";
    
    oss << "}\n";
    return oss.str();
}

} // namespace gsim
