#!/usr/bin/env python3
"""
Baseline monitor for Rainshine.
Logs system + process metrics to CSV every 60s.
Stores rolling baseline stats in a JSON file.
Usage:
    python3 baseline_monitor.py          # start monitoring (foreground)
    python3 baseline_monitor.py --report # print current baseline report
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("/home/pi/rainshine/monitor_data")
CSV_PATH = DATA_DIR / "metrics.csv"
BASELINE_PATH = DATA_DIR / "baseline.json"
PIDFILE = DATA_DIR / "monitor.pid"
INTERVAL = 60  # seconds between samples

DATA_DIR.mkdir(parents=True, exist_ok=True)


def read_rainshine_pid():
    try:
        out = os.popen("pgrep -f 'python3 .*rainshine_dmx.py' | head -1").read().strip()
        return int(out) if out else None
    except Exception:
        return None


def read_proc_stat(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().split()
        # utime is field 14, stime is 15, vsize is 23, rss is 24
        return {
            "utime": int(parts[13]),
            "stime": int(parts[14]),
            "vsize": int(parts[22]),
            "rss": int(parts[23]),
        }
    except Exception:
        return None


def read_proc_fd_count(pid):
    try:
        return len(os.listdir(f"/proc/{pid}/fd"))
    except Exception:
        return None


def read_proc_threads(pid):
    try:
        return len(os.listdir(f"/proc/{pid}/task"))
    except Exception:
        return None


def read_system_metrics():
    # Load
    with open("/proc/loadavg") as f:
        load1 = float(f.read().split()[0])

    # CPU times
    with open("/proc/stat") as f:
        line = f.readline()
    parts = line.split()
    user, nice, system, idle, iowait = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
    cpu_total = user + nice + system + idle + iowait
    cpu_used = user + nice + system

    # Memory
    mem_avail = None
    mem_total = None
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                mem_avail = int(line.split()[1])
            elif line.startswith("MemTotal:"):
                mem_total = int(line.split()[1])
    mem_avail_mb = mem_avail / 1024 if mem_avail else None
    mem_total_mb = mem_total / 1024 if mem_total else None

    # Temp
    temp_c = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp_c = int(f.read().strip()) / 1000
    except Exception:
        pass

    # GPU throttle
    gpu_throttle = None
    try:
        gpu_throttle = os.popen("vcgencmd get_throttled 2>/dev/null").read().strip().split("=")[-1]
    except Exception:
        pass

    # Disk free
    disk_free_gb = None
    try:
        st = os.statvfs("/home/pi")
        disk_free_gb = (st.f_bavail * st.f_frsize) / (1024**3)
    except Exception:
        pass

    # Uptime
    uptime_sec = None
    try:
        with open("/proc/uptime") as f:
            uptime_sec = float(f.read().split()[0])
    except Exception:
        pass

    return {
        "load1": load1,
        "cpu_total": cpu_total,
        "cpu_used": cpu_used,
        "mem_avail_mb": mem_avail_mb,
        "mem_total_mb": mem_total_mb,
        "temp_c": temp_c,
        "gpu_throttle": gpu_throttle,
        "disk_free_gb": disk_free_gb,
        "uptime_sec": uptime_sec,
    }


def read_v3d_bos():
    """Try to read V3D buffer object count from debugfs."""
    try:
        # Try different possible paths
        paths = [
            "/sys/kernel/debug/dri/0/v3d_bos",
            "/sys/kernel/debug/dri/1/v3d_bos",
        ]
        for p in paths:
            if os.path.exists(p):
                # Count non-empty lines
                with open(p) as f:
                    return sum(1 for line in f if line.strip())
    except Exception:
        pass
    return None


def read_journal_size():
    try:
        out = os.popen("journalctl --disk-usage 2>/dev/null").read().strip()
        # "Archived and active journals take up ... in the file system."
        if "take up" in out:
            # Extract number — handles "149.2M", "1.2G", etc.
            import re
            m = re.search(r'([\d.]+)\s*([KMGT]?)', out)
            if m:
                size = float(m.group(1))
                suffix = m.group(2)
                if suffix == 'G':
                    size *= 1024
                elif suffix == 'T':
                    size *= 1024 * 1024
                elif suffix == 'K':
                    size /= 1024
                # 'M' or no suffix = already in MB
                return size
    except Exception:
        pass
    return None


def sample(prev_cpu_total=None, prev_cpu_used=None, prev_rain_cpu=None):
    sys_m = read_system_metrics()
    pid = read_rainshine_pid()

    rain_stat = read_proc_stat(pid) if pid else None
    rain_fd = read_proc_fd_count(pid) if pid else None
    rain_threads = read_proc_threads(pid) if pid else None
    v3d_bos = read_v3d_bos()
    journal_mb = read_journal_size()

    # Calculate CPU percentages
    cpu_percent = None
    if prev_cpu_total is not None and prev_cpu_used is not None:
        cpu_delta = sys_m["cpu_total"] - prev_cpu_total
        used_delta = sys_m["cpu_used"] - prev_cpu_used
        if cpu_delta > 0:
            cpu_percent = 100.0 * used_delta / cpu_delta

    rain_cpu_percent = None
    if prev_rain_cpu is not None and rain_stat:
        rain_cpu_now = rain_stat["utime"] + rain_stat["stime"]
        rain_delta = rain_cpu_now - prev_rain_cpu
        if cpu_delta and cpu_delta > 0:
            rain_cpu_percent = 100.0 * rain_delta / cpu_delta

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_sec": sys_m["uptime_sec"],
        "load1": round(sys_m["load1"], 3),
        "cpu_percent": round(cpu_percent, 2) if cpu_percent is not None else None,
        "mem_avail_mb": round(sys_m["mem_avail_mb"], 1) if sys_m["mem_avail_mb"] else None,
        "mem_total_mb": round(sys_m["mem_total_mb"], 1) if sys_m["mem_total_mb"] else None,
        "temp_c": round(sys_m["temp_c"], 1) if sys_m["temp_c"] else None,
        "gpu_throttle": sys_m["gpu_throttle"],
        "disk_free_gb": round(sys_m["disk_free_gb"], 2) if sys_m["disk_free_gb"] else None,
        "rain_pid": pid,
        "rain_rss_mb": round(rain_stat["rss"] * 4096 / 1024 / 1024, 1) if rain_stat else None,
        "rain_vsz_mb": round(rain_stat["vsize"] / 1024 / 1024, 1) if rain_stat else None,
        "rain_cpu_percent": round(rain_cpu_percent, 2) if rain_cpu_percent is not None else None,
        "rain_fds": rain_fd,
        "rain_threads": rain_threads,
        "v3d_bos": v3d_bos,
        "journal_mb": journal_mb,
    }

    return row, sys_m["cpu_total"], sys_m["cpu_used"], rain_stat["utime"] + rain_stat["stime"] if rain_stat else None


def update_baseline(all_rows):
    """Compute rolling baseline from last 24h of data."""
    if len(all_rows) < 10:
        return

    numeric_keys = [
        "load1", "cpu_percent", "mem_avail_mb", "temp_c",
        "rain_rss_mb", "rain_vsz_mb", "rain_cpu_percent",
        "rain_fds", "rain_threads", "v3d_bos",
    ]

    baseline = {}
    for key in numeric_keys:
        vals = [float(r[key]) for r in all_rows if r.get(key) not in (None, "")]
        if not vals:
            continue
        vals.sort()
        n = len(vals)
        baseline[key] = {
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
            "mean": round(sum(vals) / n, 3),
            "p50": round(vals[n // 2], 3),
            "p95": round(vals[int(n * 0.95)], 3) if n > 20 else round(max(vals), 3),
            "samples": n,
        }

    baseline["updated"] = datetime.now(timezone.utc).isoformat()
    baseline["total_samples"] = len(all_rows)
    with open(BASELINE_PATH, "w") as f:
        json.dump(baseline, f, indent=2)


def print_report():
    if not BASELINE_PATH.exists():
        print("No baseline found. Run monitor for a while first.")
        return
    with open(BASELINE_PATH) as f:
        baseline = json.load(f)

    print(f"Baseline updated: {baseline.get('updated', 'unknown')}")
    print(f"Total samples: {baseline.get('total_samples', 0)}")
    print()
    print(f"{'Metric':<20} {'Min':>10} {'Mean':>10} {'P95':>10} {'Max':>10}")
    print("-" * 65)
    for key, stats in baseline.items():
        if isinstance(stats, dict) and "mean" in stats:
            print(f"{key:<20} {stats['min']:>10.2f} {stats['mean']:>10.2f} {stats['p95']:>10.2f} {stats['max']:>10.2f}")


def main():
    if "--report" in sys.argv:
        print_report()
        return

    # Check for existing instance
    if PIDFILE.exists():
        try:
            old_pid = int(PIDFILE.read_text().strip())
            if os.path.exists(f"/proc/{old_pid}"):
                print(f"Monitor already running (PID {old_pid}).")
                print("Stop it first with: kill", old_pid)
                sys.exit(1)
        except Exception:
            pass

    PIDFILE.write_text(str(os.getpid()))
    print(f"Baseline monitor started (PID {os.getpid()}). Logging every {INTERVAL}s.")
    print(f"Data: {CSV_PATH}")
    print(f"Baseline: {BASELINE_PATH}")
    print("Stop with Ctrl-C or: kill", os.getpid())

    fieldnames = [
        "timestamp", "uptime_sec", "load1", "cpu_percent",
        "mem_avail_mb", "mem_total_mb", "temp_c", "gpu_throttle",
        "disk_free_gb", "rain_pid", "rain_rss_mb", "rain_vsz_mb",
        "rain_cpu_percent", "rain_fds", "rain_threads", "v3d_bos", "journal_mb",
    ]

    write_header = not CSV_PATH.exists()
    prev_cpu_total = None
    prev_cpu_used = None
    prev_rain_cpu = None
    rows_since_baseline = 0

    try:
        with open(CSV_PATH, "a", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()

            while True:
                row, prev_cpu_total, prev_cpu_used, prev_rain_cpu = sample(
                    prev_cpu_total, prev_cpu_used, prev_rain_cpu
                )
                writer.writerow(row)
                csvfile.flush()
                rows_since_baseline += 1

                if rows_since_baseline >= 60:  # recompute baseline every hour
                    # Read all rows for baseline computation
                    with open(CSV_PATH, newline="") as f:
                        all_rows = list(csv.DictReader(f))
                    # Convert numeric strings back to float
                    for r in all_rows:
                        for k in fieldnames:
                            if k in r and r[k] != "" and k not in ("timestamp", "gpu_throttle"):
                                try:
                                    r[k] = float(r[k])
                                except ValueError:
                                    pass
                    update_baseline(all_rows)
                    rows_since_baseline = 0
                    print(f"[{row['timestamp']}] Baseline updated ({len(all_rows)} samples)")

                time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
    finally:
        PIDFILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
