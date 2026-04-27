#include <chrono>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>

#include "architecture_config.hpp"
#include "dft_hybrid_system.hpp"
#include "logging.hpp"

namespace {

std::string env_or_default(const char* name, const std::string& fallback) {
  const char* value = std::getenv(name);
  return value ? std::string(value) : fallback;
}

bool env_bool_or_default(const char* name, bool fallback) {
  const char* value = std::getenv(name);
  if (!value) {
    return fallback;
  }
  const std::string parsed(value);
  return !(parsed == "0" || parsed == "false" || parsed == "FALSE" ||
           parsed == "off" || parsed == "OFF");
}

std::string json_escape(const std::string& value) {
  std::ostringstream oss;
  for (const char ch : value) {
    switch (ch) {
      case '\\': oss << "\\\\"; break;
      case '"': oss << "\\\""; break;
      case '\n': oss << "\\n"; break;
      case '\r': oss << "\\r"; break;
      case '\t': oss << "\\t"; break;
      default: oss << ch; break;
    }
  }
  return oss.str();
}

std::string json_bool(bool value) { return value ? "true" : "false"; }

std::string now_utc_iso8601() {
  using Clock = std::chrono::system_clock;
  const auto now = Clock::now();
  const std::time_t now_time = Clock::to_time_t(now);
  std::tm utc_tm{};
#if defined(_WIN32)
  gmtime_s(&utc_tm, &now_time);
#else
  gmtime_r(&now_time, &utc_tm);
#endif
  std::ostringstream oss;
  oss << std::put_time(&utc_tm, "%Y-%m-%dT%H:%M:%SZ");
  return oss.str();
}

void write_candidate_result_json(const qebs::SCFRunReport& report,
                                 const std::string& case_id,
                                 const std::string& output_path,
                                 double wall_time_s) {
  if (output_path.empty()) {
    return;
  }

  const auto& final_state = report.final_state;
  const auto* last_iteration =
      report.iterations.empty() ? nullptr : &report.iterations.back();
  qebs::ClusterMetrics total_cluster_a;
  qebs::ClusterMetrics total_cluster_b;
  qebs::ClusterMetrics total_cluster_c;
  qebs::ClusterMetrics total_cluster_d;
  auto accumulate_cluster_metrics = [](qebs::ClusterMetrics& dst,
                                       const qebs::ClusterMetrics& src) {
    dst.cluster_name = src.cluster_name;
    dst.invocations += src.invocations;
    dst.accounted_ref_cycles += src.accounted_ref_cycles;
    dst.backpressure_ref_cycles += src.backpressure_ref_cycles;
    dst.data_movement_kib += src.data_movement_kib;
    if (!src.dominant_resource.empty() && src.dominant_resource != "NONE") {
      dst.dominant_resource = src.dominant_resource;
    }
    if (!src.detail.empty()) {
      dst.detail = src.detail;
    }
  };
  for (const auto& iteration : report.iterations) {
    accumulate_cluster_metrics(total_cluster_a, iteration.episode.cluster_a);
    accumulate_cluster_metrics(total_cluster_b, iteration.episode.cluster_b);
    accumulate_cluster_metrics(total_cluster_c, iteration.episode.cluster_c);
    accumulate_cluster_metrics(total_cluster_d, iteration.episode.cluster_d);
  }

  std::ofstream out(output_path);
  if (!out) {
    qebs::log_line("sc_main", "Failed to open candidate result JSON path: " + output_path);
    return;
  }

  out << "{\n";
  out << "  \"schema_version\": \"systemc_architecture_candidate_result_v0\",\n";
  out << "  \"generated_at_utc\": \"" << json_escape(now_utc_iso8601()) << "\",\n";
  out << "  \"case_id\": \"" << json_escape(case_id) << "\",\n";
  out << "  \"architecture_family\": \"" << json_escape(report.architecture_family) << "\",\n";
  out << "  \"assumption_set_id\": \"" << json_escape(report.assumption_set_id) << "\",\n";
  out << "  \"run_config\": {\n";
  out << "    \"software_family\": \"" << json_escape(report.run_config.software_family) << "\",\n";
  out << "    \"flow_family\": \"" << json_escape(report.run_config.flow_family) << "\",\n";
  out << "    \"case_id\": \"" << json_escape(report.run_config.case_id) << "\",\n";
  out << "    \"signature_id\": \"" << json_escape(report.run_config.signature_id) << "\",\n";
  out << "    \"property_target\": \"" << json_escape(report.run_config.property_target) << "\",\n";
  out << "    \"pseudopotential_family\": \"" << json_escape(report.run_config.pseudopotential_family) << "\",\n";
  out << "    \"solver_path_class\": \"" << json_escape(report.run_config.solver_path_class) << "\",\n";
  out << "    \"workload_topology\": \"" << json_escape(report.run_config.workload_topology) << "\",\n";
  out << "    \"post_scf_extension_level\": \"" << json_escape(report.run_config.post_scf_extension_level) << "\",\n";
  out << "    \"projector_pressure\": \"" << json_escape(report.run_config.projector_pressure) << "\",\n";
  out << "    \"nonlocal_pressure\": \"" << json_escape(report.run_config.nonlocal_pressure) << "\",\n";
  out << "    \"generalized_ratio_bucket\": \"" << json_escape(report.run_config.generalized_ratio_bucket) << "\",\n";
  out << "    \"diag_dominance\": \"" << json_escape(report.run_config.diag_dominance) << "\",\n";
  out << "    \"fft_grid_pressure\": \"" << json_escape(report.run_config.fft_grid_pressure) << "\",\n";
  out << "    \"max_scf_iters\": " << report.run_config.max_scf_iters << ",\n";
  out << "    \"enable_fft\": " << json_bool(report.run_config.enable_fft) << ",\n";
  out << "    \"device_diag_max_dim\": " << report.run_config.device_diag_max_dim << ",\n";
  out << "    \"force_host_diag\": " << json_bool(report.run_config.force_host_diag) << ",\n";
  out << "    \"allow_cpu_diag_fallback\": " << json_bool(report.run_config.allow_cpu_diag_fallback) << "\n";
  out << "  },\n";
  const std::string graph_frontdoor_mode =
      report.run_config.graph_frontdoor_mode;
  if (!graph_frontdoor_mode.empty()) {
    out << "  \"graph_frontdoor_profile\": {\n";
    out << "    \"mode\": \"" << json_escape(graph_frontdoor_mode) << "\",\n";
    out << "    \"graph_id\": \"" << json_escape(report.run_config.graph_id) << "\",\n";
    out << "    \"topology_style\": \"" << json_escape(report.run_config.graph_topology_style) << "\",\n";
    out << "    \"graph_module_count\": " << report.run_config.graph_module_count << ",\n";
    out << "    \"graph_flow_count\": " << report.run_config.graph_flow_count << ",\n";
    out << "    \"leaf_component_count\": " << report.run_config.graph_leaf_component_count << ",\n";
    out << "    \"has_fft_unit\": " << json_bool(report.run_config.graph_has_fft_unit) << ",\n";
    out << "    \"has_reduction_unit\": " << json_bool(report.run_config.graph_has_reduction_unit) << ",\n";
    out << "    \"has_diag_unit\": " << json_bool(report.run_config.graph_has_diag_unit) << ",\n";
    out << "    \"has_vector_diag_companion\": "
        << json_bool(report.run_config.graph_has_vector_diag_companion) << ",\n";
    out << "    \"has_refresh_unit\": "
        << json_bool(report.run_config.graph_has_refresh_unit) << ",\n";
    out << "    \"has_leaf_hotpath_flow\": "
        << json_bool(report.run_config.graph_has_leaf_hotpath_flow) << ",\n";
    out << "    \"prefers_diag_before_reduction\": "
        << json_bool(report.run_config.graph_prefers_diag_before_reduction) << ",\n";
    out << "    \"prefers_refresh_before_diag\": "
        << json_bool(report.run_config.graph_prefers_refresh_before_diag) << ",\n";
    out << "    \"requested_cluster_sequence\": \""
        << json_escape(report.run_config.graph_requested_cluster_sequence) << "\",\n";
    out << "    \"resolved_cluster_sequence\": \""
        << json_escape(report.run_config.graph_resolved_cluster_sequence) << "\",\n";
    out << "    \"executed_cluster_sequence\": \""
        << json_escape(last_iteration != nullptr
                           ? last_iteration->completion.episode_result.graph_executed_cluster_sequence
                           : std::string()) << "\",\n";
    out << "    \"execution_plan_source\": \""
        << json_escape(last_iteration != nullptr
                           ? last_iteration->completion.episode_result.graph_execution_plan_source
                           : std::string()) << "\",\n";
    out << "    \"sequence_constraints\": \""
        << json_escape(report.run_config.graph_sequence_constraints) << "\"\n";
    out << "  },\n";
  }
  out << "  \"final\": {\n";
  out << "    \"total_energy_ry\": " << std::setprecision(16) << final_state.total_energy << ",\n";
  out << "    \"residual_threshold_reached\": " << json_bool(final_state.converged) << ",\n";
  out << "    \"converged\": " << json_bool(final_state.converged) << ",\n";
  out << "    \"scf_iterations\": " << report.iterations.size();
  if (last_iteration != nullptr) {
    out << ",\n";
    out << "    \"residual_norm\": " << std::setprecision(16)
        << last_iteration->completion.residual_norm << ",\n";
    out << "    \"density_delta\": " << std::setprecision(16)
        << last_iteration->density_delta << "\n";
  } else {
    out << "\n";
  }
  out << "  },\n";
  out << "  \"run_summary\": {\n";
  out << "    \"total_episodes\": " << report.total_episodes << ",\n";
  out << "    \"total_ref_cycles\": " << report.total_ref_cycles << ",\n";
  out << "    \"total_backpressure_ref_cycles\": "
      << report.total_backpressure_ref_cycles << ",\n";
  out << "    \"convergence_reason\": \""
      << json_escape(report.convergence_reason) << "\"\n";
  out << "  },\n";
  if (last_iteration != nullptr) {
    out << "  \"last_iteration\": {\n";
    out << "    \"diag_path\": \""
        << json_escape(last_iteration->completion.diag_path) << "\",\n";
    out << "    \"confidence_label\": \""
        << json_escape(last_iteration->completion.confidence_label) << "\",\n";
    out << "    \"resident_reused\": "
        << json_bool(last_iteration->completion.resident_reused) << ",\n";
    out << "    \"spill_active\": "
        << json_bool(last_iteration->completion.spill_active) << ",\n";
    out << "    \"used_device_fft\": "
        << json_bool(last_iteration->completion.used_device_fft) << ",\n";
    out << "    \"cpu_diag_fallback\": "
        << json_bool(last_iteration->completion.cpu_diag_fallback) << "\n";
    out << "  },\n";
  }
  out << "  \"iteration_diagnostics\": [\n";
  for (std::size_t idx = 0; idx < report.iterations.size(); ++idx) {
    const auto& iteration = report.iterations[idx];
    out << "    {\n";
    out << "      \"scf_iteration\": " << iteration.scf_iteration << ",\n";
    out << "      \"total_energy_ry\": " << std::setprecision(16)
        << iteration.energy_after_iteration << ",\n";
    out << "      \"density_delta\": " << std::setprecision(16)
        << iteration.density_delta << ",\n";
    out << "      \"rho_out_norm\": " << std::setprecision(16)
        << iteration.rho_out_norm << ",\n";
    out << "      \"mixed_rho_norm\": " << std::setprecision(16)
        << iteration.mixed_rho_norm << ",\n";
    out << "      \"potential_norm\": " << std::setprecision(16)
        << iteration.potential_norm << ",\n";
    out << "      \"residual_norm\": " << std::setprecision(16)
        << iteration.completion.residual_norm << ",\n";
    out << "      \"diag_path\": \""
        << json_escape(iteration.completion.diag_path) << "\",\n";
    out << "      \"signature_id\": \""
        << json_escape(iteration.request.signature_id) << "\",\n";
    out << "      \"property_target\": \""
        << json_escape(iteration.request.property_target) << "\",\n";
    out << "      \"projector_mode\": \""
        << json_escape(iteration.request.resident_set.projector_mode) << "\",\n";
    out << "      \"support_grid_mode\": \""
        << json_escape(iteration.request.resident_set.support_grid_mode) << "\",\n";
    out << "      \"band_count\": "
        << iteration.descriptor.band_count << ",\n";
    out << "      \"panel_count\": "
        << iteration.descriptor.panel_count << ",\n";
    out << "      \"workload_bucket\": \""
        << json_escape(iteration.descriptor.workload_bucket) << "\",\n";
    out << "      \"max_inner_steps\": "
        << iteration.descriptor.max_inner_steps << ",\n";
    out << "      \"inner_steps\": "
        << iteration.completion.inner_steps << ",\n";
    out << "      \"spill_active\": "
        << json_bool(iteration.completion.spill_active) << ",\n";
    out << "      \"device_busy_ref_cycles\": "
        << iteration.completion.device_busy_ref_cycles << ",\n";
    out << "      \"host_assist_ref_cycles\": "
        << iteration.completion.host_assist_ref_cycles << ",\n";
    out << "      \"max_diag_condition_estimate\": "
        << iteration.descriptor.max_diag_condition_estimate << ",\n";
    out << "      \"confidence_label\": \""
        << json_escape(iteration.completion.confidence_label) << "\",\n";
    out << "      \"converged_after_iteration\": "
        << json_bool(iteration.converged) << ",\n";
    out << "      \"cpu_diag_fallback\": "
        << json_bool(iteration.completion.cpu_diag_fallback) << ",\n";
    out << "      \"resident_reused\": "
        << json_bool(iteration.completion.resident_reused) << ",\n";
    out << "      \"spill_active\": "
        << json_bool(iteration.completion.spill_active) << ",\n";
    out << "      \"used_device_fft\": "
        << json_bool(iteration.completion.used_device_fft) << ",\n";
    out << "      \"total_data_movement_kib\": " << std::setprecision(16)
        << iteration.completion.total_data_movement_kib << ",\n";
    out << "      \"dma_read_kib\": " << std::setprecision(16)
        << iteration.completion.dma_read_kib << ",\n";
    out << "      \"dma_write_kib\": " << std::setprecision(16)
        << iteration.completion.dma_write_kib << ",\n";
    out << "      \"device_busy_ref_cycles\": "
        << iteration.completion.device_busy_ref_cycles << ",\n";
    out << "      \"host_assist_ref_cycles\": "
        << iteration.completion.host_assist_ref_cycles << "\n";
    out << "    }" << (idx + 1 < report.iterations.size() ? "," : "") << "\n";
  }
  out << "  ],\n";
  out << "  \"metrics\": {\n";
  out << "    \"device_busy_ref_cycles\": " << report.total_device_busy_ref_cycles << ",\n";
  out << "    \"dma_ref_cycles\": " << report.total_dma_ref_cycles << ",\n";
  out << "    \"host_assist_ref_cycles\": " << report.total_host_assist_ref_cycles << ",\n";
  out << "    \"cpu_fallbacks\": " << report.total_cpu_fallbacks << ",\n";
  out << "    \"resident_reuse_hits\": " << report.resident_reuse_hits << ",\n";
  out << "    \"total_data_movement_kib\": " << std::setprecision(16)
      << report.total_data_movement_kib << ",\n";
  out << "    \"dma_read_kib\": " << std::setprecision(16) << report.total_dma_read_kib << ",\n";
  out << "    \"dma_write_kib\": " << std::setprecision(16) << report.total_dma_write_kib << "\n";
  out << "  },\n";
  out << "  \"cluster_metrics\": {\n";
  auto write_cluster_metrics = [&out](const char* field_name,
                                      const qebs::ClusterMetrics& metrics,
                                      bool trailing_comma) {
    out << "    \"" << field_name << "\": {\n";
    out << "      \"cluster_name\": \"" << json_escape(metrics.cluster_name) << "\",\n";
    out << "      \"invocations\": " << metrics.invocations << ",\n";
    out << "      \"accounted_ref_cycles\": " << metrics.accounted_ref_cycles << ",\n";
    out << "      \"backpressure_ref_cycles\": " << metrics.backpressure_ref_cycles << ",\n";
    out << "      \"data_movement_kib\": " << std::setprecision(16)
        << metrics.data_movement_kib << ",\n";
    out << "      \"dominant_resource\": \"" << json_escape(metrics.dominant_resource)
        << "\",\n";
    out << "      \"detail\": \"" << json_escape(metrics.detail) << "\"\n";
    out << "    }" << (trailing_comma ? "," : "") << "\n";
  };
  write_cluster_metrics("cluster_a", total_cluster_a, true);
  write_cluster_metrics("cluster_b", total_cluster_b, true);
  write_cluster_metrics("cluster_c", total_cluster_c, true);
  write_cluster_metrics("cluster_d", total_cluster_d, false);
  out << "  },\n";
  out << "  \"timing\": {\n";
  out << "    \"wall_time_s\": " << std::setprecision(16) << wall_time_s << "\n";
  out << "  }\n";
  out << "}\n";
}

int env_int_or_default(const char* name, int fallback) {
  const char* value = std::getenv(name);
  return value ? std::atoi(value) : fallback;
}

qebs::SystemRunConfig load_run_config() {
  qebs::SystemRunConfig config;
  config.software_family = env_or_default("QEBS_SOFTWARE_FAMILY", "QE");
  std::string default_flow = "CBANDS_DIAG";
  if (config.software_family == "CP2K") {
    default_flow = "QS_DIAG";
  } else if (config.software_family == "VASP") {
    default_flow = "BLOCKED_DAVIDSON";
  }
  config.flow_family = env_or_default("QEBS_FLOW_FAMILY", default_flow);
  config.case_id = env_or_default("QEBS_CASE_ID", "systemc_candidate");
  config.architecture_family = env_or_default("QEBS_ARCH_FAMILY", "F2");
  config.assumption_set_id =
      env_or_default("QEBS_ASSUMPTION_SET_ID", "default-assumptions");
  config.signature_id = env_or_default("QEBS_SIGNATURE_ID", "");
  config.property_target = env_or_default("QEBS_PROPERTY_TARGET", "");
  config.pseudopotential_family = env_or_default("QEBS_PSEUDOPOTENTIAL_FAMILY", "");
  config.solver_path_class = env_or_default("QEBS_SOLVER_PATH_CLASS", "");
  config.workload_topology = env_or_default("QEBS_WORKLOAD_TOPOLOGY", "");
  config.post_scf_extension_level = env_or_default("QEBS_POST_SCF_EXTENSION_LEVEL", "");
  config.projector_pressure = env_or_default("QEBS_PROJECTOR_PRESSURE", "");
  config.nonlocal_pressure = env_or_default("QEBS_NONLOCAL_PRESSURE", "");
  config.generalized_ratio_bucket = env_or_default("QEBS_GENERALIZED_RATIO_BUCKET", "");
  config.diag_dominance = env_or_default("QEBS_DIAG_DOMINANCE", "");
  config.fft_grid_pressure = env_or_default("QEBS_FFT_GRID_PRESSURE", "");
  config.offload_scope_override =
      env_or_default("QEBS_OFFLOAD_SCOPE", "");
  config.resident_policy_override =
      env_or_default("QEBS_RESIDENT_POLICY", "");
  config.graph_frontdoor_mode =
      env_or_default("QEBS_GRAPH_FRONTDOOR_MODE", "");
  config.graph_id = env_or_default("QEBS_GRAPH_ID", "");
  config.graph_topology_style =
      env_or_default("QEBS_GRAPH_TOPOLOGY_STYLE", "");
  config.graph_module_count =
      env_int_or_default("QEBS_GRAPH_MODULE_COUNT", 0);
  config.graph_flow_count =
      env_int_or_default("QEBS_GRAPH_FLOW_COUNT", 0);
  config.graph_leaf_component_count =
      env_int_or_default("QEBS_GRAPH_LEAF_COMPONENT_COUNT", 0);
  config.graph_has_fft_unit =
      env_bool_or_default("QEBS_GRAPH_HAS_FFT_UNIT", false);
  config.graph_has_reduction_unit =
      env_bool_or_default("QEBS_GRAPH_HAS_REDUCTION", false);
  config.graph_has_diag_unit =
      env_bool_or_default("QEBS_GRAPH_HAS_DIAG", false);
  config.graph_has_vector_diag_companion =
      env_bool_or_default("QEBS_GRAPH_HAS_VECTOR_DIAG", false);
  config.graph_has_refresh_unit =
      env_bool_or_default("QEBS_GRAPH_HAS_REFRESH", false);
  config.graph_has_leaf_hotpath_flow =
      env_bool_or_default("QEBS_GRAPH_HAS_LEAF_FLOW", false);
  config.graph_prefers_diag_before_reduction =
      env_bool_or_default("QEBS_GRAPH_PREFERS_DIAG_BEFORE_REDUCTION", false);
  config.graph_prefers_refresh_before_diag =
      env_bool_or_default("QEBS_GRAPH_PREFERS_REFRESH_BEFORE_DIAG", false);
  config.graph_requested_cluster_sequence =
      env_or_default("QEBS_GRAPH_REQUESTED_CLUSTER_SEQUENCE", "");
  config.graph_resolved_cluster_sequence =
      env_or_default("QEBS_GRAPH_RESOLVED_CLUSTER_SEQUENCE", "");
  config.graph_sequence_constraints =
      env_or_default("QEBS_GRAPH_SEQUENCE_CONSTRAINTS", "");
  config.max_scf_iters = env_int_or_default("QEBS_MAX_SCF_ITERS", 3);
  config.enable_fft = env_bool_or_default("QEBS_ENABLE_FFT", true);
  config.device_diag_max_dim = env_int_or_default("QEBS_DEVICE_DIAG_MAX_DIM", 28);
  config.force_host_diag = env_bool_or_default("QEBS_FORCE_HOST_DIAG", false);
  config.allow_cpu_diag_fallback =
      env_bool_or_default("QEBS_ALLOW_CPU_DIAG_FALLBACK", true);
  return config;
}

qebs::ArchitectureConfig load_architecture_config() {
  const std::string config_path = env_or_default("QEBS_ARCH_CONFIG", "");
  const std::string arch_family = env_or_default("QEBS_ARCH_FAMILY", "F2");
  
  if (!config_path.empty()) {
    qebs::log_line("sc_main", "Loading architecture config from: " + config_path);
    return qebs::ArchitectureConfig::from_json_file(config_path);
  }
  
  if (arch_family == "F1") {
    qebs::log_line("sc_main", "Using F1 architecture template");
    return qebs::ArchitectureConfig::from_f1_template();
  } else if (arch_family == "F3") {
    qebs::log_line("sc_main", "Using F3 architecture template");
    return qebs::ArchitectureConfig::from_f3_template();
  } else {
    qebs::log_line("sc_main", "Using F2 architecture template (default)");
    return qebs::ArchitectureConfig::from_f2_template();
  }
}

}  // namespace

