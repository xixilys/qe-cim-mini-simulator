#!/usr/bin/env python3
# Simple FPGA device test configuration for gem5

import m5
from m5.objects import *
from m5.objects.X86CPU import X86TimingSimpleCPU
from m5.util import addToPath
import os
import sys

addToPath('../')


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.lower() in ("1", "true", "yes", "on")

class SimpleFPGASystem(System):
    def __init__(self, execution_mode="smoke", real_systemc_target=False,
                 roi_stats_enabled=True, roi_label="qebs_offload",
                 binary="/bin/true", **kwargs):
        super(SimpleFPGASystem, self).__init__(**kwargs)
        
        self.clk_domain = SrcClockDomain()
        self.clk_domain.clock = '1GHz'
        self.clk_domain.voltage_domain = VoltageDomain()
        
        self.mem_mode = 'timing'
        self.mem_ranges = [AddrRange('512MB')]
        self.platform = Pc()
        
        self.cpu = X86TimingSimpleCPU()
        self.cpu.isa = [X86ISA()]
        
        self.membus = SystemXBar()
        
        self.cpu.icache_port = self.membus.cpu_side_ports
        self.cpu.dcache_port = self.membus.cpu_side_ports
        
        self.cpu.createInterruptController()
        self.cpu.interrupts[0].pio = self.membus.mem_side_ports
        self.cpu.interrupts[0].int_requestor = self.membus.cpu_side_ports
        self.cpu.interrupts[0].int_responder = self.membus.mem_side_ports
        
        self.mem_ctrl = MemCtrl()
        self.mem_ctrl.dram = DDR3_1600_8x8()
        self.mem_ctrl.dram.range = self.mem_ranges[0]
        self.mem_ctrl.port = self.membus.mem_side_ports

        self.iobus = IOXBar()
        self.bridge = Bridge(delay="50ns")
        self.bridge.cpu_side_port = self.membus.mem_side_ports
        self.bridge.mem_side_port = self.iobus.cpu_side_ports
        self.bridge.ranges = [
            AddrRange(0x8000000000000000, 0x9FFFFFFFFFFFFFFF),
            AddrRange(0xC000000000000000, Addr.max),
        ]
        self.apicbridge = Bridge(delay="50ns")
        self.apicbridge.cpu_side_port = self.iobus.mem_side_ports
        self.apicbridge.mem_side_port = self.membus.cpu_side_ports
        self.apicbridge.ranges = [
            AddrRange(0xA000000000000000, 0xA000000000000FFF),
        ]
        
        self.system_port = self.membus.cpu_side_ports
        self.workload = SEWorkload.init_compatible(binary)
        
        self.platform.attachIO(self.iobus)
        
        self.fpga = FPGAAccelerator(
            pci_dev=5,
            pci_func=0,
            execution_mode=execution_mode,
            real_systemc_target=real_systemc_target,
            roi_stats_enabled=roi_stats_enabled,
            roi_label=roi_label,
        )
        self.fpga.upstream = self.platform.pci_host
        self.platform.attachPciDevice(self.fpga)

        process = Process()
        process.cmd = [binary]
        self.cpu.workload = process
        self.cpu.createThreads()

def create_system(args=None):
    if args is None:
        class _DefaultArgs:
            fpga_execution_mode = "smoke"
            real_systemc_target = False
            disable_roi_stats = False
            roi_label = "qebs_offload"
            binary = os.environ.get("QEBS_SIMPLE_BINARY", "/bin/true")
        args = _DefaultArgs()
    system = SimpleFPGASystem(
        execution_mode=args.fpga_execution_mode,
        real_systemc_target=args.real_systemc_target,
        roi_stats_enabled=not args.disable_roi_stats,
        roi_label=args.roi_label,
        binary=args.binary,
    )
    return system

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fpga-execution-mode",
        choices=["smoke", "timed_proxy", "real_bridge"],
        default=os.environ.get("QEBS_FPGA_EXECUTION_MODE", "smoke"),
        help="B3 uses smoke; B4 uses timed_proxy unless an explicit real bridge is available",
    )
    parser.add_argument("--real-systemc-target", action="store_true")
    parser.set_defaults(real_systemc_target=env_flag("QEBS_REAL_SYSTEMC_TARGET", False))
    parser.add_argument("--disable-roi-stats", action="store_true")
    parser.add_argument("--roi-label", default=os.environ.get("QEBS_ROI_LABEL", "qebs_offload"))
    parser.add_argument("--binary", default=os.environ.get("QEBS_SIMPLE_BINARY", "/bin/true"))
    parser.add_argument("--max-ticks", type=int, default=0)
    args = parser.parse_args()

    system = create_system(args)
    
    root = Root(full_system=False, system=system)
    
    m5.instantiate()
    
    print("gem5 FPGA device test starting...")
    print(f"FPGA device: {system.fpga}")
    print(f"PCI config: dev={system.fpga.pci_dev}, func={system.fpga.pci_func}")
    
    exit_event = m5.simulate(args.max_ticks) if args.max_ticks > 0 else m5.simulate()
    
    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")

if __name__ == "__m5_main__":
    main()
