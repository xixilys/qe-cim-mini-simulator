#!/bin/bash
# gem5 Docker 测试脚本

set -e

echo "=========================================="
echo "gem5 + SystemC Docker 测试环境"
echo "=========================================="

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: Docker 未安装"
    exit 1
fi

echo "✓ Docker 已安装: $(docker --version)"

# 构建镜像
echo ""
echo "步骤 1: 构建 Docker 镜像 (x86_64)..."
docker build --platform linux/amd64 -t gem5-test:latest .

# 创建测试程序
echo ""
echo "步骤 2: 创建测试程序..."
cat > test_fpga.c << 'TESTEOF'
#include <stdio.h>
#include <stdint.h>

int main() {
    printf("=== FPGA Device Test (x86_64) ===\n");
    printf("Testing gem5 FPGA device instantiation\n");
    
    // 简单计算
    int n = 32, m = 128;
    double sum = 0.0;
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < m; j++) {
            sum += (i + j) * 0.001;
        }
    }
    
    printf("Matrix dimensions: N=%d, M=%d\n", n, m);
    printf("Computation result: %f\n", sum);
    printf("Test completed successfully!\n");
    
    return 0;
}
TESTEOF

echo "✓ 测试程序已创建"

# 运行容器并编译测试程序
echo ""
echo "步骤 3: 在容器中编译测试程序..."
docker run --rm --platform linux/amd64 \
    -v "$(pwd)":/workspace \
    -w /workspace \
    gem5-test:latest \
    bash -c "gcc -o test_fpga test_fpga.c -static && file test_fpga && ls -lh test_fpga"

echo ""
echo "=========================================="
echo "✓ Docker 环境准备完成!"
echo "=========================================="
echo ""
echo "下一步操作:"
echo "1. 进入容器: docker run -it --rm --platform linux/amd64 -v \$(pwd):/workspace -w /workspace gem5-test:latest"
echo "2. 编译 gem5: cd gem5 && scons build/X86/gem5.opt -j4"
echo "3. 运行测试: ./build/X86/gem5.opt ../configs/fpga_device_test.py --binary=../test_fpga"
echo ""
