"""ntfy push transport for alerts.

The server POSTs outbound to an ntfy topic; the phone subscribes to it. Nothing
about the Horizon box is exposed publicly. Server + topic come from settings
(`ntfy_server`, `ntfy_topic`) so you can start on ntfy.sh with a long random
topic and later self-host with no code change.

Title reflects both which list the ticker is in (BUY / HELD) and what the signal
wants (BUY / ADD / SELL). Titles are kept ASCII because ntfy carries them in an
HTTP header, which urllib encodes as latin-1:
    Buy  + BUY  -> "Horizon BUY: AAPL"
    Held + BUY  -> "Horizon HELD ADD: AAPL"
    Held + SELL -> "Horizon HELD SELL: AAPL"
"""
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from db import get_setting


def action_for(bucket, signal_dir):
    """Map (bucket, raw signal direction) to the user-facing action word."""
    if bucket == "HELD" and signal_dir == "BUY":
        return "ADD"
    return signal_dir  # BUY (buy list) or SELL


def build_title(bucket, action, ticker):
    # ASCII only — see module docstring (HTTP header is latin-1).
    if bucket == "HELD":
        return f"Horizon HELD {action}: {ticker}"
    return f"Horizon BUY: {ticker}"


def _ascii_header(s):
    """Make a header value safe for latin-1 transport (drop non-latin-1)."""
    return s.encode("ascii", "replace").decode("ascii")


def _endpoint():
    server = (get_setting("ntfy_server", "https://ntfy.sh") or "").rstrip("/")
    topic = (get_setting("ntfy_topic", "") or "").strip()
    if not server or not topic:
        return None
    return f"{server}/{topic}"


def push(title, body, priority=None, tags=None):
    """POST a message to the configured ntfy topic.

    Returns (ok, error). ok is False with a reason if the topic isn't configured
    or the POST fails — the caller records that in alert_log.
    """
    url = _endpoint()
    if not url:
        return False, "ntfy topic not configured"
    headers = {"Title": _ascii_header(title), "Content-Type": "text/plain; charset=utf-8"}
    if priority:
        headers["Priority"] = str(priority)
    if tags:
        headers["Tags"] = ",".join(tags)
    try:
        req = Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
        with urlopen(req, timeout=15) as resp:
            resp.read()
        return True, None
    except Exception as e:  # never let a single bad push abort the whole run
        return False, str(e)


def push_signal(bucket, kind, signal_dir, ticker, price, rsi=None, d=None):
    """Build + send a signal push. Returns (ok, error, title, body)."""
    action = action_for(bucket, signal_dir)
    title = build_title(bucket, action, ticker)
    parts = [f"@ {price:.2f}"] if price is not None else []
    detail = []
    if rsi is not None:
        detail.append(f"RSI {rsi:.0f}")
    if d is not None:
        detail.append(f"%D {d:.0f}")
    if detail:
        parts.append(", ".join(detail))
    parts.append(f"({kind})")
    body = " · ".join(parts)
    tags = ["chart_with_upwards_trend"] if signal_dir == "BUY" else ["chart_with_downwards_trend"]
    ok, err = push(title, body, priority=(4 if signal_dir == "SELL" else 3), tags=tags)
    return ok, err, title, body


def send_test():
    """Send a test push so the user can confirm their phone is wired up."""
    return push("Horizon test", "Alerts are configured correctly.", tags=["white_check_mark"])
