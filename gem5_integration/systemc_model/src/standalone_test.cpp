#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include "gem5_tlm_target.hpp"
#include "dft_hybrid_system_gem5.hpp"

#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

using namespace sc_core;
using namespace tlm;
using namespace qebs;

namespace {

constexpr uint64_t REG_CONTROL = 0x0000;
constexpr uint64_t REG_STATUS = 0x0004;
constexpr uint64_t REG_DMA_SRC_LO = 0x0010;
constexpr uint64_t REG_DMA_SRC_HI = 0x0014;
constexpr uint64_t REG_DMA_DST_LO = 0x0018;
constexpr uint64_t REG_DMA_DST_HI = 0x001C;
constexpr uint64_t REG_DMA_SIZE = 0x0020;
constexpr uint64_t REG_ELECTRONS_CMD = 0x0128;
constexpr uint64_t REG_ELECTRONS_CONVERGED = 0x0130;
constexpr uint64_t DEVICE_MEMORY_BASE = 0x40000000ULL;

bool expect_true(bool condition, const std::string& label) {
  if (condition) {
    std::cout << "[PASS] " << label << std::endl;
    return true;
  }
  std::cerr << "[FAIL] " << label << std::endl;
  return false;
}

std::string env_or_default(const char* key, const std::string& default_value) {
  const char* value = std::getenv(key);
  return value != nullptr && value[0] != '\0' ? std::string(value) : default_value;
}

std::string json_escape(const std::string& value) {
  std::ostringstream out;
  for (char ch : value) {
    switch (ch) {
      case '"':
        out << "\\\"";
        break;
      case '\\':
        out << "\\\\";
        break;
      case '\n':
        out << "\\n";
        break;
      case '\r':
        out << "\\r";
        break;
      case '\t':
        out << "\\t";
        break;
      default:
        out << ch;
        break;
    }
  }
  return out.str();
}

std::string json_string(const std::string& value) {
  return "\"" + json_escape(value) + "\"";
}

std::string report_mode_from_env() {
  const std::string requested = env_or_default("QEBS_EXECUTION_MODE", "systemc_timed_functional");
  if (requested == "systemc_standalone" || requested == "systemc_timed_functional") {
    return requested;
  }
  return "systemc_timed_functional";
}

std::string claim_ceiling_for_mode(const std::string& mode) {
  if (mode == "systemc_standalone") {
    return "systemc_standalone_proxy_only";
  }
  return "systemc_timed_functional_proxy_only";
}

uint64_t metric_u64(double value) {
  return value > 0.0 ? static_cast<uint64_t>(value) : 0;
}

uint32_t tlm_read32(Gem5TLMTarget& target, uint64_t addr, tlm_response_status& response) {
  uint32_t value = 0;
  tlm_generic_payload trans;
  sc_time delay = SC_ZERO_TIME;
  trans.set_command(TLM_READ_COMMAND);
  trans.set_address(addr);
  trans.set_data_ptr(reinterpret_cast<unsigned char*>(&value));
  trans.set_data_length(sizeof(value));
  trans.set_streaming_width(sizeof(value));
  trans.set_byte_enable_ptr(nullptr);
  trans.set_dmi_allowed(false);
  trans.set_response_status(TLM_INCOMPLETE_RESPONSE);
  target.b_transport(trans, delay);
  response = trans.get_response_status();
  return value;
}

void tlm_write32(Gem5TLMTarget& target, uint64_t addr, uint32_t value,
                 tlm_response_status& response) {
  tlm_generic_payload trans;
  sc_time delay = SC_ZERO_TIME;
  trans.set_command(TLM_WRITE_COMMAND);
  trans.set_address(addr);
  trans.set_data_ptr(reinterpret_cast<unsigned char*>(&value));
  trans.set_data_length(sizeof(value));
  trans.set_streaming_width(sizeof(value));
  trans.set_byte_enable_ptr(nullptr);
  trans.set_dmi_allowed(false);
  trans.set_response_status(TLM_INCOMPLETE_RESPONSE);
  target.b_transport(trans, delay);
  response = trans.get_response_status();
}

template <typename T>
void tlm_write_object(Gem5TLMTarget& target, uint64_t addr, const T& value,
                      tlm_response_status& response) {
  tlm_generic_payload trans;
  sc_time delay = SC_ZERO_TIME;
  trans.set_command(TLM_WRITE_COMMAND);
  trans.set_address(addr);
  trans.set_data_ptr(reinterpret_cast<unsigned char*>(const_cast<T*>(&value)));
  trans.set_data_length(sizeof(value));
  trans.set_streaming_width(sizeof(value));
  trans.set_byte_enable_ptr(nullptr);
  trans.set_dmi_allowed(false);
  trans.set_response_status(TLM_INCOMPLETE_RESPONSE);
  target.b_transport(trans, delay);
  response = trans.get_response_status();
}

template <typename T>
T tlm_read_object(Gem5TLMTarget& target, uint64_t addr,
                  tlm_response_status& response) {
  T value{};
  tlm_generic_payload trans;
  sc_time delay = SC_ZERO_TIME;
  trans.set_command(TLM_READ_COMMAND);
  trans.set_address(addr);
  trans.set_data_ptr(reinterpret_cast<unsigned char*>(&value));
  trans.set_data_length(sizeof(value));
  trans.set_streaming_width(sizeof(value));
  trans.set_byte_enable_ptr(nullptr);
  trans.set_dmi_allowed(false);
  trans.set_response_status(TLM_INCOMPLETE_RESPONSE);
  target.b_transport(trans, delay);
  response = trans.get_response_status();
  return value;
}

bool tlm_memory_round_trip(Gem5TLMTarget& target) {
  uint32_t written = 0xdecafbad;
  uint32_t read_back = 0;
  tlm_response_status response = TLM_INCOMPLETE_RESPONSE;
  tlm_write32(target, DEVICE_MEMORY_BASE, written, response);
  if (!expect_true(response == TLM_OK_RESPONSE, "HBM write at explicit device memory base succeeds")) {
    return false;
  }
  read_back = tlm_read32(target, DEVICE_MEMORY_BASE, response);
  return expect_true(response == TLM_OK_RESPONSE && read_back == written,
                     "HBM read/write round-trip uses explicit HBM window");
}

}  // namespace

