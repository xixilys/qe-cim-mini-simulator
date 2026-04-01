#include "command_scheduler.hpp"

namespace qebs {

CommandScheduler::CommandScheduler(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

std::vector<LCWCommand> CommandScheduler::issue_projector_chain(
    const EpisodeConfig& config, const ResidentContextDesc& context,
    int inner_step) const {
  std::vector<LCWCommand> words;
  words.reserve(static_cast<std::size_t>(context.row_block_count));
  for (int row_block_id = 0; row_block_id < context.row_block_count; ++row_block_id) {
    sc_core::wait(1.0, sc_core::SC_NS);

    LCWCommand word;
    word.word_id = config.episode_id * 100 + inner_step * 10 + row_block_id;
    word.inner_step = inner_step;
    word.resident_context_id = context.resident_context_id;
    word.resident_generation = context.generation;
    word.row_block_id = row_block_id;
    word.active_mod_group_mask = (row_block_id % 2 == 0) ? 0x7 : 0x3;
    word.fft_mode = config.enable_fft ? "PRECONDITIONED" : "BYPASS";
    words.push_back(word);
  }

  log_line(name(), "CommandScheduler issued " + std::to_string(words.size()) +
                       " LCW words for ctx " +
                       std::to_string(context.resident_context_id));
  return words;
}

}  // namespace qebs
