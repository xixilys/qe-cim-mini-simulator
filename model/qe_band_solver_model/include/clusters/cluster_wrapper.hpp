#pragma once

#include "architecture_config.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class ClusterAOperatorSweep;
class ClusterBReducedBuild;
class ClusterCHardwareDiag;
class ClusterDRefreshResidual;

class ClusterWrapper {
 public:
  virtual ~ClusterWrapper() = default;
  
  virtual ClusterType get_type() const = 0;
  virtual std::string get_id() const = 0;
  virtual sc_core::sc_module* get_module() = 0;
  
  virtual ClusterAOutput run_a(const ClusterAInput& input) const { return ClusterAOutput{}; }
  virtual ClusterBOutput run_b(const ClusterBInput& input) const { return ClusterBOutput{}; }
  virtual ClusterCOutput run_c(const ClusterCInput& input) const { return ClusterCOutput{}; }
  virtual ClusterDOutput run_d(const ClusterDInput& input) const { return ClusterDOutput{}; }
};

class ClusterAWrapper : public ClusterWrapper {
 public:
  ClusterAWrapper(ClusterAOperatorSweep* cluster, ClusterType type, const std::string& id);
  
  ClusterType get_type() const override { return type_; }
  std::string get_id() const override { return id_; }
  sc_core::sc_module* get_module() override;
  ClusterAOutput run_a(const ClusterAInput& input) const override;
  
 private:
  ClusterAOperatorSweep* cluster_;
  ClusterType type_;
  std::string id_;
};

class ClusterBWrapper : public ClusterWrapper {
 public:
  ClusterBWrapper(ClusterBReducedBuild* cluster, ClusterType type, const std::string& id);
  
  ClusterType get_type() const override { return type_; }
  std::string get_id() const override { return id_; }
  sc_core::sc_module* get_module() override;
  ClusterBOutput run_b(const ClusterBInput& input) const override;
  
 private:
  ClusterBReducedBuild* cluster_;
  ClusterType type_;
  std::string id_;
};

class ClusterCWrapper : public ClusterWrapper {
 public:
  ClusterCWrapper(ClusterCHardwareDiag* cluster, ClusterType type, const std::string& id);
  
  ClusterType get_type() const override { return type_; }
  std::string get_id() const override { return id_; }
  sc_core::sc_module* get_module() override;
  ClusterCOutput run_c(const ClusterCInput& input) const override;
  
 private:
  ClusterCHardwareDiag* cluster_;
  ClusterType type_;
  std::string id_;
};

class ClusterDWrapper : public ClusterWrapper {
 public:
  ClusterDWrapper(ClusterDRefreshResidual* cluster, ClusterType type, const std::string& id);
  
  ClusterType get_type() const override { return type_; }
  std::string get_id() const override { return id_; }
  sc_core::sc_module* get_module() override;
  ClusterDOutput run_d(const ClusterDInput& input) const override;
  
 private:
  ClusterDRefreshResidual* cluster_;
  ClusterType type_;
  std::string id_;
};

}  // namespace qebs
