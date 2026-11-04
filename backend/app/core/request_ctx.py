"""Per-request details used by the audit log: the browser's device ID and a readable device description."""
import re
from contextvars import ContextVar

device_id_var: ContextVar[str | None] = ContextVar("device_id", default=None)
user_agent_var: ContextVar[str | None] = ContextVar("user_agent", default=None)

_DEVICE_RE = re.compile(r"^[A-Za-z0-9]{8,32}$")


def clean_device_id(raw: str | None) -> str | None:
    """The browser sends a random ID it generated once and keeps (X-Device-Id). Shown as e.g. PC-7F3A9C."""
    return raw if raw and _DEVICE_RE.match(raw) else None


def describe_user_agent(ua: str | None) -> str | None:
    """'Mozilla/5.0 (Windows NT 10.0; …) Chrome/130…' → 'Chrome 130 · Windows 10/11'."""
    if not ua:
        return None
    os_ = ("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else
           "Android" if "Android" in ua else "Windows 10/11" if "Windows NT 10" in ua else
           "Windows" if "Windows" in ua else "macOS" if "Mac OS X" in ua or "Macintosh" in ua else
           "ChromeOS" if "CrOS" in ua else "Linux" if "Linux" in ua else "Other")
    for name, pat in (("Edge", r"Edg(?:A|iOS)?/(\d+)"), ("Opera", r"OPR/(\d+)"), ("Samsung Internet", r"SamsungBrowser/(\d+)"),
                      ("Chrome", r"(?:Chrome|CriOS)/(\d+)"), ("Firefox", r"(?:Firefox|FxiOS)/(\d+)"),
                      ("Safari", r"Version/(\d+).*Safari")):
        m = re.search(pat, ua)
        if m:
            return f"{name} {m.group(1)} · {os_}"
    return f"Browser · {os_}" if os_ != "Other" else ua[:120]
