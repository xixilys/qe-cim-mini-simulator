#include "density_commit_unit.hpp"

namespace qebs {

namespace {

std::string density_prefix(const std::string& software_family,
                           const std::string& flow_family) {
  if (software_family == "CP2K" && flow_family == "QS_OT") {
    return "cp2k_ot";
  }
  if (software_family == "CP2K") {
    return "cp2k";
  }
  if (software_family == "VASP" && flow_family == "FAST") {
    return "vasp_fast";
  }
  if (software_family == "VASP") {
    return "vasp";
  }
  return "qe";
}

}  // namespace

DensityCommitUnit::DensityCommitUnit(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

DensitySummary DensityCommitUnit::commit(const Body04StageRequest& request,
                                         const DensityAccumStats& stats) const {
  sc_core::wait(4.0, sc_core::SC_NS);

  const auto& summary = request.phase_b_summary;
  const std::string prefix =
      density_prefix(request.software_family, request.flow_family);

  DensitySummary density;
  density.density_object.object_handle =
      prefix + "_rho_iter_" + std::to_string(summary.config.scf_iteration);
  density.density_object.version = summary.config.scf_iteration;
  density.density_object.resident_buffer_tag = 200 + summary.config.scf_iteration;
  density.density_object.producer_body = "BODY_04A";
  density.density_object.validity_scope = "scf-iteration";
  density.rho_out_norm = stats.rho_out_norm;
  density.occupation_checksum = stats.occupation_checksum;
  density.accumulated_bands = stats.accumulated_bands;
  density.data_movement_kib = stats.data_movement_kib;

  log_line(name(), request.stage_kind + " committed density object => " + density.brief());
  return density;
}

}  // namespace qebs
