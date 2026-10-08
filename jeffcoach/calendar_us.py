"""Calendario NYSE e orari, indipendenti dall'ora legale europea.

L'apertura USA in ora di Roma NON è sempre 15:30: nelle settimane in cui Europa e USA
cambiano ora in date diverse (fine marzo, fine ottobre/inizio novembre) è alle 14:30.
Per questo tutti gli orari di mercato si calcolano in America/New_York.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROME = ZoneInfo("Europe/Rome")

# Festività NYSE (borsa chiusa). Aggiornare a fine 2027.
NYSE_HOLIDAYS = {
    # 2025
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
# Chiusura anticipata alle 13:00 ET
NYSE_HALF_DAYS = {"2025-07-03", "2025-11-28", "2025-12-24", "2026-11-27", "2026-12-24", "2027-11-26"}


def is_session(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS


def next_session(d: date) -> date:
    d = d + timedelta(days=1)
    while not is_session(d):
        d += timedelta(days=1)
    return d


def prev_session(d: date) -> date:
    d = d - timedelta(days=1)
    while not is_session(d):
        d -= timedelta(days=1)
    return d


def sessions_from(d: date, n: int) -> list[date]:
    """n sedute a partire da d compresa (d deve essere una seduta)."""
    out = [d] if is_session(d) else []
    cur = d
    while len(out) < n:
        cur = next_session(cur)
        out.append(cur)
    return out


def last_sessions(until: date, n: int) -> list[date]:
    """Le ultime n sedute fino a `until` compresa."""
    out = [until] if is_session(until) else []
    cur = until
    while len(out) < n:
        cur = prev_session(cur)
        out.insert(0, cur)
    return out


def open_et(d: date) -> datetime:
    return datetime.combine(d, time(9, 30), tzinfo=ET)


def close_et(d: date) -> datetime:
    return datetime.combine(d, time(13, 0) if d.isoformat() in NYSE_HALF_DAYS else time(16, 0), tzinfo=ET)


def today_rome() -> date:
    return datetime.now(ROME).date()


def now_et() -> datetime:
    return datetime.now(ET)


def session_for_list(now_rome: datetime | None = None) -> date | None:
    """La seduta per cui si prepara la lista del mattino (oggi, se oggi si tratta)."""
    d = (now_rome or datetime.now(ROME)).astimezone(ROME).date()
    return d if is_session(d) else None
