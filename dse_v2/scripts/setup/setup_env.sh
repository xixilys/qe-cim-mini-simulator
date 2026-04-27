#!/bin/bash
# DSE v2 环境设置脚本

set -e

echo "🚀 Setting up DSE v2 environment..."

# 检查 Python 版本
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "📌 Python version: $PYTHON_VERSION"

if [[ $(echo "$PYTHON_VERSION < 3.9" | bc) -eq 1 ]]; then
    echo "❌ Python 3.9+ required, found $PYTHON_VERSION"
    exit 1
fi

# 创建虚拟环境
echo "📦 Creating virtual environment..."
python3 -m venv venv

# 激活虚拟环境
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# 升级 pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip setuptools wheel

# 安装依赖
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# 验证安装
echo "✅ Verifying installation..."
python3 -c "import torch; print(f'PyTorch: {torch.__version__}')"
python3 -c "import botorch; print(f'BoTorch: {botorch.__version__}')"
python3 -c "import ax; print(f'Ax: {ax.__version__}')"

echo ""
echo "✅ Environment setup complete!"
echo ""
echo "To activate the environment, run:"
echo "  source dse_v2/venv/bin/activate"
