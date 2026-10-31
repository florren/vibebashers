"""Клиентский итог по подтверждённому состоянию, отдельно от внутреннего отчёта."""

from typing import Any

from app.agent.gifts import _gift_label


def outcome_text(lang: str, *, resolved: bool, late: bool, gift: str | None = None) -> str:
    if lang == "en":
        if resolved:
            text = "The issue you reported has been resolved. "
            text += "We are sorry it took longer than promised. " if late else "We are sorry for the inconvenience. "
            text += "If you need any further help, please reply to this message."
        else:
            text = "We are sorry, but we have not resolved the issue yet. We are continuing to work on it and will let you know the outcome. Your case remains open."
        if gift:
            text += f" As an apology, you have received {gift}."
    else:
        if resolved:
            text = "Проблема по вашему обращению устранена. "
            text += (
                "Простите, что решение заняло больше времени, чем мы обещали. "
                if late
                else "Приносим извинения за неудобства. "
            )
            text += "Если вам потребуется помощь, ответьте на это сообщение."
        else:
            text = "Приносим извинения: проблему пока не удалось решить. Мы продолжаем работу и сообщим вам о результате. Ваше обращение остаётся открытым."
        if gift:
            text += f" В знак извинения для вас — {gift}."
    return text


async def customer_outcome(
    ctx: Any, incident_id: int, client_id: int | None, lang: str, *, resolved: bool, late: bool
) -> str:
    gift = None
    if client_id is not None:
        row = await ctx.fetchone(
            "select t.payload->'gift',g.name_ru,g.name_en from tasks t left join gift_catalog g on g.code=t.payload->'gift'->>'gift_code' "
            "where t.run_id=%s and t.incident_id=%s and t.client_id=%s and t.kind='gift' and t.status='done' "
            "and nullif(t.payload->'issued'->>'label','') is not null order by t.id desc limit 1",
            (ctx.run_id, incident_id, client_id),
        )
        if row:
            gift = _gift_label(row[0], row[2] if lang == "en" else row[1], lang)
    return outcome_text(lang, resolved=resolved, late=late, gift=gift)


async def has_emulated_verification(ctx: Any, incident_id: int) -> bool:
    """Формат для verified close, включая закрытые legacy-цепочки без финального отчёта."""
    return bool(
        await ctx.fetchone(
            "select 1 from incident_artifacts a join incidents i on i.id=a.incident_id "
            "where a.run_id=%s and a.incident_id=%s and (a.kind='verification_report' "
            "or (a.kind='release_note' and i.status='closed')) "
            "and a.meta->>'demo'='true' and a.meta->>'outcome' in ('on_time','late','recovered') limit 1",
            (ctx.run_id, incident_id),
        )
    )


async def emulated_team_pending(ctx: Any, incident_id: int) -> bool:
    """Релиз/устранённый fault ещё не заменяют проверку услуги по плану команды."""
    return bool(
        await ctx.fetchone(
            "select 1 from team_actions ta join incidents i on i.id=ta.incident_id "
            "where ta.run_id=%s and ta.incident_id=%s and ta.payload->>'demo'='true' "
            "and i.status<>'closed' limit 1",
            (ctx.run_id, incident_id),
        )
    )
