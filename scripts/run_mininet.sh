#!/usr/bin/env bash
# ==============================================================================
# Launch Mininet Topology
# ==============================================================================

set -e

echo "=== Cleaning previous Mininet state ==="
sudo mn -c 2>/dev/null || true

echo "=== Starting Mininet SDN Topology (s1, h1, h2, h3, h4) ==="
export PYTHONPATH=".:$PYTHONPATH"
sudo -E python3 -m topology.mininet_topo "$@"
