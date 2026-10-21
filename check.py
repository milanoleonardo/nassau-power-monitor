#!/usr/bin/env python3
"""Check whether the house router answers from the internet, and update the log.

The router sits behind CGNAT on IPv4 but has a global IPv6 address. It does not
answer ICMP echo from the WAN, but it *rejects* probes with an ICMPv6 message sent
from its own address, which a traceroute reports as the final hop. GitHub's runners
have no IPv6, so the traceroute is run by Globalping probes (https://globalping.io)
and only the verdict is recorded here.

Rule: if any probe's trace ends with a reply from the router -> "up".
      if every probe finished and none reached it         -> "down".
      anything else (API error, timeouts on the API side)  -> "unknown".

An outage is declared only after CONFIRM_CHECKS consecutive "down" results, so a
single bad measurement never shows up as a power cut. When the state flips to
"down" (and again when it comes back "up") an email goes out via notify.py.
"""
import csv
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import notify

API = "https://api.globalping.io/v1/measurements"
DOCS = Path(__file__).resolve().parent / "docs"
LOG = DOCS / "log.csv"
STATUS = DOCS / "status.json"

PROBES = int(os.environ.get("PROBES", "3"))
CONFIRM = int(os.environ.get("CONFIRM_CHECKS", "2"))
TOKEN = os.environ.get("GLOBALPING_TOKEN", "").strip()
TARGETS = [t.strip() for t in os.environ.get("TARGETS", "").split(",") if t.strip()]


def api(method, url, body=None):
    headers = {"Content-Type": "application/json", "User-Agent": "nassau-power-monitor"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def same_address(a, b):
    try:
        return ipaddress.ip_address(a) == ipaddress.ip_address(b)
    except ValueError:
        return False


def trace(target):
    """Run one traceroute measurement; return (result, probes_up, probes_done, best_rtt_ms)."""
    try:
        created = api("POST", API, {
            "type": "traceroute",
            "target": target,
            "limit": PROBES,
            "locations": [{"continent": "NA"}],
            "measurementOptions": {"protocol": "ICMP"},
        })
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"globalping request failed: {e}", file=sys.stderr)
        return "unknown", 0, 0, None

    mid = created["id"]
    deadline = time.time() + 120
    while True:
        time.sleep(6)
        try:
            m = api("GET", f"{API}/{mid}")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"globalping poll failed: {e}", file=sys.stderr)
            if time.time() > deadline:
                return "unknown", 0, 0, None
            continue
        if m["status"] != "in-progress" or time.time() > deadline:
            break

    probes_done = probes_up = 0
    best_rtt = None
    for r in m["results"]:
        res = r["result"]
        if res["status"] != "finished":
            continue
        probes_done += 1
        for hop in res.get("hops") or []:
            if same_address(hop.get("resolvedAddress") or "", target):
                probes_up += 1
                rtts = [t["rtt"] for t in hop.get("timings", []) if t.get("rtt") is not None]
                if rtts and (best_rtt is None or min(rtts) < best_rtt):
                    best_rtt = round(min(rtts), 1)
                break

    if probes_up:
        return "up", probes_up, probes_done, best_rtt
    if probes_done == 0:
        return "unknown", 0, 0, None
    return "down", 0, probes_done, None


def run_checks():
    """Trace the primary target; fall back to the others only when it fails."""
    for target in TARGETS:
        result, up, done, rtt = trace(target)
        print(f"target #{TARGETS.index(target) + 1}: {result} ({up}/{done} probes reached it)")
        if result == "up":
            return result, up, done, rtt
    return result, up, done, rtt


def read_log():
    if not LOG.exists():
        return []
    with LOG.open() as f:
        return list(csv.DictReader(f))


def append_log(row):
    new = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "result", "probes_up", "probes_done", "rtt_ms"])
        if new:
            w.writeheader()
        w.writerow(row)


def build_status(rows):
    """Replay the log into the current state and the list of confirmed outages."""
    state = since = None
    outages = []
    streak = 0
    first_down = None
    for r in rows:
        res = r["result"]
        if res == "unknown":
            continue
        if res == "down":
            streak += 1
            if streak == 1:
                first_down = r["ts"]
            if streak >= CONFIRM and state != "down":
                state, since = "down", first_down
                outages.append({"start": first_down, "end": None})
        else:
            streak = 0
            if state == "down":
                outages[-1]["end"] = r["ts"]
            if state != "up":
                state, since = "up", r["ts"]

    for o in outages:
        end = o["end"] or rows[-1]["ts"]
        o["duration_s"] = int((parse(end) - parse(o["start"])).total_seconds())

    last = rows[-1]
    return {
        "state": state or "unknown",
        "since": since,
        "last_check": last["ts"],
        "last_result": last["result"],
        "probes_up": int(last["probes_up"]),
        "probes_done": int(last["probes_done"]),
        "rtt_ms": float(last["rtt_ms"]) if last["rtt_ms"] else None,
        "confirm_checks": CONFIRM,
        "log_start": rows[0]["ts"],
        "checks_total": len(rows),
        "outages": list(reversed(outages)),
    }


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main():
    if not TARGETS:
        sys.exit("TARGETS is not set")
    DOCS.mkdir(exist_ok=True)
    previous = read_log()
    before = build_status(previous) if previous else None
    result, up, done, rtt = run_checks()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    append_log({"ts": now, "result": result, "probes_up": up, "probes_done": done,
                "rtt_ms": "" if rtt is None else rtt})
    status = build_status(read_log())
    STATUS.write_text(json.dumps(status, indent=1) + "\n")
    print(f"{now}: {result} -> state={status['state']} since {status['since']}")
    notify.on_transition(before, status)


if __name__ == "__main__":
    main()
