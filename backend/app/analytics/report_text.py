"""T-244: проверяемые формулировки по наблюдениям, без LLM и бизнес-порогов."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.contracts.enums import SignalType

TEXT: dict[str, dict[str, Any]] = {
    "ru": {
        "unknown": "неизвестно",
        "empty": "За период клиентских сигналов нет.",
        "received": "За период получено {n} клиентских сигналов; негативных — {negative}.",
        "changed": "Наблюдаемых сигналов к прошлому равному окну: {delta:+d}; полнота окон не подтверждена, это не оценка популяционного CX.",
        "coverage": "Сравниваются только записанные наблюдения; полнота двух окон не подтверждена, это не оценка изменения клиентского опыта. Денежное изменение — разница сохранённых оценок, не новый расчёт или причинный эффект.",
        "main": "Чаще всего обращения поступали через {source} ({n}).",
        "no_source": "Основная тема обращений не установлена по сохранённым данным.",
        "theme": "Основная записанная тема: {theme}.",
        "saved": "Сохранённая оценка предотвращённых потерь: {money} ₽; без пересчёта.",
        "money_unknown": "Полной сохранённой оценки предотвращённых потерь нет; неизвестное не заменено нулём.",
        "attention": "Требуют разбора: {n} инцидентов с критичностью high, нарушением/зарегистрированным риском SLA или ожиданием человека; красных фраз в сигналах — {red}.",
        "signals": "Сигналы",
        "negative": "Доля негатива",
        "critical": "Доля критических сигналов",
        "loss": "Расчётная потеря dCLTV",
        "prevented": "Предотвращённая потеря",
        "incidents": "Инциденты",
        "count": "шт.",
        "growing": "растёт (число наблюдений)",
        "growing_value": "растёт (по записанным данным)",
        "warning_action": "Проверить зарегистрированный риск SLA с ответственной командой",
        "warning_note": "Показаны только native SLA warnings той же стадии и срока. После закрытия, reopen или release без нового подтверждения риск неизвестен; это не прогноз полного риска.",
        "observed": "наблюдаемые данные; норматив не задан",
        "requires": "требует внимания",
        "normal": "в норме: рисков в записанных данных не выявлено",
        "no_data": "нет данных",
        "daily": "Динамика сохранённых потерь: разрывы означают отсутствие оценки",
        "monthly": "Месячная история объединяет синтетические агрегаты и наблюдаемый хвост",
        "sources": "Распределение обращений по известным источникам; неизвестные выделены отдельно",
        "chart_note": "Это наблюдения выбранного контура, не прогноз; неполные данные не заменены нулями.",
        "unknown_source": "Неизвестный источник",
        "not_recorded": "Действие не записано",
        "region_unknown": "Регион не установлен",
        "team_unknown": "Команда не установлена",
        "action": "Разобрать инцидент с ответственной командой",
        "red_action": "Проверить сигналы с красными фразами",
        "formula_unknown": "Сохранённая формула отсутствует; отчёт не пересчитывает экономику.",
        "synthetic": "Синтетические данные",
        "rules_unknown": "Версии применённых правил не записаны",
        "method": "dCLTV — сохранённая оценка потерь, не проводка. SLA — срок реакции/решения по симуляционному времени. CSI — ответы опросов; общий индекс CSI здесь не моделируется. Уровень high — записанная критичность, не новый порог отчёта.",
        "headers": {
            "label": "Показатель",
            "value": "Значение",
            "unit": "Единица",
            "delta": "Изменение наблюдений",
            "delta_unit": "Единица изменения",
            "prevented_rub": "Предотвращено RUB (точно)",
            "verdict": "Оценка",
            "public_id": "Сигнал",
            "received_sim": "Симуляционное время",
            "summary": "Описание",
            "status": "Статус",
            "source": "Источник",
            "series": "Ряд",
            "date": "Дата",
            "signals": "Сигналы",
            "loss_rub": "Потеря RUB (точная сумма)",
            "region": "Регион",
            "negative": "Негативные",
            "affected_clients": "Пострадавшие (полное покрытие)",
            "identified_clients": "Идентифицированные клиенты",
        },
        "summary": "Главное",
        "signal_sheet": "Сигналы",
        "dynamic": "Динамика",
        "source_sheet": "Источники",
        "region_sheet": "Регионы",
        "method_sheet": "Методика",
        "solved": "решено",
        "working": "в работе",
        "human": "ждёт решения руководителя",
        "rejected": "отклонено",
        "duplicate": "дубликат",
        "waiting": "ожидает клиента",
        "new": "новое",
    },
    "en": {
        "unknown": "unknown",
        "empty": "No customer signals were recorded in this period.",
        "received": "{n} customer signals were recorded; {negative} were negative.",
        "changed": "Recorded signal count versus the preceding equal window: {delta:+d}; completeness is unconfirmed, so this is not a population CX estimate.",
        "coverage": "Only recorded observations are compared; completeness of either window is unconfirmed. This is not a change estimate of customer experience. Money changes compare saved estimates, not a new calculation or causal effect.",
        "main": "The largest recorded source was {source} ({n}).",
        "no_source": "No main customer topic was established from saved data.",
        "theme": "Main recorded topic: {theme}.",
        "saved": "Saved prevented-loss estimate: {money} RUB; no recalculation.",
        "money_unknown": "A complete saved prevented-loss estimate is unavailable; unknown values are not replaced with zero.",
        "attention": "{n} incidents need review for high criticality, an SLA breach/recorded warning or a pending human decision; {red} signals contain red phrases.",
        "signals": "Signals",
        "negative": "Negative share",
        "critical": "Critical signal share",
        "loss": "Estimated dCLTV loss",
        "prevented": "Prevented loss",
        "incidents": "Incidents",
        "count": "count",
        "growing": "growing (recorded count)",
        "growing_value": "growing (recorded value)",
        "warning_action": "Review the recorded SLA warning with the responsible team",
        "warning_note": "Only native SLA warnings for the same stage and deadline are shown. After closure, reopening or release without new evidence, risk is unknown; this is not a complete risk forecast.",
        "observed": "observations; no norm defined",
        "requires": "needs attention",
        "normal": "within norm: no risks found in recorded data",
        "no_data": "no data",
        "daily": "Saved loss trend: gaps indicate missing estimates",
        "monthly": "Monthly history combines synthetic aggregates and the observed tail",
        "sources": "Signals by recorded source; unknown sources are shown separately",
        "chart_note": "Selected-scope observations, not a forecast; missing data are not replaced with zero.",
        "unknown_source": "Unknown source",
        "not_recorded": "No action recorded",
        "region_unknown": "Region unknown",
        "team_unknown": "Team unknown",
        "action": "Review this incident with the responsible team",
        "red_action": "Review signals containing red phrases",
        "formula_unknown": "No saved formula is available; this report does not recalculate economics.",
        "synthetic": "Synthetic data",
        "rules_unknown": "Applied rule versions were not recorded",
        "method": "dCLTV is a saved loss estimate, not a ledger posting. SLA is a response/resolution deadline in simulation time. CSI means survey responses; an overall CSI index is not modelled here. High is recorded criticality, not a new report threshold.",
        "headers": {
            "label": "Indicator",
            "value": "Value",
            "unit": "Unit",
            "delta": "Recorded change",
            "delta_unit": "Change unit",
            "prevented_rub": "Prevented RUB (exact)",
            "verdict": "Assessment",
            "public_id": "Signal",
            "received_sim": "Simulation time",
            "summary": "Description",
            "status": "Status",
            "source": "Source",
            "series": "Series",
            "date": "Date",
            "signals": "Signals",
            "loss_rub": "Loss RUB (exact amount)",
            "region": "Region",
            "negative": "Negative",
            "affected_clients": "Affected clients (complete coverage)",
            "identified_clients": "Identified clients",
        },
        "summary": "Summary",
        "signal_sheet": "Signals",
        "dynamic": "Dynamics",
        "source_sheet": "Sources",
        "region_sheet": "Regions",
        "method_sheet": "Method",
        "solved": "resolved",
        "working": "in progress",
        "human": "awaiting a manager decision",
        "rejected": "rejected",
        "duplicate": "duplicate",
        "waiting": "awaiting customer",
        "new": "new",
    },
}


def status_label(status: str, lang: str) -> str:
    key = (
        "solved"
        if status in ("closed", "resolved")
        else "human"
        if status == "awaiting_human"
        else "rejected"
        if status == "rejected"
        else "duplicate"
        if status == "duplicate"
        else "waiting"
        if status == "awaiting_client"
        else "new"
        if status == "new"
        else "working"
    )
    return str(TEXT[lang][key])


def describe(
    data: dict[str, Any], previous: dict[str, Any], attention: int, red: int, lang: str, theme: str | None = None
) -> dict[str, Any]:
    t = TEXT[lang]
    k = data["kpi"]
    old = previous["kpi"]
    delta = k["signals"] - old["signals"]
    saved = k["prevented_loss_rub"]
    money = f"{saved:,.2f}" if saved is not None else ""
    if lang == "ru":
        money = money.replace(",", "\u00a0").replace(".", ",")
    summary = [
        t["received"].format(n=k["signals"], negative=k["negative"]) if k["signals"] else t["empty"],
        t["changed"].format(delta=delta),
        t["theme"].format(theme=theme) if theme else t["no_source"],
        t["saved"].format(money=money) if saved is not None else t["money_unknown"],
        t["attention"].format(n=attention, red=red),
    ]

    def difference(name: str, scale: int = 1) -> Any:
        return (k[name] - old[name]) * scale if k[name] is not None and old[name] is not None else None

    specs = [
        ("signals", k["signals"], t["count"], delta),
        ("negative", k["negative_share"], "%", difference("negative_share", 100)),
        ("critical", k["critical_share"], "%", difference("critical_share", 100)),
        ("loss", k["potential_loss_rub"], "RUB", difference("potential_loss_rub")),
        ("prevented", saved, "RUB", difference("prevented_loss_rub")),
        ("incidents", k["incidents"], t["count"], k["incidents"] - old["incidents"]),
    ]
    return {
        "summary": summary,
        "kpi": [
            {
                "code": code,
                "label": t[code],
                "value": value,
                "unit": unit,
                "delta": change,
                "delta_unit": "RUB" if unit == "RUB" else "percentage_points" if unit == "%" else "count",
                "verdict": t["no_data"]
                if value is None
                else t["requires"]
                if code == "critical" and value > 0
                else (t["growing"] if code in ("signals", "incidents") else t["growing_value"])
                if change is not None and change > 0
                else t["observed"],
            }
            for code, value, unit, change in specs
        ],
        "charts": [
            {"code": code, "title_insight": t[code], "note": t["chart_note"]}
            for code in ("daily", "monthly", "sources")
        ],
    }


THEMES = {
    SignalType.TECH_FAULT: ("технические сбои", "technical faults"),
    SignalType.CLIENT_ERROR: ("ошибки клиента", "customer errors"),
    SignalType.TARIFF_TERMS: ("условия тарифов", "tariff terms"),
    SignalType.SERVICE_QUALITY: ("качество обслуживания", "service quality"),
    SignalType.FRAUD_SUSPICION: ("подозрения на мошенничество", "suspected fraud"),
    SignalType.LEGAL_REGULATORY: ("правовые и регуляторные вопросы", "legal and regulatory matters"),
    SignalType.INFO_REQUEST: ("запросы информации", "information requests"),
    SignalType.GRATITUDE: ("благодарности", "gratitude"),
    SignalType.SUGGESTION: ("предложения", "suggestions"),
    SignalType.CHURN: ("намерение уйти", "intent to leave"),
}


def main_topic(entries: list[dict[str, Any]], lang: str) -> str | None:
    counts = Counter(row["signal_type"] for row in entries if row.get("signal_type") in THEMES)
    if not counts:
        return None
    code = min(counts, key=lambda key: (-counts[key], key))
    name = THEMES[code][1 if lang == "en" else 0]
    return (
        f"{name} — {counts[code]} из {sum(counts.values())} сигналов с известным типом ({len(entries)} всего)"
        if lang == "ru"
        else f"{name} — {counts[code]} of {sum(counts.values())} signals with a known type ({len(entries)} total)"
    )


ACTIONS = {
    "take": ("Взято в работу", "Work accepted"),
    "clarify": ("Записано уточнение", "Clarification recorded"),
    "rca": ("Записан анализ причин", "Root-cause analysis recorded"),
    "fix_decision": ("Записано решение по исправлению", "Fix decision recorded"),
    "progress_report": ("Записан отчёт о ходе работ", "Progress report recorded"),
    "release": ("Записан релиз исправления", "Fix release recorded"),
    "verify": ("Записана проверка", "Verification recorded"),
    "close": ("Записано закрытие", "Closure recorded"),
    "reassign": ("Записана передача команде", "Team reassignment recorded"),
    "escalate_ack": ("Подтверждена эскалация", "Escalation acknowledged"),
}


def recorded_action(code: str | None, lang: str) -> str:
    if code is None:
        return str(TEXT[lang]["not_recorded"])
    names = ACTIONS.get(code)
    if names:
        return names[1 if lang == "en" else 0]
    return ("Записанное действие команды" if lang == "ru" else "Recorded team action") + f" ({code})"
