import datetime as dt

import pytest

from app.analytics.csi_cohorts import cohort_status, members_fingerprint, visits_fingerprint
from app.sim.csi_scoped_corpus import generate_scoped


def test_snapshot_digest_is_order_and_timezone_independent_but_not_value_independent():
    visits = [
        {"wait_bucket": "0-5", "redirects_bucket": "0", "visits": 20},
        {"wait_bucket": "5-15", "redirects_bucket": "1", "visits": 30},
    ]
    members = [
        {
            "signal_id": 1,
            "response_at": dt.datetime(2026, 11, 8, 10, tzinfo=dt.timezone(dt.timedelta(hours=3))),
            "wait_bucket": "0-5",
            "redirects_bucket": "0",
        }
    ]
    header = {
        "visits_digest": visits_fingerprint(visits),
        "members_digest": members_fingerprint(members),
        "member_count": 1,
    }
    assert cohort_status(header, visits[::-1], members) is None
    assert (
        cohort_status(header, visits, [{**members[0], "response_at": members[0]["response_at"].astimezone(dt.UTC)}])
        is None
    )
    assert cohort_status(header, visits[:-1], members) == "visits_digest_mismatch"
    assert cohort_status(header, [{**visits[0], "visits": 21}, visits[1]], members) == "visits_digest_mismatch"
    assert cohort_status(header, visits, []) == "members_digest_mismatch"
    assert cohort_status(header, visits, [{**members[0], "signal_id": 2}]) == "members_digest_mismatch"


@pytest.mark.parametrize("id_base", [0, 30001, 899700, True])
def test_sample_namespace_is_bounded_and_never_guessed(id_base):
    with pytest.raises(ValueError, match="id_base"):
        generate_scoped(id_base=id_base)


def test_explicit_sample_namespaces_do_not_overlap():
    a, b = generate_scoped(), generate_scoped(id_base=30300)
    assert a["metadata"]["dataset_code"] != b["metadata"]["dataset_code"]
    assert {r["csi_no"] for r in a["complaints"]}.isdisjoint(r["csi_no"] for r in b["complaints"])
