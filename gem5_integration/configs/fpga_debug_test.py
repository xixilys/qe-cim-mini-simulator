"""
gem5 + SystemC FPGA Accelerator Test with Debug Output

This configuration enables FPGA debug flags to show register accesses.

Usage:
    gem5.opt --debug-flags=FPGAAccel configs/fpga_debug_test.py
"""

import m5
from m5.objects import *

system = System()

system.clk_domain = SrcClockDomain()
system.clk_domain.clock = '3GHz'
system.clk_domain.voltage_domain = VoltageDomain()

system.mem_mode = 'timing'
system.mem_ranges = [AddrRange('512MB')]

system.cpu = X86TimingSimpleCPU()

system.membus = SystemXBar()

system.fpga = FPGAAcceleratorSE(pio_addr=0xF0000000)

system.fpga.pio = system.membus.mem_side_ports

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

system.cpu.icache_port = system.membus.cpu_side_ports
system.cpu.dcache_port = system.membus.cpu_side_ports

system.cpu.createInterruptController()

system.cpu.interrupts[0].pio = system.membus.mem_side_ports
system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

system.system_port = system.membus.cpu_side_ports

binary = '/Volumes/remote/phd/year_2/project/dft加速/gem5_integration/gem5/tests/test-progs/hello/bin/x86/linux/hello'

system.workload = SEWorkload.init_compatible(binary)

process = Process()
process.cmd = [binary]
system.cpu.workload = process
system.cpu.createThreads()

root = Root(full_system=False, system=system)
m5.instantiate()

print("=" * 60)
print("gem5 + SystemC FPGA Accelerator Debug Test")
print("=" * 60)
print(f"FPGA Device: 0x{int(system.fpga.pio_addr):X}")
print("Run with: --debug-flags=FPGAAccel to see register accesses")
print("=" * 60)

print("Starting simulation...")
exit_event = m5.simulate()

print("=" * 60)
print(f"Simulation ended: {exit_event.getCause()}")
print(f"Simulated ticks: {m5.curTick()}")
print("=" * 60)
