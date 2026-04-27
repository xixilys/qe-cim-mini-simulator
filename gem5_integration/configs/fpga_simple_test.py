import m5
from m5.objects import *

# Create the system
system = System()

# Set up clock and voltage domain
system.clk_domain = SrcClockDomain()
system.clk_domain.clock = '1GHz'
system.clk_domain.voltage_domain = VoltageDomain()

# Set up memory
system.mem_mode = 'timing'
system.mem_ranges = [AddrRange('512MB')]

# Create CPU
system.cpu = X86TimingSimpleCPU()

# Create memory bus
system.membus = SystemXBar()

# Create FPGA device at 0xF0000000 as a simple memory-mapped device
system.fpga = FPGAAcceleratorSE()
system.fpga.pio_addr = 0xF0000000
system.fpga.pio = system.membus.mem_side_ports

# Connect CPU to memory bus
system.cpu.icache_port = system.membus.cpu_side_ports
system.cpu.dcache_port = system.membus.cpu_side_ports

# Create interrupt controller
system.cpu.createInterruptController()
system.cpu.interrupts[0].pio = system.membus.mem_side_ports
system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

# Create memory controller
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

system.system_port = system.membus.cpu_side_ports

# Set up the workload
binary = '/Volumes/remote/phd/year_2/project/dft加速/gem5_integration/qe_test_program/fpga_test_simple'
system.workload = SEWorkload.init_compatible(binary)

process = Process()
process.cmd = [binary]
system.cpu.workload = process
system.cpu.createThreads()

# Set up root and run
root = Root(full_system=False, system=system)
m5.instantiate()

print("Beginning simulation!")
exit_event = m5.simulate(10000000000)  # 10 billion ticks = 10 seconds at 1GHz

print('Exiting @ tick {} because {}'.format(m5.curTick(), exit_event.getCause()))
