#pragma once

#include "body04_family_controller.hpp"
#include "body10_family_controller.hpp"
#include "chip_top.hpp"
#include "interconnect.hpp"

namespace qebs {

class ReplayBundleExecutor : public sc_core::sc_module {
 public:
  ReplayBundleExecutor(sc_core::sc_module_name name, Interconnect& fabric, ChipTop& chip);
  ReplayBundleCompletion execute(const ReplayBundleDescriptor& descriptor) const;

 private:
  Interconnect& fabric_;
  ChipTop& chip_;
  Body04FamilyController body04_family_controller_;
  Body10FamilyController body10_family_controller_;
};

}  // namespace qebs
