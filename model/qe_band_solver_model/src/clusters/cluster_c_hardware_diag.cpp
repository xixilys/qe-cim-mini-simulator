#include <algorithm>

#include "cluster_graph_frontdoor_sequence.hpp"
#include "cluster_c_hardware_diag.hpp"

namespace qebs {

namespace {

bool is_experimental_signature_case(const EpisodeDescriptor& descriptor) {
  if (descriptor.software_family != "QE") {
    return false;
  }
  static constexpr const char* kStableCaseIds[] = {
      "si4_pbe_uspp_small",
      "graphene_pbe_uspp",
      "graphene_pbe_paw",
      "h2_tiny",
      "si8_pbe_nc",
      "si8_pbe_uspp",
  };
  for (const char* stable_case_id : kStableCaseIds) {
    if (descriptor.case_id == stable_case_id) {
      return false;
    }
  }
  return !descriptor.signature_id.empty() ||
         !descriptor.property_target.empty() ||
         !descriptor.pseudopotential_family.empty() ||
         !descriptor.solver_path_class.empty() ||
         !descriptor.workload_topology.empty() ||
         !descriptor.post_scf_extension_level.empty() ||
         !descriptor.projector_pressure.empty() ||
         !descriptor.nonlocal_pressure.empty() ||
         !descriptor.generalized_ratio_bucket.empty() ||
         !descriptor.diag_dominance.empty() ||
         !descriptor.fft_grid_pressure.empty();
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

WorkloadEnergyShape workload_energy_shape_for(const EpisodeDescriptor& descriptor) {
  if (descriptor.case_id == "si4_pbe_uspp_small") {
    return {4, 8, 72, 16, 30.0, 0.48571428571428577, true, false};
  }
  if (descriptor.case_id == "graphene_pbe_uspp") {
    return {2, 4, 16, 8, 40.0, 0.6585365853658537, true, true};
  }
  if (descriptor.case_id == "h2_tiny") {
    return {2, 2, 16, 4, 8.0, 0.2, true, false, true};
  }
  if (descriptor.case_id == "si8_pbe_nc") {
    return {8, 16, 64, 32, 40.0, 0.8939393939393939, false, false};
  }
  if (descriptor.case_id == "si8_pbe_uspp") {
    return {8, 16, 144, 32, 30.0, 0.8653846153846154, true, false};
  }
  if (descriptor.software_family == "VASP") {
    return {8, 16, 96, 24, 35.0, 0.72, true, false};
  }
  if (descriptor.software_family == "CP2K") {
    return {6, 12, 48, 20, 28.0, 0.78, false, false};
  }
  return {};
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

}  // namespace

ClusterCHardwareDiag::ClusterCHardwareDiag(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ClusterCOutput ClusterCHardwareDiag::run(const ClusterCInput& input) const {
  log_line(name(), "Cluster C hardware diag begins: inner_step=" +
                       std::to_string(input.inner_step + 1));

  const int diag_dim =
      std::max(input.reduced.reduced_dim,
               std::min(input.descriptor.band_count,
                        input.descriptor.panel_count *
                            input.descriptor.resident_row_block_size));
  const int eigenpair_count =
      std::min(input.descriptor.band_batch, std::max(1, diag_dim / 2));
  const int t_input = 4 + diag_dim / 2;
  const int t_factorize = 2 + diag_dim;
  const int t_transform = 2 + diag_dim;
  const int t_solver = 4 + (diag_dim * diag_dim * diag_dim) / 96;
  const int t_emit = 3 + eigenpair_count;
  int signature_compute_bonus = 0;
  int signature_emit_bonus = 0;
  double signature_condition_penalty = 0.0;
  if (is_experimental_signature_case(input.descriptor)) {
    if (input.descriptor.solver_path_class == "generalized_overlap") {
      signature_compute_bonus += 8;
      signature_condition_penalty += 0.08;
    }
    if (input.descriptor.generalized_ratio_bucket == "high") {
      signature_compute_bonus += 6;
      signature_condition_penalty += 0.05;
    }
    if (input.descriptor.post_scf_extension_level == "mobility_extension_expected" ||
        input.descriptor.post_scf_extension_level == "epw_expected") {
      signature_compute_bonus += 10;
      signature_emit_bonus += 2;
      signature_condition_penalty += 0.04;
    }
    if (input.descriptor.projector_pressure == "high") {
      signature_compute_bonus += 4;
    }
    if (input.descriptor.workload_topology == "slab_interface") {
      signature_condition_penalty += 0.02;
    } else if (input.descriptor.workload_topology == "wide_bandgap") {
      signature_condition_penalty += 0.03;
    }
  }
  int t_companion =
      24 + diag_dim * 5 +
      (input.descriptor.workload_bucket == "large" ? 12 : 0);
  int graph_compute_adjust = 0;
  int graph_emit_adjust = 0;
  double graph_condition_adjust = 0.0;
  double graph_visibility_adjust = 0.0;
  std::string graph_detail;
  if (!input.descriptor.graph_frontdoor_mode.empty()) {
    const std::string post_c_token = graph_frontdoor::next_token_after(
        input.descriptor.graph_resolved_cluster_sequence, "C");
    const int downstream_module_pressure = std::max(
        0,
        input.descriptor.graph_module_count -
            input.descriptor.graph_leaf_component_count);
    graph_compute_adjust +=
        std::min(6, input.descriptor.graph_leaf_component_count / 4);
    if (input.descriptor.graph_has_vector_diag_companion) {
      t_companion = std::max(8, t_companion - 8);
      graph_compute_adjust += std::min(2, downstream_module_pressure / 8);
      graph_emit_adjust += 1;
      graph_condition_adjust -= 0.03;
      graph_visibility_adjust += 0.05;
    }
    if (!input.descriptor.graph_has_refresh_unit) {
      graph_compute_adjust -= 2;
    }
    if (input.descriptor.graph_prefers_diag_before_reduction) {
      graph_condition_adjust += 0.03;
    }
    if (input.descriptor.graph_flow_count > 2) {
      graph_compute_adjust += 2;
    }
    if (post_c_token == "D") {
      graph_emit_adjust += std::min(2, downstream_module_pressure / 6);
    }
    if (input.descriptor.graph_prefers_refresh_before_diag &&
        post_c_token == "D") {
      graph_compute_adjust += 3;
      graph_emit_adjust += 1;
      graph_condition_adjust += 0.02;
      graph_visibility_adjust += 0.03;
    }
    graph_detail =
        " | graph_vdiag=" +
        std::string(input.descriptor.graph_has_vector_diag_companion ? "yes" : "no") +
        ", graph_refresh=" +
        std::string(input.descriptor.graph_has_refresh_unit ? "yes" : "no") +
        ", graph_diag_before_red=" +
        std::string(input.descriptor.graph_prefers_diag_before_reduction ? "yes" : "no") +
        ", graph_refresh_before_diag=" +
        std::string(input.descriptor.graph_prefers_refresh_before_diag ? "yes" : "no") +
        ", graph_flow_count=" + std::to_string(input.descriptor.graph_flow_count) +
        ", graph_modules=" + std::to_string(input.descriptor.graph_module_count) +
        ", graph_post_c=" + (post_c_token.empty() ? "unset" : post_c_token);
  }
  const int t_compute = t_factorize + t_transform + t_solver +
                        signature_compute_bonus + graph_compute_adjust;
  const int t_hw_diag = t_input + t_compute + t_emit + signature_emit_bonus +
                        graph_emit_adjust;
  if (is_experimental_signature_case(input.descriptor) &&
      input.descriptor.post_scf_extension_level == "mobility_extension_expected") {
    t_companion += 4;
  }
  const double condition_estimate =
      1.10 + 0.04 * static_cast<double>(diag_dim) /
                 static_cast<double>(std::max(1, eigenpair_count)) +
      0.12 * (input.reduced.closure_score < 0.75 ? 1.0 : 0.0) +
      signature_condition_penalty + graph_condition_adjust;

  const bool range_overflow = diag_dim > input.descriptor.max_device_diag_dim;
  const bool condition_overflow =
      condition_estimate > input.descriptor.max_diag_condition_estimate;
  const bool force_fallback =
      input.descriptor.force_cpu_diag || !input.controller_state.resident_fit ||
      range_overflow || condition_overflow ||
      t_hw_diag >= t_companion;

  sc_core::wait(static_cast<double>(t_hw_diag), sc_core::SC_NS);

  ClusterCOutput output;
  output.cdiaghg_mode_selected =
      force_fallback ? "fallback_companion" : "hardware";
  output.crossover_margin =
      static_cast<double>(t_companion - t_hw_diag);
  output.diag_solution.diag_dim_n = diag_dim;
  output.diag_solution.eigenpair_count = eigenpair_count;
  const double anchor_energy =
      workload_energy_anchor_ry(workload_energy_shape_for(input.descriptor));
  const double family_bias =
      input.descriptor.architecture_family == "F1"
          ? 0.0
          : (input.descriptor.architecture_family == "F2" ? 0.65 : 1.25);
  const double iteration_relaxation =
      1.20 / static_cast<double>(input.descriptor.scf_iteration + input.inner_step + 1);
  const double shape_offset =
      0.02 * static_cast<double>(diag_dim - eigenpair_count);
  const double closure_penalty =
      (1.0 - input.reduced.closure_score) *
      (input.descriptor.architecture_family == "F1" ? 0.9 : 1.4);
  output.diag_solution.lambda_base =
      anchor_energy + family_bias + iteration_relaxation + shape_offset +
      closure_penalty;
  output.diag_solution.coeff_norm =
      0.55 + 0.03 * static_cast<double>(eigenpair_count) +
      0.12 * input.reduced.closure_score;
  output.diag_solution.condition_estimate = condition_estimate;
  output.diag_solution.residual_visibility_score =
      0.30 + 0.04 * static_cast<double>(input.inner_step + 1) +
      graph_visibility_adjust;
  output.diag_solution.emitted_kib =
      (static_cast<double>(diag_dim * eigenpair_count) + eigenpair_count) *
      8.0 / 1024.0;
  output.diag_solution.fallback_used = force_fallback;
  output.diag_solution.source_domain =
      force_fallback ? "HostCPUFallbackBoundary" : "ClusterCHardwareDiag";
  output.metrics.cluster_name = "ClusterC";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles = t_hw_diag;
  output.metrics.backpressure_ref_cycles = force_fallback ? 5 : std::max(1, t_emit / 2);
  output.metrics.data_movement_kib = output.diag_solution.emitted_kib;
  output.metrics.dominant_resource =
      force_fallback ? "CompanionFallbackBoundary" : "ClusterC.SolverPipeline";
  output.metrics.detail =
      "T_C_input=" + std::to_string(t_input) +
      ", T_C_compute=" + std::to_string(t_compute) +
      ", T_C_emit=" +
      std::to_string(t_emit + signature_emit_bonus + graph_emit_adjust) +
      ", cond=" + std::to_string(condition_estimate) + graph_detail;

  log_line(name(), "Cluster C complete => " + output.metrics.brief());
  return output;
}

}  // namespace qebs
