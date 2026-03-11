CXX = g++
CXXFLAGS = -O3 -Wall -std=c++17 -I/opt/homebrew/include
LDFLAGS = -L/opt/homebrew/lib -lsystemc -lm

SRC = src/fft_engine.cpp src/cim_macro.cpp src/fpga_controller.cpp src/tb_mini_qe.cpp
OBJ = $(SRC:.cpp=.o)
EXEC = bin/mini_qe_cim_sim
SOCK_EXEC = bin/cim_socket_server
SUBSPACE_EXEC = bin/complex_subspace_eval

all: $(EXEC) $(SOCK_EXEC) $(SUBSPACE_EXEC)

$(EXEC): $(OBJ)
	mkdir -p bin
	$(CXX) $(OBJ) -o $@ $(LDFLAGS)

$(SOCK_EXEC): src/cim_socket_server.o
	mkdir -p bin
	$(CXX) src/cim_socket_server.o src/cim_macro.o src/fft_engine.o -o $@ $(LDFLAGS)

$(SUBSPACE_EXEC): src/tb_complex_subspace.o src/cim_macro.o
	mkdir -p bin
	$(CXX) src/tb_complex_subspace.o src/cim_macro.o -o $@ $(LDFLAGS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f src/*.o $(EXEC) $(SOCK_EXEC) $(SUBSPACE_EXEC) logs/*.log

run: $(EXEC)
	mkdir -p logs
	./$(EXEC) > logs/sim.log
