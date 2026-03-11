#!/bin/bash
export SYSTEMC_HOME=/usr/local/systemc-2.3.4
make clean
make
./bin/mini_qe_cim_sim > logs/sim.log
echo "Simulation done. Checking logs:"
cat logs/sim.log
