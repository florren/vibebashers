from decimal import Decimal

import pytest

from app.analytics.csi_statistics import quartiles, spearman


@pytest.mark.parametrize(
    "pairs,expected,n",
    [
        ([], None, 0),
        ([(1, 2)], None, 1),
        ([(1, 1), (1, 2)], None, 2),
        ([(1, 1), (2, 1)], None, 2),
        ([(3, 9), (1, 1), (2, 4)], 1, 3),
        ([(3, 1), (1, 9), (2, 4)], -1, 3),
        # Средние tied ranks: Pearson([1.5,1.5,3,4],[1,2,3,4]).
        ([(1, 1), (1, 2), (2, 3), (3, 4)], 0.9486832980505138, 4),
        ([(None, 7), (1, 2), (2, None), (3, 4), (float("nan"), 5), (5, float("inf")), (True, 6)], 1, 2),
    ],
)
def test_spearman_known_values_and_pairwise_unknown(pairs, expected, n):
    actual, count = spearman(pairs)
    assert count == n
    assert actual is None if expected is None else actual == pytest.approx(expected)


@pytest.mark.parametrize(
    "values,n,expected",
    [
        ([], 0, None),
        ([None, float("nan"), float("inf"), False, 10**1000], 0, None),
        ([17], 1, (17, 17, 17)),
        ([10, 20], 2, (12.5, 15, 17.5)),
        ([50, 10, 40, 20, 30], 5, (20, 30, 40)),
        ([0, 0, 0, 1, 1], 5, (0, 0, 1)),
        ([None, Decimal("0.25"), Decimal("1.25")], 2, (0.5, 0.75, 1)),
    ],
)
def test_quartiles_match_percentile_cont(values, n, expected):
    count, actual = quartiles(iter(values))
    assert count == n
    assert actual is None if expected is None else actual == pytest.approx(expected)
