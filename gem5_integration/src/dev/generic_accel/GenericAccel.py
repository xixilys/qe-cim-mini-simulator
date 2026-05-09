# Generic Accelerator Device Model for gem5

from m5.params import *
from m5.proxy import *
from m5.objects.Device import BasicPioDevice

class GenericAccel(BasicPioDevice):
    type = 'GenericAccel'
    cxx_header = 'dev/generic_accel/generic_accel.hh'
    cxx_class = 'gem5::GenericAccel'

    pio_addr = Param.Addr(0x10000000, "MMIO base address")
    pio_size = Param.Addr(0x10000, "MMIO region size")
    
    dma_buffer_size = Param.MemorySize('16MB', "DMA buffer size")
    cmd_queue_size = Param.Int(64, "Command queue depth")
    
    clock_mhz = Param.Float(250.0, "Accelerator clock frequency")
    peak_gops = Param.Float(1000.0, "Peak performance in GOPS")
    
    # Power parameters
    static_power = Param.Float(10.0, "Static power in Watts")
    dynamic_power = Param.Float(50.0, "Dynamic power in Watts")
    
    # Capabilities
    supports_gemm = Param.Bool(True, "Support GEMM operations")
    supports_fft = Param.Bool(False, "Support FFT operations")
    supports_eigen = Param.Bool(False, "Support eigenvalue operations")
    
    # Interrupt
    int_num = Param.Int(0, "Interrupt number")
    
    # SystemC bridge (optional)
    use_systemc = Param.Bool(False, "Enable SystemC co-simulation")
    systemc_lib_path = Param.String("", "Path to SystemC bridge library")
