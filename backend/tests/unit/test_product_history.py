"""T-240: календарь, seed и точный actual tail; без DDL или экономических допущений."""

from __future__ import annotations

import datetime as dt

import pytest

from app.contracts.enums import Criticality, ProductLine, Sentiment
from app.corpus.history import ActualSignal, HistoryConfig, build_history

NOW = dt.datetime(2026, 3, 5, 12, tzinfo=dt.UTC)
LINE = ProductLine.DEPOSITS
CONFIG = HistoryConfig((1.0,) * 12, 2.0, 0.1)


def actual() -> list[ActualSignal]:
    return [
        ActualSignal(9, LINE, NOW - dt.timedelta(days=1), "client_voice", Criticality.HIGH, Sentiment.NEGATIVE),
        ActualSignal(9, LINE, NOW - dt.timedelta(days=7), "client_voice", Criticality.MEDIUM, Sentiment.NEGATIVE),
        ActualSignal(9, LINE, NOW - dt.timedelta(days=13), "unrecognized", Criticality.LOW, Sentiment.NEUTRAL),
    ]


def build(rows: list[ActualSignal] | None = None, *, seed: int = 42, config: HistoryConfig = CONFIG):
    return build_history(
        seed=seed,
        run_id=9,
        anchor=NOW,
        actual=actual() if rows is None else rows,
        product_lines=frozenset({LINE}),
        known_platforms=frozenset({"client_voice"}),
        fault_months=frozenset({(LINE, dt.date(2025, 12, 1))}),
        config=config,
    )


def test_same_seed_and_input_permutation_same_history() -> None:
    assert build() == build(list(reversed(actual())))
    assert len(build().rows) == 12
    assert {x.run_id for x in build().rows} == {9}
    assert all(x.loss_rub is None for x in build().rows)
    assert all(0 <= x.negative_count <= x.signal_count and x.critical_count <= x.signal_count for x in build().rows)


def test_partial_month_tail_is_exact_by_line_source_severity() -> None:
    rows = build().rows
    tail = [x for x in rows if not x.is_synthetic]
    assert {x.month for x in tail} == {dt.date(2026, 2, 1), dt.date(2026, 3, 1)}
    assert sum(x.signal_count for x in tail) == 3
    assert sum(x.negative_count for x in tail) == 2
    assert sum(x.critical_count for x in tail) == 1
    assert [x.by_source for x in tail] == [
        {"client_voice": {"medium": 1}, "unknown": {"low": 1}},
        {"client_voice": {"high": 1}},
    ]
    assert tail[0].coverage_start == NOW - dt.timedelta(days=14)
    assert tail[-1].coverage_end == NOW
    assert all(x.is_partial for x in tail)
    assert tail == [x for x in build(seed=999).rows if not x.is_synthetic]


def test_month_calendar_seasonality_and_fault_spike() -> None:
    flat = HistoryConfig((1.0,) * 12, 2.0, 0)
    rows = build(config=flat).rows
    dec = next(x for x in rows if x.month == dt.date(2025, 12, 1))
    jan = next(x for x in rows if x.month == dt.date(2026, 1, 1))
    assert dec.signal_count > jan.signal_count
    seasonal = list(flat.seasonality)
    seasonal[0] = 3
    changed = build(config=HistoryConfig(tuple(seasonal), 2, 0)).rows
    assert next(x for x in changed if x.month == jan.month).signal_count > jan.signal_count
    assert all(x.coverage_start.day == 1 and x.coverage_end.day == 1 for x in rows if x.is_synthetic)


def test_unknown_direction_is_reported_not_guessed() -> None:
    rows = actual() + [ActualSignal(9, None, NOW - dt.timedelta(days=1), None, None, None)]
    assert build(rows).unmapped_actual_count == 1
    assert sum(x.signal_count for x in build(rows).rows if not x.is_synthetic) == 3


def test_foreign_run_naive_and_unknown_owner_rejected() -> None:
    for factory in [
        lambda: ActualSignal(8, LINE, NOW, None, None, None),
        lambda: ActualSignal(9, LINE, NOW.replace(tzinfo=None), None, None, None),
    ]:
        with pytest.raises(ValueError):
            build([factory()])
    with pytest.raises(ValueError):
        build_history(
            seed=1,
            run_id=True,
            anchor=NOW,
            actual=[],
            product_lines=frozenset({LINE}),
            known_platforms=frozenset(),
            fault_months=frozenset(),
            config=CONFIG,
        )


