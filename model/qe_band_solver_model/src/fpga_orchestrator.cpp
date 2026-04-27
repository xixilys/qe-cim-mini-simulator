#include "fpga_orchestrator.hpp"

#include <algorithm>

namespace qebs {

namespace {

bool is_experimental_signature_request(const ScfIterationRequest& request) {
  if (request.software_family != "QE") {
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
    if (request.case_id == stable_case_id) {
      return false;
    }
  }
  return !request.signature_id.empty() ||
         !request.property_target.empty() ||
         !request.pseudopotential_family.empty() ||
         !request.solver_path_class.empty() ||
         !request.workload_topology.empty() ||
         !request.post_scf_extension_level.empty() ||
         !request.projector_pressure.empty() ||
         !request.nonlocal_pressure.empty() ||
         !request.generalized_ratio_bucket.empty() ||
         !request.diag_dominance.empty() ||
         !request.fft_grid_pressure.empty();
}

}  // namespace

FPGAOrchestrator::FPGAOrchestrator(sc_core::sc_module_name name, Interconnect& fabric,
                                   ChipTop& chip)
    : sc_core::sc_module(name), fabric_(fabric), chip_(chip) {}

EpisodeDescriptor FPGAOrchestrator::make_episode_descriptor(
    const ScfIterationRequest& request) const {
  EpisodeDescriptor descriptor;
  descriptor.request_id = request.request_id;
  descriptor.scf_iteration = request.scf_iteration;
  descriptor.episode_id = request.episode_id;
  descriptor.case_id = request.case_id;
  descriptor.band_begin = request.band_batch.band_begin;
  descriptor.band_count = request.band_batch.band_count;
  descriptor.panel_count = request.band_batch.panel_count;
  descriptor.panel_size = request.band_batch.panel_size;
  descriptor.resident_row_block_size =
      std::max(2, request.band_batch.panel_size / 2);
  descriptor.max_inner_steps =
      request.flow_family == "QS_OT" ? 2 : (request.software_family == "VASP" ? 3 : 3);
  descriptor.band_batch = request.band_batch.band_batch;
  descriptor.enable_fft = request.enable_fft && request.resident_set.reuse_fft_support;
  descriptor.software_family = request.software_family;
  descriptor.flow_family = request.flow_family;
  descriptor.architecture_family = request.architecture_family;
  descriptor.assumption_set_id = request.assumption_set_id;
  descriptor.offload_scope = request.offload_scope;
  descriptor.resident_policy = request.resident_policy;
  descriptor.confidence_label = request.confidence_label;
  descriptor.algorithm_contract_deviation =
      request.algorithm_contract_deviation;
  descriptor.solver_mode =
      request.flow_family == "QS_OT"
          ? "OT_PRECOND_CG"
          : (request.software_family == "VASP" ? "BLOCKED_DAVIDSON" : "DAVIDSON");
  descriptor.support_grid_mode = request.resident_set.support_grid_mode;
  descriptor.precision_mode = "fp64-constrained";
  descriptor.workload_bucket =
      request.band_batch.band_count <= 12
          ? "small"
          : (request.band_batch.band_count <= 24 ? "medium" : "large");
  descriptor.signature_id = request.signature_id;
  descriptor.property_target = request.property_target;
  descriptor.pseudopotential_family = request.pseudopotential_family;
  descriptor.solver_path_class = request.solver_path_class;
  descriptor.workload_topology = request.workload_topology;
  descriptor.post_scf_extension_level = request.post_scf_extension_level;
  descriptor.projector_pressure = request.projector_pressure;
  descriptor.nonlocal_pressure = request.nonlocal_pressure;
  descriptor.generalized_ratio_bucket = request.generalized_ratio_bucket;
  descriptor.diag_dominance = request.diag_dominance;
  descriptor.fft_grid_pressure = request.fft_grid_pressure;
  descriptor.graph_frontdoor_mode = request.graph_frontdoor_mode;
  descriptor.graph_id = request.graph_id;
  descriptor.graph_topology_style = request.graph_topology_style;
  descriptor.graph_module_count = request.graph_module_count;
  descriptor.graph_flow_count = request.graph_flow_count;
  descriptor.graph_leaf_component_count = request.graph_leaf_component_count;
  descriptor.graph_has_fft_unit = request.graph_has_fft_unit;
  descriptor.graph_has_reduction_unit = request.graph_has_reduction_unit;
  descriptor.graph_has_diag_unit = request.graph_has_diag_unit;
  descriptor.graph_has_vector_diag_companion = request.graph_has_vector_diag_companion;
  descriptor.graph_has_refresh_unit = request.graph_has_refresh_unit;
  descriptor.graph_has_leaf_hotpath_flow = request.graph_has_leaf_hotpath_flow;
  descriptor.graph_prefers_diag_before_reduction = request.graph_prefers_diag_before_reduction;
  descriptor.graph_prefers_refresh_before_diag = request.graph_prefers_refresh_before_diag;
  descriptor.graph_requested_cluster_sequence = request.graph_requested_cluster_sequence;
  descriptor.graph_resolved_cluster_sequence = request.graph_resolved_cluster_sequence;
  descriptor.graph_sequence_constraints = request.graph_sequence_constraints;
  descriptor.projector_mode = request.resident_set.projector_mode;
  descriptor.preferred_diag_mode = request.diag_policy.force_cpu_diag
                                       ? "fallback_companion"
                                       : request.diag_policy.preferred_device_mode;
  descriptor.resident_set_id = request.resident_set.resident_set_id;
  descriptor.max_device_diag_dim = request.diag_policy.max_device_diag_dim;
  descriptor.max_diag_condition_estimate = request.diag_policy.max_condition_estimate;
  descriptor.force_cpu_diag = request.diag_policy.force_cpu_diag;
  descriptor.allow_cpu_diag_fallback = request.diag_policy.allow_cpu_fallback;
  descriptor.wave_object = request.band_batch.wave_object;
  descriptor.density_object = request.density_object;
  descriptor.potential_object = request.potential_object;
  descriptor.projector_object = request.resident_set.projector_object;
  descriptor.history_object = request.history_object;
  if (is_experimental_signature_request(request)) {
    if (request.post_scf_extension_level == "mobility_extension_expected" ||
        request.post_scf_extension_level == "epw_expected") {
      descriptor.max_inner_steps = std::max(descriptor.max_inner_steps, 4);
    }
    if (request.solver_path_class == "generalized_overlap") {
      descriptor.max_diag_condition_estimate -= 0.08;
    }
    if (request.projector_pressure == "high") {
      descriptor.max_device_diag_dim = std::min(descriptor.max_device_diag_dim, 24);
    }
    if (request.fft_grid_pressure == "high") {
      descriptor.resident_budget_scale *= 0.92;
    }
    if (request.workload_topology == "slab_interface") {
      descriptor.resident_budget_scale *= 0.95;
    } else if (request.workload_topology == "wide_bandgap") {
      descriptor.resident_budget_scale *= 0.90;
    }
  }
  return descriptor;
}

int FPGAOrchestrator::simulate_host_diag_service(
    EpisodeResult& result, const ScfIterationRequest& request) const {
  if (!result.diag_solution.fallback_used || !request.diag_policy.allow_cpu_fallback) {
    return 0;
  }

  const int host_cycles =
      18 + result.diag_solution.diag_dim_n * 4 +
      (result.diag_solution.condition_estimate >
               request.diag_policy.max_condition_estimate
           ? 8
           : 0);
  log_line(name(),
           "Thin device runtime requests host CPU diagonalization assist: " +
               result.diag_solution.brief());
  sc_core::wait(static_cast<double>(host_cycles), sc_core::SC_NS);
  result.diag_solution.source_domain = "HostCPUFallback";
  result.controller_state.cdiaghg_mode_selected = "host_cpu_fallback";
  return host_cycles;
}

CompletionSummary FPGAOrchestrator::make_completion_summary(
    const ScfIterationRequest& request, const EpisodeResult& result,
    bool resident_reused, int dma_ref_cycles, int host_assist_ref_cycles,
    double dma_read_kib, double dma_write_kib) const {
  CompletionSummary completion;
  completion.request_id = request.request_id;
  completion.scf_iteration = request.scf_iteration;
  completion.episode_id = request.episode_id;
  completion.case_id = request.case_id;
  completion.architecture_family = request.architecture_family;
  completion.assumption_set_id = request.assumption_set_id;
  completion.offload_scope = request.offload_scope;
  completion.resident_policy = request.resident_policy;
  completion.confidence_label = request.confidence_label;
  completion.algorithm_contract_deviation =
      request.algorithm_contract_deviation;
  completion.status = result.status;
  completion.completion_reason = result.converged_inner_loop
                                     ? "inner_hot_path_complete"
                                     : "inner_hot_path_limit";
  completion.diag_path =
      result.diag_solution.fallback_used ? "host_cpu_fallback" : "device_accelerator";
  completion.resident_reused = resident_reused;
  completion.spill_active = result.controller_state.spill_active;
  completion.used_device_fft = request.enable_fft && result.descriptor.enable_fft;
  completion.cpu_diag_fallback = result.diag_solution.fallback_used;
  completion.gold_pass = false;
  completion.inner_steps = result.completed_inner_steps;
  completion.lcw_words_issued = result.lcw_words_issued;
  completion.row_blocks_processed = result.row_blocks_processed;
  completion.device_busy_ref_cycles = result.total_ref_cycles;
  completion.dma_ref_cycles = dma_ref_cycles;
  completion.host_assist_ref_cycles = host_assist_ref_cycles;
  completion.dma_read_kib = dma_read_kib;
  completion.dma_write_kib = dma_write_kib;
  completion.total_data_movement_kib =
      result.total_data_movement_kib + dma_read_kib + dma_write_kib;
  completion.residual_norm = result.residual_norm;
  completion.updated_vector_norm = result.updated_vector_norm;
  completion.exported_wave_object = result.p_next_object;
  completion.episode_result = result;
  return completion;
}

CompletionSummary FPGAOrchestrator::execute_iteration(
    const ScfIterationRequest& request) const {
  log_line(name(), "Thin device runtime accepts request: " + request.brief());

  int dma_ref_cycles = 0;
  double dma_read_kib = 0.0;
  double dma_write_kib = 0.0;
  const bool resident_reused =
      resident_set_id_ == request.resident_set.resident_set_id &&
      resident_set_generation_ == request.resident_set.generation;

  dma_ref_cycles += fabric_.submit_iteration_request(request);
  if (!resident_reused) {
    dma_ref_cycles += fabric_.preload_resident_set(request.resident_set);
    dma_read_kib += request.resident_set.preload_kib;
    resident_set_id_ = request.resident_set.resident_set_id;
    resident_set_generation_ = request.resident_set.generation;
  }

  dma_ref_cycles += fabric_.stream_band_batch(request.band_batch);
  dma_read_kib += request.band_batch.input_wave_kib;

  auto result = chip_.run_episode(make_episode_descriptor(request));

  int host_assist_ref_cycles = 0;
  if (result.diag_solution.fallback_used && request.diag_policy.allow_cpu_fallback) {
    DmaTransferDesc reduced_export;
    reduced_export.transfer_id =
        "reduced-export-" + std::to_string(request.request_id);
    reduced_export.channel_kind = "D2H_DMA";
    reduced_export.payload_kind = "reduced_matrices";
    reduced_export.src_scope = "DEVICE_HBM";
    reduced_export.dst_scope = "HOST_DRAM";
    reduced_export.kib =
        std::max(1.0, 2.0 * static_cast<double>(result.diag_solution.diag_dim_n *
                                                result.diag_solution.diag_dim_n) *
                          8.0 / 1024.0);
    dma_ref_cycles += fabric_.dma_to_host(reduced_export);
    dma_write_kib += reduced_export.kib;

    host_assist_ref_cycles = simulate_host_diag_service(result, request);

    DmaTransferDesc diag_import;
    diag_import.transfer_id =
        "diag-import-" + std::to_string(request.request_id);
    diag_import.channel_kind = "H2D_DMA";
    diag_import.payload_kind = "diag_solution";
    diag_import.src_scope = "HOST_DRAM";
    diag_import.dst_scope = "DEVICE_HBM";
    diag_import.kib = std::max(0.5, result.diag_solution.emitted_kib);
    diag_import.double_buffered = false;
    dma_ref_cycles += fabric_.dma_to_device(diag_import);
    dma_read_kib += diag_import.kib;
  }

  DmaTransferDesc result_export;
  result_export.transfer_id = "wave-export-" + std::to_string(request.request_id);
  result_export.channel_kind = "D2H_DMA";
  result_export.payload_kind = "updated_wave";
  result_export.src_scope = "DEVICE_HBM";
  result_export.dst_scope = "HOST_DRAM";
  result_export.kib = std::max(0.5, request.band_batch.output_wave_kib);
  result_export.double_buffered = request.band_batch.double_buffered;
  dma_ref_cycles += fabric_.dma_to_host(result_export);
  dma_write_kib += result_export.kib;

  auto completion = make_completion_summary(
      request, result, resident_reused, dma_ref_cycles, host_assist_ref_cycles,
      dma_read_kib, dma_write_kib);
  fabric_.notify_completion(completion);
  log_line(name(), "Thin device runtime completes request: " + completion.brief());
  return completion;
}

}  // namespace qebs
