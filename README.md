# Nassau power monitor

Tells you whether the electricity is on at the house by checking, every 10 minutes,
whether the home router answers from the internet. No hardware at the house, no
router changes beyond a sane firewall level.

## How it works

- The router is behind CGNAT on IPv4 but has a global IPv6 address. It refuses pings
  from the WAN, yet it *rejects* probes with an ICMPv6 message sent from its own
  address, so a traceroute to it ends with a reply from the router when it is up,
  and stops at the ISP's core when it is not.
- GitHub-hosted runners have no IPv6, so the traceroute is run by
  [Globalping](https://globalping.io) probes in North America and the runner only
  reads the verdict (`check.py`).
- Results are appended to `docs/log.csv`; `docs/status.json` holds the current
  state and the list of outages. An outage is declared after `CONFIRM_CHECKS`
  (default 2) consecutive failed checks and ends at the first successful one.
- `docs/index.html` is a static status page served by GitHub Pages: hero status,
  uptime, a timeline of checks and the outage table, in Nassau local time.

## Configuration (repository secrets)

| Secret | Required | Meaning |
|---|---|---|
| `TARGETS` | yes | Comma-separated IPv6 addresses of the router. The first is traced every time; the others only if the first does not reply. |
| `GLOBALPING_TOKEN` | no | Raises the Globalping rate limit. Unauthenticated use is enough for one check every 10 minutes. |

If the ISP hands the router a new IPv6 address after a reconnect, update `TARGETS`
(or point it at a DDNS name that follows the router).

## Running locally

```
TARGETS=2001:db8::1 python3 check.py
```

writes one row to `docs/log.csv` and refreshes `docs/status.json`.
