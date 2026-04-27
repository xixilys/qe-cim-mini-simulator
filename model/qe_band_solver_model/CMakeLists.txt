cmake_minimum_required(VERSION 3.20)
project(qe_band_solver_model LANGUAGES CXX)

option(QE_BAND_SOLVER_USE_SYSTEMC "Build against a real SystemC installation" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(qe_band_solver_model
  sc_main.cpp
  src/interconnect.cpp
  src/host_scf.cpp
  src/dft_hybrid_system.cpp
  src/fpga_orchestrator.cpp
  src/architecture_template.cpp
  src/architecture_config.cpp
  src/clusters/episode_controller.cpp
  src/clusters/cluster_graph_executor.cpp
  src/clusters/cluster_factory.cpp
  src/clusters/cluster_wrapper.cpp
  src/clusters/cluster_a_operator_sweep.cpp
  src/clusters/cluster_b_reduced_build.cpp
  src/clusters/cluster_c_hardware_diag.cpp
  src/clusters/cluster_d_refresh_residual.cpp
  src/chip_top.cpp
  src/onchip/command_scheduler.cpp
  src/onchip/resident_context_controller.cpp
  src/onchip/context_loader.cpp
  src/onchip/digit_serial_input_boundary.cpp
  src/onchip/conjugate_sign_selector.cpp
  src/onchip/residue_3m_core.cpp
  src/onchip/coefficient_accumulator.cpp
  src/onchip/row_merge_tree.cpp
  src/onchip/near_sram_coeff_buffer.cpp
  src/onchip/near_sram_row_buffer.cpp
  src/onchip/cim_array_core.cpp
  src/onchip/cim_eligible_operator_subchain.cpp
  src/onchip/blocked_gemm_engine.cpp
  src/onchip/traditional_fpga_gemm_core.cpp
  src/onchip/near_sram_support.cpp
  src/onchip/near_memory_domain.cpp
  src/onchip/reduction_closure_engine.cpp
  src/onchip/vector_diag_companion.cpp
  src/onchip/fft_companion.cpp
)

target_include_directories(qe_band_solver_model PRIVATE
  include
  include/clusters
  include/onchip
  src
)

target_compile_definitions(qe_band_solver_model PRIVATE
  $<$<BOOL:${QE_BAND_SOLVER_USE_SYSTEMC}>:QE_BAND_SOLVER_USE_SYSTEMC=1>
)

if(QE_BAND_SOLVER_USE_SYSTEMC)
  if(NOT DEFINED SYSTEMC_HOME)
    message(FATAL_ERROR "QE_BAND_SOLVER_USE_SYSTEMC=ON requires -DSYSTEMC_HOME=<path>")
  endif()
  target_include_directories(qe_band_solver_model PRIVATE ${SYSTEMC_HOME}/include)
  target_link_directories(qe_band_solver_model PRIVATE ${SYSTEMC_HOME}/lib)
  target_link_libraries(qe_band_solver_model PRIVATE systemc)
endif()
