#!/usr/bin/env bash
# ==============================================================================
# Interactive Demo & Test Runner
# ==============================================================================

set -e
export PYTHONPATH=".:$PYTHONPATH"

clear
echo "======================================================================"
echo "    SDN-BASED ADAPTIVE LOAD BALANCER - DEMO CONTROL CENTER           "
echo "======================================================================"
echo " 1) Run All 5 Demonstration Scenarios (Automated Suite)"
echo " 2) Run Scenario 1: Normal Balanced Traffic"
echo " 3) Run Scenario 2: Backend Slowdown & Adaptive Steering"
echo " 4) Run Scenario 3: Backend Failure & Graceful Exclusion"
echo " 5) Run Scenario 4: Backend Recovery & Service Reintegration"
echo " 6) Run Scenario 5: Comparative Benchmark (Adaptive vs Round-Robin)"
echo " 7) Run Unit Tests (pytest)"
echo " 8) Start Standalone SDN Controller (0.0.0.0:6653)"
echo " 9) Start Mininet Topology (requires sudo/Linux)"
echo " q) Quit"
echo "======================================================================"
read -p " Select option [1-9, q]: " OPTION

case "$OPTION" in
    1)
        python3 -m scenarios.run_all_scenarios
        ;;
    2)
        python3 -m scenarios.scenario1_normal
        ;;
    3)
        python3 -m scenarios.scenario2_slowdown
        ;;
    4)
        python3 -m scenarios.scenario3_failure
        ;;
    5)
        python3 -m scenarios.scenario4_recovery
        ;;
    6)
        python3 -m scenarios.scenario5_benchmark
        ;;
    7)
        python3 -m pytest -v
        ;;
    8)
        python3 -m controller.standalone_controller
        ;;
    9)
        sudo mn -c 2>/dev/null || true
        sudo -E python3 -m topology.mininet_topo
        ;;
    q|Q)
        echo "Exiting."
        exit 0
        ;;
    *)
        echo "Invalid selection."
        exit 1
        ;;
esac
