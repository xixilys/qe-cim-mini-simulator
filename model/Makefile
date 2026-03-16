CXX = g++
CXXFLAGS = -O3 -Wall -std=c++17 -Iinclude -I/opt/homebrew/include
LDFLAGS = -L/opt/homebrew/lib -lsystemc -lm
ACCEL_LDFLAGS = -framework Accelerate
BUILD_DIR = build
OBJ_DIR = $(BUILD_DIR)/obj
ITERATIVE_CXXFLAGS = $(filter-out -O3,$(CXXFLAGS)) -O2

OZAKI_EXEC = bin/complex_ozaki_eval
GEN_SUBSPACE_EXEC = bin/generalized_subspace_eval
ITER_SUBSPACE_EXEC = bin/iterative_subspace_eval
ITER_TILE_GEMM_EXEC = bin/iterative_tile_gemm_eval
ITER_MICRO_COMPARE_EXEC = bin/iterative_micro_compare_eval
ITER_QE_REGRESSION_EXEC = bin/iterative_qe_regression_eval

all: $(OZAKI_EXEC) $(GEN_SUBSPACE_EXEC) $(ITER_SUBSPACE_EXEC) $(ITER_TILE_GEMM_EXEC) $(ITER_MICRO_COMPARE_EXEC) $(ITER_QE_REGRESSION_EXEC)

$(OZAKI_EXEC): $(OBJ_DIR)/tb_complex_ozaki.o
	mkdir -p bin
	$(CXX) $(OBJ_DIR)/tb_complex_ozaki.o -o $@ $(LDFLAGS)

$(GEN_SUBSPACE_EXEC): $(OBJ_DIR)/tb_generalized_subspace.o
	mkdir -p bin
	$(CXX) $(OBJ_DIR)/tb_generalized_subspace.o -o $@ $(LDFLAGS) $(ACCEL_LDFLAGS)

$(ITER_SUBSPACE_EXEC): $(OBJ_DIR)/tb_iterative_subspace.o $(OBJ_DIR)/iterative_subspace_engine.o
	mkdir -p bin
	$(CXX) $(OBJ_DIR)/tb_iterative_subspace.o $(OBJ_DIR)/iterative_subspace_engine.o -o $@ $(LDFLAGS)

$(ITER_TILE_GEMM_EXEC): $(OBJ_DIR)/tb_iterative_tile_gemm.o $(OBJ_DIR)/iterative_subspace_engine.o
	mkdir -p bin
	$(CXX) $(OBJ_DIR)/tb_iterative_tile_gemm.o $(OBJ_DIR)/iterative_subspace_engine.o -o $@ $(LDFLAGS)

$(ITER_MICRO_COMPARE_EXEC): $(OBJ_DIR)/tb_iterative_micro_compare.o $(OBJ_DIR)/iterative_subspace_engine.o
	mkdir -p bin
	$(CXX) $(OBJ_DIR)/tb_iterative_micro_compare.o $(OBJ_DIR)/iterative_subspace_engine.o -o $@ $(LDFLAGS) $(ACCEL_LDFLAGS)

$(ITER_QE_REGRESSION_EXEC): $(OBJ_DIR)/tb_iterative_qe_regression.o $(OBJ_DIR)/iterative_subspace_engine.o
	mkdir -p bin
	$(CXX) $(OBJ_DIR)/tb_iterative_qe_regression.o $(OBJ_DIR)/iterative_subspace_engine.o -o $@ $(LDFLAGS) $(ACCEL_LDFLAGS)

$(OBJ_DIR)/iterative_subspace_engine.o: CXXFLAGS := $(ITERATIVE_CXXFLAGS)
$(OBJ_DIR)/tb_iterative_subspace.o: CXXFLAGS := $(ITERATIVE_CXXFLAGS)
$(OBJ_DIR)/tb_iterative_tile_gemm.o: CXXFLAGS := $(ITERATIVE_CXXFLAGS)
$(OBJ_DIR)/tb_iterative_micro_compare.o: CXXFLAGS := $(ITERATIVE_CXXFLAGS)
$(OBJ_DIR)/tb_iterative_qe_regression.o: CXXFLAGS := $(ITERATIVE_CXXFLAGS)

$(OBJ_DIR)/%.o: src/%.cpp
	mkdir -p $(OBJ_DIR)
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -rf $(OBJ_DIR) $(OZAKI_EXEC) $(GEN_SUBSPACE_EXEC) $(ITER_SUBSPACE_EXEC) $(ITER_TILE_GEMM_EXEC) $(ITER_MICRO_COMPARE_EXEC) $(ITER_QE_REGRESSION_EXEC) logs/*.log