#if defined(QE_BAND_SOLVER_USE_SYSTEMC) && QE_BAND_SOLVER_USE_SYSTEMC
int sc_main(int argc, char** argv) {
#else
int main(int argc, char** argv) {
#endif
  (void)argc;
  (void)argv;

  const auto arch_config = load_architecture_config();
  const auto run_config = load_run_config();
  const auto result_json_path = env_or_default("QEBS_RESULT_JSON", "");
  qebs::DFTHybridSystem system(sc_core::sc_module_name("dft_hybrid_system"), arch_config);
  const auto run_begin = std::chrono::steady_clock::now();
  const auto report = system.run_full_flow(run_config);
  const auto run_end = std::chrono::steady_clock::now();
  const double wall_time_s =
      std::chrono::duration<double>(run_end - run_begin).count();
  const auto& state = report.final_state;
  write_candidate_result_json(report, run_config.case_id, result_json_path, wall_time_s);
  qebs::log_line("sc_main", "Host-managed full-SCF report: " + report.brief());
  qebs::log_line("sc_main",
                 "Demo finished: software=" + state.software_family +
                     ", flow=" + state.flow_family +
                     ", completed_episodes=" +
                     std::to_string(state.completed_episodes) +
                     ", completed_bodies=" + std::to_string(state.completed_bodies) +
                     ", rho_norm=" + std::to_string(state.rho_norm) +
                     ", energy=" + std::to_string(state.total_energy) +
                     ", density=" + state.density_object.object_handle +
                     ", converged=" + qebs::yes_no(state.converged));
  return 0;
}
