.section .text
.globl _start

_start:
    # Write n_bands = 10 to FPGA (offset 0x08)
    movl $10, %eax
    movl $0xF0000008, %edi
    movl %eax, (%edi)
    
    # Write n_basis = 100 to FPGA (offset 0x0C)
    movl $100, %eax
    movl $0xF000000C, %edi
    movl %eax, (%edi)
    
    # Write control = 1 to start computation (offset 0x00)
    movl $1, %eax
    movl $0xF0000000, %edi
    movl %eax, (%edi)
    
    # Poll status register until done (offset 0x04)
poll_loop:
    movl $0xF0000004, %edi
    movl (%edi), %eax
    testl $1, %eax
    jz poll_loop
    
    # Read cycles result (offset 0x10)
    movl $0xF0000010, %edi
    movl (%edi), %eax
    
    # Exit with cycles as return code
    movl %eax, %edi
    movl $60, %eax
    syscall
