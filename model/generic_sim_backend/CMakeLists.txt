cmake_minimum_required(VERSION 3.16)
project(GenericSimBackend VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Options
option(GSIM_BUILD_TESTS "Build tests" ON)
option(GSIM_USE_SYSTEMC "Enable SystemC integration" OFF)

# Find SystemC if enabled
if(GSIM_USE_SYSTEMC)
    find_package(SystemC REQUIRED)
    if(SystemC_FOUND)
        include_directories(${SystemC_INCLUDE_DIRS})
        link_libraries(${SystemC_LIBRARIES})
        add_definitions(-DGSIM_USE_SYSTEMC)
    endif()
endif()

# Include directories
include_directories(${CMAKE_SOURCE_DIR}/include)
include_directories(${CMAKE_SOURCE_DIR}/include/microarchitecture)

# Source files
set(GSIM_SOURCES
    src/main.cpp
    src/json_parser.cpp
    src/graph_executor.cpp
    src/op_model_registry.cpp
)

# Main executable
add_executable(generic_sim
    ${GSIM_SOURCES}
)

# Tests
if(GSIM_BUILD_TESTS)
    enable_testing()
    add_executable(test_microarchitecture_simulators
        tests/test_microarchitecture_simulators.cpp
    )
    target_include_directories(test_microarchitecture_simulators PRIVATE
        ${CMAKE_SOURCE_DIR}/include
    )
    add_test(NAME microarchitecture_simulators COMMAND test_microarchitecture_simulators)

    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    add_test(
        NAME python_reference_model_contract
        COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_python_reference_model.py
    )
    set_tests_properties(
        python_reference_model_contract
        PROPERTIES WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
endif()

# Install
install(TARGETS generic_sim DESTINATION bin)
install(DIRECTORY schemas DESTINATION share/generic_sim)
