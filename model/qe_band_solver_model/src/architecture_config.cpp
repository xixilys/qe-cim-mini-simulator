#include "architecture_config.hpp"

#include <fstream>
#include <sstream>

namespace qebs {

std::string ComputeUnitConfig::brief() const {
  std::ostringstream oss;
  oss << "type=" << to_string(type);
  
  if (type == ComputeUnitType::CIM_ARRAY) {
    oss << ", moduli=" << cim_moduli_count
        << ", array=" << cim_array_rows << "x" << cim_array_cols
        << ", freq=" << cim_frequency_mhz << "MHz";
  } else if (type == ComputeUnitType::TRADITIONAL_FPGA) {
    oss << ", tile=" << fpga_tile_size
        << ", dsp=" << fpga_dsp_count
        << ", freq=" << fpga_frequency_mhz << "MHz";
  }
  
  oss << ", parallelism=" << parallelism
      << ", karatsuba=" << (enable_karatsuba ? "on" : "off");
  
  return oss.str();
}

std::string ClusterConfig::brief() const {
  std::ostringstream oss;
  oss << "id=" << cluster_id
      << ", type=" << to_string(type)
      << ", buffer=" << on_chip_buffer_kb << "KB"
      << ", dma=" << dma_bandwidth_gbps << "Gbps"
      << ", pipeline=" << (enable_pipelining ? "on" : "off")
      << ", depth=" << pipeline_depth
      << ", resident_policy=" << resident_policy
      << ", compute_unit={" << compute_unit.brief() << "}";
  return oss.str();
}

bool ArchitectureConfig::ResourceUsage::within_limits(const ResourceLimits& limits) const {
  return dsp_used <= limits.max_dsp &&
         bram_18k_used <= limits.max_bram_18k &&
         uram_used <= limits.max_uram &&
         lut_used <= limits.max_lut &&
         ff_used <= limits.max_ff;
}

std::string ArchitectureConfig::ResourceUsage::brief() const {
  std::ostringstream oss;
  oss << "DSP=" << dsp_used
      << ", BRAM=" << bram_18k_used
      << ", URAM=" << uram_used
      << ", LUT=" << lut_used
      << ", FF=" << ff_used;
  return oss.str();
}

bool ArchitectureConfig::is_valid() const {
  return validate().empty();
}

std::string ArchitectureConfig::validate() const {
  if (clusters.empty()) {
    return "No clusters defined";
  }
  
  if (template_id.empty()) {
    return "template_id is empty";
  }
  
  for (const auto& cluster : clusters) {
    if (cluster.cluster_id.empty()) {
      return "Cluster has empty cluster_id";
    }
  }
  
  auto resources = estimate_resources();
  if (!resources.within_limits(resource_limits)) {
    return "Resource usage exceeds FPGA limits: " + resources.brief();
  }
  
  return "";
}

ArchitectureConfig::ResourceUsage ArchitectureConfig::estimate_resources() const {
  ResourceUsage usage;
  
  for (const auto& cluster : clusters) {
    const auto& cu = cluster.compute_unit;
    
    if (cu.type == ComputeUnitType::CIM_ARRAY) {
      usage.dsp_used += 50;
      usage.bram_18k_used += 80;
      usage.uram_used += 10;
      usage.lut_used += 50000;
      usage.ff_used += 80000;
    } else if (cu.type == ComputeUnitType::TRADITIONAL_FPGA) {
      usage.dsp_used += cu.fpga_dsp_count;
      usage.bram_18k_used += 60;
      usage.uram_used += 8;
      usage.lut_used += 40000;
      usage.ff_used += 60000;
    }
    
    usage.bram_18k_used += cluster.on_chip_buffer_kb / 36;
  }
  
  usage.lut_used += 50000;
  usage.ff_used += 80000;
  
  return usage;
}

std::string ArchitectureConfig::brief() const {
  std::ostringstream oss;
  oss << "template=" << template_id
      << ", label=" << template_label
      << ", family=" << architecture_family
      << ", clusters=" << cluster_count()
      << ", offload=" << offload_scope
      << ", diag=" << diag_policy
      << ", fft=" << (enable_device_fft ? "device" : "host");
  return oss.str();
}

ArchitectureConfig ArchitectureConfig::from_f1_template() {
  ArchitectureConfig config;
  config.template_id = "F1";
  config.template_label = "HostHeavySingleHotpath";
  config.architecture_family = "F1";
  config.offload_scope = "single_hotpath";
  config.diag_policy = "cpu_only";
  config.enable_device_fft = false;
  config.force_host_diag = true;
  config.allow_cpu_diag_fallback = true;
  
  ClusterConfig cluster_a;
  cluster_a.cluster_id = "cluster_a";
  cluster_a.type = ClusterType::OPERATOR_SWEEP;
  cluster_a.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_a.on_chip_buffer_kb = 448;
  cluster_a.resident_policy = "fit_first";
  cluster_a.resident_budget_scale = 0.85;
  
  ClusterConfig cluster_b;
  cluster_b.cluster_id = "cluster_b";
  cluster_b.type = ClusterType::REDUCED_BUILD;
  cluster_b.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_b.on_chip_buffer_kb = 128;
  
  ClusterConfig cluster_c;
  cluster_c.cluster_id = "cluster_c";
  cluster_c.type = ClusterType::HARDWARE_DIAG;
  cluster_c.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_c.on_chip_buffer_kb = 256;
  
  ClusterConfig cluster_d;
  cluster_d.cluster_id = "cluster_d";
  cluster_d.type = ClusterType::REFRESH_RESIDUAL;
  cluster_d.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_d.on_chip_buffer_kb = 128;
  
  config.clusters = {cluster_a, cluster_b, cluster_c, cluster_d};
  
  return config;
}

ArchitectureConfig ArchitectureConfig::create_default() {
  // Default to F2 balanced architecture
  return from_f2_template();
}

ArchitectureConfig ArchitectureConfig::from_f2_template() {
  ArchitectureConfig config;
  config.template_id = "F2";
  config.template_label = "BalancedHybrid";
  config.architecture_family = "F2";
  config.offload_scope = "balanced";
  config.diag_policy = "device_first_fallback";
  config.enable_device_fft = true;
  config.force_host_diag = false;
  config.allow_cpu_diag_fallback = true;
  
  ClusterConfig cluster_a;
  cluster_a.cluster_id = "cluster_a";
  cluster_a.type = ClusterType::OPERATOR_SWEEP;
  cluster_a.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_a.on_chip_buffer_kb = 448;
  cluster_a.resident_policy = "fit_first";
  cluster_a.resident_budget_scale = 1.0;
  
  ClusterConfig cluster_b;
  cluster_b.cluster_id = "cluster_b";
  cluster_b.type = ClusterType::REDUCED_BUILD;
  cluster_b.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_b.on_chip_buffer_kb = 128;
  
  ClusterConfig cluster_c;
  cluster_c.cluster_id = "cluster_c";
  cluster_c.type = ClusterType::HARDWARE_DIAG;
  cluster_c.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_c.on_chip_buffer_kb = 256;
  
  ClusterConfig cluster_d;
  cluster_d.cluster_id = "cluster_d";
  cluster_d.type = ClusterType::REFRESH_RESIDUAL;
  cluster_d.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_d.on_chip_buffer_kb = 128;
  
  config.clusters = {cluster_a, cluster_b, cluster_c, cluster_d};
  
  return config;
}

ArchitectureConfig ArchitectureConfig::from_f3_template() {
  ArchitectureConfig config;
  config.template_id = "F3";
  config.template_label = "DeviceHeavyFullInnerLoop";
  config.architecture_family = "F3";
  config.offload_scope = "device_heavy";
  config.diag_policy = "aggressive_device";
  config.enable_device_fft = true;
  config.force_host_diag = false;
  config.allow_cpu_diag_fallback = true;
  
  ClusterConfig cluster_a;
  cluster_a.cluster_id = "cluster_a";
  cluster_a.type = ClusterType::OPERATOR_SWEEP;
  cluster_a.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_a.on_chip_buffer_kb = 512;
  cluster_a.resident_policy = "spill_tolerant";
  cluster_a.resident_budget_scale = 1.2;
  
  ClusterConfig cluster_b;
  cluster_b.cluster_id = "cluster_b";
  cluster_b.type = ClusterType::REDUCED_BUILD;
  cluster_b.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_b.on_chip_buffer_kb = 192;
  
  ClusterConfig cluster_c;
  cluster_c.cluster_id = "cluster_c";
  cluster_c.type = ClusterType::HARDWARE_DIAG;
  cluster_c.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_c.on_chip_buffer_kb = 384;
  
  ClusterConfig cluster_d;
  cluster_d.cluster_id = "cluster_d";
  cluster_d.type = ClusterType::REFRESH_RESIDUAL;
  cluster_d.compute_unit.type = ComputeUnitType::CIM_ARRAY;
  cluster_d.on_chip_buffer_kb = 192;
  
  config.clusters = {cluster_a, cluster_b, cluster_c, cluster_d};
  
  return config;
}

namespace {

std::string trim(const std::string& str) {
  size_t start = 0;
  while (start < str.size() && std::isspace(str[start])) ++start;
  size_t end = str.size();
  while (end > start && std::isspace(str[end - 1])) --end;
  return str.substr(start, end - start);
}

std::string unquote(const std::string& str) {
  std::string s = trim(str);
  if (s.size() >= 2 && s.front() == '"' && s.back() == '"') {
    return s.substr(1, s.size() - 2);
  }
  return s;
}

double parse_double(const std::string& str) {
  std::string s = trim(str);
  if (s.empty()) return 0.0;
  try {
    return std::stod(s);
  } catch (...) {
    return 0.0;
  }
}

int parse_int(const std::string& str) {
  std::string s = trim(str);
  if (s.empty()) return 0;
  try {
    return std::stoi(s);
  } catch (...) {
    return 0;
  }
}

bool parse_bool(const std::string& str) {
  std::string s = trim(str);
  return s == "true" || s == "1";
}

std::string extract_json_value(const std::string& json, const std::string& key) {
  std::string search = "\"" + key + "\"";
  size_t pos = json.find(search);
  if (pos == std::string::npos) return "";
  
  pos = json.find(':', pos);
  if (pos == std::string::npos) return "";
  ++pos;
  
  while (pos < json.size() && std::isspace(json[pos])) ++pos;
  
  if (json[pos] == '"') {
    size_t end = json.find('"', pos + 1);
    if (end == std::string::npos) return "";
    return json.substr(pos, end - pos + 1);
  } else if (json[pos] == '{') {
    int depth = 1;
    size_t start = pos;
    ++pos;
    while (pos < json.size() && depth > 0) {
      if (json[pos] == '{') ++depth;
      else if (json[pos] == '}') --depth;
      ++pos;
    }
    return json.substr(start, pos - start);
  } else if (json[pos] == '[') {
    int depth = 1;
    size_t start = pos;
    ++pos;
    while (pos < json.size() && depth > 0) {
      if (json[pos] == '[') ++depth;
      else if (json[pos] == ']') --depth;
      ++pos;
    }
    return json.substr(start, pos - start);
  } else {
    size_t end = pos;
    while (end < json.size() && json[end] != ',' && json[end] != '}' && json[end] != ']') {
      ++end;
    }
    return json.substr(pos, end - pos);
  }
}

std::vector<std::string> split_json_array(const std::string& json_array) {
  std::vector<std::string> result;
  std::string arr = trim(json_array);
  if (arr.empty() || arr.front() != '[' || arr.back() != ']') return result;
  
  arr = arr.substr(1, arr.size() - 2);
  
  size_t pos = 0;
  int depth = 0;
  size_t start = 0;
  
  while (pos < arr.size()) {
    if (arr[pos] == '{' || arr[pos] == '[') {
      ++depth;
    } else if (arr[pos] == '}' || arr[pos] == ']') {
      --depth;
    } else if (arr[pos] == ',' && depth == 0) {
      result.push_back(trim(arr.substr(start, pos - start)));
      start = pos + 1;
    }
    ++pos;
  }
  
  if (start < arr.size()) {
    result.push_back(trim(arr.substr(start)));
  }
  
  return result;
}

ComputeUnitConfig parse_compute_unit(const std::string& json) {
  ComputeUnitConfig cu;
  
  std::string type_str = unquote(extract_json_value(json, "type"));
  cu.type = compute_unit_type_from_string(type_str);
  
  cu.parallelism = parse_int(extract_json_value(json, "parallelism"));
  cu.enable_karatsuba = parse_bool(extract_json_value(json, "enable_karatsuba"));
  
  if (cu.type == ComputeUnitType::CIM_ARRAY) {
    cu.cim_moduli_count = parse_int(extract_json_value(json, "cim_moduli_count"));
    cu.cim_array_rows = parse_int(extract_json_value(json, "cim_array_rows"));
    cu.cim_array_cols = parse_int(extract_json_value(json, "cim_array_cols"));
    cu.cim_frequency_mhz = parse_double(extract_json_value(json, "cim_frequency_mhz"));
  } else if (cu.type == ComputeUnitType::TRADITIONAL_FPGA) {
    cu.fpga_tile_size = parse_int(extract_json_value(json, "fpga_tile_size"));
    cu.fpga_dsp_count = parse_int(extract_json_value(json, "fpga_dsp_count"));
    cu.fpga_frequency_mhz = parse_double(extract_json_value(json, "fpga_frequency_mhz"));
  }
  
  return cu;
}

ClusterConfig parse_cluster(const std::string& json) {
  ClusterConfig cluster;
  
  cluster.cluster_id = unquote(extract_json_value(json, "cluster_id"));
  
  std::string type_str = unquote(extract_json_value(json, "type"));
  if (type_str.empty()) {
    type_str = unquote(extract_json_value(json, "role"));
  }
  cluster.type = cluster_type_from_string(type_str);
  
  cluster.enabled = parse_bool(extract_json_value(json, "enabled"));
  if (extract_json_value(json, "enabled").empty()) {
    cluster.enabled = true;
  }
  
  cluster.fusion_group = unquote(extract_json_value(json, "fusion_group"));
  
  std::string cu_str = unquote(extract_json_value(json, "compute_unit"));
  if (!cu_str.empty()) {
    ComputeUnitConfig cu;
    cu.type = compute_unit_type_from_string(cu_str);
    cluster.compute_unit = cu;
  } else {
    std::string cu_json = extract_json_value(json, "compute_unit");
    cluster.compute_unit = parse_compute_unit(cu_json);
  }
  
  cluster.on_chip_buffer_kb = parse_int(extract_json_value(json, "on_chip_buffer_kb"));
  cluster.dma_bandwidth_gbps = parse_int(extract_json_value(json, "dma_bandwidth_gbps"));
  cluster.enable_pipelining = parse_bool(extract_json_value(json, "enable_pipelining"));
  cluster.pipeline_depth = parse_int(extract_json_value(json, "pipeline_depth"));
  cluster.resident_policy = unquote(extract_json_value(json, "resident_policy"));
  cluster.resident_budget_scale = parse_double(extract_json_value(json, "resident_budget_scale"));
  cluster.enable_backpressure = parse_bool(extract_json_value(json, "enable_backpressure"));
  cluster.max_concurrent_ops = parse_int(extract_json_value(json, "max_concurrent_ops"));
  
  return cluster;
}

}  // namespace

ArchitectureConfig ArchitectureConfig::from_json_file(const std::string& path) {
  std::ifstream file(path);
  if (!file) {
    ArchitectureConfig config;
    config.template_id = "error";
    config.template_label = "FileNotFound";
    config.architecture_family = "error";
    return config;
  }
  
  std::stringstream buffer;
  buffer << file.rdbuf();
  std::string json = buffer.str();
  
  ArchitectureConfig config;
  config.template_id = unquote(extract_json_value(json, "template_id"));
  config.template_label = unquote(extract_json_value(json, "template_label"));
  config.architecture_family = unquote(extract_json_value(json, "architecture_family"));
  
  std::string clusters_json = extract_json_value(json, "clusters");
  auto cluster_jsons = split_json_array(clusters_json);
  
  for (const auto& cluster_json : cluster_jsons) {
    config.clusters.push_back(parse_cluster(cluster_json));
  }
  
  std::string limits_json = extract_json_value(json, "resource_limits");
  if (!limits_json.empty()) {
    config.resource_limits.max_dsp = parse_int(extract_json_value(limits_json, "max_dsp"));
    config.resource_limits.max_bram_18k = parse_int(extract_json_value(limits_json, "max_bram_18k"));
    config.resource_limits.max_uram = parse_int(extract_json_value(limits_json, "max_uram"));
    config.resource_limits.max_lut = parse_int(extract_json_value(limits_json, "max_lut"));
    config.resource_limits.max_ff = parse_int(extract_json_value(limits_json, "max_ff"));
  }
  
  return config;
}

std::string to_string(ComputeUnitType type) {
  switch (type) {
    case ComputeUnitType::CIM_ARRAY: return "cim_array";
    case ComputeUnitType::TRADITIONAL_FPGA: return "traditional_fpga";
    case ComputeUnitType::PIM: return "pim";
    case ComputeUnitType::HYBRID: return "hybrid";
    default: return "unknown";
  }
}

std::string to_string(ClusterType type) {
  switch (type) {
    case ClusterType::OPERATOR_SWEEP: return "operator_sweep";
    case ClusterType::REDUCED_BUILD: return "reduced_build";
    case ClusterType::HARDWARE_DIAG: return "hardware_diag";
    case ClusterType::REFRESH_RESIDUAL: return "refresh_residual";
    case ClusterType::FUSED_BUILD_DIAG: return "fused_build_diag";
    case ClusterType::CUSTOM: return "custom";
    default: return "unknown";
  }
}

ComputeUnitType compute_unit_type_from_string(const std::string& str) {
  if (str == "cim_array") return ComputeUnitType::CIM_ARRAY;
  if (str == "traditional_fpga" || str == "traditional_fpga_dsp") return ComputeUnitType::TRADITIONAL_FPGA;
  if (str == "pim" || str == "pim_array") return ComputeUnitType::PIM;
  if (str == "hybrid") return ComputeUnitType::HYBRID;
  return ComputeUnitType::CIM_ARRAY;
}

ClusterType cluster_type_from_string(const std::string& str) {
  if (str == "operator_sweep") return ClusterType::OPERATOR_SWEEP;
  if (str == "reduced_build") return ClusterType::REDUCED_BUILD;
  if (str == "hardware_diag") return ClusterType::HARDWARE_DIAG;
  if (str == "refresh_residual") return ClusterType::REFRESH_RESIDUAL;
  if (str == "fused_build_diag") return ClusterType::FUSED_BUILD_DIAG;
  if (str == "custom") return ClusterType::CUSTOM;
  return ClusterType::OPERATOR_SWEEP;
}

}  // namespace qebs
