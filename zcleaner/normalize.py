"""Field normalizers.

Every function takes a raw string and returns a cleaned string. They never
raise and never invent data: if a value can't be confidently cleaned, it is
returned trimmed but otherwise untouched (and the validator flags it instead).
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

_WS = re.compile(r"\s+")


def squash(value: str) -> str:
    """Trim and collapse internal whitespace."""
    return _WS.sub(" ", str(value or "")).strip()


def fold(value: str) -> str:
    """Lowercase ASCII-folded form, for comparisons only (``Côté`` -> ``cote``)."""
    nfkd = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


def _badly_cased(value: str) -> bool:
    letters = [c for c in value if c.isalpha()]
    return bool(letters) and (value == value.lower() or value == value.upper())


# --------------------------------------------------------------------------- #
# People names
# --------------------------------------------------------------------------- #


def _cap_word(word: str) -> str:
    lower = word.lower()
    if lower.startswith("mc") and len(lower) > 2:
        return "Mc" + lower[2].upper() + lower[3:]
    if lower.startswith("o'") and len(lower) > 2:
        return "O'" + lower[2].upper() + lower[3:]
    return lower[:1].upper() + lower[1:]


def norm_person_name(value: str) -> str:
    """Fix whitespace, and fix casing only when it's clearly wrong.

    ``SARAH`` and ``sarah`` become ``Sarah``; ``DeAndre`` is left alone because
    mixed case usually means someone typed it deliberately.
    """
    s = squash(value)
    if not _badly_cased(s):
        return s
    parts = []
    for word in s.split(" "):
        parts.append("-".join(_cap_word(p) for p in word.split("-")))
    return " ".join(parts)


# Nicknames -> canonical first name, used only for matching (never written back).
NICKNAMES = {
    "mike": "michael", "mick": "michael", "jen": "jennifer", "jenny": "jennifer",
    "dave": "david", "dan": "daniel", "danny": "daniel", "bob": "robert",
    "bobby": "robert", "rob": "robert", "robbie": "robert", "bill": "william",
    "will": "william", "billy": "william", "matt": "matthew", "chris": "christopher",
    "andy": "andrew", "drew": "andrew", "josh": "joshua", "nate": "nathan",
    "liz": "elizabeth", "beth": "elizabeth", "lizzie": "elizabeth", "eliza": "elizabeth",
    "ben": "benjamin", "benny": "benjamin", "kate": "katherine", "katie": "katherine",
    "kathy": "katherine", "cathy": "katherine", "tom": "thomas", "tommy": "thomas",
    "becky": "rebecca", "becca": "rebecca", "tony": "anthony", "maggie": "margaret",
    "meg": "margaret", "peggy": "margaret", "nick": "nicholas", "nicky": "nicholas",
    "sam": "samuel", "sammy": "samuel", "jon": "jonathan", "jim": "james",
    "jimmy": "james", "jamie": "james", "steve": "stephen", "steven": "stephen",
    "rick": "richard", "rich": "richard", "sue": "susan", "susie": "susan",
    "abby": "abigail", "alex": "alexander", "greg": "gregory", "jeff": "jeffrey",
    "pat": "patrick", "ed": "edward", "eddie": "edward", "ted": "edward",
    "fred": "frederick", "joe": "joseph", "joey": "joseph", "johnny": "john",
    "izzy": "isabelle", "isabel": "isabelle", "zach": "zachary", "gabe": "gabriel",
}


def canonical_first(value: str) -> str:
    f = re.sub(r"[^a-z\- ]", "", fold(squash(value)))
    return NICKNAMES.get(f, f)


def name_key(value: str) -> str:
    """Comparison key for a surname: folded, letters only."""
    return re.sub(r"[^a-z]", "", fold(value))


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #

EMAIL_RE = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~.\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}$")
ROLE_LOCALPARTS = {
    "info", "sales", "admin", "contact", "support", "hello", "office", "team",
    "noreply", "no-reply", "marketing", "billing", "accounts", "hr", "jobs",
    "enquiries", "inquiries", "help", "service", "reception", "general",
}


def norm_email(value: str) -> str:
    s = squash(value).lower()
    s = s.removeprefix("mailto:").strip("<>").strip()
    return s


def is_valid_email(value: str) -> bool:
    return bool(value) and ".." not in value and bool(EMAIL_RE.match(value))


def is_role_email(value: str) -> bool:
    return "@" in value and value.split("@", 1)[0] in ROLE_LOCALPARTS


def email_domain(value: str) -> str:
    return value.split("@", 1)[1] if "@" in value else ""


# --------------------------------------------------------------------------- #
# Phone (North American Numbering Plan)
# --------------------------------------------------------------------------- #

_EXT = re.compile(r"\s*(?:ext\.?|extension|x|#)\s*(\d{1,6})\s*$", re.IGNORECASE)
PHONE_CANON_RE = re.compile(r"^\(\d{3}\) \d{3}-\d{4}( ext\. \d+)?$")


def _split_ext(value: str) -> tuple[str, str]:
    m = _EXT.search(value)
    if not m:
        return value, ""
    return value[: m.start()], m.group(1)


def phone_digits(value: str) -> str:
    """The 10-digit NANP number, or ``""`` if it isn't one."""
    main, _ = _split_ext(squash(value))
    digits = re.sub(r"\D", "", main)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "23456789" and digits[3] in "23456789":
        return digits
    return ""


