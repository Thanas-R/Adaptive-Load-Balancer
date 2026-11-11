# Adaptive load balancer Guide

A practical operations and execution manual for the SDN Adaptive TCP Load Balancer project for Team 5.

## 1. Environment Setup

The project supports two execution modes:
1. Native Mininet Environment: Recommended for production SDN testing on Ubuntu Linux with Open vSwitch and Ryu controller.
2. In-Process Testbed Environment: Runs on any platform (Windows, macOS, Linux) without requiring root or Mininet installation.

### Package Installation
Install required Python dependencies:
```bash
pip install -r requirements.txt
```

Verify that the unit tests pass:
```bash
python -m pytest
```

## 2. Running in Mininet on Ubuntu Linux

### Step 1: Start the Ryu SDN Controller
Open a terminal and launch the OpenFlow 1.3 controller application:
```bash
python3 -m controller.ryu_controller
```
The controller binds to 0.0.0.0 on TCP port 6653 and starts the internal telemetry collector loop.

### Step 2: Launch the Mininet Topology
Open a second terminal with root privileges:
```bash
sudo python3 -m topology.mininet_topo
```
Mininet creates:
- Switch s1 configured with OpenFlow 1.3
- Client host h1 connected to switch port 1
- Backend hosts h2, h3, h4 connected to switch ports 2, 3, 4
- Automatically launches the backend TCP workers and telemetry agents inside host namespaces
- Drops into the interactive `mininet>` prompt

### Step 3: Verify OpenFlow Switch Connection
From another terminal, inspect the OpenFlow flow table on s1:
```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```
You will see the default table-miss entry (priority 0) installed by the controller directing unmatched packets to the controller.

### Step 4: Generate Client Requests
Inside the Mininet CLI, execute test requests from host h1:

Send a single test request to the VIP:
```bash
mininet> h1 python3 -m client.client --vip 10.0.0.100 --port 8000
```

Run concurrent benchmark traffic:
```bash
mininet> h1 python3 -m client.load_generator --vip 10.0.0.100 --port 8000 --requests 100 --concurrency 10
```

### Step 5: Verify Flow Rules and Distribution
Inspect the active flow table on switch s1 while traffic is flowing:
```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```
Observe bidirectional per-flow entries with priority 100 rewriting destination addresses on the forward path and source addresses on the reverse path.

## 3. Running Automated Demonstration Scenarios

For development, testing, or demonstrations without Mininet, six automated scenarios are provided in the `scenarios/` directory.

### Scenario 1: Normal Balanced Traffic
Demonstrates even flow distribution across all three healthy backend servers under baseline conditions:
```bash
python -m scenarios.scenario1_normal
```

### Scenario 2: Server Slowdown and Adaptive Load Shedding
Injects a 200ms processing delay into server h2. The controller detects the increased latency through telemetry and shifts traffic toward h3 and h4:
```bash
python -m scenarios.scenario2_slowdown
```

### Scenario 3: Server Failure Mid-Operation
Terminates server h3 abruptly. The controller detects three consecutive heartbeat probe timeouts, marks h3 as UNHEALTHY, and routes all subsequent requests to h2 and h4 without dropped client requests:
```bash
python -m scenarios.scenario3_failure
```

### Scenario 4: Server Recovery and Re-Warming
Restarts a previously failed server. The controller detects successful telemetry probes, moves the server into RECOVERING status with a probation score penalty, and re-integrates it into rotation:
```bash
python -m scenarios.scenario4_recovery
```

### Scenario 5: Comparative Benchmark (Static vs Adaptive)
Runs identical concurrent client workloads through Static Round-Robin and Adaptive Load Balancing, outputting side-by-side comparison tables of latency percentiles and load variance:
```bash
python -m scenarios.scenario5_benchmark
```

### Scenario 6: Hard Viva Scenario
Combines server degradation and sudden mid-run process termination. Server h2 is overloaded, and server h3 is killed mid-run. The system demonstrates zero dropped client connections and automatic failover:
```bash
python -m scenarios.scenario6_hard
```

### Run All Scenarios Automatically
To execute all six scenarios sequentially and log results:
```bash
python -m scenarios.run_all_scenarios
```

## 4. 3D WebGL Topology Visualizer

The project includes an interactive 3D browser visualizer located at `visualization/animation.html`.

### How It Works
- Built with Three.js and OrbitControls in an isometric perspective.
- Renders the full topology: client laptops, Open vSwitch appliance, modular backend server racks, database node, and the floating SDN controller cloud.
- Animates data packets traveling along Catmull-Rom spline curves connecting switch ports to hosts.
- Dynamically reflects system states such as healthy green indicators, degraded amber warnings, and unhealthy red statuses driven by network telemetry data.
- Device name tags remain hidden to keep the 3D scene clean, and fade into view smoothly when the user hovers over any device.

To view the visualizer, open `visualization/animation.html` in any modern web browser.

## 5. Troubleshooting Guide

### Port Already in Use (Address already in use)
If port 6653 or port 8000 is still bound by an earlier run:
```bash
# On Linux:
sudo fuser -k 6653/tcp 8000/tcp 9002/tcp 9003/tcp 9004/tcp

# On Windows:
netstat -ano | findstr :8000
taskkill /F /PID <PID>
```

### Mininet Open vSwitch Socket Issues
If Mininet reports switch configuration errors or leftover sockets:
```bash
sudo mn -c
```
This cleans up stale virtual interfaces, Open vSwitch bridges, and controller processes.

### Permission Denied on Mininet Launch
Mininet creates Linux network namespaces and virtual Ethernet interfaces, which requires root privileges:
```bash
sudo python3 -m topology.mininet_topo
```

### Checksum Offloading Errors in Emulation
If TCP packets fail checksum verification inside Mininet host namespaces, ensure hardware offload is disabled:
```bash
sudo ethtool -K s1-eth1 tx off rx off
sudo ethtool -K s1-eth2 tx off rx off
sudo ethtool -K s1-eth3 tx off rx off
sudo ethtool -K s1-eth4 tx off rx off
```
The `mininet_topo.py` script executes these commands automatically on startup.
