from sqlalchemy.orm import Session

from app.models import ApplicationSetting

DEFAULTS: dict[str, tuple[str, str]] = {
    "reopen_window_days": ("7", "Days after resolution during which the requester may reopen"),
    "no_reply_close_days": ("3", "Days without a reply from the employee after IT's last message (a public reply "
                                 "or Resolved) before the ticket closes automatically (0 disables)"),
    "duplicate_lookback_days": ("7", "Days to look back for likely duplicate tickets"),
    "recurring_issue_threshold": ("5", "Same category+subcategory tickets in 24h that alert IT leads"),
    "anonymous_suggestions_enabled": ("false", "Allow anonymous suggestions (future module)"),
}


def get_setting(db: Session, key: str) -> str:
    row = db.get(ApplicationSetting, key)
    if row:
        return row.value
    return DEFAULTS[key][0]


def get_int(db: Session, key: str) -> int:
    try:
        return int(get_setting(db, key))
    except (TypeError, ValueError):
        return int(DEFAULTS[key][0])
