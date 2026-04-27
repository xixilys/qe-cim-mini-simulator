# Makefile for QE-FPGA integration

CC = gcc
FC = gfortran
CFLAGS = -O2 -Wall -fPIC
FFLAGS = -O2 -Wall -fPIC
LDFLAGS = -shared

LIBNAME = libfpga_offload.so

C_SOURCES = fpga_offload.c
F_SOURCES = fpga_offload_module.f90

C_OBJECTS = $(C_SOURCES:.c=.o)
F_OBJECTS = $(F_SOURCES:.f90=.o)

all: $(LIBNAME)

$(LIBNAME): $(C_OBJECTS) $(F_OBJECTS)
	$(FC) $(LDFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

%.o: %.f90
	$(FC) $(FFLAGS) -c $< -o $@

clean:
	rm -f $(C_OBJECTS) $(F_OBJECTS) $(LIBNAME) *.mod

install: $(LIBNAME)
	cp $(LIBNAME) $(QE_DIR)/lib/
	cp fpga_offload.h $(QE_DIR)/include/
	cp *.mod $(QE_DIR)/include/

.PHONY: all clean install
