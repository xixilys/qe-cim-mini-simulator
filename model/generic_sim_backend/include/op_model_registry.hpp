#pragma once

#include "simulation_types.hpp"
#include <map>
#include <memory>

namespace gsim {

class OpModel {
public:
    virtual ~OpModel() = default;
    virtual bool supports(const std::string& op_type) const = 0;
    virtual double estimate_compute_cycles(
        const ComputeNode& node,
        const AcceleratorDesc& accel,
        double context
    ) const = 0;
    virtual double estimate_memory_bytes(
        const ComputeNode& node,
        const AcceleratorDesc& accel
    ) const = 0;
    virtual double estimate_energy_joules(
        const ComputeNode& node,
        const AcceleratorDesc& accel,
        double cycles
    ) const = 0;
};

class OpModelRegistry {
public:
    OpModelRegistry();
    
    void register_model(std::unique_ptr<OpModel> model);
    const OpModel* find_model(const std::string& op_type) const;
    
private:
    std::vector<std::unique_ptr<OpModel>> models_;
};

// Concrete operation models
class GemmModel : public OpModel {
public:
    bool supports(const std::string& op_type) const override;
    double estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const override;
    double estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const override;
    double estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const override;
};

class FftModel : public OpModel {
public:
    bool supports(const std::string& op_type) const override;
    double estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const override;
    double estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const override;
    double estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const override;
};

class EigenModel : public OpModel {
public:
    bool supports(const std::string& op_type) const override;
    double estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const override;
    double estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const override;
    double estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const override;
};

class ReductionModel : public OpModel {
public:
    bool supports(const std::string& op_type) const override;
    double estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const override;
    double estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const override;
    double estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const override;
};

class GenericOpModel : public OpModel {
public:
    bool supports(const std::string& op_type) const override;
    double estimate_compute_cycles(const ComputeNode& node, const AcceleratorDesc& accel, double context) const override;
    double estimate_memory_bytes(const ComputeNode& node, const AcceleratorDesc& accel) const override;
    double estimate_energy_joules(const ComputeNode& node, const AcceleratorDesc& accel, double cycles) const override;
};

} // namespace gsim
