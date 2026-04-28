cmake_minimum_required(VERSION 3.10)
project(gem5_systemc_integration)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(SYSTEMC_HOME $ENV{SYSTEMC_HOME})
if(NOT SYSTEMC_HOME)
  set(SYSTEMC_HOME "/opt/homebrew")
endif()

include_directories(
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${SYSTEMC_HOME}/include
)

link_directories(
  ${SYSTEMC_HOME}/lib
)

set(QE_BAND_SOLVER_MODEL_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../model/qe_band_solver_model")

include_directories(
  ${QE_BAND_SOLVER_MODEL_DIR}/include
  ${QE_BAND_SOLVER_MODEL_DIR}/include/clusters
  ${QE_BAND_SOLVER_MODEL_DIR}/include/onchip
)

set(QE_BAND_SOLVER_SOURCES
  ${QE_BAND_SOLVER_MODEL_DIR}/src/architecture_template.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/architecture_config.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/interconnect.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/host_scf.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/fpga_orchestrator.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/dft_hybrid_system.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/chip_top.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/clusters/cluster_graph_executor.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/clusters/episode_controller.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/clusters/cluster_factory.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/clusters/cluster_wrapper.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/clusters/cluster_a_operator_sweep.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/clusters/cluster_b_reduced_build.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/clusters/cluster_c_hardware_diag.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/clusters/cluster_d_refresh_residual.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/cim_array_core.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/cim_eligible_operator_subchain.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/fft_companion.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/near_memory_domain.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/reduction_closure_engine.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/vector_diag_companion.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/near_sram_coeff_buffer.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/near_sram_row_buffer.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/near_sram_support.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/resident_context_controller.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/context_loader.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/command_scheduler.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/digit_serial_input_boundary.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/conjugate_sign_selector.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/residue_3m_core.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/coefficient_accumulator.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/row_merge_tree.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/traditional_fpga_gemm_core.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/blocked_gemm_engine.cpp
  ${QE_BAND_SOLVER_MODEL_DIR}/src/onchip/compute_unit_factory.cpp
)

set(SOURCES
  src/gem5_tlm_target.cpp
  src/gem5_bridge.cpp
  src/dft_hybrid_system_gem5.cpp
  ${QE_BAND_SOLVER_SOURCES}
)

add_library(gem5_systemc_bridge STATIC ${SOURCES})

target_compile_definitions(gem5_systemc_bridge PRIVATE
  QE_BAND_SOLVER_USE_SYSTEMC=1
)

target_link_libraries(gem5_systemc_bridge
  systemc
)

add_executable(gem5_systemc_standalone
  src/standalone_test.cpp
  src/gem5_tlm_target.cpp
  src/dft_hybrid_system_gem5.cpp
  src/gem5_bridge.cpp
  ${QE_BAND_SOLVER_SOURCES}
)

target_compile_definitions(gem5_systemc_standalone PRIVATE
  QE_BAND_SOLVER_USE_SYSTEMC=1
)

target_link_libraries(gem5_systemc_standalone
  systemc
)

install(TARGETS gem5_systemc_bridge gem5_systemc_standalone
  LIBRARY DESTINATION lib
  ARCHIVE DESTINATION lib
  RUNTIME DESTINATION bin
)
