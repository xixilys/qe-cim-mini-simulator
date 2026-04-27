#!/usr/bin/env python3
# Simple FPGA device test configuration for gem5

import m5
from m5.objects import *
from m5.util import addToPath
import os
import sys

addToPath('../')

class SimpleFPGASystem(System):
    def __init__(self, **kwargs):
        super(SimpleFPGASystem, self).__init__(**kwargs)
        
        self.clk_domain = SrcClockDomain()
        self.clk_domain.clock = '1GHz'
        self.clk_domain.voltage_domain = VoltageDomain()
        
        self.mem_mode = 'timing'
        self.mem_ranges = [AddrRange('512MB')]
        
        self.cpu = X86TimingSimpleCPU()
        
        self.membus = SystemXBar()
        
        self.cpu.icache_port = self.membus.cpu_side_ports
        self.cpu.dcache_port = self.membus.cpu_side_ports
        
        self.cpu.createInterruptController()
        
        self.mem_ctrl = MemCtrl()
        self.mem_ctrl.dram = DDR3_1600_8x8()
        self.mem_ctrl.dram.range = self.mem_ranges[0]
        self.mem_ctrl.port = self.membus.mem_side_ports
        
        self.system_port = self.membus.cpu_side_ports
        
        self.pci_host = GenericPciHost(
            conf_base=0xC000000000000000,
            conf_size='16MB',
            conf_device_bits=12,
            pci_pio_base=0x8000000000000000)
        
        self.fpga = FPGAAccelerator(pci_bus=0, pci_dev=4, pci_func=0)
        self.fpga.pio = self.membus.mem_side_ports
        self.fpga.dma = self.membus.cpu_side_ports
        
        self.pci_host.device = self.fpga
        
        self.intrctrl = IntrControl()

def create_system():
    system = SimpleFPGASystem()
    return system

def main():
    system = create_system()
    
    root = Root(full_system=False, system=system)
    
    m5.instantiate()
    
    print("gem5 FPGA device test starting...")
    print(f"FPGA device: {system.fpga}")
    print(f"PCI config: bus={system.fpga.pci_bus}, dev={system.fpga.pci_dev}, func={system.fpga.pci_func}")
    
    exit_event = m5.simulate()
    
    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")

if __name__ == "__main__":
    main()
