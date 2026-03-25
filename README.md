# Rainshine — Pi 5 DMX LED Shader

**A GPU-accelerated generative LED art engine** — renders beautiful GLSL animations headlessly on a Raspberry Pi 5, streams pixel data via sACN/E1.31 DMX to an ENTTEC Pixel OCTO, driving a 300-pixel WS2812B LED array.

## About

Rainshine combines real-time GPU rendering with DMX protocol to create a reactive, network-controlled light display. The shader runs at 30–60 fps on the Pi 5's V3D GPU, with zero CPU overhead. Pixel data is read back efficiently and streamed as sACN unicast UDP to a pixel controller, enabling both live parameter control (via OSC from TouchDesigner or command line) and responsive hardware triggering (future: motion sensor integration).

**Key features:**
- **Headless GPU rendering** — moderngl + EGL, no display needed, runs 24/7
- **Direct sACN/E1.31 UDP** — zero-copy streaming to ENTTEC Pixel OCTO (replaces legacy OLA)
- **Live OSC control** — adjust `speed`, `trail`, `density`, `fps`, `brightness` in real time (port 7700)
- **Systemd autostart** — runs persistently with automatic restart on crash
- **Memory-safe** — pre-allocated buffers, RSS monitoring, graceful exit at 400MB
- **Extensible shader architecture** — drop in any GLSL fragment shader (rainshine.frag is just the default)

## Hardware

- **Raspberry Pi 5** — Trixie Lite 64-bit, headless, IP 10.0.0.127 (`PiDMX.local`)
- **ENTTEC Pixel OCTO** — sACN ingress → WS2812B output, IP 10.0.0.123
- **WS2812B LED strip** — 10 columns × 30 rows (300 pixels), zigzag wired column-major, GRB color order

### Network & GPIO

- Ethernet: Pi and OCTO on same 10.0.0.x LAN
- I2C: GPIO 2 (SDA) and 3 (SCL) for future sensors (e.g., STHS34PF80 motion sensor)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│             Raspberry Pi 5 (headless)                    │
├─────────────────────────────────────────────────────────┤
│  rainshine_dmx.py (Python)                              │
│  ├─ Render thread:                                       │
│  │  ├ Load rainshine.frag shader                         │
│  │  ├ Set uniforms (uTime, uSpeed, uTrailLen, uDensity)  │
│  │  ├ Render 10×30 FBO @ 30-60 fps                       │
│  │  ├ Read pixels → remap (zigzag) → apply brightness   │
│  │  └ Send sACN packets to OCTO                          │
│  │                                                       │
│  ├─ OSC server (port 7700):                              │
│  │  └ Live param updates (speed, trail, density, etc.)   │
│  │                                                       │
│  └─ Sensor thread (future):                              │
│     └ I2C motion detection → param automation            │
│                                                          │
│  Params (thread-safe):                                   │
│  └ speed, trail, density, fps, brightness               │
└─────────────────────────────────────────────────────────┘
         │ sACN E1.31 UDP unicast
         ↓ (2 universes, 900 channels)
    ┌─────────────────┐
    │ ENTTEC Octo     │
    │ 10.0.0.123:5568 │
    └─────────────────┘
         │ SPI
         ↓
    300 WS2812B pixels (10×30 grid)
```

## Files

| File | Description |
|---|---|
| `rainshine_dmx.py` | **Main host** — GPU render loop, pixel remap, sACN sender, OSC server, thread orchestration |
| `rainshine.frag` | **GLSL ES 3.0 shader** — fragment shader for rainbow rain effect (drop in any .frag file to change animation) |
| `rainshine.conf` | **Config** — shader params, sACN destination, color order, brightness, OSC port (auto-created on first run) |
| `rainshine.service` | **systemd unit** — runs as daemon, autostart on Pi boot, Restart=always for resilience |
| `setup.sh` | **Installation script** — installs apt packages, creates venv, sets up systemd service |
| `README.md` | This file |

## Quick Start

### On Raspberry Pi (one-time setup)

```bash
cd ~
git clone https://github.com/jpkelly/PiDMX.git
cd PiDMX
bash setup.sh
sudo systemctl restart rainshine
```

Check that it's running:

```bash
journalctl -u rainshine -f
```

### Control with OSC

```bash
# From your Mac (adjust IP to match your Pi)
python3 -c "
from pythonosc.udp_client import SimpleUDPClient
client = SimpleUDPClient('PiDMX.local', 7700)
client.send_message('/rainshine/speed', 10.0)
client.send_message('/rainshine/density', 5.0)
"
```

---

## Full Installation on Raspberry Pi

### 1. Install system dependencies

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv libegl1-mesa-dev libgles2-mesa-dev mesa-utils
sudo raspi-config nonint do_i2c 0  # Enable I2C (for future sensor support)
```

### 2. Create Python environment

```bash
python3 -m venv --system-site-packages ~/rainshine-env
source ~/rainshine-env/bin/activate
pip3 install moderngl python-osc numpy
```

### 3. Clone and install the service

```bash
cd ~
git clone https://github.com/jpkelly/PiDMX.git fadeaway
cd fadeaway
sudo cp rainshine.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable rainshine
```

### 4. Configure ENTTEC Pixel OCTO

Via http://10.0.0.123 web UI:
- **Input Protocol:** sACN
- **Universes:** 1, 2, 3, 4 (or as needed)
- **Pixel Protocol:** WS2812B
- **Color Order:** GRB
- **DMX Start Address:** 1

### 5. Test the installation

```bash
source ~/rainshine-env/bin/activate
cd ~/fadeaway
python3 rainshine_dmx.py --preview
```

Press `Ctrl+C` to stop. You should see shader output in console logs.

### 6. Start the service

