#include "microarchitecture_simulator.hpp"

#include <cmath>
#include <iostream>
#include <string>

namespace {

bool expect_true(bool condition, const std::string& label) {
    if (condition) {
        std::cout << "[PASS] " << label << std::endl;
        return true;
    }
    std::cerr << "[FAIL] " << label << std::endl;
    return false;
}

gsim::ComputeNode gemm_node(double flops, double memory_bytes) {
    gsim::ComputeNode node;
    node.node_id = "gemm0";
    node.op_type = "gemm";
    node.estimated_flops = flops;
    node.estimated_memory_bytes = memory_bytes;
    return node;
}

gsim::AcceleratorDesc fpga_desc() {
    gsim::AcceleratorDesc accel;
    accel.accel_id = "fpga0";
    accel.accel_type = gsim::AccelType::FPGA;
    accel.accel_type_str = "fpga";
    accel.clock_mhz = 250.0;
    accel.power.static_w = 2.0;
    accel.power.max_w = 20.0;
    accel.microarchitecture.accel_type = gsim::AccelType::FPGA;
    accel.microarchitecture.array_size = 16;
    accel.microarchitecture.local_sram_kb = 2048;
    accel.microarchitecture.dma_channels = 4;
    accel.microarchitecture.memory_bandwidth_gbps = 100.0;
    return accel;
}

gsim::AcceleratorDesc cim_desc() {
    gsim::AcceleratorDesc accel;
    accel.accel_id = "cim0";
    accel.accel_type = gsim::AccelType::CIM;
    accel.accel_type_str = "cim";
    accel.clock_mhz = 100.0;
    accel.power.static_w = 1.0;
    accel.power.max_w = 8.0;
    accel.microarchitecture.accel_type = gsim::AccelType::CIM;
    accel.microarchitecture.crossbar_rows = 256;
    accel.microarchitecture.crossbar_cols = 256;
    accel.microarchitecture.adc_resolution = 8;
    accel.microarchitecture.dac_resolution = 8;
    accel.microarchitecture.peripheral_digital_units = 16;
    accel.microarchitecture.memory_bandwidth_gbps = 50.0;
    return accel;
}

gsim::AcceleratorDesc gpu_desc() {
    gsim::AcceleratorDesc accel;
    accel.accel_id = "gpu0";
    accel.accel_type = gsim::AccelType::GPU;
    accel.accel_type_str = "gpu";
    accel.clock_mhz = 1400.0;
    accel.power.static_w = 20.0;
    accel.power.max_w = 250.0;
    accel.microarchitecture.accel_type = gsim::AccelType::GPU;
    accel.microarchitecture.sm_count = 108;
    accel.microarchitecture.shared_memory_kb = 164;
    accel.microarchitecture.warp_size = 32;
    accel.microarchitecture.max_warps_per_sm = 64;
    accel.microarchitecture.memory_bandwidth_gbps = 900.0;
    return accel;
}

gsim::AcceleratorDesc asic_desc() {
    gsim::AcceleratorDesc accel;
    accel.accel_id = "asic0";
    accel.accel_type = gsim::AccelType::ASIC;
    accel.accel_type_str = "asic";
    accel.clock_mhz = 800.0;
    accel.power.static_w = 5.0;
    accel.power.max_w = 50.0;
    accel.microarchitecture.accel_type = gsim::AccelType::ASIC;
    accel.microarchitecture.pipeline_stages = 12;
    accel.microarchitecture.vector_width = 64;
    accel.microarchitecture.memory_bandwidth_gbps = 200.0;
    return accel;
}

gsim::DataEdge transfer_edge(const std::string& dtype) {
    gsim::DataEdge edge;
    edge.source = "a";
    edge.target = "b";
    edge.tensor_name = "x";
    edge.tensor_shape = {1024, 1024};
    edge.tensor_dtype = dtype;
    return edge;
}

} 

