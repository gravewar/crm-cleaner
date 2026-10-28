"""Duplicate detection: blocking, explainable pair scoring, and clustering.

Comparing every record with every other record is O(n^2), which gets slow
fast. Instead, each record is given a handful of cheap "blocking keys" (its
email, its phone, the start of its surname…) and only records that share at
least one key are compared. Every score comes with plain-English reasons, so a
person reviewing a match can see *why* it was suggested.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from . import normalize as N

HIGH = 85      # confident enough to pre-approve
REVIEW = 60    # worth a human look
MAX_BLOCK = 150  # ignore giant blocks (e.g. a shared switchboard number on 500 rows)


@dataclass
class PersonRec:
    module: str
    rid: str
    display: str
    first: str          # canonical first name (nicknames resolved)
    last: str           # surname key
    email: str
    phones: set[str]
    company_key: str
    completeness: int
    created: str = ""

    @property
    def ref(self) -> tuple[str, str]:
        return (self.module, self.rid)


@dataclass
class AccountRec:
    module: str
    rid: str
    display: str
    key: str
    phone: str
    domain: str
    completeness: int
    created: str = ""

    @property
    def ref(self) -> tuple[str, str]:
        return (self.module, self.rid)


@dataclass
class Pair:
    a: tuple[str, str]
    b: tuple[str, str]
    score: float
    reasons: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# People (Leads + Contacts together, so cross-module duplicates are found)
# --------------------------------------------------------------------------- #


def person_blocking_keys(p: PersonRec) -> list[str]:
    keys = []
    if p.email and not N.is_role_email(p.email):
        keys.append("e:" + p.email)
    keys += ["p:" + ph for ph in p.phones]
    if p.last:
        keys.append(f"n:{p.last[:4]}:{p.first[:1]}")
        keys.append(f"t:{p.last[-4:]}:{p.first[:1]}")  # survives a typo early in the surname
    if p.first and p.company_key:
        keys.append(f"c:{p.company_key[:8]}:{p.first[:3]}")
    return keys


def score_people(a: PersonRec, b: PersonRec) -> Pair:
    reasons: list[str] = []
    name_sim = fuzz.token_sort_ratio(f"{a.first} {a.last}", f"{b.first} {b.last}")
    last_sim = fuzz.ratio(a.last, b.last) if a.last and b.last else 0
    score = 0.5 * name_sim
    reasons.append(f"Names {name_sim:.0f}% alike")

    role_a, role_b = N.is_role_email(a.email), N.is_role_email(b.email)
    email_match = bool(a.email) and a.email == b.email and not role_a
    if email_match:
        score += 40
        reasons.append("Same email")
    elif a.email and a.email == b.email and role_a:
        reasons.append("Shared role inbox ignored")
    elif (a.email and b.email and N.email_domain(a.email) == N.email_domain(b.email)
          and not role_a and not role_b):
        score -= 20
        reasons.append("Different emails at the same domain")

    if a.phones & b.phones:
        score += 25
        reasons.append("Same phone")

    if a.company_key and b.company_key:
        comp_sim = fuzz.token_sort_ratio(a.company_key, b.company_key)
        if comp_sim >= 90:
            score += 15
            reasons.append("Same company")
        elif comp_sim < 60:
            score -= 15
            reasons.append("Different company")

    # Two people with different surnames who share a switchboard number and an
    # employer are colleagues, not duplicates.
    if last_sim < 75 and not email_match:
        score = min(score, 55)
        reasons.append("Surnames differ")
    # Same surname, same office, different first name: family members or
    # unrelated colleagues (Sam Gagnon and Leah Gagnon), not one person.
    first_sim = fuzz.ratio(a.first, b.first) if a.first and b.first else 100
    if first_sim < 60 and not email_match:
        score = min(score, 55)
        reasons.append("First names differ")

    return Pair(a.ref, b.ref, round(max(0.0, min(100.0, score)), 1), reasons)


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #


def account_blocking_keys(a: AccountRec) -> list[str]:
    keys = []
    if a.key:
        keys.append("k:" + a.key.replace(" ", "")[:6])
    if a.phone:
        keys.append("p:" + a.phone)
    if a.domain:
        keys.append("d:" + a.domain)
    return keys


def score_accounts(a: AccountRec, b: AccountRec) -> Pair:
    reasons: list[str] = []
    name_sim = max(fuzz.ratio(a.key, b.key), fuzz.ratio(a.key.replace(" ", ""), b.key.replace(" ", "")))
    score = 0.7 * name_sim
    reasons.append(f"Names {name_sim:.0f}% alike")
    if a.domain and a.domain == b.domain:
        score += 20
        reasons.append("Same website")
    if a.phone and a.phone == b.phone:
        score += 15
        reasons.append("Same phone")
    if name_sim < 80:
        score = min(score, 50)
        reasons.append("Names too different")
    return Pair(a.ref, b.ref, round(max(0.0, min(100.0, score)), 1), reasons)


# --------------------------------------------------------------------------- #
# Generic machinery
# --------------------------------------------------------------------------- #


def candidate_pairs(records, key_fn):
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, rec in enumerate(records):
        for k in key_fn(rec):
            blocks[k].append(i)
    seen: set[tuple[int, int]] = set()
    for members in blocks.values():
        if len(members) < 2 or len(members) > MAX_BLOCK:
            continue
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                i, j = sorted((members[x], members[y]))
                if i != j and (i, j) not in seen:
                    seen.add((i, j))
                    yield i, j


def find_pairs(records, key_fn, score_fn, threshold: float = REVIEW) -> list[Pair]:
    pairs = []
    for i, j in candidate_pairs(records, key_fn):
        p = score_fn(records[i], records[j])
        if p.score >= threshold:
            pairs.append(p)
    return pairs


def cluster(pairs: list[Pair]) -> list[list[tuple[str, str]]]:
    """Union-find: records joined by any qualifying pair end up in one cluster."""
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in sorted(pairs, key=lambda p: -p.score):
        ra, rb = find(p.a), find(p.b)
        if ra != rb:
            parent[rb] = ra
    groups: dict = defaultdict(list)
    for node in parent:
        groups[find(node)].append(node)
    return [sorted(g) for g in groups.values() if len(g) > 1]