def test_boundary_half_open_tail_and_empty_lines() -> None:
    rows = [
        ActualSignal(9, LINE, NOW, None, None, None),
        ActualSignal(9, LINE, NOW - dt.timedelta(days=14), None, None, None),
        ActualSignal(9, LINE, NOW - dt.timedelta(days=14, seconds=1), None, None, None),
    ]
    assert sum(x.signal_count for x in build(rows).rows if not x.is_synthetic) == 1
    assert all(x.signal_count == 0 and x.by_source == {} for x in build([]).rows)


@pytest.mark.parametrize(
    "config",
    [
        lambda: HistoryConfig((1.0,), 1, 0),
        lambda: HistoryConfig((1.0,) * 12, 0.5, 0),
        lambda: HistoryConfig((1.0,) * 12, 1, 1.1),
        lambda: HistoryConfig((float("nan"),) * 12, 1, 0),
        lambda: HistoryConfig((True,) * 12, 1, 0),
    ],
)
def test_invalid_history_config(config) -> None:
    with pytest.raises(ValueError):
        config()


def test_actual_rows_do_not_accept_untyped_state() -> None:
    with pytest.raises(ValueError):
        ActualSignal(True, LINE, NOW, None, None, None)
    with pytest.raises(ValueError):
        ActualSignal(9, "deposits", NOW, None, None, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ActualSignal(9, LINE, NOW, None, "high", False)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ActualSignal(9, LINE, NOW, None, None, 1)  # type: ignore[arg-type]


def test_exact_tail_all_fifteen_lines_sources_and_severities() -> None:
    from collections import Counter

    lines = frozenset(line for line in ProductLine if line != ProductLine.OTHER)
    assert len(lines) == 15
    rows = [
        ActualSignal(
            9,
            line,
            NOW - dt.timedelta(days=index % 13 + 1),
            source,
            severity,
            Sentiment.NEGATIVE if severity != Criticality.LOW else Sentiment.NEUTRAL,
        )
        for index, line in enumerate(sorted(lines))
        for source in ("client_voice", "app_feedback", "unrecognized")
        for severity in Criticality
    ]
    result = build_history(
        seed=42,
        run_id=9,
        anchor=NOW,
        actual=rows,
        product_lines=lines,
        known_platforms=frozenset({"client_voice", "app_feedback"}),
        fault_months=frozenset(),
        config=CONFIG,
    )
    expected = Counter(
        (r.product_line, r.source_platform if r.source_platform != "unrecognized" else "unknown", r.criticality.value)
        for r in rows
    )
    found = Counter()
    for month in result.rows:
        if not month.is_synthetic:
            for source, severities in month.by_source.items():
                for severity, count in severities.items():
                    found[month.product_line, source, severity] += count
    assert found == expected  # По каждой ячейке отклонение ровно 0%, не только по общему итогу.
    assert len(result.rows) == 180 and result.unmapped_actual_count == 0


def test_exact_month_boundary_never_fabricates_future_month() -> None:
    anchor = dt.datetime(2026, 3, 1, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Moscow"))
    result = build_history(
        seed=1,
        run_id=9,
        anchor=anchor,
        actual=[],
        product_lines=frozenset({LINE}),
        known_platforms=frozenset(),
        fault_months=frozenset(),
        config=CONFIG,
    )
    assert len(result.rows) == 12
    assert result.rows[-1].month == dt.date(2026, 2, 1)
    assert all(row.coverage_end <= anchor for row in result.rows)


def test_unknown_sentiment_is_not_counted_as_neutral() -> None:
    rows = actual() + [ActualSignal(9, LINE, NOW - dt.timedelta(days=1), None, None, None)]
    tail = [row for row in build(rows).rows if not row.is_synthetic]
    assert sum(row.signal_count for row in tail) == 4
    assert sum(row.sentiment_known_count for row in tail) == 3
    assert sum(row.negative_count for row in tail) == 2
    assert all(0 <= row.negative_count <= row.sentiment_known_count <= row.signal_count for row in build(rows).rows)


def test_mixed_legacy_aggregation_keeps_quality_unknown() -> None:
    from app.corpus.history_store import summarize_history

    modern = dict(run_id=9, signal_count=4, sentiment_known_count=3, negative_count=2, loss_rub=None)
    legacy = dict(run_id=None, signal_count=2, sentiment_known_count=None, negative_count=0, loss_rub=0)
    assert summarize_history([modern]) == dict(
        signal_count=4,
        sentiment_known_count=3,
        negative_count=2,
        unknown_count=1,
        sentiment_quality="known",
        loss_rub=None,
    )
    result = summarize_history([modern, legacy])
    assert result["signal_count"] == 6
    assert result["sentiment_quality"] == "unknown"
    assert all(result[key] is None for key in ("negative_count", "sentiment_known_count", "unknown_count", "loss_rub"))
