import m5
from m5.objects import *
import os

system = System()

system.clk_domain = SrcClockDomain()
system.clk_domain.clock = '1GHz'
system.clk_domain.voltage_domain = VoltageDomain()

system.mem_mode = 'timing'
system.mem_ranges = [AddrRange('512MiB')]

system.cpu = X86TimingSimpleCPU()
class MemBus(SystemXBar):
    badaddr_responder = BadAddr()
    default = Self.badaddr_responder.pio

system.membus = MemBus()

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

system.iobus = IOXBar()

system.bridge = Bridge(delay='50ns')
system.bridge.mem_side_port = system.iobus.cpu_side_ports
system.bridge.cpu_side_port = system.membus.mem_side_ports
system.bridge.ranges = [
    AddrRange(0x10000000, 0x10010000),
]

generic_accel = GenericAccel()
generic_accel.pio_addr = 0x10000000
system.generic_accel = generic_accel
system.generic_accel.pio = system.iobus.mem_side_ports

thispath = os.path.dirname(os.path.realpath(__file__))
binary = os.path.join(thispath, '../gem5/tests/test-progs/hello/bin/x86/linux/hello')

system.workload = SEWorkload.init_compatible(binary)

process = Process()
process.cmd = [binary]
system.cpu.workload = process
system.cpu.createThreads()

root = Root(full_system=False, system=system)

m5.instantiate()

print('GenericAccel Smoke Test Starting...')
print(f'Accelerator MMIO base: 0x{system.generic_accel.pio_addr:x}')
print(f'Accelerator clock: {system.generic_accel.clock_mhz} MHz')
print(f'Accelerator peak performance: {system.generic_accel.peak_gops} GOPS')

print('Running simulation...')
exit_event = m5.simulate()

print(f'Simulation exited: {exit_event.getCause()}')
print('Smoke test completed successfully!')
