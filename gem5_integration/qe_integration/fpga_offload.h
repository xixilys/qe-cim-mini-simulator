#ifndef FPGA_OFFLOAD_H
#define FPGA_OFFLOAD_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int fd;
    void* mmio_base;
    size_t mmio_size;
    bool initialized;
} fpga_device_t;

typedef struct {
    uint32_t n;
    uint32_t m;
    uint32_t k;
    uint64_t h_matrix_addr;
    uint64_t s_matrix_addr;
    uint64_t result_addr;
} fpga_c_bands_request_t;

int fpga_init(fpga_device_t* dev, const char* device_path);
void fpga_cleanup(fpga_device_t* dev);

int fpga_c_bands_offload(fpga_device_t* dev, 
                         const fpga_c_bands_request_t* req,
                         void* h_matrix,
                         void* s_matrix,
                         void* result_matrix);

bool fpga_is_available(void);

#ifdef __cplusplus
}
#endif

#endif