def norm_phone(value: str) -> str:
    """Format North American numbers as ``(416) 555-0123 ext. 12``.

    International numbers (``+44 …``) and anything unparseable are only trimmed.
    """
    s = squash(value)
    if not s:
        return s
    digits = phone_digits(s)
    if not digits:
        return s
    _, ext = _split_ext(s)
    out = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return f"{out} ext. {ext}" if ext else out


def is_valid_phone(value: str) -> bool:
    s = squash(value)
    return bool(phone_digits(s)) or (s.startswith("+") and len(re.sub(r"\D", "", s)) >= 8)


# --------------------------------------------------------------------------- #
# Regions and countries
# --------------------------------------------------------------------------- #

CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
REGION_CODES = set(CA_PROVINCES) | set(US_STATES)

_REGION_EXTRA = {
    "ont": "ON", "que": "QC", "pq": "QC", "nfld": "NL", "newfoundland": "NL",
    "labrador": "NL", "pei": "PE", "alta": "AB", "man": "MB", "sask": "SK",
    "yukon territory": "YT", "nwt": "NT", "mass": "MA", "tex": "TX", "ill": "IL",
    "wash": "WA", "calif": "CA", "cal": "CA", "fla": "FL", "penn": "PA", "penna": "PA",
    "mich": "MI", "minn": "MN", "wis": "WI", "conn": "CT", "ariz": "AZ", "colo": "CO",
    "ore": "OR", "okla": "OK", "vt": "VT", "washington dc": "DC", "dc": "DC",
}


def _region_key(value: str) -> str:
    return squash(fold(value).replace(".", "").replace(",", ""))


_REGION_LOOKUP: dict[str, str] = {}
for _code, _name in {**CA_PROVINCES, **US_STATES}.items():
    _REGION_LOOKUP[_region_key(_code)] = _code
    _REGION_LOOKUP[_region_key(_name)] = _code
_REGION_LOOKUP.update(_REGION_EXTRA)


def norm_region(value: str) -> str:
    """``Ont.``, ``ontario`` and ``ON `` all become ``ON``."""
    s = squash(value)
    if not s:
        return s
    return _REGION_LOOKUP.get(_region_key(s), s)


def region_country(code: str) -> str:
    if code in CA_PROVINCES:
        return "Canada"
    if code in US_STATES:
        return "United States"
    return ""


_COUNTRY_LOOKUP = {
    "canada": "Canada", "ca": "Canada", "can": "Canada",
    "us": "United States", "usa": "United States", "united states": "United States",
    "united states of america": "United States", "america": "United States",
}


def norm_country(value: str) -> str:
    s = squash(value)
    return _COUNTRY_LOOKUP.get(_region_key(s), s) if s else s


# --------------------------------------------------------------------------- #
# Postal / ZIP codes
# --------------------------------------------------------------------------- #

