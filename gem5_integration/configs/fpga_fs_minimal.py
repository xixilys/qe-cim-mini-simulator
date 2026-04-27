import m5
from m5.objects import *
import os

IO_ADDRESS_SPACE_BASE = 0x8000000000000000
PCI_CONFIG_ADDRESS_SPACE_BASE = 0xC000000000000000
INTERRUPTS_ADDRESS_SPACE_BASE = 0xA000000000000000
APIC_RANGE_SIZE = 1 << 12

# System configuration
system = System()
system.m5ops_base = 0xFFFF0000
cpu_type = os.environ.get('GEM5_CPU_TYPE', 'timing').lower()
default_mem_mode = 'atomic' if cpu_type == 'atomic' else 'timing'
system.clk_domain = SrcClockDomain()
system.clk_domain.clock = os.environ.get('GEM5_CPU_CLOCK', '1GHz')
system.clk_domain.voltage_domain = VoltageDomain()

# Memory configuration
system.mem_mode = os.environ.get('GEM5_MEM_MODE', default_mem_mode)
system.mem_ranges = [AddrRange('512MB')]

# Kernel and initramfs paths
home = os.path.expanduser("~")
kernel_path = f'{home}/.cache/gem5/x86-linux-kernel-6.8.0-52-generic-1.0.0'
script_dir = os.path.dirname(os.path.abspath(__file__))
initramfs_path = os.path.join(script_dir, '..', 'minimal_rootfs', 'initramfs.cpio.gz')
max_ticks = int(os.environ.get('GEM5_MAX_TICKS', '1000000000000'))

# Workload setup
system.workload = X86FsLinux()
system.workload.object_file = kernel_path
system.workload.initrd_filename = initramfs_path
system.workload.initrd_addr = 0x10000000

# CPU configuration
if cpu_type == 'atomic':
    system.cpu = AtomicSimpleCPU()
elif cpu_type == 'timing':
    system.cpu = X86TimingSimpleCPU()
else:
    raise ValueError(f'Unsupported GEM5_CPU_TYPE: {cpu_type}')
system.cpu.createThreads()

# Memory bus
system.membus = IOXBar()
system.iobus = IOXBar()

# FPGA device
system.fpga = FPGAAcceleratorSE()
system.fpga.pio_addr = 0xF0000000
system.fpga.pio_latency = '1ns'

# Bridge for IO devices
system.bridge = Bridge(delay='50ns')
system.bridge.mem_side_port = system.iobus.cpu_side_ports
system.bridge.cpu_side_port = system.membus.mem_side_ports
system.bridge.ranges = [
    AddrRange(0xC0000000, 0xFFFF0000),
    AddrRange(IO_ADDRESS_SPACE_BASE, INTERRUPTS_ADDRESS_SPACE_BASE - 1),
    AddrRange(PCI_CONFIG_ADDRESS_SPACE_BASE, Addr.max),
]

system.apicbridge = Bridge(delay='50ns')
system.apicbridge.cpu_side_port = system.iobus.mem_side_ports
system.apicbridge.mem_side_port = system.membus.cpu_side_ports
system.apicbridge.ranges = [
    AddrRange(
        INTERRUPTS_ADDRESS_SPACE_BASE,
        INTERRUPTS_ADDRESS_SPACE_BASE + APIC_RANGE_SIZE - 1,
    )
]

# PC platform
system.pc = Pc()
system.pc.pci_bus.frontend_latency = 0
system.pc.pci_bus.forward_latency = 0
system.pc.pci_bus.response_latency = 0
system.pc.attachIO(system.iobus)

system.fpga.pio = system.iobus.mem_side_ports

# Memory controller
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

# CPU connections
system.cpu.createInterruptController()
system.cpu.interrupts[0].pio = system.membus.mem_side_ports
system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports
system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports

system.cpu.icache_port = system.membus.cpu_side_ports
system.cpu.dcache_port = system.membus.cpu_side_ports

# Connect MMU page table walkers (both to cpu_side_ports)
system.cpu.mmu.connectWalkerPorts(
    system.membus.cpu_side_ports, system.membus.cpu_side_ports
)

# System port
system.system_port = system.membus.cpu_side_ports

# E820 memory map
mem_size = system.mem_ranges[0].size()
entries = [
    X86E820Entry(addr=0, size="639KiB", range_type=1),
    X86E820Entry(addr=0x9FC00, size="385KiB", range_type=2),
    X86E820Entry(addr=0x100000, size="%dB" % (mem_size - 0x100000), range_type=1),
]
if mem_size < 0xC0000000:
    entries.append(
        X86E820Entry(addr=mem_size, size="%dB" % (0xC0000000 - mem_size), range_type=2)
    )
