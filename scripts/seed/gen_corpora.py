#!/usr/bin/env python3
"""Генерация корпусов (T-219, T-016): data/import/transcripts (20 файлов JSON/TXT + эталоны), data/bench/*.jsonl.

Детерминировано (seed=7). Запуск: `python scripts/seed/gen_corpora.py`. Результат коммитится в репозиторий."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.seed.common import DATA, load_yaml  # noqa: E402
from scripts.seed.textgen import TextGen  # noqa: E402

OUT_TR = DATA / "import" / "transcripts"
OUT_EXP = DATA / "bench" / "transcripts_v1"
OUT_BENCH = DATA / "bench"

# --- транскрипты: сцены (сотрудник/клиент), находки и этапы скрипта ------------------------------------------------
GREET = [
    "Здравствуйте, меня зовут {emp}, чем могу помочь?",
    "Добрый день! Присаживайтесь. Меня зовут {emp}.",
    "Здравствуйте! Слушаю вас.",
]
IDENT = [
    "Паспорт, пожалуйста, для идентификации.",
    "Назовите, пожалуйста, фамилию и покажите документ.",
    "Для начала подтвердим личность — паспорт с собой?",
]
NEEDS = [
    "Расскажите, какая у вас задача — накопить, разместить свободные деньги или что-то другое?",
    "Уточню: вам важнее доходность или возможность снять деньги в любой момент?",
    "Чем могу помочь? Что вас интересует в первую очередь?",
]
OFFER_OK = {
    "deposit": "По вкладу «Накопительный» ставка девять с половиной процентов годовых на шесть месяцев, пополнение разрешено, досрочное закрытие — по ставке до востребования. Обратите внимание на этот пункт договора.",
    "credit": "Ставка по кредиту девятнадцать и девять десятых процента. Страховка добровольная: с ней ставка ниже на два пункта, но решение за вами.",
    "credit_card": "Льготный период сто двадцать дней на покупки, снятие наличных — комиссия три и девять десятых процента плюс триста девяносто рублей. Обслуживание бесплатное.",
    "debit_card": "Обслуживание карты бесплатное, оплата по QR и картой без комиссии, кешбэк один процент.",
}
SUMMARY = [
    "Подведу итог: {sum}. Следующий шаг — подписание договора, я распечатаю.",
    "Итак, резюмирую: {sum}. Если всё верно, оформляем.",
]
CLOSE = ["Спасибо, что обратились! Всего доброго.", "Хорошего дня, обращайтесь.", "Спасибо за обращение, до свидания."]
CLIENT_OPEN = {
    "deposit": "Хочу открыть вклад, какая сейчас ставка?",
    "credit": "Интересует потребительский кредит на триста тысяч.",
    "credit_card": "Хочу оформить кредитную карту, расскажите про льготный период.",
    "debit_card": "Нужна дебетовая карта, чтобы без комиссий платить по QR.",
}
CLIENT_Q = [
    "А если закрыть раньше срока?",
    "А комиссии какие-то есть?",
    "Это точно без скрытых условий?",
    "А можно подумать и прийти завтра?",
]
CLIENT_OK = ["Хорошо, понятно, оформляем.", "Спасибо, всё ясно.", "Да, подходит."]
CLIENT_HURT = [
    "Зачем вы так со мной разговариваете?",
    "Я просто спросил. Не надо грубить.",
    "Мне неприятно, позовите руководителя.",
]

RED = {
    "rudeness": [
        "Вы вообще читали условия, прежде чем сюда идти?",
        "Я вам уже три раза сказала, что непонятного?",
        "Это не моя проблема, читайте договор.",
        "Слушайте внимательно, у меня очередь.",
    ],
    "misinformation": {
        "deposit": (
            "По вкладу «Накопительный» ставка четырнадцать процентов.",
            "14 %",
            "9,5 %",
            "products.deposit.tariffs.base_rate_pct",
        ),
        "debit_card": (
            "Комиссия за оплату по QR один процент, это стандарт.",
            "1 %",
            "0 %",
            "tariffs.debit_card.payment.qr_sbp",
        ),
        "credit_card": (
            "Снятие наличных с кредитки бесплатно в любом банкомате.",
            "бесплатно",
            "3,9 % + 390 ₽",
            "tariffs.credit_card.cash_withdraw",
        ),
        "credit": (
            "Без страховки ставка будет тридцать процентов.",
            "30 %",
            "19,9 %",
            "products.credit.tariffs.rate_pct",
        ),
    },
    "tie_in": ["Без страховки кредит вам не одобрят, это условие.", "Карту выдадим, только если оформите подписку."],
    "substitution": [
        "Это как вклад, только лучше — по сути тот же депозит, но доходнее.",
        "Это не инвестиции, это накопления с гарантией.",
    ],
    "concealment": [
        "Подпишите, это формальность, условия стандартные, читать не обязательно.",
        "Комиссий нет, там мелкий шрифт, ничего важного.",
    ],
    "script_violation": [
        "Давайте сразу к делу, оформляем, паспорт не нужен — я вас и так помню.",
        "Подпишите, потом почитаете.",
    ],
}

SCENES = [  # (id, kind, branch, desk, employee, product, findings, missed_steps, fmt)
    (
        "scenario10_retail",
        "branch_retail",
        "0042",
        5,
        "Сидорова А. А.",
        "deposit",
        ["rudeness", "misinformation"],
        ["identification", "needs", "summary"],
        "txt",
    ),
    (
        "scenario09_isj",
        "branch_retail",
        "0042",
        3,
        "Петров П. П.",
        "deposit",
        ["substitution", "concealment", "tie_in"],
        ["summary"],
        "json",
    ),
    ("br_clean_deposit", "branch_retail", "0107", 1, None, "deposit", [], [], "json"),
    ("br_clean_credit", "branch_retail", "0211", 2, None, "credit", [], [], "txt"),
    ("br_tiein_credit", "branch_retail", "0315", 4, None, "credit", ["tie_in"], [], "json"),
    ("br_misinfo_qr", "branch_retail", "0418", 2, None, "debit_card", ["misinformation"], [], "txt"),
    ("br_rude_card", "branch_retail", "0520", 6, None, "credit_card", ["rudeness"], ["closing"], "json"),
    (
        "br_script_skip",
        "branch_retail",
        "0633",
        1,
        None,
        "debit_card",
        ["script_violation"],
        ["identification", "needs"],
        "txt",
    ),
    ("br_conceal_cc", "branch_retail", "0741", 3, None, "credit_card", ["concealment", "misinformation"], [], "json"),
    ("br_clean_cc", "branch_retail", "0856", 5, None, "credit_card", [], [], "txt"),
    ("br_subst_premium", "branch_retail", "0962", 2, None, "deposit", ["substitution"], ["summary"], "json"),
    ("br_clean_debit", "branch_retail", "0042", 1, None, "debit_card", [], [], "txt"),
    ("cc_call_clean", "contact_center_call", None, None, None, "debit_card", [], [], "json"),
    ("cc_call_rude", "contact_center_call", None, None, None, "credit", ["rudeness"], ["summary"], "txt"),
    ("cc_call_misinfo", "contact_center_call", None, None, None, "deposit", ["misinformation"], [], "json"),
    ("cc_chat_clean", "contact_center_chat", None, None, None, "credit_card", [], [], "txt"),
    (
        "cc_chat_script",
        "contact_center_chat",
        None,
        None,
        None,
        "debit_card",
        ["script_violation"],
        ["identification"],
        "json",
    ),
    ("cc_call_tiein", "contact_center_call", None, None, None, "credit", ["tie_in"], [], "txt"),
    ("cc_chat_conceal", "contact_center_chat", None, None, None, "deposit", ["concealment"], [], "json"),
    ("cc_call_clean2", "contact_center_call", None, None, None, "credit_card", [], [], "txt"),
]


def build_turns(rnd: random.Random, scene: tuple, emp_name: str) -> tuple[list[dict], list[dict]]:
    sid, kind, _b, _d, _e, product, findings, missed, _f = scene
    turns: list[dict] = []
    expected_findings: list[dict] = []

    def say(speaker: str, text: str, finding: dict | None = None) -> None:
        turns.append({"seq": len(turns) + 1, "speaker": speaker, "text": text})
        if finding:
            expected_findings.append({**finding, "turn_seq": len(turns), "quote": text})

    if kind == "branch_retail":
        say("employee", rnd.choice(GREET).format(emp=emp_name) if "greeting" not in missed else "Слушаю.")
    else:
        say("employee", f"Банк, меня зовут {emp_name}, здравствуйте." if "greeting" not in missed else "Да, говорите.")
    say("client", CLIENT_OPEN[product])
    if "identification" not in missed:
        say(
            "employee",
            rnd.choice(IDENT) if kind == "branch_retail" else "Назовите, пожалуйста, кодовое слово и дату рождения.",
        )
        say("client", "Да, пожалуйста." if kind == "branch_retail" else "Кодовое слово «Ромашка», двенадцатое марта.")
    if "needs" not in missed:
        say("employee", rnd.choice(NEEDS))
        say(
            "client",
            rnd.choice(
                ["Хочу разместить свободные деньги на полгода.", "Важнее доходность.", "Чтобы без комиссий и просто."]
            ),
        )
    if "script_violation" in findings:
        say("employee", rnd.choice(RED["script_violation"]), {"code": "script_violation", "alert": "report"})
    if "misinformation" in findings:
        text, claimed, truth, src = RED["misinformation"][product]
        say(
            "employee",
            text,
            {"code": "misinformation", "alert": "immediate", "claimed": claimed, "truth": truth, "source_table": src},
        )
    else:
        say("employee", OFFER_OK[product])
    say("client", rnd.choice(CLIENT_Q))
    if "rudeness" in findings:
        say(
            "employee",
            RED["rudeness"][0] if sid == "scenario10_retail" else rnd.choice(RED["rudeness"]),
            {"code": "rudeness", "alert": "immediate"},
        )
        say("client", rnd.choice(CLIENT_HURT))
    for code in ("substitution", "concealment", "tie_in"):
        if code in findings:
            say("employee", rnd.choice(RED[code]), {"code": code, "alert": "counter"})
            say("client", rnd.choice(["Хм, ну если вы так говорите…", "А это точно так?", "Ладно."]))
    if not any(
        c in findings
        for c in ("rudeness", "substitution", "concealment", "tie_in", "script_violation", "misinformation")
    ):
        say(
            "employee",
            "Досрочное закрытие — по ставке до востребования, комиссий нет. Можете взять договор домой и вернуться завтра.",
        )
        say("client", rnd.choice(CLIENT_OK))
    if "summary" not in missed:
        say(
            "employee",
            rnd.choice(SUMMARY).format(
                sum={
                    "deposit": "вклад на шесть месяцев, ставка девять с половиной, с пополнением",
                    "credit": "кредит триста тысяч на три года, страховка по желанию",
                    "credit_card": "кредитная карта с льготным периодом сто двадцать дней",
                    "debit_card": "дебетовая карта с бесплатным обслуживанием и кешбэком",
                }[product]
            ),
        )
    if "closing" not in missed:
        say("employee", rnd.choice(CLOSE))
    t = 0
    for turn in turns:
        dur = 900 + 60 * len(turn["text"])
        turn["t0_ms"], turn["t1_ms"] = t, t + dur
        t += dur + 400
    return turns, expected_findings


def to_txt(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        s = t["t0_ms"] // 1000
        lines.append(
            f"[{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}] {'Сотрудник' if t['speaker'] == 'employee' else 'Клиент'}: {t['text']}"
        )
    return "\n".join(lines) + "\n"


def gen_transcripts(rnd: random.Random) -> None:
    OUT_TR.mkdir(parents=True, exist_ok=True)
    OUT_EXP.mkdir(parents=True, exist_ok=True)
    branches = {b["code"]: b for b in load_yaml("branches.yaml")["branches"]}
    for scene in SCENES:
        sid, kind, bcode, desk, emp, product, findings, missed, fmt = scene
        emp_name = emp or rnd.choice(["Анна", "Мария", "Елена", "Дмитрий", "Сергей", "Ольга"])
        turns, exp = build_turns(rnd, scene, emp_name.split()[0])
        meta = {
            "external_id": sid,
            "kind": kind,
            "branch_code": f"VSP-{bcode}" if bcode else None,
            "employee_public_id": None,
            "desk_no": desk,
            "client": None,
            "deal_product": {
                "deposit": "Вклад «Накопительный»",
                "credit": "Потребительский кредит",
                "credit_card": "Кредитная карта",
                "debit_card": "Дебетовая карта",
            }[product],
            "started_at": "2026-11-09T11:05:00+03:00",
            "geo": {"region_code": None, "city_id": None, "lat": None, "lon": None, "source": "contact"}
            if bcode
            else None,
            "analyses": ["client_signal", "employee_quality"],
            "turns": turns,
            "meta": {
                "employee_display_name": emp,
                "branch_city": branches[bcode]["city"] if bcode else None,
                "synthetic": True,
            },
        }
        if fmt == "json":
            (OUT_TR / f"{sid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            header = f"# kind: {kind}; branch: {meta['branch_code'] or '-'}; desk: {desk or '-'}; employee: {emp or emp_name}; product: {product}\n"
            (OUT_TR / f"{sid}.txt").write_text(header + to_txt(turns), encoding="utf-8")
        expected = {
            "id": sid,
            "kind": kind,
            "product": product,
            "findings": exp,
            "finding_codes": sorted({f["code"] for f in exp}),
            "script_steps_missed": missed,
            "script_code": "retail_service_v1" if kind == "branch_retail" else "contact_center_v1",
            "client_signal": {
                "signal_type": "service_quality" if "rudeness" in findings else "info_request",
                "sentiment": "negative" if "rudeness" in findings else "neutral",
            },
        }
        (OUT_EXP / f"{sid}.expected.json").write_text(
            json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def gen_bench(rnd: random.Random) -> None:
    OUT_BENCH.mkdir(parents=True, exist_ok=True)
    tg = TextGen(7)
    combos = tg.all_combinations()
    feed = load_yaml("corpus/mock_feed.yaml")["posts"]

    def write(name: str, rows: list[dict]) -> None:
        (OUT_BENCH / f"{name}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )

    # sentiment_v1: 300 = 280 из шаблонов (стили кроме сарказма) + 20 из mock-ленты
    rows = []
    for i in range(280):
        st, p = combos[i % len(combos)]
        g = tg.generate(st, p, style=rnd.choice(["plain", "plain", "slang", "typos", "caps"]))
        rows.append(
            {
                "id": f"sent-{i + 1:03d}",
                "channel": rnd.choice(["chat", "social", "email", "call"]),
                "text": g.text,
                "gold": {"sentiment": g.gold["sentiment"]},
                "tags": [st, p, g.style],
            }
        )
    for i, post in enumerate(feed[:20]):
        rows.append(
            {
                "id": f"sent-feed-{i + 1:02d}",
                "channel": "social",
                "text": post["text"],
                "gold": {"sentiment": post["gold"]["sentiment"]},
                "tags": ["feed"],
            }
        )
    write("sentiment_v1", rows)
    # hidden_negativity_v1: 60 сарказм (true) + 60 прямых (false)
    rows = []
    neg_types = [
        c for c in combos if c[0] in ("tech_fault", "tariff_terms", "service_quality", "churn", "client_error")
    ]
    for i in range(60):
        st, p = neg_types[i % len(neg_types)]
        g = tg.generate(st, p, style="sarcasm")
        rows.append(
            {
                "id": f"hid-{i + 1:03d}",
                "channel": "social",
                "text": g.text,
                "gold": {"hidden_negativity": True, "sentiment": "negative", "markers": ["sarcasm"]},
                "tags": [st, p],
            }
        )
    for i in range(60):
        st, p = combos[(i * 3) % len(combos)]
        g = tg.generate(st, p, style="plain")
        rows.append(
            {
                "id": f"hid-{i + 61:03d}",
                "channel": "chat",
                "text": g.text,
                "gold": {"hidden_negativity": False, "sentiment": g.gold["sentiment"], "markers": []},
                "tags": [st, p],
            }
        )
    write("hidden_negativity_v1", rows)
    # summary_v1: 60 — эталон = ключевые факты, которые должны попасть в резюме
    names = {r["code"]: r["name_ru"] for r in load_yaml("error_codes.yaml")["signal_types"]}
    prods = {p["code"]: p["name_ru"] for p in load_yaml("products.yaml")["products"]}
    rows = []
    for i in range(60):
        st, p = combos[(i * 7) % len(combos)]
        g = tg.generate(st, p, style="plain")
        facts = [names[st].lower(), prods[p].lower()]
        if g.gold.get("error_code"):
            facts.append(g.gold["error_code"])
        rows.append(
            {
                "id": f"sum-{i + 1:03d}",
                "channel": "email",
                "text": g.text,
                "gold": {
                    "must_mention": facts,
                    "max_words": 40,
                    "reference": f"{names[st]} — {prods[p]}: {g.text[:80].rstrip('.,!?')}",
                },
                "tags": [st, p],
            }
        )
    write("summary_v1", rows)
    # red_phrases_v1: по 30 на rudeness / script_violation / misinformation + 30 чистых + misselling-семейство
    pats = {p["code"]: p for p in load_yaml("misselling_patterns.yaml")["patterns"]}
    rows = []
    for code in ("rudeness", "script_violation", "misinformation"):
        pool = list(pats[code]["examples"]) + (
            RED["rudeness"]
            if code == "rudeness"
            else RED["script_violation"]
            if code == "script_violation"
            else [v[0] for v in RED["misinformation"].values()]
        )
        for i in range(30):
            text = pool[i % len(pool)]
            gold: dict = {"patterns": [code], "alert": pats[code]["alert_policy"]}
            if code == "misinformation":
                claimed_truth = {v[0]: (v[1], v[2], v[3]) for v in RED["misinformation"].values()}.get(text)
                if claimed_truth:
                    gold.update(
                        {"claimed": claimed_truth[0], "truth": claimed_truth[1], "source_table": claimed_truth[2]}
                    )
            rows.append(
                {"id": f"red-{code}-{i + 1:02d}", "channel": "branch_audio", "text": text, "gold": gold, "tags": [code]}
            )
    for code in ("tie_in", "substitution", "concealment", "pressure", "guarantee"):
        for i, text in enumerate(pats[code]["examples"]):
            rows.append(
                {
                    "id": f"red-{code}-{i + 1:02d}",
                    "channel": "branch_audio",
                    "text": text,
                    "gold": {"patterns": [code], "alert": "counter"},
                    "tags": [code, "misselling"],
                }
            )
    clean = (
        [c for p in pats.values() for c in p["counter_examples"]]
        + [OFFER_OK[k] for k in OFFER_OK]
        + GREET[:2]
        + IDENT
        + NEEDS
        + CLOSE
    )
    for i in range(30):
        rows.append(
            {
                "id": f"red-clean-{i + 1:02d}",
                "channel": "branch_audio",
                "text": clean[i % len(clean)].format(emp="Анна"),
                "gold": {"patterns": [], "alert": None},
                "tags": ["clean"],
            }
        )
    write("red_phrases_v1", rows)
    # golden_v1: классификация тип × продукт × 3 канала
    rows = []
    for st, p in combos:
        for ch in ("chat", "social", "email"):
            g = tg.generate(st, p, style=rnd.choice(["plain", "plain", "sarcasm", "slang", "typos"]))
            rows.append(
                {
                    "id": f"gold-{st}-{p}-{ch}",
                    "channel": ch,
                    "text": g.text,
                    "gold": {k: v for k, v in g.gold.items() if k != "style"},
                    "tags": [g.style],
                }
            )
    write("golden_v1", rows)


def main() -> int:
    rnd = random.Random(7)
    gen_transcripts(rnd)
    gen_bench(rnd)
    sizes = {f.stem: sum(1 for _ in f.open(encoding="utf-8")) for f in OUT_BENCH.glob("*.jsonl")}
    print("transcripts:", len(list(OUT_TR.iterdir())), "bench:", sizes)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
