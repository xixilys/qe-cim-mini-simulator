#include "architecture_template.hpp"

namespace qebs {

ArchitectureTemplateConfig resolve_architecture_template(
    const SystemRunConfig& run_config) {
  ArchitectureTemplateConfig config;
  config.template_id = run_config.architecture_family;
  config.device_diag_max_dim = run_config.device_diag_max_dim;
  config.force_host_diag = run_config.force_host_diag;
  config.allow_cpu_diag_fallback = run_config.allow_cpu_diag_fallback;

  if (run_config.architecture_family == "F1") {
    config.template_label = "HostHeavySingleHotpath";
    config.offload_scope = "single_hotpath";
    config.resident_policy = "fit_first";
    config.diag_policy = "cpu_only";
    config.confidence_label = "high";
    config.enable_device_fft = false;
    config.force_host_diag = true;
    config.allow_cpu_diag_fallback = true;
    config.resident_budget_scale = 0.85;
    config.device_diag_max_dim = 8;
  } else if (run_config.architecture_family == "F3") {
    config.template_label = "DeviceHeavyFullInnerLoop";
    config.offload_scope = "device_heavy";
    config.resident_policy = "spill_tolerant";
    config.diag_policy = "aggressive_device";
    config.confidence_label = "exploratory";
    config.enable_device_fft = run_config.enable_fft;
    config.force_host_diag = run_config.force_host_diag;
    config.allow_cpu_diag_fallback = run_config.allow_cpu_diag_fallback;
    config.resident_budget_scale = 1.20;
    config.device_diag_max_dim =
        std::max(run_config.device_diag_max_dim, 40);
  } else {
    config.template_id = "F2";
    config.template_label = "BalancedHybrid";
    config.offload_scope = "balanced";
    config.resident_policy = "fit_first";
    config.diag_policy = "device_first_fallback";
    config.confidence_label = "medium";
    config.enable_device_fft = run_config.enable_fft;
    config.force_host_diag = run_config.force_host_diag;
    config.allow_cpu_diag_fallback = run_config.allow_cpu_diag_fallback;
    config.resident_budget_scale = 1.00;
    config.device_diag_max_dim =
        std::max(run_config.device_diag_max_dim, 28);
  }

  if (!run_config.offload_scope_override.empty()) {
    config.offload_scope = run_config.offload_scope_override;
  }
  if (!run_config.resident_policy_override.empty()) {
    config.resident_policy = run_config.resident_policy_override;
  }
  return config;
}

}  // namespace qebs