int main() {
    bool passed = true;

    auto fpga = gsim::MicroarchitectureSimulatorFactory::create_simulator(gsim::AccelType::FPGA);
    auto cim = gsim::MicroarchitectureSimulatorFactory::create_simulator(gsim::AccelType::CIM);
    auto gpu = gsim::MicroarchitectureSimulatorFactory::create_simulator(gsim::AccelType::GPU);
    auto asic = gsim::MicroarchitectureSimulatorFactory::create_simulator(gsim::AccelType::ASIC);
    auto cpu = gsim::MicroarchitectureSimulatorFactory::create_simulator(gsim::AccelType::CPU);

    passed &= expect_true(fpga && fpga->get_supported_type() == gsim::AccelType::FPGA,
                          "factory creates FPGA simulator");
    passed &= expect_true(cim && cim->get_supported_type() == gsim::AccelType::CIM,
                          "factory creates CIM simulator");
    passed &= expect_true(gpu && gpu->get_supported_type() == gsim::AccelType::GPU,
                          "factory creates GPU simulator");
    passed &= expect_true(asic && asic->get_supported_type() == gsim::AccelType::ASIC,
                          "factory creates ASIC simulator");
    passed &= expect_true(!cpu, "factory rejects CPU simulator creation");

    const auto fpga_accel = fpga_desc();
    const auto cim_accel = cim_desc();
    const auto gpu_accel = gpu_desc();
    const auto asic_accel = asic_desc();
    const auto node = gemm_node(2.0 * 64.0 * 64.0 * 64.0, 3.0 * 64.0 * 64.0 * 8.0);

    const double fpga_cycles = fpga->simulate_compute_cycles(node, fpga_accel);
    const double fpga_power = fpga->estimate_power_w(node, fpga_accel);
    passed &= expect_true(fpga_cycles > 0.0 && std::isfinite(fpga_cycles),
                          "FPGA simulator reports finite positive compute cycles");
    passed &= expect_true(fpga_power >= fpga_accel.power.static_w && fpga_power <= fpga_accel.power.max_w,
                          "FPGA simulator power stays within configured range");

    const double cim_cycles = cim->simulate_compute_cycles(node, cim_accel);
    const double cim_power = cim->estimate_power_w(node, cim_accel);
    passed &= expect_true(cim_cycles > 0.0 && std::isfinite(cim_cycles),
                          "CIM simulator reports finite positive compute cycles");
    passed &= expect_true(cim_power >= cim_accel.power.static_w && std::isfinite(cim_power),
                          "CIM simulator reports finite power above static floor");

    const double gpu_cycles = gpu->simulate_compute_cycles(node, gpu_accel);
    const double gpu_power = gpu->estimate_power_w(node, gpu_accel);
    passed &= expect_true(gpu_cycles > 0.0 && std::isfinite(gpu_cycles),
                          "GPU simulator reports finite positive compute cycles");
    passed &= expect_true(gpu_power >= gpu_accel.power.static_w && gpu_power <= gpu_accel.power.max_w,
                          "GPU simulator power stays within configured range");

    const double asic_cycles = asic->simulate_compute_cycles(node, asic_accel);
    const double asic_power = asic->estimate_power_w(node, asic_accel);
    passed &= expect_true(asic_cycles > 0.0 && std::isfinite(asic_cycles),
                          "ASIC simulator reports finite positive compute cycles");
    passed &= expect_true(asic_power >= asic_accel.power.static_w && asic_power <= asic_accel.power.max_w,
                          "ASIC simulator power stays within configured range");

    const auto fp64_edge = transfer_edge("FP64");
    const auto fp32_edge = transfer_edge("FP32");
    const double fp64_cycles = fpga->simulate_transfer_cycles(fp64_edge, fpga_accel, "host", "fpga0");
    const double fp32_cycles = fpga->simulate_transfer_cycles(fp32_edge, fpga_accel, "host", "fpga0");
    passed &= expect_true(fp64_cycles > fp32_cycles,
                          "transfer simulation accounts for tensor dtype width");

    auto explicit_size_edge = transfer_edge("FP64");
    explicit_size_edge.size_bytes = 1024.0;
    const double explicit_cycles = fpga->simulate_transfer_cycles(explicit_size_edge, fpga_accel, "host", "fpga0");
    passed &= expect_true(explicit_cycles < fp32_cycles,
                          "transfer simulation honors explicit tensor payload size");

    return passed ? 0 : 1;
}
