"""
gem5 + SystemC FPGA Accelerator Test Configuration

This script creates a simple gem5 system with:
- X86 CPU (TimingSimpleCPU)
- Memory system (512MB)
- FPGA accelerator device (SE mode, BasicPioDevice)
- SystemC bridge for FPGA simulation

Usage:
    gem5.opt configs/fpga_systemc_test.py
"""

import m5
from m5.objects import *

# Create the system
system = System()

# Set up clock domain
system.clk_domain = SrcClockDomain()
system.clk_domain.clock = '3GHz'
system.clk_domain.voltage_domain = VoltageDomain()

# Set up memory mode and ranges
system.mem_mode = 'timing'
system.mem_ranges = [AddrRange('512MB')]

# Create CPU
system.cpu = X86TimingSimpleCPU()

# Create memory bus
system.membus = SystemXBar()

# Create FPGA device at high address (outside main memory)
# Address: 0xF0000000 (3.75GB), Size: 4KB
system.fpga = FPGAAcceleratorSE(pio_addr=0xF0000000)

# Connect FPGA to memory bus
system.fpga.pio = system.membus.mem_side_ports

# Create memory controller
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

# Connect CPU to memory bus
system.cpu.icache_port = system.membus.cpu_side_ports
system.cpu.dcache_port = system.membus.cpu_side_ports

# Create interrupt controller (required for X86)
system.cpu.createInterruptController()

# For X86, connect interrupt ports to memory bus
system.cpu.interrupts[0].pio = system.membus.mem_side_ports
system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

# Set up system port
system.system_port = system.membus.cpu_side_ports

# Create a simple test workload
# This will write to FPGA registers and read back results
binary = '/Volumes/remote/phd/year_2/project/dft加速/gem5_integration/qe_test_program/fpga_test'

system.workload = SEWorkload.init_compatible(binary)

process = Process()
process.cmd = [binary]
system.cpu.workload = process
system.cpu.createThreads()

# Instantiate the system
root = Root(full_system=False, system=system)
m5.instantiate()

print("=" * 60)
print("gem5 + SystemC FPGA Accelerator Test")
print("=" * 60)
print(f"CPU: {system.cpu}")
print(f"Memory: {system.mem_ranges[0]}")
print(f"FPGA Device: 0x{int(system.fpga.pio_addr):X} (4KB)")
print("=" * 60)

# Run simulation
print("Starting simulation...")
exit_event = m5.simulate()

print("=" * 60)
print(f"Simulation ended: {exit_event.getCause()}")
print(f"Simulated ticks: {m5.curTick()}")
print("=" * 60)
