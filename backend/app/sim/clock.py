"""Симуляционное время (ТЗ 4.1, T-031): скорость, пресеты, фазы, рабочие дни и SLA-арифметика."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MSK = dt.timezone(dt.timedelta(hours=3))
PRESETS: dict[str, float] = {
    "demo_5min": 12 * 3600 / 300,  # 12 сим-часов за 5 реальных минут = 144 сим-с/с
    "day_12min": 60.0,  # сим-час за минуту (по умолчанию ТЗ 4.1)
    "realtime": 1.0,
}
WORK_START, WORK_END = 9, 18  # рабочие часы для SLA (AGENTS §6: пн–пт 09:00–18:00)


def phase_of(t: dt.datetime) -> str:
    h = t.astimezone(MSK).hour
    if 6 <= h < 11:
        return "morning"
    if 11 <= h < 18:
        return "day"
    if 18 <= h < 23:
        return "evening"
    return "night"


def is_working_day(t: dt.datetime) -> bool:
    return t.astimezone(MSK).weekday() < 5


def is_working_time(t: dt.datetime) -> bool:
    lt = t.astimezone(MSK)
    return lt.weekday() < 5 and WORK_START <= lt.hour < WORK_END


def add_working_days(t: dt.datetime, days: int) -> dt.datetime:
    """Срок SLA в рабочих днях: считаем от следующего рабочего дня, выходные пропускаем, время суток сохраняем."""
    cur = t
    left = days
    while left > 0:
        cur += dt.timedelta(days=1)
        if is_working_day(cur):
            left -= 1
    return cur


def add_working_hours(t: dt.datetime, hours: float) -> dt.datetime:
    """Сим-часы «взято в работу» идут только в рабочее время; вне его — переносятся на начало следующего рабочего дня."""
    cur = t.astimezone(MSK)
    left = dt.timedelta(hours=hours)
    while left > dt.timedelta(0):
        if not is_working_time(cur):
            nxt = cur.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
            if cur.hour >= WORK_END or not is_working_day(cur) or cur >= nxt:
                nxt += dt.timedelta(days=1)
            while not is_working_day(nxt):
                nxt += dt.timedelta(days=1)
            cur = nxt
            continue
        end = cur.replace(hour=WORK_END, minute=0, second=0, microsecond=0)
        step = min(left, end - cur)
        cur += step
        left -= step
    return cur


@dataclass
class SimClock:
    sim_time: dt.datetime
    speed: float = PRESETS["day_12min"]
    running: bool = False
    day_no: int = 0

    def advance(self, real_seconds: float) -> dt.timedelta:
        delta = dt.timedelta(seconds=real_seconds * self.speed)
        before_day = self.sim_time.astimezone(MSK).date()
        self.sim_time += delta
        if self.sim_time.astimezone(MSK).date() != before_day:
            self.day_no += (self.sim_time.astimezone(MSK).date() - before_day).days
        return delta

    @property
    def phase(self) -> str:
        return phase_of(self.sim_time)

    def set_preset(self, name: str) -> None:
        self.speed = PRESETS[name]
