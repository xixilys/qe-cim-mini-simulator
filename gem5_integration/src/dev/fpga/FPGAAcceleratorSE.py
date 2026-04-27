from m5.params import *
from m5.proxy import *
from m5.objects.Device import BasicPioDevice

class FPGAAcceleratorSE(BasicPioDevice):
    type = 'FPGAAcceleratorSE'
    cxx_header = "dev/fpga/fpga_accelerator_se.hh"
    cxx_class = 'gem5::FPGAAcceleratorSE'
