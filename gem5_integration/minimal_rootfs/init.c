#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <stdint.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <string.h>

#define FPGA_BASE 0xF0000000UL
#define FPGA_SIZE 0x1000

static int cmdline_has_flag(const char *flag) {
    FILE *f = fopen("/proc/cmdline", "r");
    if (!f) {
        return 0;
    }

    char buf[4096];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = '\0';
    return strstr(buf, flag) != NULL;
}

static int run_binary(const char *path) {
    pid_t pid = fork();
    if (pid < 0) {
        perror("fork failed");
        return -1;
    }

    if (pid == 0) {
        char *const argv[] = {(char *)path, NULL};
        execv(path, argv);
        perror("execv failed");
        _exit(127);
    }

    int status = 0;
    if (waitpid(pid, &status, 0) < 0) {
        perror("waitpid failed");
        return -1;
    }

    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    }

    return -1;
}

int main() {
    printf("Minimal init starting...\n");
    
    // Mount essential filesystems
    mount("proc", "/proc", "proc", 0, NULL);
    mount("sysfs", "/sys", "sysfs", 0, NULL);
    mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);
    
    printf("Filesystems mounted\n");
    
    int use_pci_mode = cmdline_has_flag("fpga_mode=pci");
    printf("FPGA mode: %s\n", use_pci_mode ? "pci" : "se");

    if (!use_pci_mode) {
        // Test FPGA device access via /dev/mem for the SE-style MMIO path.
        int fd = open("/dev/mem", O_RDWR | O_SYNC);
        if (fd < 0) {
            perror("Failed to open /dev/mem");
            printf("Trying to create /dev/mem manually...\n");
            mknod("/dev/mem", S_IFCHR | 0600, makedev(1, 1));
            fd = open("/dev/mem", O_RDWR | O_SYNC);
        }

        if (fd >= 0) {
            printf("Successfully opened /dev/mem\n");

            void *fpga_mem = mmap(NULL, FPGA_SIZE, PROT_READ | PROT_WRITE,
                                  MAP_SHARED, fd, FPGA_BASE);

            if (fpga_mem != MAP_FAILED) {
                printf("Successfully mapped FPGA at 0x%lx\n", FPGA_BASE);

                volatile uint32_t *regs = (volatile uint32_t *)fpga_mem;

                // SE FPGA register map:
                // 0x00 control, 0x04 status, 0x08 nBands, 0x0C nBasis, 0x10 cycles
                printf("Initial control register: 0x%08x\n", regs[0]);
                printf("Initial status register:  0x%08x\n", regs[1]);

                regs[2] = 32;
                regs[3] = 128;

                printf("Configured nBands=%u nBasis=%u\n", regs[2], regs[3]);
                printf("Writing start bit to control register...\n");
                regs[0] = 0x1;

                printf("Final status register:    0x%08x\n", regs[1]);
                printf("Reported cycles:          %u\n", regs[4]);

                munmap(fpga_mem, FPGA_SIZE);
            } else {
                perror("Failed to mmap FPGA");
            }

            close(fd);
        } else {
            printf("Could not access /dev/mem\n");
        }
    } else {
        printf("Skipping /dev/mem SE smoke test in PCI mode\n");
    }

    printf("\nStep 2: Attempting PCIe/SystemC smoke test binary...\n");
    if (access("/bin/fpga_pci_electrons_test", X_OK) == 0) {
        int rc = run_binary("/bin/fpga_pci_electrons_test");
        if (rc == -1) {
            perror("Failed to launch /bin/fpga_pci_electrons_test");
        } else {
            printf("PCIe smoke test exit status: %d\n", rc);
        }
    } else {
        printf("PCIe smoke binary not present in initramfs\n");
    }
    
    printf("\nTest complete. System will halt in 5 seconds...\n");
    sleep(5);
    
    // Exit to trigger gem5 shutdown
    return 0;
}
