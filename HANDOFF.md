# PiDMX — Session Handoff
_Last updated: 2026-05-23_

## Current State: WORKING ✓ — Baseline Monitor Active

The installation is live, deployed, and running on the Pi. A system-health baseline monitor is now logging continuously to catch a suspected long-term slowdown/leak (weeks-to-months timescale). No code changes were made to the shader or Python host.

---

## What Was Built This Session

### Baseline Monitor (new)
- **`/home/pi/rainshine/baseline_monitor.py`** — logs system + process metrics every 60s to `/home/pi/rainshine/monitor_data/metrics.csv`
- Rolling baseline stats (min/mean/p95/max) recomputed hourly to `baseline.json`
- Tracks: RSS, VSZ, FD count, thread count, V3D BO count, load, temp, GPU throttle, memory, disk, journal size
- **`baseline_monitor.service`** — systemd unit, enabled, auto-starts on boot
- **`/home/pi/rainshine/monitor_report.sh`** — one-shot report: current state vs baseline

### Session Context
- Shader and Python code were **not modified** (user request)
- Suspected issue: after weeks-to-months of uptime, animation slows down; reboot fixes it
- Current hypothesis: long-term memory/FD/V3D leak, or shader `uTime` precision loss in `mediump float`
- Next step: wait for slowdown, then SSH in and compare live metrics against baseline

### Spawn-Gate Architecture (replaces all masking)
- Drops always spawn in an off-screen buffer `trailLen` rows above the visible panel.
  Once spawned, they travel their full lifecycle off the bottom, **never interrupted**.
- Sensor ON → spawn gate opens → drops form off-screen and enter fully-formed from top.
- Sensor OFF → spawn gate closes → existing drops drain naturally → screen goes dark on its own.

### Motion-Driven Brightness
- Still presence → dim (`motion_brightness_base`, currently `0.01`)
- Active movement → bright (climbs toward `1.0` as `motion_value` rises)
- EMA-smoothed (α=0.15) — no flicker, no snapping
- `brightness` config key is the ceiling (keep at `1.0`); `motion_scale` operates within it

### Visual Fixes
- Trail direction corrected (trail is now **above** the head, behind the falling drop)
- Hue randomised per-cycle pass (`hash2(seed, cycleIdx)`) — each drop has a new color every time
- Trail fade: `smoothstep(1.0, 0.0, t)` — smooth cubic ease to black at tail

---

## Current Pi Config (`~/rainshine/rainshine.conf`)
```ini
[shader]
speed = 25.0
trail = 25
density = 0.5

[output]
fps = 60.0
universe = 1
color_order = grb
brightness = 1.0
sacn_dest = 10.0.0.123

[osc]
port = 7700

[sensor]
enabled = true
trigger_hold = 5.0
presence_threshold = 2.0
motion_threshold = 5.0
trigger_hits = 1
motion_brightness_base = 0.01
motion_brightness_full = 150.0
```

---

## Current Git State
- **Repo**: `jpkelly/PiDMX`, branch `main`
- **Latest commit**: `d21a99c` — `Remove entry spawn buffer — drops appear instantly at top edge`
- Mac workspace: `/Users/jp/Documents/GitHub/PiDMX`
- Pi repo: `~/rainshine/`
- Pi process uptime: ~2 days, 6 hours
- Current health: 60.0 fps, RSS 106 MB, 12 FDs, 10 threads, temp 38–40°C, no throttling

---

## Key Technical Details

### Shader Uniforms
`uTime`, `uSpeed`, `uTrailLen`, `uDensity`, `uActive`, `uSpawnGateStart`, `uSpawnGateStop`

### Params Snapshot Order
```python
speed, trail, density, fps, brightness, active, spawn_gate_start_abs, spawn_gate_stop_abs, motion_scale
```

### Effective Brightness Formula
```python
effective_brightness = params.brightness * params.motion_scale
```

### Sensor Thread Key Facts
- `motion_value` is **signed** — `abs()` is required for threshold comparisons
- EMA never snaps to zero — always let it decay naturally
- `trigger_hits = 1` for fastest response; raise to 2-3 if false triggers occur

---

## Tuning Knobs (via `rainshine.conf` on Pi, restart needed)

| Key | Location | Effect |
|---|---|---|
| `speed` | `[shader]` | Drop fall speed |
| `trail` | `[shader]` | Trail length in pixels |
| `density` | `[shader]` | Drops per column (≥1) or probability (<1) |
| `fps` | `[output]` | Render rate |
| `brightness` | `[output]` | **Keep at 1.0** — ceiling for motion_scale |
| `trigger_hold` | `[sensor]` | Seconds of inactivity before gate closes |
| `presence_threshold` | `[sensor]` | Raw presence_value floor to count as hit |
| `motion_threshold` | `[sensor]` | Raw abs(motion_value) floor to count as hit |
| `motion_brightness_base` | `[sensor]` | Dim floor brightness when still (0.0–1.0) |
| `motion_brightness_full` | `[sensor]` | motion_value that maps to full brightness |

---

## Live OSC Control (no restart, from any machine on the network)
```bash
# From Mac command line:
python3 -c "
from pythonosc.udp_client import SimpleUDPClient
c = SimpleUDPClient('pidmx.local', 7700)
c.send_message('/rainshine/brightness', 0.8)
"
# Addresses: /rainshine/speed, /rainshine/trail, /rainshine/density, /rainshine/fps, /rainshine/brightness
```

---

## Open Ideas / Future Work
1. **Density driven by motion** — more drops when moving, fewer when still
2. **Speed driven by motion** — drops fall faster with more energetic movement
3. **Multiple shaders** — config key to switch which `.frag` is loaded at startup
4. **Move COLS/ROWS to config** — currently hardcoded as constants in both Python and shader
5. **Multi-destination sACN** — comma-separated IPs in `sacn_dest` for multiple OCTO units

---

## Diagnostics

### Rainshine Service
```bash
# Live logs
journalctl -u rainshine -f

# Recent errors only
journalctl -u rainshine --since "1 hour ago" --no-pager | grep -E "ERROR|WARNING|Status:"

# Restart count
systemctl show rainshine --property=NRestarts

# Memory check
free -h
```

### Baseline Monitor
```bash
# Quick report (current state vs rolling baseline)
/home/pi/rainshine/monitor_report.sh

# Raw metrics
head -1 /home/pi/rainshine/monitor_data/metrics.csv
tail -20 /home/pi/rainshine/monitor_data/metrics.csv

# Baseline stats
python3 -c "import json; print(json.dumps(json.load(open('/home/pi/rainshine/monitor_data/baseline.json')), indent=2))"

# Monitor service status
systemctl status baseline_monitor --no-pager
journalctl -u baseline_monitor -f
```

### When Slowdown Occurs
1. Run `/home/pi/rainshine/monitor_report.sh` on the Pi
2. Check which metrics have drifted from baseline (RSS, FDs, V3D BOs, load, temp)
3. Do NOT reboot until diagnostics are captured
