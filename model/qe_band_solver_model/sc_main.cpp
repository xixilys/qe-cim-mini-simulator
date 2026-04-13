#include <chrono>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>

#include "dft_hybrid_system.hpp"
#include "logging.hpp"

namespace {

std::string env_or_default(const char* name, const std::string& fallback) {
  const char* value = std::getenv(name);
  return value ? std::string(value) : fallback;
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
  out << "    \"max_scf_iters\": " << report.run_config.max_scf_iters << ",\n";
  out << "    \"enable_fft\": " << json_bool(report.run_config.enable_fft) << "\n";
  out << "  },\n";
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
  out << "  \"timing\": {\n";
  out << "    \"wall_time_s\": " << std::setprecision(16) << wall_time_s << "\n";
  out << "  }\n";
  out << "}\n";
}

int env_int_or_default(const char* name, int fallback) {
  const char* value = std::getenv(name);
  return value ? std::atoi(value) : fallback;
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
  config.architecture_family = env_or_default("QEBS_ARCH_FAMILY", "F2");
  config.assumption_set_id =
      env_or_default("QEBS_ASSUMPTION_SET_ID", "default-assumptions");
  config.offload_scope_override =
      env_or_default("QEBS_OFFLOAD_SCOPE", "");
  config.resident_policy_override =
      env_or_default("QEBS_RESIDENT_POLICY", "");
  config.max_scf_iters = env_int_or_default("QEBS_MAX_SCF_ITERS", 3);
  config.enable_fft = env_bool_or_default("QEBS_ENABLE_FFT", true);
  config.device_diag_max_dim = env_int_or_default("QEBS_DEVICE_DIAG_MAX_DIM", 28);
  config.force_host_diag = env_bool_or_default("QEBS_FORCE_HOST_DIAG", false);
  config.allow_cpu_diag_fallback =
      env_bool_or_default("QEBS_ALLOW_CPU_DIAG_FALLBACK", true);
  return config;
}

}  // namespace

#if defined(QE_BAND_SOLVER_USE_SYSTEMC) && QE_BAND_SOLVER_USE_SYSTEMC
int sc_main(int argc, char** argv) {
#else
int main(int argc, char** argv) {
#endif
  (void)argc;
  (void)argv;

  const auto run_config = load_run_config();
  const auto case_id = env_or_default("QEBS_CASE_ID", "systemc_candidate");
  const auto result_json_path = env_or_default("QEBS_RESULT_JSON", "");
  qebs::DFTHybridSystem system(sc_core::sc_module_name("dft_hybrid_system"));
  const auto run_begin = std::chrono::steady_clock::now();
  const auto report = system.run_full_flow(run_config);
  const auto run_end = std::chrono::steady_clock::now();
  const double wall_time_s =
      std::chrono::duration<double>(run_end - run_begin).count();
  const auto& state = report.final_state;
  write_candidate_result_json(report, case_id, result_json_path, wall_time_s);
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
