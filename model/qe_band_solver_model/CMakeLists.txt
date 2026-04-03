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
  src/episode_controller.cpp
  src/cluster_graph_executor.cpp
  src/cluster_a_operator_sweep.cpp
  src/cluster_b_reduced_build.cpp
  src/cluster_c_hardware_diag.cpp
  src/cluster_d_refresh_residual.cpp
  src/replay_bundle_executor.cpp
  src/body04_family_controller.cpp
  src/outer_update_runtime_domain.cpp
  src/body10_family_controller.cpp
  src/preconditioned_update_vector.cpp
  src/wave_candidate_commit.cpp
  src/orthogonalize_unit.cpp
  src/rebind_commit.cpp
  src/history_integrator.cpp
  src/ot_summary_commit.cpp
  src/chip_top.cpp
  src/density_accumulation_stage.cpp
  src/density_accumulator_unit.cpp
  src/density_commit_unit.cpp
  src/potential_refresh_stage.cpp
  src/potential_field_unit.cpp
  src/projector_state_updater.cpp
  src/mixing_convergence_stage.cpp
  src/density_mixer_unit.cpp
  src/convergence_tracker.cpp
  src/command_scheduler.cpp
  src/resident_context_controller.cpp
  src/context_loader.cpp
  src/digit_serial_input_boundary.cpp
  src/conjugate_sign_selector.cpp
  src/residue_3m_core.cpp
  src/coefficient_accumulator.cpp
  src/row_merge_tree.cpp
  src/near_sram_coeff_buffer.cpp
  src/near_sram_row_buffer.cpp
  src/cim_array_core.cpp
  src/cim_eligible_operator_subchain.cpp
  src/near_sram_support.cpp
  src/near_memory_domain.cpp
  src/reduction_closure_engine.cpp
  src/vector_diag_companion.cpp
  src/fft_companion.cpp
)

target_include_directories(qe_band_solver_model PRIVATE src)

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
