"""three priorities: P1 High, P2 Medium, P3 Low

Before: P1 Critical, P2 High, P3 Medium, P4 Low.  After: P1 High, P2 Medium, P3 Low.
Every ticket moves to the code that now carries its meaning (P2→P1, P3→P2, P4→P3; old P1 Critical → P1 High),
and each level keeps the SLA targets it had (High keeps High's targets, etc.).

Revision ID: 0010_three_priorities
Revises: 0009_department_category
Create Date: 2026-11-19 15:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010_three_priorities'
down_revision: Union[str, None] = '0009_department_category'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW = {"P1": ("High", "Significant impact on work or a key business process — handled first"),
       "P2": ("Medium", "Normal issue with a workaround or limited impact"),
       "P3": ("Low", "Low-impact query, suggestion or routine request")}


def upgrade() -> None:
    bind = op.get_bind()
    ids = dict(bind.execute(sa.text("SELECT code, id FROM priorities")).all())
    if not {"P1", "P2", "P3", "P4"} <= set(ids):
        return   # fresh database: the seed creates the three priorities directly
    p1, p2, p3, p4 = ids["P1"], ids["P2"], ids["P3"], ids["P4"]
    shift = (f"CASE {{col}} WHEN {p2} THEN {p1} WHEN {p3} THEN {p2} WHEN {p4} THEN {p3} ELSE {{col}} END")

    # tickets and routing rules follow the meaning of their priority
    bind.execute(sa.text(f"UPDATE tickets SET priority_id = {shift.format(col='priority_id')}"))
    bind.execute(sa.text(f"UPDATE automation_rules SET match_priority_id = {shift.format(col='match_priority_id')} "
                         "WHERE match_priority_id IS NOT NULL"))

    # SLA policies: each level keeps the targets it had (High's targets move to P1, …). Rows are merged/moved in
    # order P2→P1, P3→P2, P4→P3; SLA records of open tickets are re-pointed before any row is removed.
    rows = bind.execute(sa.text("SELECT id, priority_id, category_id, response_minutes, resolution_minutes "
                                "FROM sla_policies")).all()
    by_key = {(r.priority_id, r.category_id): r for r in rows}
    for old, new in ((p2, p1), (p3, p2), (p4, p3)):
        for (pid, cid), r in list(by_key.items()):
            if pid != old:
                continue
            target = by_key.get((new, cid))
            if target is not None:      # a row already exists at the new level
                if cid is None:          # general targets: the new level takes this row's targets
                    bind.execute(sa.text("UPDATE sla_policies SET response_minutes = :a, resolution_minutes = :b "
                                         "WHERE id = :i"), {"a": r.response_minutes, "b": r.resolution_minutes,
                                                             "i": target.id})
                bind.execute(sa.text("UPDATE sla_tracking SET policy_id = :t WHERE policy_id = :o"),
                             {"t": target.id, "o": r.id})
                bind.execute(sa.text("DELETE FROM sla_policies WHERE id = :o"), {"o": r.id})
            else:
                bind.execute(sa.text("UPDATE sla_policies SET priority_id = :n WHERE id = :i"), {"n": new, "i": r.id})
                by_key[(new, cid)] = r
            del by_key[(pid, cid)]
    bind.execute(sa.text("UPDATE sla_policies SET name = 'Standard ' || "
                         "(SELECT code FROM priorities WHERE priorities.id = sla_policies.priority_id) "
                         "WHERE category_id IS NULL AND name LIKE 'Standard P%'"))

    # employee form: impact is Medium (2), so urgency High/Medium/Low → P1/P2/P3
    for i in (1, 2, 3):
        for u in (1, 2, 3):
            s = i + u
            pid = p1 if s <= 3 else p2 if s == 4 else p3
            bind.execute(sa.text(f"UPDATE priority_matrix SET priority_id = {pid} WHERE impact = {i} AND urgency = {u}"))

    for code, (name, desc) in NEW.items():
        bind.execute(sa.text("UPDATE priorities SET name = :n, description = :d, rank = :r WHERE code = :c"),
                     {"n": name, "d": desc, "r": int(code[1]), "c": code})
    # P4 is no longer used anywhere
    used = bind.execute(sa.text(
        f"SELECT (SELECT COUNT(*) FROM tickets WHERE priority_id = {p4}) + "
        f"(SELECT COUNT(*) FROM sla_policies WHERE priority_id = {p4}) + "
        f"(SELECT COUNT(*) FROM priority_matrix WHERE priority_id = {p4}) + "
        f"(SELECT COUNT(*) FROM automation_rules WHERE match_priority_id = {p4})")).scalar()
    if not used:
        bind.execute(sa.text(f"DELETE FROM priorities WHERE id = {p4}"))


def downgrade() -> None:
    # Not reversible automatically (tickets were merged from four levels into three).
    pass
