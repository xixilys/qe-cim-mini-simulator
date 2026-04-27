#include "digit_serial_input_boundary.hpp"

namespace qebs {

DigitSerialInputBoundary::DigitSerialInputBoundary(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

DigitStreamSlice DigitSerialInputBoundary::pack_project_stream(
    const WavePanel& panel, const RowBlockWindowDesc& window) const {
  sc_core::wait(2.0, sc_core::SC_NS);

  DigitStreamSlice slice;
  slice.panel_id = panel.panel_id;
  slice.row_block_id = window.row_block_id;
  slice.digit_count = static_cast<int>(panel.samples.size());
  for (std::size_t index = 0; index < panel.samples.size(); ++index) {
    const double digit = panel.samples[index] * (1.0 + 0.005 * static_cast<double>(index + 1));
    slice.digits.push_back(digit);
    slice.magnitude_checksum += digit;
  }

  log_line(name(), "DigitSerialInputBoundary packed " + slice.brief());
  return slice;
}

}  // namespace qebs
