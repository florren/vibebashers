"""Независимый PostgreSQL oracle, без schema/data mutation."""

import psycopg
import pytest

from app.analytics.csi_statistics import quartiles, spearman
from tests.helpers import dsn


@pytest.mark.parametrize("values", [[10, 20], [50, 10, 40, 20, 30], [0, 0, 0, 1, 1], [17]])
def test_quartiles_agree_with_postgresql_percentile_cont(db_url, values):
    with psycopg.connect(dsn(db_url)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        expected = conn.execute(
            "SELECT percentile_cont(ARRAY[0.25,0.5,0.75]) WITHIN GROUP(ORDER BY v) FROM unnest(%s::numeric[]) v",
            (values,),
        ).fetchone()[0]
    count, actual = quartiles(values)
    assert count == len(values) and actual == pytest.approx(expected)


def test_tied_spearman_matches_postgresql_average_ranks(db_url):
    xs, ys = [1, 1, 2, 3, 3, 4], [5, 3, 4, 2, 1, 1]
    with psycopg.connect(dsn(db_url)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        expected = conn.execute(
            "WITH pairs AS (SELECT * FROM unnest(%s::numeric[],%s::numeric[]) p(x,y)), "
            "ranks AS (SELECT rank() OVER(ORDER BY x)+(count(*) OVER(PARTITION BY x)-1)/2.0 rx, "
            "rank() OVER(ORDER BY y)+(count(*) OVER(PARTITION BY y)-1)/2.0 ry FROM pairs) "
            "SELECT corr(rx,ry) FROM ranks",
            (xs, ys),
        ).fetchone()[0]
    actual, count = spearman(zip(xs, ys, strict=True))
    assert count == 6 and actual == pytest.approx(expected)