CA_POSTAL_RE = re.compile(r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] \d[ABCEGHJ-NPRSTV-Z]\d$")
US_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def norm_postal(value: str, country: str = "") -> str:
    """``m5v2t6`` -> ``M5V 2T6``; restores ZIP leading zeros Excel strips (``2108`` -> ``02108``)."""
    s = squash(value)
    if not s:
        return s
    compact = re.sub(r"[\s\-]", "", s).upper()
    if re.fullmatch(r"[A-Z]\d[A-Z]\d[A-Z]\d", compact):
        return f"{compact[:3]} {compact[3:]}"
    if compact.isdigit():
        if len(compact) == 9:
            return f"{compact[:5]}-{compact[5:]}"
        if len(compact) == 5:
            return compact
        if len(compact) in (3, 4) and country == "United States":
            return compact.zfill(5)
    return s


def is_canonical_postal(value: str) -> bool:
    return bool(CA_POSTAL_RE.match(value) or US_ZIP_RE.match(value))


# --------------------------------------------------------------------------- #
# Companies and websites
# --------------------------------------------------------------------------- #

_SUFFIX_CANON = {
    "inc": "Inc.", "incorporated": "Inc.", "ltd": "Ltd.", "limited": "Ltd.",
    "corp": "Corp.", "corporation": "Corp.", "llc": "LLC", "l l c": "LLC",
    "co": "Co.", "ltee": "Ltée", "lp": "LP", "llp": "LLP",
    "plc": "PLC", "gmbh": "GmbH",
}
_SUFFIX_RE = re.compile(
    r"[\s,]+(" + "|".join(sorted((re.escape(k).replace(r"\ ", r"\.?\s?") for k in _SUFFIX_CANON),
                               key=len, reverse=True)) + r")\.?$",
    re.IGNORECASE,
)
_SMALL_WORDS = {"and", "of", "the", "for", "de", "du", "la", "le", "et"}


def _title_company(value: str) -> str:
    was_upper = value == value.upper()
    words = []
    for i, w in enumerate(value.split(" ")):
        lw = w.lower()
        if i > 0 and lw in _SMALL_WORDS:
            words.append(lw)
        elif was_upper and len(w) <= 3 and w.isalpha() and lw not in _SUFFIX_CANON:
            words.append(w)  # likely an acronym like "ABC"
        else:
            words.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(words)


def norm_company(value: str) -> str:
    """Tidy a company name: whitespace, casing, and one spelling of the legal suffix.

    ``NORTHWIND ANALYTICS, INC`` -> ``Northwind Analytics Inc.``
    """
    s = squash(value).strip(",")
    if not s:
        return s
    m = _SUFFIX_RE.search(s)
    base, suffix = (s[: m.start()], m.group(1)) if m else (s, "")
    base = base.strip(" ,")
    if not base:  # the whole name was a "suffix", e.g. a company called "Co"
        base, suffix = s, ""
    if _badly_cased(base):
        base = _title_company(base)
    if suffix:
        key = re.sub(r"[.\s]", "", fold(suffix))
        suffix = _SUFFIX_CANON.get(key, suffix)
        return f"{base} {suffix}"
    return base


def company_key(value: str) -> str:
    """Comparison key: ``The Northwind Analytics, Inc.`` -> ``northwind analytics``."""
    s = fold(squash(value)).replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    words = s.split()
    suffix_words = {re.sub(r"\s", "", k) for k in _SUFFIX_CANON} | {"company"}
    while words and words[-1] in suffix_words:
        words.pop()
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(words)


def norm_website(value: str) -> str:
    s = squash(value)
    if not s:
        return s
    if not re.match(r"^https?://", s, re.IGNORECASE):
        s = "https://" + s
    m = re.match(r"^(https?://)([^/]+)(.*)$", s, re.IGNORECASE)
    if m:
        s = m.group(1).lower() + m.group(2).lower() + m.group(3)
    return s.rstrip("/")


def website_domain(value: str) -> str:
    s = squash(value).lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/", 1)[0]
    return s.removeprefix("www.")


def norm_city(value: str) -> str:
    s = squash(value)
    if not _badly_cased(s):
        return s
    return " ".join("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")) for w in s.split(" "))


def is_well_cased(value: str) -> bool:
    return not _badly_cased(squash(value))
