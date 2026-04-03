#include <algorithm>

#include "cluster_c_hardware_diag.hpp"

namespace qebs {

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
  const int t_compute = t_factorize + t_transform + t_solver;
  const int t_hw_diag = t_input + t_compute + t_emit;
  const int t_companion =
      24 + diag_dim * 5 +
      (input.descriptor.workload_bucket == "large" ? 12 : 0);

  const bool range_overflow =
      diag_dim > (input.descriptor.workload_bucket == "large" ? 24 : 32);
  const bool force_fallback =
      !input.controller_state.resident_fit || range_overflow ||
      t_hw_diag >= t_companion;

  sc_core::wait(static_cast<double>(t_hw_diag), sc_core::SC_NS);

  ClusterCOutput output;
  output.cdiaghg_mode_selected =
      force_fallback ? "fallback_companion" : "hardware";
  output.crossover_margin =
      static_cast<double>(t_companion - t_hw_diag);
  output.diag_solution.diag_dim_n = diag_dim;
  output.diag_solution.eigenpair_count = eigenpair_count;
  output.diag_solution.lambda_base =
      -12.0 + 0.07 * static_cast<double>(input.descriptor.scf_iteration) -
      0.01 * input.reduced.h_small;
  output.diag_solution.coeff_norm =
      0.55 + 0.03 * static_cast<double>(eigenpair_count) +
      0.12 * input.reduced.closure_score;
  output.diag_solution.residual_visibility_score =
      0.30 + 0.04 * static_cast<double>(input.inner_step + 1);
  output.diag_solution.emitted_kib =
      (static_cast<double>(diag_dim * eigenpair_count) + eigenpair_count) *
      8.0 / 1024.0;
  output.diag_solution.fallback_used = force_fallback;
  output.diag_solution.source_domain =
      force_fallback ? "CompanionBoundary" : "ClusterCHardwareDiag";
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
      ", T_C_emit=" + std::to_string(t_emit);

  log_line(name(), "Cluster C complete => " + output.metrics.brief());
  return output;
}

}  // namespace qebs
