"""Generate realistic, entirely fake Zoho CRM exports for demos and testing.

Everything here is invented. Companies are made-up word pairs, every email
uses the reserved ``.example`` domain, and every phone number uses the
555-01XX block set aside for fiction. The generator also writes an answer key
(``_truth.csv``) so the matcher's precision and recall can be measured.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .normalize import fold

FIRST = ["Sarah", "Michael", "Jennifer", "David", "Emily", "James", "Olivia", "Daniel",
         "Sophie", "Robert", "Hannah", "William", "Chloe", "Matthew", "Grace", "Christopher",
         "Ava", "Andrew", "Maya", "Joshua", "Leah", "Nathan", "Priya", "Ethan", "Fatima",
         "Liam", "Mei", "Noah", "Aisha", "Lucas", "Elizabeth", "Benjamin", "Katherine",
         "Thomas", "Rebecca", "Anthony", "Margaret", "Nicholas", "Isabelle", "Samuel", "Zoe",
         "Jonathan", "Amara", "Owen", "Claire", "Gabriel", "Nadia", "Ryan", "Julia", "Arjun",
         "Mateo", "Yuki", "Siobhan", "Declan", "Marie-Claude", "Rohan", "Ingrid", "Tariq"]
LAST = ["Chen", "MacDonald", "Smith", "Nguyen", "O'Brien", "Patel", "Tremblay", "Campbell",
        "Singh", "Martin", "Roy", "Wilson", "Gagnon", "Taylor", "Brown", "LeBlanc", "McNeil",
        "Kowalski", "Fraser", "Ahmed", "Morrison", "Kim", "Bouchard", "Murphy", "Rossi",
        "Johnson", "Garcia", "Okafor", "Sullivan", "Wong", "Côté", "Fitzgerald", "MacLeod",
        "Henderson", "Dubois", "Reid", "Hughes", "Park", "Lam", "Ferreira", "Doucette",
        "Boudreau", "Abebe", "Novak", "Schmidt", "Ivanova", "Morales", "Thompson", "Clarke",
        "Bennett", "Sato", "Lindqvist", "Haddad", "Petrov", "Osei", "Ramirez"]
NICK = {"Michael": "Mike", "Jennifer": "Jen", "David": "Dave", "Daniel": "Dan",
        "Robert": "Bob", "William": "Bill", "Matthew": "Matt", "Christopher": "Chris",
        "Andrew": "Andy", "Joshua": "Josh", "Nathan": "Nate", "Elizabeth": "Liz",
        "Benjamin": "Ben", "Katherine": "Kate", "Thomas": "Tom", "Rebecca": "Becky",
        "Anthony": "Tony", "Margaret": "Maggie", "Nicholas": "Nick", "Samuel": "Sam",
        "Jonathan": "Jon", "James": "Jim"}

PREFIX = ["Northwind", "Bluefin", "Maple Ridge", "Granite", "Harbourview", "Cobalt",
          "Silverline", "Tidewater", "Kestrel", "Keystone", "Lighthouse", "Pinecrest",
          "Ironbark", "Sable", "Juniper", "Fathom", "Brightwater", "Larkspur", "Driftwood",
          "Copperleaf", "Halcyon", "Quarry", "Thistle", "Bayberry", "Foxglove", "Wolfhound"]
INDUSTRY = ["Analytics", "Robotics", "Biotech", "Consulting", "Labs", "Energy", "Systems",
            "Media", "Logistics", "Health", "Capital", "Software", "Research", "Materials"]
CA_SUFFIX = ["Inc.", "Ltd.", "Corp.", ""]
US_SUFFIX = ["Inc.", "LLC", "Corp.", ""]
SUFFIX_VARIANTS = {"Inc.": ["Inc", "Inc.", "Incorporated", "INC"], "Ltd.": ["Ltd", "Limited", "LTD."],
                   "Corp.": ["Corp", "Corporation", "CORP"], "LLC": ["L.L.C.", "llc", "LLC."], "": [""]}

# city, region code, region spellings, area codes, postal prefix, country
CITIES = [
    ("Toronto", "ON", ["Ontario", "Ont.", "ontario", "on"], ["416", "647", "437"], "M", "Canada"),
    ("Ottawa", "ON", ["Ontario", "Ont.", "ONTARIO"], ["613", "343"], "K", "Canada"),
    ("Halifax", "NS", ["Nova Scotia", "N.S.", "nova scotia"], ["902", "782"], "B", "Canada"),
    ("Sydney", "NS", ["Nova Scotia", "N.S."], ["902", "782"], "B", "Canada"),
    ("Vancouver", "BC", ["British Columbia", "B.C.", "b.c."], ["604", "778"], "V", "Canada"),
    ("Calgary", "AB", ["Alberta", "Alta.", "alberta"], ["403", "587"], "T", "Canada"),
    ("Montréal", "QC", ["Quebec", "Québec", "Que.", "PQ"], ["514", "438"], "H", "Canada"),
    ("Winnipeg", "MB", ["Manitoba", "Man."], ["204", "431"], "R", "Canada"),
    ("St. John's", "NL", ["Newfoundland", "Nfld.", "Newfoundland and Labrador"], ["709"], "A", "Canada"),
    ("Charlottetown", "PE", ["P.E.I.", "Prince Edward Island", "PEI"], ["902", "782"], "C", "Canada"),
    ("Boston", "MA", ["Massachusetts", "Mass.", "mass"], ["617", "857"], "021", "United States"),
    ("New York", "NY", ["New York", "N.Y.", "new york"], ["212", "646"], "100", "United States"),
    ("Seattle", "WA", ["Washington", "Wash."], ["206", "564"], "981", "United States"),
    ("Austin", "TX", ["Texas", "Tex.", "texas"], ["512", "737"], "787", "United States"),
    ("Chicago", "IL", ["Illinois", "Ill."], ["312", "872"], "606", "United States"),
    ("Portland", "ME", ["Maine", "maine"], ["207"], "041", "United States"),
    ("Burlington", "VT", ["Vermont", "Vt."], ["802"], "054", "United States"),
]
COUNTRY_VARIANTS = {"Canada": ["Canada", "CA", "canada", "CAN"],
                    "United States": ["United States", "USA", "US", "U.S.", "United States of America"]}
LEAD_SOURCES = ["Web Form", "Trade Show", "Referral", "Cold Call", "LinkedIn", "Webinar", "Partner"]
LEAD_STATUS = ["Not Contacted", "Attempted to Contact", "Contact in Future", "Contacted", "Pre-Qualified"]
POSTAL_LETTERS = "ABCEGHJKLMNPRSTVWXYZ"


@dataclass
class Account:
    eid: str
    base: str
    suffix: str
    city: tuple
    phone: str
    domain: str
    postal: str = ""

    @property
    def name(self) -> str:
        return f"{self.base} {self.suffix}".strip()


@dataclass
class Person:
    eid: str
    first: str
    last: str
    account: Account
    email: str
    phone: str
    mobile: str
    postal: str
    extras: dict = field(default_factory=dict)


class Gen:
    def __init__(self, seed: int = 42):
        self.r = random.Random(seed)
        self.used_phones: set[str] = set()
        self.used_emails: set[str] = set()
        self.ids: dict[str, int] = {"Leads": 0, "Contacts": 0, "Accounts": 0}
        self.id_base = {"Leads": 6420931000000180000, "Contacts": 6420931000000250000,
                        "Accounts": 6420931000000090000}

    # -- small helpers ------------------------------------------------------ #
    def chance(self, p: float) -> bool:
        return self.r.random() < p

    def record_id(self, module: str) -> str:
        self.ids[module] += self.r.randint(1, 40)
        return f"zcrm_{self.id_base[module] + self.ids[module] * 1000 + 1}"

    def new_phone(self, city) -> str:
        # Only 100 fictional numbers exist per area code (555-0100 to 555-0199),
        # so fall back to any area code in the same country if a city runs dry.
        pool = city[3]
        for attempt in range(10_000):
            if attempt == 200:
                pool = sorted({ac for c in CITIES if c[5] == city[5] for ac in c[3]})
            d = f"{self.r.choice(pool)}555{self.r.randint(100, 199):04d}"
            if d not in self.used_phones:
                self.used_phones.add(d)
                return d
        raise RuntimeError("Ran out of fictional phone numbers; generate fewer people")

    def postal(self, city) -> str:
        if city[5] == "Canada":
            r = self.r
            return (f"{city[4]}{r.randint(0, 9)}{r.choice(POSTAL_LETTERS)} "
                    f"{r.randint(0, 9)}{r.choice(POSTAL_LETTERS)}{r.randint(0, 9)}")
        return f"{city[4]}{self.r.randint(0, 99):02d}"

    def created(self) -> str:
        return (f"20{self.r.randint(22, 26)}-{self.r.randint(1, 12):02d}-{self.r.randint(1, 28):02d} "
                f"{self.r.randint(8, 18):02d}:{self.r.randint(0, 59):02d}:{self.r.randint(0, 59):02d}")

    # -- messiness ---------------------------------------------------------- #
    def mess_phone(self, d: str) -> str:
        if not d:
            return ""
        a, b, c = d[:3], d[3:6], d[6:]
        fmt = self.r.choice([f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}.{b}.{c}", d,
                             f"+1 {a} {b} {c}", f"1-{a}-{b}-{c}", f"+1{d}", f"({a}){b}-{c}"])
        if self.chance(0.06):
            fmt += self.r.choice([" x", " ext ", " ext. ", " #"]) + str(self.r.randint(10, 999))
        return fmt

    def mess_name(self, s: str) -> str:
        roll = self.r.random()
        if roll < 0.12:
            return s.lower()
        if roll < 0.20:
            return s.upper()
        if roll < 0.28:
            return f" {s}  "
        return s

    def mess_company(self, acc: Account) -> str:
        suffix = self.r.choice(SUFFIX_VARIANTS[acc.suffix] + [acc.suffix] * 3)
        sep = ", " if suffix and self.chance(0.25) else " "
        s = f"{acc.base}{sep}{suffix}".strip() if suffix else acc.base
        if self.chance(0.15):
            s = acc.base  # suffix dropped entirely
        roll = self.r.random()
        if roll < 0.10:
            s = s.upper()
        elif roll < 0.18:
            s = s.lower()
        elif roll < 0.24:
            s = s.replace(" ", "  ", 1) + " "
        return s

    def mess_region(self, city) -> str:
        return self.r.choice([city[1]] * 3 + city[2] + [city[1].lower(), city[1] + " "])

    def mess_country(self, country: str) -> str:
        return self.r.choice([country] * 3 + COUNTRY_VARIANTS[country])

    def mess_postal(self, code: str, country: str) -> str:
        roll = self.r.random()
        if country == "Canada":
            if roll < 0.25:
                return code.replace(" ", "").lower()
            if roll < 0.40:
                return code.replace(" ", "")
            if roll < 0.48:
                return code.replace(" ", "-")
            return code
        if roll < 0.35 and code.startswith("0"):
            return code.lstrip("0")  # what Excel does to New England ZIP codes
        return code

    def mess_email(self, e: str) -> str:
        if not e:
            return e
        roll = self.r.random()
        if roll < 0.12:
            return e.upper() if self.chance(0.3) else e[0].upper() + e[1:]
        if roll < 0.18:
            return f" {e} "
        return e

    def typo(self, s: str) -> str:
        if len(s) < 5:
            return s
        i = self.r.randint(1, len(s) - 2)
        kind = self.r.random()
        if kind < 0.4:
            return s[:i] + s[i + 1] + s[i] + s[i + 2:]          # transposition
        if kind < 0.7:
            return s[:i] + s[i + 1:]                              # dropped letter
        return s[:i] + s[i] + s[i:]                               # doubled letter

    # -- entities ----------------------------------------------------------- #
    def make_accounts(self, n: int) -> list[Account]:
        combos = [(p, i) for p in PREFIX for i in INDUSTRY]
        self.r.shuffle(combos)
        accounts = []
        for k, (p, i) in enumerate(combos[:n]):
            city = self.r.choice(CITIES)
            base = f"{p} {i}"
            suffix = self.r.choice(CA_SUFFIX if city[5] == "Canada" else US_SUFFIX)
            domain = fold(base).replace(" ", "") + ".example"
            accounts.append(Account(f"A{k + 1:04d}", base, suffix, city, self.new_phone(city), domain))
        return accounts

    def make_email(self, first: str, last: str, domain: str) -> str:
        f = "".join(ch for ch in fold(first) if ch.isalpha())
        l_ = "".join(ch for ch in fold(last) if ch.isalpha())
        local = self.r.choice([f"{f}.{l_}", f"{f[0]}{l_}", f"{f}{l_[0]}", f"{f}.{l_}"])
        email, n = f"{local}@{domain}", 2
        while email in self.used_emails:
            email, n = f"{local}{n}@{domain}", n + 1
        self.used_emails.add(email)
        return email

    def make_person(self, eid, first, last, acc: Account) -> Person:
        city = acc.city
        phone = acc.phone if self.chance(0.25) else self.new_phone(city)  # 25% only list the switchboard
        mobile = self.new_phone(city) if self.chance(0.4) else ""
        return Person(eid, first, last, acc, self.make_email(first, last, acc.domain), phone, mobile,
                      self.postal(city))


def _person_row(g: Gen, p: Person, module: str, variant: bool) -> dict:
    first, last, email, phone, mobile = p.first, p.last, p.email, p.phone, p.mobile
    if variant:  # a second copy of the same person, entered differently
        if first in NICK and g.chance(0.4):
            first = NICK[first]
        elif g.chance(0.3):
            first = g.typo(first)
        if g.chance(0.3):
            last = g.typo(last)
        roll = g.r.random()
        if roll < 0.2:
            email = f"{fold(first).replace(' ', '')}.{''.join(c for c in fold(last) if c.isalpha())}@mail.example"
        elif roll < 0.35:
            email = ""
        roll = g.r.random()
        if roll < 0.15:
            phone = ""
        elif roll < 0.35 and mobile:
            phone = ""
    else:  # problems that live on a single record
        roll = g.r.random()
        if roll < 0.04:
            email = g.r.choice([email.replace("@", " at "), email.rsplit(".", 1)[0],
                                email.replace("@", "@@"), email.replace(".", ",", 1)])
        elif roll < 0.07 and module == "Leads":
            email = f"info@{p.account.domain}"
        elif roll < 0.10:
            email, phone, mobile = "", "", ""
        elif roll < 0.12:
            phone = phone[:6] + phone[7:]  # a digit got lost

    city = p.account.city
    country = city[5]
    row = {
        "Record Id": g.record_id(module),
        "First Name": g.mess_name(first),
        "Last Name": g.mess_name(last),
        "Email": g.mess_email(email),
        "Phone": g.mess_phone(phone),
        "Mobile": g.mess_phone(mobile),
    }
    company = g.mess_company(p.account)
    if module == "Leads":
        row["Company"] = company
        row["Lead Source"] = g.r.choice(LEAD_SOURCES)
        row["Lead Status"] = g.r.choice(LEAD_STATUS)
        row["City"] = g.mess_name(city[0])
        row["State"] = g.mess_region(city)
        row["Zip Code"] = g.mess_postal(p.postal, country)
        row["Country"] = g.mess_country(country)
    else:
        row["Account Name"] = company
        row["Mailing City"] = g.mess_name(city[0])
        row["Mailing State"] = g.mess_region(city)
        row["Mailing Zip"] = g.mess_postal(p.postal, country)
        row["Mailing Country"] = g.mess_country(country)
    row["Created Time"] = g.created()
    return row


def _account_row(g: Gen, acc: Account, variant: bool) -> dict:
    city = acc.city
    phone, site = acc.phone, f"https://www.{acc.domain}"
    if variant:
        if g.chance(0.4):
            phone = ""
        site = g.r.choice([f"www.{acc.domain}", f"http://{acc.domain}/", acc.domain.upper(), ""])
        if not phone and not site:
            site = acc.domain
    return {
        "Record Id": g.record_id("Accounts"),
        "Account Name": g.mess_company(acc) if variant else acc.name,
        "Phone": g.mess_phone(phone),
        "Website": site,
        "Billing City": g.mess_name(city[0]),
        "Billing State": g.mess_region(city),
        "Billing Code": g.mess_postal(acc.postal, city[5]),
        "Billing Country": g.mess_country(city[5]),
        "Created Time": g.created(),
    }


def generate(n_accounts: int = 60, n_people: int = 320, seed: int = 42):
    """Return ``(leads, contacts, accounts, truth)`` DataFrames."""
    g = Gen(seed)
    accounts = g.make_accounts(n_accounts)
    for acc in accounts:
        acc.postal = g.postal(acc.city)

    people: list[Person] = []
    names_used: set[tuple] = set()
    while len(people) < n_people:
        first, last = g.r.choice(FIRST), g.r.choice(LAST)
        acc = g.r.choice(accounts)
        if (first, last) in names_used:
            continue
        names_used.add((first, last))
        people.append(g.make_person(f"P{len(people) + 1:04d}", first, last, acc))
    # Traps: different people who happen to share a name with someone at another company.
    for twin in g.r.sample(people[:60], 8):
        other = g.r.choice([a for a in accounts if a is not twin.account])
        people.append(g.make_person(f"P{len(people) + 1:04d}", twin.first, twin.last, other))

    leads, contacts, acc_rows, truth = [], [], [], []

    def emit(p: Person, module: str, variant: bool):
        row = _person_row(g, p, module, variant)
        (leads if module == "Leads" else contacts).append(row)
        truth.append({"Module": module, "Record Id": row["Record Id"], "Entity": p.eid})

    for p in people:
        roll = g.r.random()
        if roll < 0.42:
            emit(p, "Leads", False)
        elif roll < 0.80:
            emit(p, "Contacts", False)
        elif roll < 0.90:                      # converted lead left behind
            emit(p, "Contacts", False)
            emit(p, "Leads", True)
        elif roll < 0.96:                      # entered twice as a contact
            emit(p, "Contacts", False)
            emit(p, "Contacts", True)
        elif roll < 0.98:                      # filled in the web form twice
            emit(p, "Leads", False)
            emit(p, "Leads", True)
        else:                                  # the full mess
            emit(p, "Contacts", False)
            emit(p, "Contacts", True)
            emit(p, "Leads", True)

    for k, acc in enumerate(accounts):
        row = _account_row(g, acc, False)
        acc_rows.append(row)
        truth.append({"Module": "Accounts", "Record Id": row["Record Id"], "Entity": acc.eid})
        if k % 9 == 4:  # roughly one account in nine was created twice
            row = _account_row(g, acc, True)
            acc_rows.append(row)
            truth.append({"Module": "Accounts", "Record Id": row["Record Id"], "Entity": acc.eid})

    for rows in (leads, contacts, acc_rows):
        g.r.shuffle(rows)
    return (pd.DataFrame(leads), pd.DataFrame(contacts), pd.DataFrame(acc_rows), pd.DataFrame(truth))


def write_sample(out_dir: str | Path, **kwargs) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    leads, contacts, accounts, truth = generate(**kwargs)
    leads.to_csv(out / "Leads.csv", index=False)
    contacts.to_csv(out / "Contacts.csv", index=False)
    accounts.to_csv(out / "Accounts.csv", index=False)
    truth.to_csv(out / "_truth.csv", index=False)
    return out
