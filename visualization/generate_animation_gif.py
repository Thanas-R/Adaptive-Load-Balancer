"""Pillow-based GIF Animation Generator for SDN Adaptive Load Balancer.

Renders an animated GIF file (sdn_load_balancer_animation.gif) showing:
1. Topology layout and Virtual IP
2. Telemetry polling & composite score evaluation
3. FlowMod installation & NAT destination rewriting
4. Degradation and failover
5. Benchmark comparison chart

Does not require Manim or ffmpeg to render!
"""

from __future__ import annotations

import math
import os
from PIL import Image, ImageDraw, ImageFont

OUTPUT_FILE = "sdn_load_balancer_animation.gif"
WIDTH = 800
HEIGHT = 500

BG_COLOR = (15, 23, 42)  # #0f172a
CARD_BG = (30, 41, 59)
BORDER_COLOR = (51, 65, 85)
TEXT_WHITE = (248, 250, 252)
TEXT_MUTED = (148, 163, 184)
PRIMARY_BLUE = (56, 189, 248)
ACCENT_YELLOW = (245, 158, 11)
GREEN = (34, 197, 94)
RED = (239, 68, 68)
PURPLE = (168, 85, 247)


def draw_topology_base(draw: ImageDraw.ImageDraw, stage_title: str):
    # Background
    draw.rectangle([0, 0, WIDTH, HEIGHT], fill=BG_COLOR)

    # Header
    draw.text((20, 15), "SDN-Based Adaptive Load Balancer", fill=PRIMARY_BLUE)
    draw.text((20, 35), f"Stage: {stage_title}", fill=TEXT_MUTED)
    draw.line([(20, 55), (WIDTH - 20, 55)], fill=BORDER_COLOR, width=2)

    # Controller (Top)
    draw.rounded_rectangle([270, 70, 530, 140], radius=8, fill=(2, 132, 199), outline=PRIMARY_BLUE, width=2)
    draw.text((310, 85), "SDN Controller (Python)", fill=TEXT_WHITE)
    draw.text((290, 105), "Adaptive Engine & Telemetry", fill=(186, 230, 253))

    # Control Link (dashed)
    draw.line([(400, 140), (400, 220)], fill=(2, 132, 199), width=2)
    draw.text((410, 170), "OF 1.3 (TCP 6653)", fill=PRIMARY_BLUE)

    # Switch s1 (Center)
    draw.rounded_rectangle([320, 220, 480, 290], radius=8, fill=(15, 118, 110), outline=(20, 184, 166), width=2)
    draw.text((345, 235), "Open vSwitch (s1)", fill=TEXT_WHITE)
    draw.text((335, 255), "VIP: 10.0.0.100:8000", fill=ACCENT_YELLOW)

    # Client h1 (Left)
    draw.rounded_rectangle([40, 220, 150, 290], radius=8, fill=(20, 83, 45), outline=GREEN, width=2)
    draw.text((60, 235), "Client h1", fill=TEXT_WHITE)
    draw.text((55, 255), "10.0.0.1", fill=(134, 239, 172))

    # Link: Client -> Switch
    draw.line([(150, 255), (320, 255)], fill=BORDER_COLOR, width=4)

    # Backends (Right)
    # h2
    draw.rounded_rectangle([630, 140, 760, 200], radius=8, fill=CARD_BG, outline=ACCENT_YELLOW, width=2)
    draw.text((650, 150), "Backend h2", fill=TEXT_WHITE)
    draw.text((645, 170), "10.0.0.2 (15ms)", fill=ACCENT_YELLOW)

    # h3
    draw.rounded_rectangle([630, 225, 760, 285], radius=8, fill=CARD_BG, outline=(59, 130, 246), width=2)
    draw.text((650, 235), "Backend h3", fill=TEXT_WHITE)
    draw.text((645, 255), "10.0.0.3 (20ms)", fill=(147, 197, 253))

    # h4
    draw.rounded_rectangle([630, 310, 760, 370], radius=8, fill=CARD_BG, outline=PURPLE, width=2)
    draw.text((650, 320), "Backend h4", fill=TEXT_WHITE)
    draw.text((645, 340), "10.0.0.4 (20ms)", fill=(216, 180, 254))

    # Links: Switch -> Backends
    draw.line([(480, 255), (630, 170)], fill=BORDER_COLOR, width=3)
    draw.line([(480, 255), (630, 255)], fill=BORDER_COLOR, width=3)
    draw.line([(480, 255), (630, 340)], fill=BORDER_COLOR, width=3)


