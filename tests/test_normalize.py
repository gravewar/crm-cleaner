import pytest

from zcleaner import normalize as N


@pytest.mark.parametrize("raw, expected", [
    ("4165550123", "(416) 555-0123"),
    ("+1 416 555 0123", "(416) 555-0123"),
    ("1-416-555-0123", "(416) 555-0123"),
    ("416.555.0123 x12", "(416) 555-0123 ext. 12"),
    ("(416)555-0123 ext 7", "(416) 555-0123 ext. 7"),
    ("+44 20 7946 0958", "+44 20 7946 0958"),   # international: left alone
    ("555-012", "555-012"),                      # unparseable: left alone
    ("", ""),
])
def test_phone(raw, expected):
    assert N.norm_phone(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Ont.", "ON"), ("ontario", "ON"), ("ON ", "ON"), ("Québec", "QC"), ("PQ", "QC"),
    ("P.E.I.", "PE"), ("Mass.", "MA"), ("new york", "NY"), ("Narnia", "Narnia"),
])
def test_region(raw, expected):
    assert N.norm_region(raw) == expected


@pytest.mark.parametrize("raw, country, expected", [
    ("m5v2t6", "", "M5V 2T6"),
    ("M5V-2T6", "Canada", "M5V 2T6"),
    ("2108", "United States", "02108"),     # Excel ate the leading zero
    ("2108", "", "2108"),                   # without a country we don't guess
    ("021081234", "", "02108-1234"),
])
def test_postal(raw, country, expected):
    assert N.norm_postal(raw, country) == expected


@pytest.mark.parametrize("raw, expected", [
    ("NORTHWIND ANALYTICS, INC", "Northwind Analytics Inc."),
    ("northwind analytics incorporated", "Northwind Analytics Inc."),
    ("Bluefin  Labs   Limited", "Bluefin Labs Ltd."),
    ("ABC HOLDINGS CORP", "ABC Holdings Corp."),
    ("Maple Ridge L.L.C.", "Maple Ridge LLC"),
    ("Ironbark-ish Co", "Ironbark-ish Co."),
])
def test_company(raw, expected):
    assert N.norm_company(raw) == expected


def test_company_key_ignores_suffix_case_and_the():
    assert N.company_key("The Northwind Analytics, Inc.") == N.company_key("NORTHWIND ANALYTICS") == "northwind analytics"


@pytest.mark.parametrize("raw, expected", [
    ("SARAH", "Sarah"), ("o'brien", "O'Brien"), ("mcneil", "McNeil"),
    ("marie-claude", "Marie-Claude"), ("DeAndre", "DeAndre"), ("  Sarah  ", "Sarah"),
])
def test_person_name(raw, expected):
    assert N.norm_person_name(raw) == expected


def test_email():
    assert N.norm_email("  Jane.Doe@Example.COM ") == "jane.doe@example.com"
    assert N.is_valid_email("jane.doe@bluefin.example")
    for bad in ("jane at bluefin.example", "jane@@bluefin.example", "jane@bluefin", "jane..d@x.example"):
        assert not N.is_valid_email(bad)
    assert N.is_role_email("info@bluefin.example")


def test_nicknames():
    assert N.canonical_first("Bob") == N.canonical_first("robert") == "robert"
    assert N.canonical_first("Liz") == "elizabeth"
