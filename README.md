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
- When the state flips to "down", `notify.py` emails everyone in `ALERT_TO`; a second
  email goes out when the router answers again, with the outage duration.
- `docs/index.html` is a static status page served by GitHub Pages: hero status,
  uptime, a timeline of checks and the outage table, in Nassau local time.

## Configuration (repository secrets)

| Secret | Required | Meaning |
|---|---|---|
| `TARGETS` | yes | Comma-separated IPv6 addresses of the router. The first is traced every time; the others only if the first does not reply. |
| `GLOBALPING_TOKEN` | no | Raises the Globalping rate limit. Unauthenticated use is enough for one check every 10 minutes. |
| `ALERT_TO` | for email | Comma-separated recipients of outage emails. |
| `SMTP_USER` | for email | Mailbox the alerts are sent from (its full address). |
| `SMTP_PASSWORD` | for email | An *app password* for that mailbox, not the normal login password. |
| `SMTP_HOST` | no | Default `smtp.gmail.com`. Use `smtp.mail.yahoo.com` for Yahoo. |
| `SMTP_PORT` | no | Default `465` (SSL). `587` switches to STARTTLS. |

Email is skipped, and the check still runs, until `SMTP_USER`, `SMTP_PASSWORD` and
`ALERT_TO` are all set. To get an app password: Gmail → Google Account → Security →
2-Step Verification → App passwords; Yahoo → Account Security → Generate app password.
To verify the setup, run the `check-power` workflow by hand with **Send a test email**
ticked.

If the ISP hands the router a new IPv6 address after a reconnect, update `TARGETS`
(or point it at a DDNS name that follows the router).

## Running locally

```
TARGETS=2001:db8::1 python3 check.py
```

writes one row to `docs/log.csv` and refreshes `docs/status.json`. With the SMTP
variables set, `python3 notify.py` sends a test email.
