"""T-015: точные Decimal ставки из ТЗ0.4, без округления долей копейки."""

import csv
import json
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
# Независимый эталон таблицы ТЗ0.4 в том же порядке, с явными кодами приложения.
EXPECTED = dict(
    zip(
        "mobile_app deposit bank_average debit_card transfers loyalty credit_card payments salary_card support_chat call_center atm branches card_delivery pension consumer_loan premium_service brokerage subscription pos_terminals mortgage pay_service kids_card investments bnpl insurance kids_service auto_loan real_estate id_service".split(),
        "1323 961 4050 458.46 373.005 373.005 305 292.005 232.875 206.955 204.93 131.22 115 99.225 96.795 92.745 91.53 66.015 63.585 50.22 48.195 40.5 38.475 32.805 32.4 20.655 17.82 15.795 5.67 0.405".split(),
        strict=True,
    )
)


def test_all_tz_rates_and_existing_notification_alias_are_exact():
    with (ROOT / "data/dcltv_rates.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    by_code = {row["code"]: row for row in rows}
    assert len(rows) == len(by_code) == 31
    assert set(by_code) == set(EXPECTED) | {"notifications"}
    for code, expected in EXPECTED.items():
        assert Decimal(by_code[code]["rate_rub"]) == Decimal(expected), code
        assert by_code[code]["name_ru"] and by_code[code]["name_en"]
        assert isinstance(json.loads(by_code[code]["maps_to"]), dict)
    assert Decimal(by_code["notifications"]["rate_rub"]) == Decimal(EXPECTED["payments"])
    assert json.loads(by_code["notifications"]["maps_to"]) == {"systems": ["notification_gw"]}
    assert json.loads(by_code["bank_average"]["maps_to"]) == {"fallback": True}


def test_economics_and_bonus_catalog_defaults_are_unchanged():
    document = yaml.safe_load((ROOT / "data/gifts.yaml").read_text())
    settings = document["economics_settings"]
    assert Decimal(str(settings["detractor_share"])) == Decimal("0.10")
    assert Decimal(str(settings["no_return_share"])) == Decimal("0.50")
    assert settings["fallback_rate_code"] == "bank_average"
    assert settings["calibration_mode"] == "manual"
    bonus = next(row for row in document["gift_catalog"] if row["code"] == "bonus_points")
    assert bonus["rule"] == {
        "by_criticality": {"low": 300, "medium": 600, "high": 1000},
        "repeat_bonus": 200,
        "cap": 1000,
    }
