import m5
from m5.objects import *
from m5.util import addToPath
import argparse

addToPath('../')

def create_fpga_system(args):
    system = System()
    
    system.clk_domain = SrcClockDomain()
    system.clk_domain.clock = '3GHz'
    system.clk_domain.voltage_domain = VoltageDomain()
    
    system.mem_mode = 'timing'
    system.mem_ranges = [AddrRange('8GB')]
    
    system.cpu = X86TimingSimpleCPU()
    system.cpu.createInterruptController()
    
    system.membus = SystemXBar()
    system.cpu.icache_port = system.membus.cpu_side_ports
    system.cpu.dcache_port = system.membus.cpu_side_ports
    system.cpu.interrupts[0].pio = system.membus.mem_side_ports
    system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
    system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports
    
    system.mem_ctrl = MemCtrl()
    system.mem_ctrl.dram = DDR4_2400_16x4()
    system.mem_ctrl.dram.range = system.mem_ranges[0]
    system.mem_ctrl.port = system.membus.mem_side_ports
    
    system.iobus = IOXBar()
    system.membus.mem_side_ports = system.iobus.cpu_side_ports
    
    system.fpga = FPGAAccelerator()
    system.fpga.pio = system.iobus.mem_side_ports
    system.fpga.dma = system.iobus.cpu_side_ports
    
    system.system_port = system.membus.cpu_side_ports
    
    process = Process()
    process.cmd = [args.binary] + args.options.split()
    system.cpu.workload = process
    system.cpu.createThreads()
    
    return system

if __name__ == "__m5_main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=str, required=True,
                       help="Path to binary to execute")
    parser.add_argument("--options", type=str, default="",
                       help="Options to pass to binary")
    args = parser.parse_args()
    
    system = create_fpga_system(args)
    root = Root(full_system=False, system=system)
    m5.instantiate()
    
    print("Beginning simulation!")
    exit_event = m5.simulate()
    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")