```bash
sudo systemctl start rainshine
journalctl -u rainshine -f  # Watch logs
```

The `rainshine.service` is now enabled and will start automatically at boot.

---

## Configuration

`rainshine.conf` is created automatically on first run:

```ini
[shader]
speed = 4.0       # rain speed
trail = 10        # trail length
density = 3.0     # drops per column

[output]
fps = 30.0
universe = 1           # first sACN universe
color_order = grb      # match LED hardware
brightness = 1.0       # 0.0–1.0
sacn_dest = 10.0.0.123 # pixel controller IP

[osc]
port = 7700
```

Apply changes:

```bash
sudo systemctl restart rainshine
```

## Live OSC Control

Parameters can be adjusted in real time via OSC on port **7700**.

| OSC Address | Type | Range |
|---|---|---|
| `/rainshine/speed` | float | 0.5 – 15.0 |
| `/rainshine/trail` | int | 1 – 25 |
| `/rainshine/density` | float | 0.5 – 5.0 |
| `/rainshine/fps` | float | 15 – 60 |
| `/rainshine/brightness` | float | 0.0 – 1.0 |

### From TouchDesigner

OSC Out CHOP → `PiDMX.local:7700`

### From command line

```bash
pip3 install python-osc
python3 -c "from pythonosc.udp_client import SimpleUDPClient; SimpleUDPClient('PiDMX.local', 7700).send_message('/rainshine/speed', 8.0)"
```

## Service Management

```bash
sudo systemctl status rainshine                  # status
sudo systemctl stop rainshine                    # stop
sudo systemctl restart rainshine                 # restart
sudo systemctl disable rainshine                 # disable autostart
journalctl -u rainshine -f                       # live logs
systemctl show rainshine --property=NRestarts    # restart count
```

Redeploy after editing files:

```bash
cd ~/rainshine && git pull
sudo cp rainshine.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart rainshine
```

## Monitoring

Status is logged every 5 minutes with frame count, FPS, errors, and RSS:

```
2026-03-17 18:03:38 [INFO] Status: 18001 frames in 300s (60.0 fps), 0 send errors, 0 consecutive errors, RSS 101MB
```

```bash
ssh pi@PiDMX.local 'journalctl -u rainshine -f'
journalctl -u rainshine --since "1 hour ago" --no-pager | grep -E "ERROR|WARNING|Status:"
```

## Error Handling

- **Render/GPU errors** — caught and retried; exits after 50 consecutive failures for clean systemd restart
- **sACN send errors** — caught and retried with backoff
- **RSS watchdog** — exits cleanly if RSS exceeds 400MB; systemd restarts the process

## Customizing the Shader

To use a different GLSL animation:

1. Replace `rainshine.frag` with your own fragment shader (GLSL ES 3.0)
2. Ensure your shader has these uniforms:
   ```glsl
   uniform float uTime;              // elapsed time in seconds
   uniform float uSpeed;             // animation speed
   uniform int uTrailLen;            // trail/decay length
   uniform float uDensity;           // density/intensity multiplier
   ```
3. Restart: `sudo systemctl restart rainshine`

The renderer always outputs a 10×30 texture, so design for that aspect ratio.

## Future Enhancements

- [ ] **Motion sensor** — STHS34PF80 I2C integration to trigger animation on presence
- [ ] **Configurable grid size** — move COLS/ROWS to config file
- [ ] **Generic uniform binding** — auto-bind custom uniforms from config
- [ ] **Multi-destination sACN** — support multiple ENTTEC OCTOs
- [ ] **Pixel mapping presets** — zigzag, sequential, custom CSV layouts

See [Issues](https://github.com/jpkelly/PiDMX/issues) for planned work.

## Troubleshooting

**Service won't start:**
```bash
journalctl -u rainshine --no-pager | tail -20
sudo systemctl status rainshine
```

**Connection refused (OCTO):**
- Verify OCTO is on 10.0.0.123 and online: `ping 10.0.0.123`
- Check OCTO web UI for sACN input status

**No GPU acceleration:**
```bash
glxinfo | grep -i "opengl version"  # Should show ES 3.1
```

**Frame dropping / low fps:**
- Check RSS: `watch -n 1 'ps aux | grep rainshine_dmx.py'`
- Reduce FPS in config or shader complexity
- Monitor: `journalctl -u rainshine -f | grep Status`

## Resources

- [moderngl docs](https://moderngl.readthedocs.io/)
- [sACN/E1.31 spec](https://en.wikipedia.org/wiki/Architecture_for_Control_Networks)
- [ENTTEC Pixel OCTO manual](https://www.enttec.com/en/products/lighting-control/pixel-control/pixel-octo/)
- [Shadertoy](https://www.shadertoy.com/) — great reference for GLSL patterns

## License

MIT
- **Blackout on exit** — sends all-zero DMX data before shutting down

## Pixel Mapping

The strip is wired as a zigzag, column-major:
- Column 0: bottom → top (pixels 1–30)
- Column 1: top → bottom (pixels 31–60)
- Column 2: bottom → top, etc.

Universes are split at 510-channel (170-pixel) boundaries to keep RGB triplets intact.

## Network

| Device | IP | Purpose |
|---|---|---|
| Pi 5 | 10.0.0.127 | Shader rendering + sACN source |
| ENTTEC OCTO | 10.0.0.123 | sACN → WS2812B pixel driver |
| OLA Web UI | http://PiDMX.local:9090 | DMX universe management |
| ENTTEC Web UI | http://10.0.0.123 | OCTO configuration |

## Git Workflow

The project runs from the git repo at `~/rainshine/` on the Pi. After making changes:

```bash
cd ~/rainshine
git add -A
git commit -m "description of changes"
git push
```

If the service file changed, also run the redeploy commands above.
