#include "cim_eligible_operator_subchain.hpp"

namespace qebs {

namespace {

ModuleOccupancy make_occupancy(const std::string& module_name,
                               int activation_count,
                               int busy_ref_cycles,
                               int transfer_count) {
  ModuleOccupancy occupancy;
  occupancy.module_name = module_name;
  occupancy.activation_count = activation_count;
  occupancy.busy_ref_cycles = busy_ref_cycles;
  occupancy.transfer_count = transfer_count;
  return occupancy;
}

}  // namespace

CIMEligibleOperatorSubchain::CIMEligibleOperatorSubchain(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      command_scheduler_(sc_core::sc_module_name("command_scheduler")),
      resident_context_controller_(sc_core::sc_module_name("resident_context_controller")),
      context_loader_(sc_core::sc_module_name("context_loader")),
      digit_serial_input_boundary_(sc_core::sc_module_name("digit_serial_input_boundary")),
      conjugate_sign_selector_(sc_core::sc_module_name("conjugate_sign_selector")),
      near_sram_coeff_buffer_(sc_core::sc_module_name("near_sram_coeff_buffer")),
      near_sram_row_buffer_(sc_core::sc_module_name("near_sram_row_buffer")),
      cim_array_core_(sc_core::sc_module_name("cim_array_core")) {}

OperatorChainReport CIMEligibleOperatorSubchain::run(
    const EpisodeConfig& config, const std::vector<WavePanel>& panels,
    int inner_step) const {
  log_line(name(), "Dispatching CIM-eligible operator subchain for episode " +
                       std::to_string(config.episode_id) +
                       ", step=" + std::to_string(inner_step + 1));

  OperatorChainReport report;
  report.resident_context = resident_context_controller_.bind_context(config, inner_step);
  const auto schedule =
      command_scheduler_.issue_projector_chain(config, report.resident_context, inner_step);
  report.lcw_words_issued = static_cast<int>(schedule.size());

  const int panel_visits = static_cast<int>(panels.size());
  const int row_block_visits = panel_visits * report.lcw_words_issued;
  report.structural.model_level = "STRUCTURAL_TIMED_FUNCTIONAL_WITH_PHASEB_LEAF_FLOW_CONTROL_PROXY";
  report.structural.panel_visits = panel_visits;
  report.structural.row_block_visits = row_block_visits;
  report.structural.control_ref_cycles = report.lcw_words_issued + 3 + row_block_visits;
  report.structural.near_sram_ref_cycles =
      row_block_visits * (2 + 4 + 3);
  report.structural.cim_ref_cycles =
      row_block_visits * (2 + 1 + 6 + 3 + 1 + 6 + 3);
  report.structural.total_ref_cycles = report.structural.control_ref_cycles +
                                       report.structural.near_sram_ref_cycles +
                                       report.structural.cim_ref_cycles;
  report.structural.critical_domain = "CIM_PROJECT_BACKPROJECT_CHAIN";
  report.structural.module_occupancy.push_back(
      make_occupancy("CommandScheduler", 1, report.lcw_words_issued, report.lcw_words_issued));
  report.structural.module_occupancy.push_back(
      make_occupancy("ResidentContextController",
                     2 + row_block_visits,
                     3 + row_block_visits,
                     row_block_visits));
  report.structural.module_occupancy.push_back(
      make_occupancy("ContextLoader", row_block_visits, 2 * row_block_visits, row_block_visits));
  report.structural.module_occupancy.push_back(make_occupancy("DigitSerialInputBoundary",
                     row_block_visits,
                     2 * row_block_visits,
                     row_block_visits));
  report.structural.module_occupancy.push_back(make_occupancy("ConjugateSignSelector",
                     2 * row_block_visits,
                     2 * row_block_visits,
                     2 * row_block_visits));
  report.structural.module_occupancy.push_back(make_occupancy("Residue3MCore",
                     2 * row_block_visits,
                     12 * row_block_visits,
                     2 * row_block_visits));
  report.structural.module_occupancy.push_back(make_occupancy("CoefficientAccumulator",
                     row_block_visits,
                     3 * row_block_visits,
                     row_block_visits));
  report.structural.module_occupancy.push_back(make_occupancy("NearSRAMCoeffBuffer",
                     row_block_visits,
                     4 * row_block_visits,
                     row_block_visits));
  report.structural.module_occupancy.push_back(
      make_occupancy("RowMergeTree", row_block_visits, 3 * row_block_visits, row_block_visits));
  report.structural.module_occupancy.push_back(make_occupancy("NearSRAMRowBuffer",
                     row_block_visits,
                     3 * row_block_visits,
                     row_block_visits));

  report.partials.reserve(panels.size());
  for (const auto& panel : panels) {
    PartialHS panel_partial;
    panel_partial.panel_id = panel.panel_id;

    for (const auto& word : schedule) {
      const auto window = resident_context_controller_.open_row_block(
          config, report.resident_context, word.row_block_id);
      const auto loaded_panel =
          context_loader_.load_row_window(panel, report.resident_context, window);
      const auto digit_slice =
          digit_serial_input_boundary_.pack_project_stream(loaded_panel, window);
      const auto project_slice =
          conjugate_sign_selector_.apply_project_policy(window, digit_slice);
      const auto coeff =
          cim_array_core_.project(config, report.resident_context, window, project_slice);
      const auto transformed_coeff =
          near_sram_coeff_buffer_.store_and_transform(config, report.resident_context, coeff);
      const auto backproject_coeff =
          conjugate_sign_selector_.apply_backproject_policy(window, transformed_coeff);
      const auto partial =
          cim_array_core_.backproject(config, report.resident_context, window, backproject_coeff);
      const auto committed =
          near_sram_row_buffer_.commit_partial(config, report.resident_context, partial);

      panel_partial.h_contrib += committed.h_contrib;
      panel_partial.s_contrib += committed.s_contrib;
      panel_partial.local_condition += committed.local_condition;
      report.row_blocks_processed += 1;
    }

    if (!schedule.empty()) {
      panel_partial.local_condition /= static_cast<double>(schedule.size());
    }
    report.partials.push_back(panel_partial);
  }

  resident_context_controller_.release_context(report.resident_context);
  log_line(name(), "CIM-eligible operator subchain completed panels=" +
                       std::to_string(report.partials.size()) +
                       ", row_blocks=" + std::to_string(report.row_blocks_processed) +
                       ", hw=" + report.structural.brief());
  return report;
}

}  // namespace qebs
