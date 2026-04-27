#include "fpga_offload.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <errno.h>

#define FPGA_DEVICE_PATH "/dev/fpga0"
#define MMIO_SIZE (64 * 1024)

#define REG_CONTROL       0x0000
#define REG_STATUS        0x0004
#define REG_DMA_SRC_LO    0x0010
#define REG_DMA_SRC_HI    0x0014
#define REG_DMA_DST_LO    0x0018
#define REG_DMA_DST_HI    0x001C
#define REG_DMA_SIZE      0x0020
#define REG_DMA_CONTROL   0x0024
#define REG_MATRIX_N      0x0030
#define REG_MATRIX_M      0x0034
#define REG_MATRIX_K      0x0038
#define REG_COMPUTE_CMD   0x0040
#define REG_COMPUTE_STATUS 0x0044

static inline void write_reg(fpga_device_t* dev, uint32_t offset, uint32_t value) {
    volatile uint32_t* reg = (volatile uint32_t*)((char*)dev->mmio_base + offset);
    *reg = value;
}

static inline uint32_t read_reg(fpga_device_t* dev, uint32_t offset) {
    volatile uint32_t* reg = (volatile uint32_t*)((char*)dev->mmio_base + offset);
    return *reg;
}

int fpga_init(fpga_device_t* dev, const char* device_path) {
    if (!dev) return -1;
    
    memset(dev, 0, sizeof(fpga_device_t));
    
    if (!device_path) {
        device_path = FPGA_DEVICE_PATH;
    }
    
    dev->fd = open(device_path, O_RDWR | O_SYNC);
    if (dev->fd < 0) {
        fprintf(stderr, "Failed to open FPGA device %s: %s\n", 
                device_path, strerror(errno));
        return -1;
    }
    
    dev->mmio_base = mmap(NULL, MMIO_SIZE, PROT_READ | PROT_WRITE, 
                          MAP_SHARED, dev->fd, 0);
    if (dev->mmio_base == MAP_FAILED) {
        fprintf(stderr, "Failed to mmap FPGA MMIO: %s\n", strerror(errno));
        close(dev->fd);
        return -1;
    }
    
    dev->mmio_size = MMIO_SIZE;
    dev->initialized = true;
    
    write_reg(dev, REG_CONTROL, 0x01);
    usleep(1000);
    
    uint32_t status = read_reg(dev, REG_STATUS);
    if ((status & 0x01) == 0) {
        fprintf(stderr, "FPGA device not ready after reset\n");
        fpga_cleanup(dev);
        return -1;
    }
    
    printf("FPGA device initialized successfully\n");
    return 0;
}

void fpga_cleanup(fpga_device_t* dev) {
    if (!dev) return;
    
    if (dev->mmio_base && dev->mmio_base != MAP_FAILED) {
        munmap(dev->mmio_base, dev->mmio_size);
        dev->mmio_base = NULL;
    }
    
    if (dev->fd >= 0) {
        close(dev->fd);
        dev->fd = -1;
    }
    
    dev->initialized = false;
}

static int wait_for_completion(fpga_device_t* dev, uint32_t timeout_ms) {
    uint32_t elapsed = 0;
    const uint32_t poll_interval = 10;
    
    while (elapsed < timeout_ms) {
        uint32_t status = read_reg(dev, REG_COMPUTE_STATUS);
        if (status & 0x10) {
            return 0;
        }
        usleep(poll_interval * 1000);
        elapsed += poll_interval;
    }
    
    fprintf(stderr, "FPGA computation timeout after %u ms\n", timeout_ms);
    return -1;
}

int fpga_c_bands_offload(fpga_device_t* dev,
                         const fpga_c_bands_request_t* req,
                         void* h_matrix,
                         void* s_matrix,
                         void* result_matrix) {
    if (!dev || !dev->initialized || !req) {
        return -1;
    }
    
    printf("FPGA c_bands offload: n=%u m=%u k=%u\n", req->n, req->m, req->k);
    
    write_reg(dev, REG_MATRIX_N, req->n);
    write_reg(dev, REG_MATRIX_M, req->m);
    write_reg(dev, REG_MATRIX_K, req->k);
    
    size_t h_size = req->n * req->m * sizeof(double) * 2;
    size_t s_size = req->m * req->m * sizeof(double) * 2;
    
    write_reg(dev, REG_DMA_SRC_LO, (uint32_t)(req->h_matrix_addr & 0xFFFFFFFF));
    write_reg(dev, REG_DMA_SRC_HI, (uint32_t)(req->h_matrix_addr >> 32));
    write_reg(dev, REG_DMA_DST_LO, 0);
    write_reg(dev, REG_DMA_DST_HI, 0);
    write_reg(dev, REG_DMA_SIZE, h_size);
    write_reg(dev, REG_DMA_CONTROL, 1);
    
    usleep(100);
    
    write_reg(dev, REG_DMA_SRC_LO, (uint32_t)(req->s_matrix_addr & 0xFFFFFFFF));
    write_reg(dev, REG_DMA_SRC_HI, (uint32_t)(req->s_matrix_addr >> 32));
    write_reg(dev, REG_DMA_DST_LO, h_size);
    write_reg(dev, REG_DMA_DST_HI, 0);
    write_reg(dev, REG_DMA_SIZE, s_size);
    write_reg(dev, REG_DMA_CONTROL, 1);
    
    usleep(100);
    
    write_reg(dev, REG_COMPUTE_CMD, 1);
    
    if (wait_for_completion(dev, 10000) != 0) {
        return -1;
    }
    
    size_t result_size = req->n * sizeof(double);
    write_reg(dev, REG_DMA_SRC_LO, h_size + s_size);
    write_reg(dev, REG_DMA_SRC_HI, 0);
    write_reg(dev, REG_DMA_DST_LO, (uint32_t)(req->result_addr & 0xFFFFFFFF));
    write_reg(dev, REG_DMA_DST_HI, (uint32_t)(req->result_addr >> 32));
    write_reg(dev, REG_DMA_SIZE, result_size);
    write_reg(dev, REG_DMA_CONTROL, 1);
    
    usleep(100);
    
    printf("FPGA c_bands offload completed\n");
    return 0;
}

bool fpga_is_available(void) {
    int fd = open(FPGA_DEVICE_PATH, O_RDWR);
    if (fd < 0) {
        return false;
    }
    close(fd);
    return true;
}
