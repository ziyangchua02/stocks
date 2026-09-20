from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from app.models import iso, utcnow


class MarketClock:
    def __init__(self, name="NYSE", timezone="America/New_York"):
        self.calendar = mcal.get_calendar(name)
        self.timezone = ZoneInfo(timezone)
        self._schedules = {}

    def schedule(self, day):
        if day.year not in self._schedules:
            self._schedules[day.year] = self.calendar.schedule(
                start_date=f"{day.year - 1}-12-01", end_date=f"{day.year + 1}-01-15"
            )
        return self._schedules[day.year]

    def state(self, now: datetime | None = None):
        now = now or utcnow()
        day = now.astimezone(self.timezone).date()
        rows = self.schedule(day)
        active = rows[(rows.market_open <= now) & (rows.market_close > now)]
        past = rows[rows.market_close <= now]
        future = rows[rows.market_open > now]
        last_close = past.iloc[-1].market_close.to_pydatetime() if not past.empty else None
        last_date = str(past.index[-1].date()) if not past.empty else None
        next_open = future.iloc[0].market_open.to_pydatetime() if not future.empty else None
        return {
            "is_open": not active.empty,
            "timezone": str(self.timezone),
            "checked_at": iso(now),
            "last_close": iso(last_close) if last_close else None,
            "last_completed_session": last_date,
            "next_open": iso(next_open) if next_open else None,
        }

    def should_refresh(self, now=None):
        now = now or utcnow()
        state = self.state(now)
        # Include the closing tick, including half days, to capture the final session data.
        just_closed = (
            state["last_close"] is not None
            and 0 <= (now - datetime.fromisoformat(state["last_close"])).total_seconds() < 60
        )
        return state["is_open"] or just_closed

    def is_complete(self, session_date, now=None):
        now = now or utcnow()
        day = datetime.fromisoformat(session_date).date()
        schedule = self.schedule(day)
        matches = schedule[schedule.index.date == day]
        return not matches.empty and now >= matches.iloc[0].market_close.to_pydatetime()

    def bar_label(self, session_date):
        # A daily bar is labelled by session, not by an exact trade observation time.
        return datetime.fromisoformat(session_date).replace(tzinfo=self.timezone).astimezone(UTC)

    def sessions(self, start, end):
        """Actual exchange sessions, including holidays and half days, as ISO dates."""
        days = set()
        for year in range(start.year, end.year + 1):
            rows = self.schedule(start.replace(year=year, month=1, day=1))
            days.update(day.date().isoformat() for day in rows.index if start <= day.date() <= end)
        return sorted(days)
