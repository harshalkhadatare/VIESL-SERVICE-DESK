"""Per-request details used by the audit log: a readable browser/device description (no device IDs are collected)."""
import re
from contextvars import ContextVar

user_agent_var: ContextVar[str | None] = ContextVar("user_agent", default=None)

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
