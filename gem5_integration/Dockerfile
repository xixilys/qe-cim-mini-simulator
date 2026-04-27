# Dockerfile for gem5 + SystemC testing on x86_64
FROM --platform=linux/amd64 ubuntu:22.04

# 设置非交互模式
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 安装基础工具和编译依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    python3 \
    python3-dev \
    python3-pip \
    git \
    scons \
    m4 \
    libprotobuf-dev \
    protobuf-compiler \
    libgoogle-perftools-dev \
    libboost-all-dev \
    pkg-config \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# 创建工作目录
WORKDIR /workspace

# 设置默认命令
CMD ["/bin/bash"]