SC_MODULE(TestBench) {
  tlm_utils::simple_initiator_socket<TestBench> initiator_socket;
  DFTHybridSystemGem5* dft_system;
  Gem5TLMTarget* tlm_target;
  DFTHybridSystemGem5::ElectronsResult last_electrons_result;
  bool has_electrons_result;
  bool passed;

  SC_CTOR(TestBench)
      : initiator_socket("initiator_socket"),
        dft_system(nullptr),
        tlm_target(nullptr),
        last_electrons_result{},
        has_electrons_result(false),
        passed(true) {
    dft_system = new DFTHybridSystemGem5(
        "dft_system", ArchitectureConfig::create_default(), false);
    tlm_target = new Gem5TLMTarget("tlm_target", dft_system);
    initiator_socket.bind(tlm_target->target_socket);

    SC_THREAD(run_test);
  }

  void run_tlm_address_map_tests() {
    tlm_response_status response = TLM_INCOMPLETE_RESPONSE;

    std::cout << "\n=== Test 1: TLM address map/register semantics ===" << std::endl;

    tlm_write32(*tlm_target, REG_CONTROL, 0x00000000, response);
    passed &= expect_true(response == TLM_OK_RESPONSE,
                          "register offset 0x0000 routes to REG_CONTROL");
    uint32_t control = tlm_read32(*tlm_target, REG_CONTROL, response);
    passed &= expect_true(response == TLM_OK_RESPONSE && control == 0,
                          "REG_CONTROL readback remains independent of HBM");

    uint32_t status = tlm_read32(*tlm_target, REG_STATUS, response);
    passed &= expect_true(response == TLM_OK_RESPONSE && status == 0x00000001,
                          "REG_STATUS default ready bit is set");

    tlm_write32(*tlm_target, REG_ELECTRONS_CMD, 1, response);
    passed &= expect_true(response == TLM_OK_RESPONSE,
                          "REG_ELECTRONS_CMD accepts one command write");
    uint32_t command_count = tlm_read32(*tlm_target, REG_ELECTRONS_CMD, response);
    passed &= expect_true(response == TLM_OK_RESPONSE && command_count == 1 &&
                              tlm_target->electrons_command_count() == 1,
                          "REG_ELECTRONS_CMD increments exactly one command counter");

    const uint64_t src_addr = DEVICE_MEMORY_BASE + 0x1000;
    const uint64_t dst_addr = DEVICE_MEMORY_BASE + 0x2000;
    tlm_write32(*tlm_target, REG_DMA_SRC_LO, static_cast<uint32_t>(src_addr), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "DMA SRC_LO write succeeds");
    tlm_write32(*tlm_target, REG_DMA_SRC_HI, static_cast<uint32_t>(src_addr >> 32), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "DMA SRC_HI write succeeds");
    tlm_write32(*tlm_target, REG_DMA_DST_LO, static_cast<uint32_t>(dst_addr), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "DMA DST_LO write succeeds");
    tlm_write32(*tlm_target, REG_DMA_DST_HI, static_cast<uint32_t>(dst_addr >> 32), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "DMA DST_HI write succeeds");
    tlm_write32(*tlm_target, REG_DMA_SIZE, 4096, response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "DMA SIZE write succeeds");

    uint64_t src_read = tlm_read32(*tlm_target, REG_DMA_SRC_LO, response);
    src_read |= static_cast<uint64_t>(tlm_read32(*tlm_target, REG_DMA_SRC_HI, response)) << 32;
    uint64_t dst_read = tlm_read32(*tlm_target, REG_DMA_DST_LO, response);
    dst_read |= static_cast<uint64_t>(tlm_read32(*tlm_target, REG_DMA_DST_HI, response)) << 32;
    uint32_t size_read = tlm_read32(*tlm_target, REG_DMA_SIZE, response);
    passed &= expect_true(src_read == src_addr && dst_read == dst_addr && size_read == 4096,
                          "DMA descriptor registers round-trip consistently");

    uint32_t converged = tlm_read32(*tlm_target, REG_ELECTRONS_CONVERGED, response);
    passed &= expect_true(response == TLM_OK_RESPONSE && converged == 0 &&
                              REG_ELECTRONS_CONVERGED != REG_ELECTRONS_CMD,
                          "result/mailbox offset is distinct from command window");

    (void)tlm_read32(*tlm_target, 0x0200, response);
    passed &= expect_true(response == TLM_ADDRESS_ERROR_RESPONSE,
                          "unmapped register-space address returns address error");

    uint32_t low_bar_memory_probe = 0xa5a55a5a;
    tlm_write32(*tlm_target, 0x0040, low_bar_memory_probe, response);
    passed &= expect_true(response == TLM_ADDRESS_ERROR_RESPONSE,
                          "low BAR offset outside registers cannot alias HBM");
    passed &= tlm_memory_round_trip(*tlm_target);

    uint32_t control_after_hbm = tlm_read32(*tlm_target, REG_CONTROL, response);
    passed &= expect_true(response == TLM_OK_RESPONSE && control_after_hbm == 0,
                          "HBM writes cannot alias low register offset 0x0000");
  }

  void run_backend_dispatch_tests() {
    tlm_response_status response = TLM_INCOMPLETE_RESPONSE;
    std::cout << "\n=== Test 2: backend dispatch/main-path metrics ===" << std::endl;

    const uint64_t req_addr = DEVICE_MEMORY_BASE + 0x3000;
    const uint64_t result_addr = DEVICE_MEMORY_BASE + 0x4000;
    DFTHybridSystemGem5::ElectronsRequest req{};
    req.n_bands = 8;
    req.n_basis = 32;
    req.n_kpoints = 1;
    req.n_spin = 1;
    req.max_iterations = 2;
    req.conv_threshold = 1e-3;
    req.diag_threshold = 1e-6;
    req.mixing_beta = 0.7;
    req.mixing_ndim = 8;
    req.enable_cim = true;
    req.control_policy = 2;  // polling

    tlm_write_object(*tlm_target, req_addr, req, response);
    passed &= expect_true(response == TLM_OK_RESPONSE,
                          "electrons request payload writes to HBM");
    tlm_write32(*tlm_target, REG_DMA_SRC_LO, static_cast<uint32_t>(req_addr), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "request SRC_LO write succeeds");
    tlm_write32(*tlm_target, REG_DMA_SRC_HI, static_cast<uint32_t>(req_addr >> 32), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "request SRC_HI write succeeds");
    tlm_write32(*tlm_target, REG_DMA_DST_LO, static_cast<uint32_t>(result_addr), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "result DST_LO write succeeds");
    tlm_write32(*tlm_target, REG_DMA_DST_HI, static_cast<uint32_t>(result_addr >> 32), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "result DST_HI write succeeds");
    tlm_write32(*tlm_target, REG_DMA_SIZE, sizeof(req), response);
    passed &= expect_true(response == TLM_OK_RESPONSE, "request size write succeeds");
    const uint32_t count_before = tlm_target->electrons_command_count();
    tlm_write32(*tlm_target, REG_ELECTRONS_CMD, 1, response);
    passed &= expect_true(response == TLM_OK_RESPONSE,
                          "electrons command dispatches to DFTHybridSystemGem5");
    const auto result =
        tlm_read_object<DFTHybridSystemGem5::ElectronsResult>(
            *tlm_target, result_addr, response);
    last_electrons_result = result;
    has_electrons_result = response == TLM_OK_RESPONSE;
    passed &= expect_true(response == TLM_OK_RESPONSE,
                          "electrons result payload reads from HBM");
    passed &= expect_true(tlm_target->electrons_command_count() == count_before + 1,
                          "backend dispatch increments exactly one additional command");
    passed &= expect_true(tlm_target->host_launch_count() >= 1 &&
                              tlm_target->completion_count() >= 1,
                          "backend dispatch records host launch/completion counters");
    passed &= expect_true(result.iterations > 0 && result.total_time_ns > 0.0,
                          "DFTHybridSystemGem5 result is derived from non-empty main path");
    passed &= expect_true(result.dma_read_bytes > 0 || result.dma_write_bytes > 0,
                          "main-path result exposes DMA byte metrics");
    passed &= expect_true(tlm_target->last_control_policy() == "polling",
                          "compact command records polling control policy");
    (void)tlm_read32(*tlm_target, REG_ELECTRONS_CONVERGED, response);
    passed &= expect_true(tlm_target->polling_read_count() >= 1,
                          "status/mailbox reads increment polling counter");
  }

  void run_test() {
    wait(10, SC_NS);

    run_tlm_address_map_tests();
    run_backend_dispatch_tests();

    wait(100, SC_NS);

    if (passed) {
      std::cout << "\n=== All tests completed successfully ===" << std::endl;
    } else {
      std::cerr << "\n=== Standalone tests FAILED ===" << std::endl;
    }
    sc_stop();
  }

  bool write_backend_execution_report() const {
    const std::string report_path = env_or_default("QEBS_BACKEND_EXECUTION_REPORT_JSON", "");
    if (report_path.empty()) {
      return true;
    }

    std::ofstream out(report_path);
    if (!out) {
      std::cerr << "[FAIL] unable to open backend report path: " << report_path << std::endl;
      return false;
    }

    const std::string mode = report_mode_from_env();
    const std::string candidate_id =
        env_or_default("QEBS_CANDIDATE_ID", "gem5_systemc_standalone");
    const std::string domain = env_or_default("QEBS_WORKLOAD_DOMAIN", "dft");
    const uint64_t cycle_proxy =
        has_electrons_result ? metric_u64(last_electrons_result.total_time_ns) : 0;
    const double device_busy_s =
        has_electrons_result ? static_cast<double>(last_electrons_result.device_busy_ns) / 1e9 : 0.0;
    const uint64_t bytes_moved =
        has_electrons_result ? last_electrons_result.bytes_moved_to_convergence : 0;

    out << std::setprecision(12);
    out << "{\n";
    out << "  \"schema_version\": \"backend_execution_report_v0\",\n";
    out << "  \"candidate_id\": " << json_string(candidate_id) << ",\n";
    out << "  \"execution_status\": " << json_string(passed ? "executed" : "failed") << ",\n";
    out << "  \"fidelity\": " << json_string(mode) << ",\n";
    out << "  \"claim_ceiling\": " << json_string(claim_ceiling_for_mode(mode)) << ",\n";
    out << "  \"environment\": {\n";
    out << "    \"source\": \"gem5_systemc_standalone\",\n";
    out << "    \"target\": \"Gem5TLMTarget local SystemC target\",\n";
    out << "    \"execution_mode_env\": " << json_string(env_or_default("QEBS_EXECUTION_MODE", "")) << "\n";
    out << "  },\n";
    out << "  \"control_path\": {\n";
    out << "    \"host_launch_count\": " << tlm_target->host_launch_count() << ",\n";
    out << "    \"completion_count\": " << tlm_target->completion_count() << ",\n";
    out << "    \"fallback_count\": " << tlm_target->fallback_count() << ",\n";
    out << "    \"deadlock\": false,\n";
    out << "    \"completion_source\": \"gem5_systemc_standalone_tlm_dispatch\",\n";
    out << "    \"polling_read_count\": " << tlm_target->polling_read_count() << ",\n";
    out << "    \"interrupt_count\": " << tlm_target->interrupt_count() << ",\n";
    out << "    \"last_control_policy\": " << json_string(tlm_target->last_control_policy()) << "\n";
    out << "  },\n";
    out << "  \"metrics\": {\n";
    out << "    \"time_to_completion_s\": " << sc_time_stamp().to_seconds() << ",\n";
    out << "    \"cycle_proxy\": " << cycle_proxy << ",\n";
    out << "    \"host_wait_s\": null,\n";
    out << "    \"device_busy_s\": " << device_busy_s << ",\n";
    out << "    \"dma_read_bytes\": " << tlm_target->dma_read_bytes() << ",\n";
    out << "    \"dma_write_bytes\": " << tlm_target->dma_write_bytes() << ",\n";
    out << "    \"bytes_moved_to_convergence\": " << bytes_moved << ",\n";
    out << "    \"resident_reuse_ratio\": " << tlm_target->resident_reuse_ratio() << ",\n";
    out << "    \"spill_ratio\": " << tlm_target->spill_ratio() << ",\n";
    out << "    \"fallback_ratio\": " << tlm_target->fallback_ratio() << ",\n";
    out << "    \"standalone_passed\": " << (passed ? "true" : "false") << "\n";
    out << "  },\n";
    out << "  \"correctness_gate\": {\n";
    out << "    \"workload_equivalent_claim\": false,\n";
    out << "    \"domain\": " << json_string(domain) << ",\n";
    out << "    \"domain_equivalence_claim\": false\n";
    out << "  },\n";
    out << "  \"artifact_refs\": {\n";
    out << "    \"source_schema_version\": \"gem5_systemc_standalone_backend_report_v0\",\n";
    out << "    \"systemc_target\": \"Gem5TLMTarget\",\n";
    out << "    \"systemc_model\": \"DFTHybridSystemGem5\",\n";
    out << "    \"backend_dispatch\": \"local_tlm_dispatch_to_qe_band_solver_model_main_path\"\n";
    out << "  },\n";
    out << "  \"non_claims\": [\n";
    out << "    \"no_qe_equivalent_scf_claim\",\n";
    out << "    \"no_cycle_accuracy_claim\",\n";
    out << "    \"no_rtl_hls_board_or_asic_implementation_claim\",\n";
    out << "    \"no_real_gem5_bridge_claim\",\n";
    out << "    \"no_full_qe_under_gem5_claim\"\n";
    out << "  ],\n";
    out << "  \"notes\": [\n";
    out << "    \"Gem5-facing SystemC standalone target dispatch only; not a gem5 simulation run.\",\n";
    out << "    \"Report is bounded to SystemC standalone/timed-functional proxy evidence.\"\n";
    out << "  ]\n";
    out << "}\n";
    out.close();
    if (!out) {
      std::cerr << "[FAIL] unable to finish backend report path: " << report_path << std::endl;
      return false;
    }
    std::cout << "[PASS] wrote backend execution report: " << report_path << std::endl;
    return true;
  }
};

int sc_main(int argc, char* argv[]) {
  std::cout << "=== gem5-SystemC Integration Standalone Test ===" << std::endl;
  std::cout << "This test validates local TLM address-map and MMIO semantics" << std::endl;

  TestBench tb("testbench");

  std::cout << "\nSystemC modules instantiated successfully" << std::endl;
  std::cout << "Starting simulation...\n" << std::endl;

  sc_start();

  std::cout << "\nSimulation completed at " << sc_time_stamp() << std::endl;
  if (!tb.write_backend_execution_report()) {
    return 1;
  }

  return tb.passed ? 0 : 1;
}
