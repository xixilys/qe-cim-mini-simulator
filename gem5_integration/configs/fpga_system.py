import m5
from m5.objects import *

system = System()
system.clk_domain = SrcClockDomain(clock='3GHz', voltage_domain=VoltageDomain())
system.mem_mode = 'timing'
system.mem_ranges = [AddrRange('512MB')]

binary = 'tests/test-progs/hello/bin/x86/linux/hello'

system.cpu = X86TimingSimpleCPU()

process = Process()
process.cmd = [binary]
system.cpu.workload = process
system.cpu.createThreads()

system.workload = SEWorkload.init_compatible(binary)

system.membus = SystemXBar()

system.cpu.icache_port = system.membus.cpu_side_ports
system.cpu.dcache_port = system.membus.cpu_side_ports

system.cpu.createInterruptController()
system.cpu.interrupts[0].pio = system.membus.mem_side_ports
system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

system.system_port = system.membus.cpu_side_ports

# Add FPGA device as memory-mapped device (SE mode)
system.fpga = FPGAAcceleratorSE(pio_addr=0xF0000000, pio_latency='10ns')
system.fpga.pio = system.membus.mem_side_ports

print("System configuration created successfully!")
print("FPGA device added at address 0xF0000000")

root = Root(full_system=False, system=system)

m5.instantiate()

print("=" * 60)
print("gem5 System Configuration")
print("=" * 60)
print(f"CPU: {system.cpu.type}")
print(f"Clock: {system.clk_domain.clock}")
print(f"Memory: {system.mem_ranges[0]}")
print(f"FPGA: {system.fpga.type} @ 0xC0000000")
print("=" * 60)
print("\nStarting simulation...")

exit_event = m5.simulate()

print(f"\nSimulation ended: {exit_event.getCause()}")
print(f"Simulated ticks: {m5.curTick()}")
print(f"Simulated time: {m5.curTick() / 1e12:.6f} seconds")
