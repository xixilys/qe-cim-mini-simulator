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
    printf("Minimal PCI init starting...\n");

    mount("proc", "/proc", "proc", 0, NULL);
    mount("sysfs", "/sys", "sysfs", 0, NULL);
    mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);

    printf("Filesystems mounted\n");

    // Run DMA transfer test first
    if (access("/bin/test_dma_transfer", X_OK) == 0) {
        printf("Running DMA transfer test...\n\n");
        int rc = run_binary("/bin/test_dma_transfer");
        printf("\nDMA transfer test exit status: %d\n\n", rc);
    } else {
        printf("DMA test binary not found, skipping...\n\n");
    }

    // Run QE FPGA benchmark
    if (access("/bin/qe_fpga_benchmark", X_OK) == 0) {
        printf("Running QE FPGA benchmark...\n\n");
        int rc = run_binary("/bin/qe_fpga_benchmark");
        printf("\nQE FPGA benchmark exit status: %d\n\n", rc);
    }

    // Run QE offload test
    if (access("/bin/test_qe_offload_minimal", X_OK) == 0) {
        printf("Running QE-like offload test...\n\n");
        int rc = run_binary("/bin/test_qe_offload_minimal");
        printf("\nQE offload test exit status: %d\n", rc);
    } else if (access("/bin/fpga_pci_electrons_test", X_OK) == 0) {
        printf("Running PCIe smoke test...\n\n");
        int rc = run_binary("/bin/fpga_pci_electrons_test");
        printf("\nPCIe smoke test exit status: %d\n", rc);
    } else {
        printf("No test binaries found in initramfs\n");
    }

    printf("\nPCI init complete. System will halt in 5 seconds...\n");
    sleep(5);
    return 0;
}
