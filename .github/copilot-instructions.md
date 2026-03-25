# PiDMX — GitHub Copilot Project Instructions

## What This Is
A GLSL rainbow rain shader rendered headlessly on a Raspberry Pi 5, driving 300 WS2812B LEDs
via sACN/E1.31 DMX. Shader runs on the GPU; pixels are read back and sent as sACN UDP unicast
to an ENTTEC Pixel OCTO.

## Core Design Principle — DROP LIFECYCLE (NON-NEGOTIABLE)
- Drops **spawn off-screen** above the visible area (trailLen rows above the top edge).
- Once spawned, they **always travel their full lifecycle off the bottom**. NEVER hidden, clipped, masked, or interrupted mid-flight.
- Sensor trigger ON → spawn gate opens → new cycles form in the off-screen buffer → enter screen fully-formed.
- Sensor trigger OFF → spawn gate closes → no new cycles start → existing drops drain naturally off the bottom → screen goes dark on its own.
- **Do NOT implement**: drain timers, forced blackout, `params.active = 0.0` countdowns, masking, `uRevealRows`, or any mid-flight interruption.

## Hardware
- **Raspberry Pi 5** — Trixie Lite 64-bit, headless, `pi@pidmx.local` / `10.0.0.127`
- **ENTTEC Pixel OCTO** — sACN → WS2812B, `10.0.0.123`, web UI `http://10.0.0.123`
- **WS2812B LED strip** — 10 columns × 30 rows (300 pixels), zigzag column-major, GRB color order
- **STHS34PF80 IR sensor** — I2C `0x5A`, wired to header pins 1/3/5/6 (3.3V/SDA/SCL/GND)

## File Roles
- `rainshine.frag` — GLSL ES 3.0 fragment shader. Edit for visual changes.
- `rainshine_dmx.py` — Python host: render loop, sACN, OSC, sensor thread. Edit for logic changes.
- `rainshine.conf` — Live config on Pi (not committed to git; set via SSH or Transmit). Edit for tuning.
- `rainshine.service` — systemd unit. If changed, must `sudo cp` to `/etc/systemd/system/` and `daemon-reload`.
- `setup.sh` — One-time Pi setup only.

## Shader Uniforms
| Uniform | Type | Description |
|---|---|---|
| `uTime` | float | Elapsed seconds since start |
| `uSpeed` | float | Drop speed (pixels/sec, default 4.0) |
| `uTrailLen` | int | Trail length in pixels (default 10) |
| `uDensity` | float | ≥1: drops/column; <1: probability per cycle |
| `uActive` | float | 1.0 = rain on, 0.0 = dark (sensor gate) |
| `uSpawnGateStart` | float | uTime when gate opened (-1 = no gate) |
| `uSpawnGateStop` | float | uTime when gate closed (-1 = no gate) |

## Shader Virtual Canvas
```
virtual row 0                  ← top of off-screen spawn buffer
...
virtual row trailLen-1         ← last off-screen row (all drops fully formed here)
virtual row trailLen           ← TOP of visible screen (GL row ROWS-1)
...
virtual row trailLen+ROWS-1    ← BOTTOM of visible screen (GL row 0)
virtual row trailLen+ROWS ...  ← exit buffer below screen
```
- `cycleLen = ROWS + 2 * trailLen`
- `fragVirtual = trailLen + ROWS - 1 - row`
- `tSpawn = (cycleIdx * cycleLen - phase) / spdRate` — exact uTime cycle was spawned
- Spawn gate: `tSpawn >= uSpawnGateStart && tSpawn <= uSpawnGateStop`
- Trail: `dist = headVirtual - fragVirtual` (trail is ABOVE head, dist > 0)
- Hue: `fract(t + hash2(seed, cycleIdx))` — unique per cycle pass
- Brightness: `smoothstep(1.0, 0.0, t)` — smooth cubic fade to black at tail

## Sensor System
- `presence` = warm body in range (even still). `motion` = change in IR (movement).
- `motion_value` is **signed** — moving away = negative. ALWAYS use `abs(motion_value)` for thresholds.
- Spawn gate fires on `presence_hit OR motion_hit`, holds for `trigger_hold` seconds.
- `motion_scale` in `Params` multiplies `brightness` → `effective_brightness` in render loop.
- `motion_base` (config: `motion_brightness_base`) = floor at still presence.
- `motion_full` (config: `motion_brightness_full`) = motion_value that hits 1.0.
- EMA smoothing: `motion_ema = 0.15 * abs(motion_value) + 0.85 * motion_ema` — never snap to 0.
- **`brightness` in `[output]` should stay at `1.0`** — it's the ceiling; `motion_scale` operates within it.

## Params Snapshot (current order)
```python
speed, trail, density, fps, brightness, active, spawn_gate_start_abs, spawn_gate_stop_abs, motion_scale = params.snapshot()
```

## OSC Control (port 7700, live — no restart needed)
- `/rainshine/speed` float, `/rainshine/trail` int, `/rainshine/density` float
- `/rainshine/fps` float, `/rainshine/brightness` float

## Deploy Workflow
```bash
# Mac:
git add -A && git commit -m "message" && git push

# Pi (SSH):
cd ~/rainshine && git pull --ff-only origin main && sudo systemctl restart rainshine

# One-liner from Mac:
ssh pi@pidmx.local "cd ~/rainshine && git pull --ff-only origin main && sudo systemctl restart rainshine"
```

## Service Management
```bash
sudo systemctl start|stop|restart|status rainshine
journalctl -u rainshine -f
journalctl -u rainshine --since "1 hour ago" --no-pager | grep -E "ERROR|WARNING|Status:"
systemctl show rainshine --property=NRestarts
```

## Known Pitfalls
- Do NOT add `Type=notify` or `WatchdogSec` to the service — `sdnotify` is not installed.
- Do NOT use `ctx.finish()` in the render loop — causes Mesa V3D fence leak.
- `rainshine.conf` on Pi is NOT tracked in git (gitignored). Changes via `configparser` over SSH or Transmit.
- `motion_value` is signed — absent `abs()`, movement away from sensor won't register for threshold checks.
- `drain_deadline` / forced `active=0.0` are **abolished** — do not reintroduce.
