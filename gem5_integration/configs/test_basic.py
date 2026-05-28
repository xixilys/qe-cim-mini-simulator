"""Basic gem5 smoke config.

The file name is intentionally historical, but it is a gem5 configuration
script rather than a pytest module.  Keep gem5 imports and simulation side
effects inside ``main`` so repository-wide pytest collection can import the
file on hosts that do not have gem5's ``m5`` Python module on ``PYTHONPATH``.
"""


def main():
    import m5
    from m5.objects import (
        AddrRange,
        DDR3_1600_8x8,
        MemCtrl,
        Process,
        Root,
        SrcClockDomain,
        System,
        SystemXBar,
        VoltageDomain,
        X86TimingSimpleCPU,
    )

    system = System()
    system.clk_domain = SrcClockDomain()
    system.clk_domain.clock = "1GHz"
    system.clk_domain.voltage_domain = VoltageDomain()
    system.mem_mode = "timing"
    system.mem_ranges = [AddrRange("512MB")]

    system.cpu = X86TimingSimpleCPU()
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

    binary = "../test_programs/hello.x86"
    process = Process()
    process.cmd = [binary]
    system.cpu.workload = process
    system.cpu.createThreads()

    root = Root(full_system=False, system=system)
    m5.instantiate()
    print("Running basic gem5 test...")
    exit_event = m5.simulate()
    print(f"Exiting @ tick {m5.curTick()} because {exit_event.getCause()}")


if __name__ in {"__main__", "__m5_main__"}:
    main()
