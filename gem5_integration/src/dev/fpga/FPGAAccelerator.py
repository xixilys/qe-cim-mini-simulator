from m5.params import *
from m5.proxy import *
from m5.objects.PciDevice import PciEndpoint, PciMemBar, PciBarNone

class FPGAAccelerator(PciEndpoint):
    type = 'FPGAAccelerator'
    cxx_header = "dev/fpga/fpga_accelerator.hh"
    cxx_class = 'gem5::FPGAAccelerator'

    VendorID = 0x10EE
    DeviceID = 0x9038
    SubsystemVendorID = 0x0000
    SubsystemID = 0x0000
    # Keep memory-space decoding enabled from reset so BAR0 is routable
    # before the guest installs a driver or touches the command register.
    Command = 0x0002
    Status = 0x0280
    Revision = 0x00
    ProgIF = 0x00
    SubClassCode = 0x00
    ClassCode = 0x12
    InterruptLine = 0x0B
    InterruptPin = 0x01

    BAR0 = PciMemBar(size='64KiB')
    BAR1 = PciBarNone()
    BAR2 = PciBarNone()
    BAR3 = PciBarNone()
    BAR4 = PciBarNone()
    BAR5 = PciBarNone()

    pio_latency = Param.Latency('1ns', "PIO latency")