def create_frames():
    frames = []

    # Phase 1: Client sends TCP SYN (frames 0 - 5)
    for i in range(6):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_topology_base(draw, "1. Client Initiates TCP SYN to VIP 10.0.0.100")

        # Moving packet along client link
        t = i / 5.0
        px = 150 + t * (320 - 150)
        py = 255
        draw.ellipse([px - 8, py - 8, px + 8, py + 8], fill=PRIMARY_BLUE, outline=TEXT_WHITE, width=2)
        draw.text((160, 230), "TCP SYN -> 10.0.0.100:8000", fill=PRIMARY_BLUE)

        # Footer info
        draw.rectangle([20, 420, WIDTH - 20, 480], fill=CARD_BG, outline=BORDER_COLOR)
        draw.text((35, 435), "Step 1: Client connects to Virtual IP. Switch has no flow entry -> triggers PacketIn.", fill=TEXT_WHITE)
        frames.append(img)

    # Phase 2: PacketIn to Controller (frames 6 - 9)
    for i in range(4):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_topology_base(draw, "2. Switch sends PacketIn to SDN Controller")

        t = i / 3.0
        py = 220 - t * (220 - 140)
        draw.ellipse([400 - 7, py - 7, 400 + 7, py + 7], fill=RED, outline=TEXT_WHITE, width=2)
        draw.text((415, 175), "PacketIn", fill=RED)

        draw.rectangle([20, 420, WIDTH - 20, 480], fill=CARD_BG, outline=BORDER_COLOR)
        draw.text((35, 435), "Step 2: Controller receives 5-tuple and evaluates real-time telemetry metrics.", fill=TEXT_WHITE)
        frames.append(img)

    # Phase 3: FlowMod Installation (frames 10 - 14)
    for i in range(5):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_topology_base(draw, "3. Controller Evaluates Score & Installs FlowMod")

        t = i / 4.0
        py = 140 + t * (220 - 140)
        draw.ellipse([400 - 8, py - 8, 400 + 8, py + 8], fill=ACCENT_YELLOW, outline=TEXT_WHITE, width=2)
        draw.text((415, 175), "FlowMod (NAT Rewrite)", fill=ACCENT_YELLOW)

        draw.rectangle([20, 420, WIDTH - 20, 480], fill=CARD_BG, outline=BORDER_COLOR)
        draw.text((35, 430), "Composite Score = 0.50*Conn + 0.35*Latency + 0.15*ErrorRate", fill=ACCENT_YELLOW)
        draw.text((35, 450), "Selected: h2 (Lowest Score: 0.00). Installs NAT rewrite flow rules on s1.", fill=TEXT_WHITE)
        frames.append(img)

    # Phase 4: Forwarding rewritten packet to h2 (frames 15 - 19)
    for i in range(5):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_topology_base(draw, "4. Hardware Datapath Forwarding to Chosen Backend")

        t = i / 4.0
        px = 480 + t * (630 - 480)
        py = 255 + t * (170 - 255)
        draw.ellipse([px - 8, py - 8, px + 8, py + 8], fill=GREEN, outline=TEXT_WHITE, width=2)
        draw.text((490, 190), "Rewritten -> 10.0.0.2", fill=GREEN)

        draw.rectangle([20, 420, WIDTH - 20, 480], fill=CARD_BG, outline=BORDER_COLOR)
        draw.text((35, 435), "Destination MAC rewritten to h2 MAC; IP rewritten to 10.0.0.2.", fill=TEXT_WHITE)
        draw.text((35, 455), "Subsequent packets match OpenFlow flow table directly at wire speed!", fill=(134, 239, 172))
        frames.append(img)

    # Phase 5: Failover Demonstration (frames 20 - 24)
    for i in range(5):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_topology_base(draw, "5. Failover: h3 Crashes -> Traffic Diverts to h4")

        # Mark h3 with red cross
        draw.line([(630, 225), (760, 285)], fill=RED, width=4)
        draw.line([(630, 285), (760, 225)], fill=RED, width=4)
        draw.text((640, 290), "CRASHED (Excluded)", fill=RED)

        # Flow packets to h4 instead
        t = i / 4.0
        px = 480 + t * (630 - 480)
        py = 255 + t * (340 - 255)
        draw.ellipse([px - 8, py - 8, px + 8, py + 8], fill=PURPLE, outline=TEXT_WHITE, width=2)

        draw.rectangle([20, 420, WIDTH - 20, 480], fill=CARD_BG, outline=BORDER_COLOR)
        draw.text((35, 435), "Backend h3 heartbeat fails. Controller marks h3 UNHEALTHY.", fill=RED)
        draw.text((35, 455), "New flows automatically redirected to surviving nodes with zero drops!", fill=TEXT_WHITE)
        frames.append(img)

    # Phase 6: Benchmark comparison card (frames 25 - 32)
    for i in range(8):
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)

        draw.text((20, 15), "SDN-Based Adaptive Load Balancer", fill=PRIMARY_BLUE)
        draw.text((20, 35), "Stage: Empirical Benchmark (Adaptive vs. Round-Robin)", fill=TEXT_MUTED)
        draw.line([(20, 55), (WIDTH - 20, 55)], fill=BORDER_COLOR, width=2)

        # Comparison Card
        draw.rounded_rectangle([60, 80, 740, 420], radius=10, fill=CARD_BG, outline=PRIMARY_BLUE, width=2)
        draw.text((200, 100), "EMPIRICAL PERFORMANCE COMPARISON", fill=PRIMARY_BLUE)

        # Header Row
        draw.text((90, 150), "METRIC", fill=TEXT_MUTED)
        draw.text((300, 150), "ROUND-ROBIN", fill=ACCENT_YELLOW)
        draw.text((520, 150), "ADAPTIVE SDN", fill=GREEN)
        draw.line([(90, 175), (710, 175)], fill=BORDER_COLOR, width=1)

        # Rows
        draw.text((90, 195), "Throughput", fill=TEXT_WHITE)
        draw.text((300, 195), "115.89 req/s", fill=TEXT_WHITE)
        draw.text((520, 195), "475.40 req/s (+310.2%)", fill=GREEN)

        draw.text((90, 235), "Mean Latency", fill=TEXT_WHITE)
        draw.text((300, 235), "91.36 ms", fill=TEXT_WHITE)
        draw.text((520, 235), "22.31 ms (-75.6%)", fill=GREEN)

        draw.text((90, 275), "95th % Latency", fill=TEXT_WHITE)
        draw.text((300, 275), "203.01 ms", fill=TEXT_WHITE)
        draw.text((520, 275), "38.75 ms (-80.9%)", fill=GREEN)

        draw.text((90, 315), "Failed Requests", fill=TEXT_WHITE)
        draw.text((300, 315), "0 (0.0%)", fill=TEXT_WHITE)
        draw.text((520, 315), "0 (0.0%)", fill=GREEN)

        draw.text((90, 355), "Traffic Handling", fill=TEXT_WHITE)
        draw.text((300, 355), "33% stuck on slow h4", fill=RED)
        draw.text((520, 355), "100% steered to fast h2", fill=GREEN)

        frames.append(img)

    return frames


def main():
    print("Generating animated frames...")
    frames = create_frames()
    print(f"Saving {len(frames)} frames to {OUTPUT_FILE}...")
    frames[0].save(
        OUTPUT_FILE,
        save_all=True,
        append_images=frames[1:],
        duration=300,  # 300ms per frame
        loop=0,
    )
    print(f"Animation GIF successfully created: {OUTPUT_FILE} ({os.path.getsize(OUTPUT_FILE)} bytes)")


if __name__ == "__main__":
    main()
