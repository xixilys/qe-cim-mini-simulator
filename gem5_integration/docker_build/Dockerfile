# Dockerfile for cross-compiling x86_64 Linux programs on macOS
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    gcc-x86-64-linux-gnu \
    g++-x86-64-linux-gnu \
    make \
    cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

CMD ["/bin/bash"]
