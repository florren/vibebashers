"""Детектор по правилам (T-184, T-215): ключевые слова/примеры паттернов, словарь грубости, запрещённые фразы скрипта, факт-чек цифр.

Срабатывание — предварительное (preliminary); окончательный вердикт даёт LLM-детектор (на mock = правила).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.compliance.fact_check import FactResult, check_claims, extract_claims
from app.compliance.taxonomy import Pattern, ServiceScript

RUDENESS_WORDS: tuple[str, ...] = (
    "вы вообще",
    "не моя проблема",
    "сами виноваты",
    "что непонятного",
    "слушайте внимательно",
    "я вам русским языком",
    "не задерживайте",
    "мне некогда",
    "это ваши проблемы",
    "не мешайте",
    "вы что, не понимаете",
    "сколько можно",
    "не надо мне",
    "уже три раза",
    "идите",
    "не нравится — ",
)

SOFTENERS = ("не говорю, что", "ни в коем случае не", "нельзя говорить", "не гарантир", "никто не гарантирует")


@dataclass
class Finding:
    pattern_code: str
    family: str
    confidence: float
    quote: str
    evidence: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    recommendation_ru: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


WEAK_KEYWORDS = {
    "комиссий нет",
    "стандартные условия",
    "условия стандартные",
    "ставка",
    "комиссия",
    "процент",
    "годовых",
    "бесплатно",
    "льготный период",
}
_NEGATED_AFTER = re.compile(r"^\W*(не нужен|не нужна|не надо|не требуется|не обязателен)")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower().replace("ё", "е")).strip()


def _stem(w: str) -> str:
    w = re.sub(r"[^а-яa-z0-9%]", "", w)
    return w[:5] if len(w) > 5 else w


def _tokens(t: str) -> list[str]:
    return [x for x in (_stem(w) for w in _norm(t).split()) if x]


def phrase_matches(text: str, phrase: str, *, max_gap: int = 2) -> bool:
    """Нечёткое вхождение фразы: все слова (по основам) идут по порядку, между соседними ≤ max_gap лишних слов."""
    if _norm(phrase) in _norm(text):
        return True
    pt, tt = _tokens(phrase), _tokens(text)
    if not pt or len(pt) < 2:
        return False
    i = 0
    last = -1
    for tok in pt:
        found = -1
        for j in range(max(i, last + 1), min(len(tt), (last + 1 + max_gap + 1) if last >= 0 else len(tt))):
            if tt[j] == tok:
                found = j
                break
        if found < 0:
            return False
        last = found
        i = found + 1
    return True


def _hits(text: str, phrases: list[str] | tuple[str, ...]) -> list[str]:
    return [p for p in phrases if phrase_matches(text, p)]


def _softened(text: str) -> bool:
    t = _norm(text)
    return any(s in t for s in SOFTENERS)


def detect_utterance(
    text: str,
    patterns: list[Pattern],
    *,
    script: ServiceScript | None = None,
    products: dict[str, dict[str, Any]] | None = None,
    deal_product: str | None = None,
) -> list[Finding]:
    """Реплика сотрудника → предварительные находки по всем активным паттернам."""
    out: list[Finding] = []
    if not text.strip():
        return out
    soft = _softened(text)
    for p in patterns:
        if not p.is_active:
            continue
        if p.code == "misinformation":
            facts = check_claims(extract_claims(text, deal_product), products or {}) if products else []
            false_facts = [f for f in facts if f.verified and f.is_false]
            if false_facts:
                out.append(
                    Finding(
                        pattern_code=p.code,
                        family=p.family,
                        confidence=min(0.95, 0.7 + 0.1 * len(false_facts)),
                        quote=text.strip()[:240],
                        evidence=[f"{f.claim} ≠ {f.truth}" for f in false_facts],
                        facts=[_fact(f) for f in facts],
                        recommendation_ru=p.recommendation_ru,
                    )
                )
            continue
        if p.code == "rudeness":
            hits = _hits(text, list(p.keywords) + list(RUDENESS_WORDS))
        elif p.code == "script_violation":
            hits = _hits(text, list(p.keywords) + list(script.forbidden_phrases if script else []))
        else:
            hits = _hits(text, p.keywords)
        ex_hits = [h for h in _hits(text, p.examples) if _norm(h) not in WEAK_KEYWORDS]
        strong = [h for h in hits if _norm(h) not in WEAK_KEYWORDS]
        if not strong and not ex_hits and len(hits) < 2:
            continue  # одиночное слабое слово («комиссий нет» про вклад без комиссий) — не нарушение
        if soft and p.code in ("guarantee", "pressure", "concealment", "tie_in"):
            continue  # «никто не гарантирует …» — не нарушение
        kw_score = 0.55 + 0.12 * min(3, len(hits)) + (0.2 if ex_hits else 0.0)
        out.append(
            Finding(
                pattern_code=p.code,
                family=p.family,
                confidence=round(min(0.97, kw_score * max(0.5, min(1.5, p.weight))), 2),
                quote=text.strip()[:240],
                evidence=sorted(set(hits + ex_hits))[:5],
                recommendation_ru=p.recommendation_ru,
            )
        )
    return out


def _fact(f: FactResult) -> dict[str, Any]:
    return {
        "claim": f.claim,
        "truth": f.truth,
        "source_table": f.source_table,
        "source_key": f.source_key,
        "verified": f.verified,
        "is_false": f.is_false,
    }


def check_script(employee_turns: list[str], script: ServiceScript | None) -> list[dict[str, Any]]:
    """Этапы скрипта: есть ли маркеры в репликах сотрудника. Возвращает [{code, name_ru, status: done|missed, evidence}]."""
    if not script:
        return []
    joined = _norm(" \n ".join(employee_turns))
    res = []
    for s in script.steps:
        ev = [m for m in s.markers if _marker_present(joined, _norm(m))]
        res.append(
            {
                "code": s.code,
                "name_ru": s.name_ru,
                "status": "done" if ev else ("missed" if s.required else "skipped"),
                "evidence": ev[:3],
            }
        )
    return res


def _marker_present(joined: str, marker: str) -> bool:
    """Маркер этапа засчитывается, если он не отрицается («паспорт не нужен», «без паспорта»)."""
    for m in re.finditer(re.escape(marker), joined):
        before = joined[max(0, m.start() - 6) : m.start()]
        after = joined[m.end() : m.end() + 24]
        if _NEGATED_AFTER.match(after) or before.rstrip().endswith("без"):
            continue
        return True
    return False


def aggregate_counter(
    findings: list[Finding], patterns: list[Pattern], *, min_confidence: float = 0.6
) -> dict[str, Any]:
    """Счётчик нарушений за встречу (ДТЗ FR-2.4): уникальные паттерны ≥ порога, семейства, максимальная уверенность."""
    strong = [f for f in findings if f.confidence >= min_confidence]
    by_code: dict[str, Finding] = {}
    for f in strong:
        if f.pattern_code not in by_code or f.confidence > by_code[f.pattern_code].confidence:
            by_code[f.pattern_code] = f
    pmap = {p.code: p for p in patterns}
    immediate = [
        f.pattern_code
        for f in by_code.values()
        if pmap.get(f.pattern_code)
        and pmap[f.pattern_code].alert_policy == "immediate"
        and f.confidence >= pmap[f.pattern_code].immediate_threshold
    ]
    return {
        "violations": len(strong),
        "unique_patterns": sorted(by_code),
        "families": sorted({f.family for f in strong}),
        "max_confidence": max((f.confidence for f in strong), default=0.0),
        "immediate": immediate,
    }
