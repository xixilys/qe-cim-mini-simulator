import m5
from m5.objects import *

# 创建最简单的 SE 模式系统来测试 FPGA 设备
system = System()

# 时钟
system.clk_domain = SrcClockDomain()
system.clk_domain.clock = '1GHz'
system.clk_domain.voltage_domain = VoltageDomain()

# 内存
system.mem_mode = 'timing'
system.mem_ranges = [AddrRange('512MB')]

# CPU
system.cpu = X86TimingSimpleCPU()
system.membus = SystemXBar()

# 连接 CPU
system.cpu.icache_port = system.membus.cpu_side_ports
system.cpu.dcache_port = system.membus.cpu_side_ports
system.cpu.createInterruptController()
system.cpu.interrupts[0].pio = system.membus.mem_side_ports
system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

# 内存控制器
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

# 系统端口
system.system_port = system.membus.cpu_side_ports

# 进程
binary = '/tmp/fpga_test'
process = Process()
process.cmd = [binary]
system.cpu.workload = process
system.cpu.createThreads()

# 实例化
root = Root(full_system=False, system=system)

print("=" * 60)
print("Minimal gem5 Test (without FPGA)")
print("=" * 60)

m5.instantiate()
print("System instantiated!")

print("\nRunning simulation...")
exit_event = m5.simulate()

print("\n" + "=" * 60)
print(f"Simulation finished @ tick {m5.curTick()}")
print(f"Reason: {exit_event.getCause()}")
print("=" * 60)
