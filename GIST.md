# Adaptive load balancer Gist

An executive summary of the SDN-based Adaptive TCP Load Balancer project for Team 5.

## 1. Problem Statement and Core Idea

Traditional Layer 4 load balancers use static policies like Round-Robin or random selection. These policies do not account for varying request complexity, hardware differences, or sudden server slowdowns.

This project implements an SDN adaptive load balancer where an OpenFlow 1.3 controller acts as an intelligent control plane. The controller continuously monitors backend server metrics over low-level TCP sockets and installs dynamic Open vSwitch flow rules to route new client TCP connections to the best performing server.

## 2. Mathematical Formulation

### Composite Score Calculation
For each eligible backend server i:
Composite_Score(i) = (w_conn * Norm_Connections(i)) + (w_lat * Norm_Latency(i)) + (w_err * Norm_Error_Rate(i))

Default weight distribution:
- w_conn = 0.50 (active connections)
- w_lat = 0.35 (smoothed latency)
- w_err = 0.15 (error rate)

The server with the lowest Composite_Score is selected for the next TCP connection.

### Exponential Moving Average (EMA) for Latency
Raw latency measurements are smoothed to prevent oscillations from temporary jitter:
EMA_t = (alpha * Raw_Latency_t) + ((1 - alpha) * EMA_{t-1})
where alpha = 0.25.

### Min-Max Normalization
Each raw metric M is scaled across all currently eligible servers into the range 0.0 to 1.0:
Norm_M(i) = (M(i) - min(M)) / (max(M) - min(M)) if max(M) > min(M) else 0.0

### Penalties for Degradation and Recovery
- If server health status is DEGRADED: Composite_Score += 0.20
- If server health status is RECOVERING: Composite_Score += 0.35

## 3. OpenFlow 1.3 Flow Table Modifications

The virtual service is addressed at VIP 10.0.0.100 on TCP port 8000.

### Forward Path Rule (Priority 100)
- Match:
  - in_port = client_switch_port (1)
  - eth_type = 0x0800 (IPv4)
  - ip_proto = 6 (TCP)
  - ipv4_src = client_ip
  - ipv4_dst = 10.0.0.100
  - tcp_src = client_ephemeral_port
  - tcp_dst = 8000
- Actions:
  - set_field: eth_dst = chosen_backend_mac
  - set_field: ipv4_dst = chosen_backend_ip
  - output: chosen_backend_switch_port

### Reverse Path Rule (Priority 100)
- Match:
  - in_port = chosen_backend_switch_port
  - eth_type = 0x0800 (IPv4)
  - ip_proto = 6 (TCP)
  - ipv4_src = chosen_backend_ip
  - ipv4_dst = client_ip
  - tcp_src = 8000
  - tcp_dst = client_ephemeral_port
- Actions:
  - set_field: eth_src = 00:00:00:00:00:fe (virtual MAC)
  - set_field: ipv4_src = 10.0.0.100 (VIP)
  - output: client_switch_port (1)

## 4. Health and Failure Recovery State Machine

```
+------------+   Error rate >= 25% or Latency >= 500ms   +------------+
|  HEALTHY   +------------------------------------------>+  DEGRADED  |
|            +<------------------------------------------+            |
+-----+------+   Error rate < 10% and Latency < 200ms    +------------+
      |
      | 3 consecutive probe failures
      v
+------------+
| UNHEALTHY  | (Excluded from flow installation)
+-----+------+
      |
      | Server responds to health probe
      v
+------------+
| RECOVERING | (Probation penalty +0.35 applied)
+-----+------+
      |
      | 5-second cooldown elapsed
      v
+------------+
|  HEALTHY   | (Fully returned to normal rotation)
+------------+
```

## 5. Top 5 Viva Questions and Answers

### Question 1: Why use SDN for load balancing instead of a reverse proxy like Nginx or HAProxy?
Answer: A traditional reverse proxy terminates TCP connections, inspects them, and establishes a second TCP connection to the backend. This creates a CPU and memory bottleneck at layer 7. In our SDN architecture, the controller inspects only the first packet (TCP SYN) to make a routing decision. Once the OpenFlow rewrite rules are installed into Open vSwitch, all subsequent packets flow directly at hardware layer 2 and layer 3 wire speed, achieving significantly higher throughput with minimal latency overhead.

### Question 2: How does the controller track server load without interfering with client traffic?
Answer: Each backend server runs a lightweight TelemetryAgent on a dedicated management port (9002, 9003, 9004). The controller polls these ports periodically via TCP sockets sending a STATS query. The agent responds with a JSON snapshot containing active connection count, smoothed latency, error count, and CPU utilization. This out-of-band monitoring ensures that telemetry traffic does not consume bandwidth on the data path.

### Question 3: What prevents the controller from oscillating traffic back and forth between servers?
Answer: Two mechanisms prevent oscillation:
1. Exponential Moving Average (EMA) smoothing dampens transient latency spikes so decisions are not made on outlier packets.
2. Min-max normalization scales active connections, latency, and error rates together. Because active connections have a 50% weight, as soon as a fast server receives new connections, its score rises smoothly, naturally balancing the arrival rate across nodes.

### Question 4: How does the system handle server failure mid-run?
Answer: The telemetry collector probes each server every 1.0 second. If a server process crashes or is killed, socket connections to its telemetry port fail with Connection Refused or Timeout. After 3 consecutive probe failures, the server is marked UNHEALTHY and omitted from future flow rule selections. Existing rules timeout via OpenFlow idle_timeout, and new connections are routed exclusively to remaining healthy servers without dropping client requests.

### Question 5: Why is per-flow bi-directional rewriting necessary?
Answer: The client sends packets to the VIP (10.0.0.100). The backend server only listens on its local IP (such as 10.0.0.2). The forward flow rule rewrites the destination IP and MAC so the backend accepts the packet. On the return path, the backend replies with its own IP as the source. If the client received packets from 10.0.0.2 instead of the VIP, the client TCP stack would reject the packets with TCP RST because no socket was opened to 10.0.0.2. The reverse flow rule rewrites the source IP and MAC back to the VIP so the client perceives a single seamless connection.
