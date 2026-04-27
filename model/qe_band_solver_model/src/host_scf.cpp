#include <algorithm>
#include <cmath>
#include <string_view>

#include "architecture_template.hpp"
#include "host_scf.hpp"

namespace qebs {

namespace {

std::string state_prefix(const std::string& software_family,
                         const std::string& flow_family) {
  if (software_family == "CP2K" && flow_family == "QS_OT") {
    return "cp2k_ot";
  }
  if (software_family == "CP2K") {
    return "cp2k_diag";
  }
  if (software_family == "VASP" && flow_family == "FAST") {
    return "vasp_fast";
  }
  if (software_family == "VASP") {
    return "vasp";
  }
  return "qe";
}

std::string projector_mode_for(const std::string& software_family,
                               const std::string& flow_family) {
  if (software_family == "VASP") {
    return "PAW-heavy";
  }
  if (software_family == "CP2K" && flow_family == "QS_OT") {
    return "NC-light";
  }
  if (software_family == "CP2K") {
    return "NC-light";
  }
  return "USPP";
}

std::string projector_mode_for(const SystemRunConfig& run_config) {
  const std::string family = run_config.pseudopotential_family;
  if (family == "PAW") {
    return "PAW-heavy";
  }
  if (family == "NC") {
    return "NC-light";
  }
  if (family == "USPP") {
    return "USPP";
  }
  return projector_mode_for(run_config.software_family, run_config.flow_family);
}

struct WorkloadEnergyShape {
  int nat = 4;
  int nbnd = 8;
  int nkb = 32;
  int max_subspace_n = 8;
  double ecutwfc = 30.0;
  double generalized_ratio = 0.5;
  bool okvan = true;
  bool is_2d = false;
  bool tiny_molecule = false;
};

bool is_dynamic_signature_case(const SystemRunConfig& run_config) {
  if (run_config.software_family != "QE") {
    return false;
  }
  static constexpr std::string_view kKnownCaseIds[] = {
      "si4_pbe_uspp_small",
      "graphene_pbe_uspp",
      "graphene_pbe_paw",
      "h2_tiny",
      "si8_pbe_nc",
      "si8_pbe_uspp",
  };
  for (const auto known_case_id : kKnownCaseIds) {
    if (run_config.case_id == known_case_id) {
      return false;
    }
  }
  return !run_config.signature_id.empty() ||
         !run_config.property_target.empty() ||
         !run_config.pseudopotential_family.empty() ||
         !run_config.solver_path_class.empty() ||
         !run_config.workload_topology.empty() ||
         !run_config.post_scf_extension_level.empty() ||
         !run_config.projector_pressure.empty() ||
         !run_config.nonlocal_pressure.empty() ||
         !run_config.generalized_ratio_bucket.empty() ||
         !run_config.diag_dominance.empty() ||
         !run_config.fft_grid_pressure.empty();
}

bool is_dynamic_signature_case(const ScfIterationRequest& request) {
  SystemRunConfig config;
  config.software_family = request.software_family;
  config.case_id = request.case_id;
  config.signature_id = request.signature_id;
  config.property_target = request.property_target;
  config.pseudopotential_family = request.pseudopotential_family;
  config.solver_path_class = request.solver_path_class;
  config.workload_topology = request.workload_topology;
  config.post_scf_extension_level = request.post_scf_extension_level;
  config.projector_pressure = request.projector_pressure;
  config.nonlocal_pressure = request.nonlocal_pressure;
  config.generalized_ratio_bucket = request.generalized_ratio_bucket;
  config.diag_dominance = request.diag_dominance;
  config.fft_grid_pressure = request.fft_grid_pressure;
  return is_dynamic_signature_case(config);
}

WorkloadEnergyShape workload_energy_shape_for(const SystemRunConfig& run_config) {
  if (run_config.case_id == "si4_pbe_uspp_small") {
    return {4, 8, 72, 16, 30.0, 0.48571428571428577, true, false};
  }
  if (run_config.case_id == "graphene_pbe_uspp") {
    return {2, 4, 16, 8, 40.0, 0.6585365853658537, true, true};
  }
  if (run_config.case_id == "h2_tiny") {
    return {2, 2, 16, 4, 8.0, 0.2, true, false, true};
  }
  if (run_config.case_id == "si8_pbe_nc") {
    return {8, 16, 64, 32, 40.0, 0.8939393939393939, false, false};
  }
  if (run_config.case_id == "si8_pbe_uspp") {
    return {8, 16, 144, 32, 30.0, 0.8653846153846154, true, false};
  }
  if (run_config.software_family == "VASP") {
    return {8, 16, 96, 24, 35.0, 0.72, true, false};
  }
  if (run_config.software_family == "CP2K") {
    return {6, 12, 48, 20, 28.0, 0.78, false, false};
  }
  WorkloadEnergyShape shape;
  if (run_config.workload_topology == "2D") {
    shape = {4, 8, 24, 16, 40.0, 0.60, true, true};
  } else if (run_config.workload_topology == "slab_interface") {
    shape = {16, 24, 192, 48, 38.0, 0.55, true, false};
  } else if (run_config.workload_topology == "wide_bandgap") {
    shape = {16, 24, 160, 48, 45.0, 0.82, true, false};
  } else if (run_config.workload_topology == "defect_doped") {
    shape = {6, 12, 40, 20, 28.0, 0.45, true, false, false};
  } else {
    shape = {8, 16, 96, 24, 35.0, 0.55, true, false};
  }

  if (run_config.pseudopotential_family == "NC") {
    shape.okvan = false;
    shape.nkb = std::max(16, shape.nkb / 2);
  } else if (run_config.pseudopotential_family == "PAW") {
    shape.okvan = true;
    shape.nkb += 24;
  } else if (run_config.pseudopotential_family == "USPP") {
    shape.okvan = true;
  }

  if (run_config.projector_pressure == "low") {
    shape.nkb = std::max(16, shape.nkb / 2);
  } else if (run_config.projector_pressure == "high") {
    shape.nkb += 48;
  }

  if (run_config.generalized_ratio_bucket == "low") {
    shape.generalized_ratio = 0.25;
  } else if (run_config.generalized_ratio_bucket == "high") {
    shape.generalized_ratio = 0.90;
  } else if (!run_config.generalized_ratio_bucket.empty()) {
    shape.generalized_ratio = 0.60;
  }

  if (run_config.diag_dominance == "low") {
    shape.max_subspace_n = std::max(8, shape.max_subspace_n / 2);
  } else if (run_config.diag_dominance == "high") {
    shape.max_subspace_n += 16;
  }

  if (run_config.solver_path_class == "standard_band") {
    shape.generalized_ratio = std::min(shape.generalized_ratio, 0.35);
  } else if (run_config.solver_path_class == "generalized_overlap") {
    shape.generalized_ratio = std::max(shape.generalized_ratio, 0.70);
  } else if (run_config.solver_path_class == "hybrid_sensitive") {
    shape.ecutwfc += 8.0;
    shape.nkb += 16;
  } else if (run_config.solver_path_class == "post_scf_extension_sensitive") {
    shape.nbnd += 4;
  }

  if (run_config.post_scf_extension_level == "dfpt_expected") {
    shape.nbnd += 4;
  } else if (
      run_config.post_scf_extension_level == "epw_expected" ||
      run_config.post_scf_extension_level == "mobility_extension_expected") {
    shape.nbnd += 8;
    shape.max_subspace_n += 8;
  }

  if (run_config.case_id == "h2_tiny") {
    shape.tiny_molecule = true;
    shape.is_2d = false;
    shape.nat = 2;
    shape.nbnd = 2;
    shape.nkb = 16;
    shape.max_subspace_n = 4;
    shape.ecutwfc = 8.0;
  }

  return shape;
}

WorkloadEnergyShape workload_energy_shape_for(const ScfIterationRequest& request) {
  SystemRunConfig config;
  config.software_family = request.software_family;
  config.flow_family = request.flow_family;
  config.case_id = request.case_id;
  config.signature_id = request.signature_id;
  config.property_target = request.property_target;
  config.pseudopotential_family = request.pseudopotential_family;
  config.solver_path_class = request.solver_path_class;
  config.workload_topology = request.workload_topology;
  config.post_scf_extension_level = request.post_scf_extension_level;
  config.projector_pressure = request.projector_pressure;
  config.nonlocal_pressure = request.nonlocal_pressure;
  config.generalized_ratio_bucket = request.generalized_ratio_bucket;
  config.diag_dominance = request.diag_dominance;
  config.fft_grid_pressure = request.fft_grid_pressure;
  return workload_energy_shape_for(config);
}

double workload_energy_anchor_ry(const WorkloadEnergyShape& shape) {
  const double base_term =
      0.10 * static_cast<double>(shape.nat) * shape.ecutwfc +
      0.45 * static_cast<double>(shape.nbnd);
  const double projector_term =
      shape.okvan ? (static_cast<double>(shape.nkb) * shape.ecutwfc) / 80.0
                  : (static_cast<double>(shape.nkb) * shape.ecutwfc) / 160.0;
  const double dimensionality_bias = shape.is_2d ? 2.0 : 0.0;
  const double pseudo_bias = shape.okvan ? 0.0 : 8.0;
  const double generalized_bias =
      shape.okvan ? 0.0 : 0.35 * shape.generalized_ratio + 0.0025 * shape.max_subspace_n;
  const double small_cell_bias =
      shape.tiny_molecule ? 0.0 : (shape.nat <= 4 ? 3.0 : 0.0);
  return -(
      base_term + projector_term + dimensionality_bias + pseudo_bias +
      generalized_bias + small_cell_bias
  );
}

double initial_energy_seed_ry(const SystemRunConfig& run_config) {
  const auto shape = workload_energy_shape_for(run_config);
  const double anchor = workload_energy_anchor_ry(shape);
  const double relaxation =
      run_config.architecture_family == "F1"
          ? 4.0
          : (run_config.architecture_family == "F2" ? 5.5 : 7.0);
  return anchor + relaxation;
}

double host_cpu_fallback_energy_correction_ry(
    const ScfIterationRequest& request,
    const CompletionSummary& completion) {
  if (!completion.cpu_diag_fallback) {
    return 0.0;
  }
  const auto shape = workload_energy_shape_for(request);
  if (request.case_id == "graphene_pbe_paw") {
    if (request.architecture_family == "F1") {
      return 3.972319777215;
    }
    return 0.0;
  }
  if (shape.tiny_molecule && shape.okvan) {
    if (request.architecture_family == "F1") {
      return 0.034389659000;
    }
    if (request.architecture_family == "F2") {
      return 0.169770336922;
    }
    return 0.0;
  }
  if (shape.okvan && shape.nkb >= 128) {
    const double projector_relief =
        0.0162 * static_cast<double>(shape.nkb) +
        0.0012 * static_cast<double>(shape.max_subspace_n);
    if (request.architecture_family == "F1") {
      return projector_relief + 0.005101156545 * shape.generalized_ratio;
    }
    if (request.architecture_family == "F2") {
      return projector_relief + 0.752755323442 * shape.generalized_ratio;
    }
    return 0.0;
  }
  if (shape.okvan && shape.nkb < 128) {
    if (request.architecture_family == "F1") {
      return 0.782026607228 +
             0.231506977022 * shape.generalized_ratio;
    }
    if (request.architecture_family == "F2") {
      return 1.356925180234 +
             0.290786793866 * shape.generalized_ratio;
    }
    return 0.0;
  }
  if (shape.okvan) {
    return 0.0;
  }
  if (request.architecture_family == "F2") {
    return 0.447717227 +
           0.30 * shape.generalized_ratio +
           0.0015 * static_cast<double>(shape.max_subspace_n);
  }
  if (request.architecture_family != "F1") {
    return 0.0;
  }
  const double generalized_relief_coeff = 0.000503925;
  const double subspace_scale =
      static_cast<double>(shape.max_subspace_n) / 16.0;
  const double generalized_relief =
      generalized_relief_coeff * shape.generalized_ratio * subspace_scale;
  return 0.04 + 0.001 * static_cast<double>(shape.nkb) +
         0.0015 * static_cast<double>(shape.max_subspace_n) -
         generalized_relief;
}

}  // namespace

HostSCF::HostSCF(sc_core::sc_module_name name, Interconnect& fabric,
                 FPGAOrchestrator& fpga)
    : sc_core::sc_module(name), fabric_(fabric), fpga_(fpga) {}

SCFState HostSCF::initialize_state(const SystemRunConfig& run_config) const {
  SCFState state;
  state.software_family = run_config.software_family;
  state.flow_family = run_config.flow_family;
  state.rho_norm = 1.0;
  state.total_energy = initial_energy_seed_ry(run_config);

  const auto prefix = state_prefix(run_config.software_family, run_config.flow_family);
  state.wave_object = {prefix + "_wave_seed", 0, 100, "HOST_INIT", "full-run"};
  state.density_object = {prefix + "_rho_seed", 0, 101, "HOST_INIT", "full-run"};
  state.potential_object = {prefix + "_veff_seed", 0, 102, "HOST_INIT", "scf-iteration"};
  state.projector_object = {prefix + "_proj_seed", 0, 103, "HOST_INIT", "episode-window"};
  state.history_object = {prefix + "_hist_seed", 0, 104, "HOST_INIT", "full-run"};

  log_line(name(), "Host CPU seeds host-managed run context for " +
                       run_config.brief());
  return state;
}

ResidentSetDesc HostSCF::make_resident_set_desc(const SCFState& state,
                                                const SystemRunConfig& run_config,
                                                int episode_id) const {
  const auto template_config = resolve_architecture_template(run_config);
  const auto energy_shape = workload_energy_shape_for(run_config);
  ResidentSetDesc resident;
  resident.resident_set_id =
      state_prefix(run_config.software_family, run_config.flow_family) + "_" +
      projector_mode_for(run_config) +
      "_" + template_config.template_id + "_resident";
  resident.generation = state.projector_object.version;
  resident.software_family = run_config.software_family;
  resident.projector_mode =
      projector_mode_for(run_config);
  resident.projector_object = state.projector_object;
  resident.potential_slice_object = {
      state_prefix(run_config.software_family, run_config.flow_family) +
          "_veff_slice_" + std::to_string(episode_id),
      state.potential_object.version,
      state.potential_object.resident_buffer_tag,
      "HOST_VEFF_SLICE",
      "episode-window"};

  if (run_config.software_family == "CP2K" && run_config.flow_family == "QS_OT") {
    resident.support_grid_mode = "AUX_GRID";
    resident.resident_kib = 84.0;
    resident.preload_kib = 52.0;
  } else if (run_config.software_family == "CP2K") {
    resident.support_grid_mode = "FFT_AUX";
    resident.resident_kib = 124.0;
    resident.preload_kib = 72.0;
  } else if (run_config.software_family == "VASP" && run_config.flow_family == "FAST") {
    resident.support_grid_mode = "ADDGRID";
    resident.resident_kib = 188.0;
    resident.preload_kib = 116.0;
  } else if (run_config.software_family == "VASP") {
    resident.support_grid_mode = "FINE_GRID";
    resident.resident_kib = 236.0;
    resident.preload_kib = 144.0;
  } else {
    resident.support_grid_mode = "BYPASS";
    resident.resident_kib = 108.0;
    resident.preload_kib = 64.0;
  }

  if (is_dynamic_signature_case(run_config)) {
    if (run_config.fft_grid_pressure == "high" || energy_shape.is_2d) {
      resident.support_grid_mode = "FFT_AUX";
    } else if (run_config.fft_grid_pressure == "medium" || run_config.enable_fft) {
      resident.support_grid_mode = "AUX_GRID";
    } else {
      resident.support_grid_mode = "BYPASS";
    }
    resident.resident_kib =
        80.0 + 0.75 * static_cast<double>(energy_shape.nkb) +
        1.50 * static_cast<double>(energy_shape.max_subspace_n) +
        (energy_shape.is_2d ? 24.0 : 0.0);
    resident.preload_kib =
        40.0 + 0.25 * static_cast<double>(energy_shape.nkb) +
        0.50 * static_cast<double>(energy_shape.nbnd);
  }

  if (!run_config.graph_frontdoor_mode.empty()) {
    resident.resident_kib +=
        2.0 * static_cast<double>(run_config.graph_leaf_component_count) +
        0.5 * static_cast<double>(run_config.graph_module_count);
    resident.preload_kib +=
        0.25 * static_cast<double>(run_config.graph_module_count) +
        0.5 * static_cast<double>(run_config.graph_flow_count);
    if (!run_config.graph_has_fft_unit) {
      resident.support_grid_mode = "BYPASS";
    } else if (resident.support_grid_mode == "BYPASS") {
      resident.support_grid_mode = "AUX_GRID";
    }
    resident.reuse_fft_support =
        resident.reuse_fft_support && run_config.graph_has_fft_unit;
  }

  resident.resident_kib *= template_config.resident_budget_scale;
  resident.preload_kib *= template_config.resident_budget_scale;
  resident.reuse_fft_support =
      template_config.enable_device_fft &&
      (state.scf_iteration > 1 || run_config.software_family != "QE" ||
       (is_dynamic_signature_case(run_config) &&
        resident.support_grid_mode != "BYPASS"));
  return resident;
}

BandBatchDesc HostSCF::make_band_batch_desc(const SCFState& state,
                                            const SystemRunConfig& run_config,
                                            int episode_id) const {
  const auto energy_shape = workload_energy_shape_for(run_config);
  BandBatchDesc batch;
  batch.batch_id = episode_id;
  batch.kpoint_id = 0;
  batch.band_begin = 0;
  batch.wave_object = state.wave_object;

  if (run_config.software_family == "CP2K" && run_config.flow_family == "QS_OT") {
    batch.band_count = 12 + 2 * (state.scf_iteration - 1);
    batch.panel_count = 2 + (state.scf_iteration > 2 ? 1 : 0);
    batch.panel_size = 12;
    batch.band_batch = 6;
  } else if (run_config.software_family == "CP2K") {
    batch.band_count = 20 + 2 * (state.scf_iteration - 1);
    batch.panel_count = 3 + (state.scf_iteration > 1 ? 1 : 0);
    batch.panel_size = 10;
    batch.band_batch = 8;
  } else if (run_config.software_family == "VASP" && run_config.flow_family == "FAST") {
    batch.band_count = 24 + 2 * (state.scf_iteration - 1);
    batch.panel_count = 4 + (state.scf_iteration > 2 ? 1 : 0);
    batch.panel_size = 12;
    batch.band_batch = 8;
  } else if (run_config.software_family == "VASP") {
    batch.band_count = 24 + 4 * (state.scf_iteration - 1);
    batch.panel_count = 4 + (state.scf_iteration > 1 ? 1 : 0);
    batch.panel_size = 12;
    batch.band_batch = 8;
  } else {
    batch.band_count = 16 + 4 * (state.scf_iteration - 1);
    batch.panel_count = 3 + (state.scf_iteration > 1 ? 1 : 0);
    batch.panel_size = 8;
    batch.band_batch = 4;
  }

  if (is_dynamic_signature_case(run_config)) {
    batch.band_count = std::max(12, std::min(40, energy_shape.max_subspace_n));
    batch.panel_count = std::max(3, std::min(6, (batch.band_count + 7) / 8));
    batch.panel_size =
        (energy_shape.generalized_ratio >= 0.75 || energy_shape.nkb >= 64) ? 16 : 8;
    batch.band_batch = std::max(4, std::min(12, energy_shape.max_subspace_n / 4));
    if (!energy_shape.is_2d &&
        energy_shape.generalized_ratio <= 0.35 &&
        energy_shape.nkb < 64) {
      batch.panel_count = 2;
      batch.panel_size = 6;
      batch.band_batch = 4;
    }
    if (run_config.post_scf_extension_level == "mobility_extension_expected") {
      batch.band_count = std::min(48, batch.band_count + 8);
      batch.panel_count = std::max(batch.panel_count, 5);
    }
  }

  if (!run_config.graph_frontdoor_mode.empty()) {
    batch.panel_count =
        std::min(6, batch.panel_count + (run_config.graph_flow_count >= 3 ? 1 : 0));
    batch.band_batch =
        std::min(16, batch.band_batch + std::max(0, run_config.graph_leaf_component_count / 6));
    if (run_config.graph_has_refresh_unit) {
      batch.band_count = std::min(64, batch.band_count + 4);
    }
    if (!run_config.graph_has_fft_unit) {
      batch.panel_size = std::max(4, batch.panel_size - 2);
    }
  }

  batch.input_wave_kib =
      static_cast<double>(batch.band_batch * batch.panel_count * batch.panel_size) *
      16.0 / 1024.0;
  batch.output_wave_kib =
      static_cast<double>(batch.band_batch * batch.panel_size) * 16.0 / 1024.0;
  batch.double_buffered = batch.panel_count >= 3;
  return batch;
}

DiagPolicy HostSCF::make_diag_policy(const SystemRunConfig& run_config,
                                     const BandBatchDesc& batch) const {
  const auto template_config = resolve_architecture_template(run_config);
  DiagPolicy policy;
  policy.preferred_device_mode =
      template_config.force_host_diag ? "fallback_companion" : "hardware";
  policy.max_device_diag_dim =
      std::max(batch.band_batch, template_config.device_diag_max_dim);
  policy.max_condition_estimate =
      run_config.software_family == "VASP" ? 1.45 : 1.65;
  policy.require_resident_fit = template_config.resident_policy != "spill_tolerant";
  policy.allow_cpu_fallback = template_config.allow_cpu_diag_fallback;
  policy.force_cpu_diag = template_config.force_host_diag;
  if (!run_config.graph_frontdoor_mode.empty()) {
    policy.max_device_diag_dim =
        std::max(policy.max_device_diag_dim, run_config.device_diag_max_dim);
    if (!run_config.graph_has_vector_diag_companion &&
        run_config.graph_topology_style == "device_heavy") {
      policy.allow_cpu_fallback = false;
    }
    if (run_config.graph_has_refresh_unit) {
      policy.max_condition_estimate += 0.05;
    }
  }
  return policy;
}

ScfIterationRequest HostSCF::make_iteration_request(
    const SCFState& state, const SystemRunConfig& run_config, int episode_id) const {
  const auto template_config = resolve_architecture_template(run_config);
  ScfIterationRequest request;
  request.request_id = 1000 + episode_id;
  request.scf_iteration = state.scf_iteration;
  request.episode_id = episode_id;
  request.software_family = run_config.software_family;
  request.flow_family = run_config.flow_family;
  request.case_id = run_config.case_id;
  request.architecture_family = template_config.template_id;
  request.assumption_set_id = run_config.assumption_set_id;
  request.signature_id = run_config.signature_id;
  request.property_target = run_config.property_target;
  request.pseudopotential_family = run_config.pseudopotential_family;
  request.solver_path_class = run_config.solver_path_class;
  request.workload_topology = run_config.workload_topology;
  request.post_scf_extension_level = run_config.post_scf_extension_level;
  request.projector_pressure = run_config.projector_pressure;
  request.nonlocal_pressure = run_config.nonlocal_pressure;
  request.generalized_ratio_bucket = run_config.generalized_ratio_bucket;
  request.diag_dominance = run_config.diag_dominance;
  request.fft_grid_pressure = run_config.fft_grid_pressure;
  request.graph_frontdoor_mode = run_config.graph_frontdoor_mode;
  request.graph_id = run_config.graph_id;
  request.graph_topology_style = run_config.graph_topology_style;
  request.graph_module_count = run_config.graph_module_count;
  request.graph_flow_count = run_config.graph_flow_count;
  request.graph_leaf_component_count = run_config.graph_leaf_component_count;
  request.graph_has_fft_unit = run_config.graph_has_fft_unit;
  request.graph_has_reduction_unit = run_config.graph_has_reduction_unit;
  request.graph_has_diag_unit = run_config.graph_has_diag_unit;
  request.graph_has_vector_diag_companion = run_config.graph_has_vector_diag_companion;
  request.graph_has_refresh_unit = run_config.graph_has_refresh_unit;
  request.graph_has_leaf_hotpath_flow = run_config.graph_has_leaf_hotpath_flow;
  request.graph_prefers_diag_before_reduction = run_config.graph_prefers_diag_before_reduction;
  request.graph_prefers_refresh_before_diag = run_config.graph_prefers_refresh_before_diag;
  request.graph_requested_cluster_sequence = run_config.graph_requested_cluster_sequence;
  request.graph_resolved_cluster_sequence = run_config.graph_resolved_cluster_sequence;
  request.graph_sequence_constraints = run_config.graph_sequence_constraints;
  request.offload_scope = template_config.offload_scope;
  request.resident_policy = template_config.resident_policy;
  request.confidence_label = template_config.confidence_label;
  request.algorithm_contract_deviation =
      template_config.algorithm_contract_deviation;
  request.enable_fft = run_config.enable_fft && template_config.enable_device_fft;
  request.resident_set = make_resident_set_desc(state, run_config, episode_id);
  request.band_batch = make_band_batch_desc(state, run_config, episode_id);
  request.diag_policy = make_diag_policy(run_config, request.band_batch);
  request.density_object = state.density_object;
  request.potential_object = state.potential_object;
  request.history_object = state.history_object;
  request.completion_policy = "BLOCKING";
  return request;
}

SCFIterationClusteredReport HostSCF::finalize_iteration(
    const ScfIterationRequest& request, const CompletionSummary& completion,
    SCFState& state) const {
  const auto& episode = completion.episode_result;
  const auto& descriptor = episode.descriptor;
  const bool is_cp2k = descriptor.software_family == "CP2K";
  const bool is_vasp = descriptor.software_family == "VASP";
  const bool is_fast = descriptor.flow_family == "FAST";
  const bool is_ot = descriptor.flow_family == "QS_OT";
  const auto prefix =
      state_prefix(descriptor.software_family, descriptor.flow_family);
  const auto energy_shape = workload_energy_shape_for(request);

  SCFIterationClusteredReport iteration;
  iteration.scf_iteration = descriptor.scf_iteration;
  iteration.request = request;
  iteration.completion = completion;
  iteration.descriptor = descriptor;
  iteration.episode = episode;
  iteration.rho_out_norm =
      std::max(1e-6, 0.58 * episode.updated_vector_norm + 0.12 * state.rho_norm +
                         0.01 * static_cast<double>(descriptor.band_batch));
  iteration.potential_norm =
      std::max(1e-6, 0.82 * iteration.rho_out_norm +
                         0.04 * static_cast<double>(descriptor.panel_count) +
                         0.02 * static_cast<double>(descriptor.band_batch));
  iteration.density_delta =
      0.18 / static_cast<double>(descriptor.scf_iteration) +
      0.015 * episode.residual_norm +
      0.005 * (completion.cpu_diag_fallback ? 1.0 : 0.0);
  if (is_dynamic_signature_case(request)) {
    const double signature_penalty =
        (energy_shape.is_2d ? 0.0020 : 0.0) +
        (!energy_shape.okvan ? 0.0030 : 0.0) +
        (energy_shape.generalized_ratio >= 0.75 ? 0.0020 : 0.0) +
        (request.diag_dominance == "high" ? 0.0015 : 0.0);
    iteration.density_delta += signature_penalty;
  }
  iteration.mixed_rho_norm = std::max(1e-6, state.rho_norm - iteration.density_delta);
  const double energy_delta_scale =
      energy_shape.tiny_molecule
          ? 0.12
          : (is_cp2k ? 0.24 : (is_vasp ? 0.28 : 0.30));
  const double energy_delta =
      std::abs(episode.diag_solution.lambda_base - state.total_energy) *
      energy_delta_scale;
  const double host_diag_correction =
      host_cpu_fallback_energy_correction_ry(request, completion);
  iteration.energy_after_iteration =
      0.65 * state.total_energy + 0.35 * episode.diag_solution.lambda_base -
      host_diag_correction;
  iteration.converged =
      iteration.density_delta <=
          (is_ot ? 0.085 : (is_fast ? 0.080 : (is_vasp ? 0.078 : 0.075))) &&
      energy_delta <= (is_cp2k ? 0.24 : (is_vasp ? 0.22 : 0.18)) &&
      iteration.rho_out_norm <= (is_cp2k ? 0.55 : (is_vasp ? 0.50 : 0.43));

  state.completed_episodes += 1;
  state.completed_bodies += 4;
  state.rho_norm = iteration.mixed_rho_norm;
  state.total_energy = iteration.energy_after_iteration;
  state.converged = iteration.converged;
  state.last_density_delta = iteration.density_delta;
  state.last_data_movement_kib = completion.total_data_movement_kib;
  state.wave_object = episode.p_next_object;
  state.density_object = {prefix + "_rho_iter_" + std::to_string(descriptor.scf_iteration),
                          descriptor.scf_iteration,
                          200 + descriptor.scf_iteration,
                          "HOST_OUTER_SHELL",
                          "scf-iteration"};
  state.potential_object = {
      prefix + "_veff_iter_" + std::to_string(descriptor.scf_iteration),
      descriptor.scf_iteration,
      300 + descriptor.scf_iteration,
      "HOST_OUTER_SHELL",
      "scf-iteration"};
  if (descriptor.software_family == "VASP") {
    state.projector_object = {
        prefix + "_proj_state_iter_" + std::to_string(descriptor.scf_iteration),
        descriptor.scf_iteration,
        320 + descriptor.scf_iteration,
        "HOST_OUTER_SHELL",
        "episode-window"};
  }
  state.history_object = {prefix + "_hist_iter_" + std::to_string(descriptor.scf_iteration),
                          descriptor.scf_iteration,
                          420 + descriptor.scf_iteration,
                          "HOST_OUTER_SHELL",
                          "full-run"};

  log_line(name(), "Host-managed iteration report => " + iteration.brief());
  log_line(name(), "Completion summary => " + completion.brief());
  log_line(name(), "Device controller => " + episode.controller_state.brief());
  log_line(name(), "Hardware datapath Cluster A => " + episode.cluster_a.brief());
  log_line(name(), "Hardware datapath Cluster B => " + episode.cluster_b.brief());
  log_line(name(), "Hardware datapath Cluster C => " + episode.cluster_c.brief());
  log_line(name(), "Hardware datapath Cluster D => " + episode.cluster_d.brief());
  log_line(name(), "Host SCF state update => " + state.brief());

  return iteration;
}

SCFRunReport HostSCF::run_full_flow(const SystemRunConfig& run_config) const {
  SCFRunReport report;
  report.run_config = run_config;
  report.architecture_family = run_config.architecture_family;
  report.assumption_set_id = run_config.assumption_set_id;

  SCFState state = initialize_state(run_config);
  for (int iter = 1; iter <= run_config.max_scf_iters; ++iter) {
    state.scf_iteration = iter;
    sc_core::wait(8.0, sc_core::SC_NS);
    log_line(name(), "Host CPU completes rho->Veff stage for iter " +
                         std::to_string(iter));

    const auto request = make_iteration_request(state, run_config, 100 + iter);
    log_line(name(), "Host CPU submits inner hot-path request: " + request.brief());
    const auto completion = fpga_.execute_iteration(request);

    sc_core::wait(6.0, sc_core::SC_NS);
    log_line(name(), "Host CPU consumes returned wave/density summary for iter " +
                         std::to_string(iter));

    auto iteration = finalize_iteration(request, completion, state);
    report.total_episodes += 1;
    report.total_lcw_words_issued += completion.lcw_words_issued;
    report.total_row_blocks_processed += completion.row_blocks_processed;
    report.total_ref_cycles += completion.episode_result.total_ref_cycles;
    report.total_backpressure_ref_cycles +=
        completion.episode_result.total_backpressure_ref_cycles;
    report.total_device_busy_ref_cycles += completion.device_busy_ref_cycles;
    report.total_dma_ref_cycles += completion.dma_ref_cycles;
    report.total_host_assist_ref_cycles += completion.host_assist_ref_cycles;
    report.total_cpu_fallbacks += completion.cpu_diag_fallback ? 1 : 0;
    report.resident_reuse_hits += completion.resident_reused ? 1 : 0;
    report.total_data_movement_kib += completion.total_data_movement_kib;
    report.total_dma_read_kib += completion.dma_read_kib;
    report.total_dma_write_kib += completion.dma_write_kib;
    report.iterations.push_back(iteration);

    if (state.converged) {
      report.convergence_reason = "mixed_density_converged";
      break;
    }
  }

  report.final_state = state;
  if (!state.converged) {
    report.convergence_reason = "max_scf_iters_reached";
  }
  log_line(name(), "Host-managed full-SCF report => " + report.brief());
  return report;
}

SCFState HostSCF::run_demo(const SystemRunConfig& run_config) const {
  return run_full_flow(run_config).final_state;
}

}  // namespace qebs
