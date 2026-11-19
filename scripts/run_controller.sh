#!/usr/bin/env bash

set -e

MODE="${1:-adaptive}"
CONTROLLER_TYPE="${2:-standalone}"

export PYTHONPATH=".:$PYTHONPATH"

echo "=========================================================="
echo " Starting SDN Load Balancer Controller"
echo " Scheduling Mode : $MODE"
echo " Engine          : $CONTROLLER_TYPE"
echo " Port            : 6653 (OpenFlow 1.3)"
echo "=========================================================="

if [ "$CONTROLLER_TYPE" = "ryu" ]; then
    if command -v ryu-manager >/dev/null 2>&1; then
        export SDN_CONFIG="config.json"
        exec ryu-manager --ofp-tcp-listen-port 6653 controller/ryu_controller.py
    else
        echo "WARNING: ryu-manager not found, using the standalone controller"
        exec python3 -m controller.standalone_controller --mode "$MODE"
    fi
else
    exec python3 -m controller.standalone_controller --mode "$MODE"
fi
