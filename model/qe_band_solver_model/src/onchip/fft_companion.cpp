#include "fft_companion.hpp"

namespace qebs {

FFTCompanion::FFTCompanion(sc_core::sc_module_name name) : sc_core::sc_module(name) {}

void FFTCompanion::transform(WavePanel& panel) const {
  sc_core::wait(5.0, sc_core::SC_NS);
  for (std::size_t i = 0; i < panel.samples.size(); ++i) {
    panel.samples[i] += 0.003 * static_cast<double>(i + 1);
  }
  panel.amplitude_norm *= 0.985;
  log_line(name(), "FFT companion updated spectral view for " + panel.brief());
}

}  // namespace qebs