entries.append(X86E820Entry(addr=0xFFFF0000, size="64KiB", range_type=2))
system.workload.e820_table.entries = entries

system.workload.smbios_table.structures = [X86SMBiosBiosInformation()]

base_entries = []
ext_entries = []
madt_records = []

bp = X86IntelMPProcessor(
    local_apic_id=0,
    local_apic_version=0x14,
    enable=True,
    bootstrap=True,
)
base_entries.append(bp)
madt_records.append(X86ACPIMadtLAPIC(acpi_processor_id=0, apic_id=0, flags=1))

io_apic = X86IntelMPIOAPIC(
    id=1,
    version=0x11,
    enable=True,
    address=0xFEC00000,
)
system.pc.south_bridge.io_apic.apic_id = io_apic.id
base_entries.append(io_apic)
madt_records.append(
    X86ACPIMadtIOAPIC(id=io_apic.id, address=io_apic.address, int_base=0)
)

pci_bus = X86IntelMPBus(bus_id=0, bus_type='PCI   ')
isa_bus = X86IntelMPBus(bus_id=1, bus_type='ISA   ')
base_entries.extend([pci_bus, isa_bus])
ext_entries.append(
    X86IntelMPBusHierarchy(bus_id=1, subtractive_decode=True, parent_bus=0)
)

pci_dev4_inta = X86IntelMPIOIntAssignment(
    interrupt_type='INT',
    polarity='ConformPolarity',
    trigger='ConformTrigger',
    source_bus_id=0,
    source_bus_irq=0 + (4 << 2),
    dest_io_apic_id=io_apic.id,
    dest_io_apic_intin=16,
)
base_entries.append(pci_dev4_inta)
madt_records.append(
    X86ACPIMadtIntSourceOverride(
        bus_source=pci_dev4_inta.source_bus_id,
        irq_source=pci_dev4_inta.source_bus_irq,
        sys_int=pci_dev4_inta.dest_io_apic_intin,
        flags=0,
    )
)

def assign_isa_int(irq, apic_pin):
    base_entries.append(
        X86IntelMPIOIntAssignment(
            interrupt_type='ExtInt',
            polarity='ConformPolarity',
            trigger='ConformTrigger',
            source_bus_id=1,
            source_bus_irq=irq,
            dest_io_apic_id=io_apic.id,
            dest_io_apic_intin=0,
        )
    )
    base_entries.append(
        X86IntelMPIOIntAssignment(
            interrupt_type='INT',
            polarity='ConformPolarity',
            trigger='ConformTrigger',
            source_bus_id=1,
            source_bus_irq=irq,
            dest_io_apic_id=io_apic.id,
            dest_io_apic_intin=apic_pin,
        )
    )
    madt_records.append(
        X86ACPIMadtIntSourceOverride(
            bus_source=1,
            irq_source=irq,
            sys_int=apic_pin,
            flags=0,
        )
    )

assign_isa_int(0, 2)
assign_isa_int(1, 1)
for irq in range(3, 15):
    assign_isa_int(irq, irq)

system.workload.intel_mp_table.base_entries = base_entries
system.workload.intel_mp_table.ext_entries = ext_entries

madt = X86ACPIMadt(local_apic_address=0, records=madt_records, oem_id='madt')
system.workload.acpi_description_table_pointer.rsdt.entries.append(madt)
system.workload.acpi_description_table_pointer.xsdt.entries.append(madt)
system.workload.acpi_description_table_pointer.oem_id = 'gem5'
system.workload.acpi_description_table_pointer.rsdt.oem_id = 'gem5'
system.workload.acpi_description_table_pointer.xsdt.oem_id = 'gem5'

# Boot command
system.workload.command_line = (
    'earlyprintk=ttyS0 console=ttyS0 ignore_loglevel '
    'root=/dev/ram0 rdinit=/init'
)

# Root
root = Root(full_system=True, system=system)
m5.instantiate()

print("=" * 60)
print("gem5 FS Mode - FPGA Device Test")
print("=" * 60)
print(f"FPGA: 0x{int(system.fpga.pio_addr):X}")
print(f"Kernel: {os.path.basename(kernel_path)}")
print(f"Initramfs: {os.path.basename(initramfs_path)}")
print(f"CPU type: {cpu_type}")
print(f"CPU clock: {system.clk_domain.clock}")
print(f"Memory mode: {system.mem_mode}")
print(f"Max ticks: {max_ticks}")
print("=" * 60)

exit_event = m5.simulate(max_ticks)
print(f"\nExit @ tick {m5.curTick()}: {exit_event.getCause()}")
