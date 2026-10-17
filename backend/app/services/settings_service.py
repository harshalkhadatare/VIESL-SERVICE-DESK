from sqlalchemy.orm import Session

from app.models import ApplicationSetting

DEFAULTS: dict[str, tuple[str, str]] = {
    "reopen_window_days": ("7", "Days after resolution during which the requester may reopen"),
    "auto_close_after_days": ("5", "Business days after resolution before auto-closure (0 disables)"),
    "auto_close_reminder_days": ("3", "Days after resolution to remind requester to confirm"),
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
