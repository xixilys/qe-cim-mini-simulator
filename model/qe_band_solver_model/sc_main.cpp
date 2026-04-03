#include <cstdlib>
#include <string>

#include "dft_hybrid_system.hpp"
#include "logging.hpp"

namespace {

std::string env_or_default(const char* name, const std::string& fallback) {
  const char* value = std::getenv(name);
  return value ? std::string(value) : fallback;
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
  config.max_scf_iters = env_int_or_default("QEBS_MAX_SCF_ITERS", 3);
  config.enable_fft = env_bool_or_default("QEBS_ENABLE_FFT", true);
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
  qebs::DFTHybridSystem system(sc_core::sc_module_name("dft_hybrid_system"));
  const auto report = system.run_full_flow(run_config);
  const auto& state = report.final_state;
  qebs::log_line("sc_main", "Cluster-first full-flow report: " + report.brief());
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
