#!/usr/bin/env bash

set -e

echo "=== [1/4] Updating package indexes ==="
sudo apt-get update -y

echo "=== [2/4] Installing Mininet, Open vSwitch, and networking tools ==="
sudo apt-get install -y \
    mininet \
    openvswitch-switch \
    openvswitch-testcontroller \
    iproute2 \
    ethtool \
    net-tools \
    tcpdump \
    iperf3 \
    curl \
    python3 \
    python3-pip \
    python3-venv

echo "=== [3/4] Ensuring Open vSwitch service is active ==="
sudo systemctl enable --now openvswitch-switch
sudo ovs-vsctl --version

echo "=== [4/4] Installing Python requirements ==="
python3 -m pip install -r requirements.txt || true

echo "=== SDN environment setup completed ==="
