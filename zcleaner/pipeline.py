"""The end-to-end cleanup: normalize -> match accounts -> align -> match people -> report."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from rapidfuzz import fuzz, process

from . import match as M
from . import normalize as N
from .schema import MODULES, detect_roles
from .validate import find_issues

# (role, normalizer, rule shown in the change log)
FIELD_RULES = [
    ("first", N.norm_person_name, "Name casing & spacing"),
    ("last", N.norm_person_name, "Name casing & spacing"),
    ("email", N.norm_email, "Email trimmed & lowercased"),
    ("phone", N.norm_phone, "Phone number formatted"),
    ("mobile", N.norm_phone, "Phone number formatted"),
    ("city", N.norm_city, "City casing & spacing"),
    ("state", N.norm_region, "State/province standardized"),
    ("country", N.norm_country, "Country standardized"),
    ("website", N.norm_website, "Website formatted"),
    ("company", N.norm_company, "Company name tidied"),
    ("account", N.norm_company, "Company name tidied"),
]
ALIGN_RULE = "Matched to existing Account name"


@dataclass
class Cluster:
    cid: int
    kind: str                      # "People" or "Accounts"
    members: list[tuple[str, str]]
    master: tuple[str, str]
    confidence: float
    band: str                      # "High" or "Review"
    reasons: list[str]
    labels: dict = field(default_factory=dict)  # ref -> display name

    @property
    def modules(self) -> str:
        mods = sorted({m for m, _ in self.members})
        return " + ".join(mods)

    @property
    def cross_module(self) -> bool:
        return len({m for m, _ in self.members}) > 1


@dataclass
class Result:
    raw: dict[str, pd.DataFrame]
    cleaned: dict[str, pd.DataFrame]
    roles: dict[str, dict[str, str]]
    changes: pd.DataFrame
    issues: pd.DataFrame
    clusters: list[Cluster]
    high: float
    review: float

    # ----------------------------------------------------------------- #
    def default_approved(self) -> set[int]:
        return {c.cid for c in self.clusters if c.band == "High"}

    def merge_plan(self, approved: set[int] | None = None) -> pd.DataFrame:
        approved = self.default_approved() if approved is None else approved
        rows = []
        for c in self.clusters:
            if c.cid not in approved:
                continue
            mm, mid = c.master
            for ref in c.members:
                if ref == c.master:
                    continue
                dm, did = ref
                rows.append({
                    "Cluster": c.cid, "Type": c.kind, "Confidence": c.confidence,
                    "Master Module": mm, "Master Record Id": mid, "Master": c.labels.get(c.master, ""),
                    "Duplicate Module": dm, "Duplicate Record Id": did, "Duplicate": c.labels.get(ref, ""),
                    "Suggested Action": suggested_action(mm, dm),
                    "Why": "; ".join(c.reasons),
                })
        cols = ["Cluster", "Type", "Confidence", "Master Module", "Master Record Id", "Master",
                "Duplicate Module", "Duplicate Record Id", "Duplicate", "Suggested Action", "Why"]
        return pd.DataFrame(rows, columns=cols)

    def quality_before(self) -> dict:
        dups = {ref for c in self.clusters for ref in c.members if ref != c.master}
        return quality(self.raw, self.roles, dups)

    def quality_after(self, approved: set[int] | None = None) -> dict:
        approved = self.default_approved() if approved is None else approved
        unresolved = {ref for c in self.clusters if c.cid not in approved
                      for ref in c.members if ref != c.master}
        return quality(self.cleaned, self.roles, unresolved)


def suggested_action(master_module: str, dup_module: str) -> str:
    if master_module == "Contacts" and dup_module == "Leads":
        return "Lead is already a Contact: convert it into the master Contact, or delete it"
    return f"Merge into the master {master_module[:-1]} in Zoho (keeps notes, activities & deals)"


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #


def _clean_module(df, module, roles, account_names=None, account_keys=None):
    out = df.copy()
    changes = []
    id_col = roles.get("id")
    for idx in out.index:
        rid = str(out.at[idx, id_col]) if id_col else str(idx)

        def apply(col, new, rule):
            old = str(out.at[idx, col])
            if new != old:
                out.at[idx, col] = new
                changes.append({"Module": module, "Record Id": rid, "Field": col,
                                "Before": old, "After": new, "Rule": rule})

        for role, fn, rule in FIELD_RULES:
            if role not in roles:
                continue
            col = roles[role]
            raw = str(out.at[idx, col])
            new = fn(raw)
            if role in ("company", "account") and module != "Accounts" and new and account_names:
                aligned = _align_company(new, account_names, account_keys)
                if aligned and aligned != new:
                    apply(col, aligned, ALIGN_RULE)
                    continue
            apply(col, new, rule)

        if "zip" in roles:
            country = str(out.at[idx, roles["country"]]) if "country" in roles else ""
            if not country and "state" in roles:
                country = N.region_country(str(out.at[idx, roles["state"]]))
            col = roles["zip"]
            apply(col, N.norm_postal(str(out.at[idx, col]), country), "Postal/ZIP formatted")
    return out, changes


def _align_company(name, account_names, account_keys):
    key = N.company_key(name)
    if not key:
        return None
    if key in account_names:
        return account_names[key]
    hit = process.extractOne(key, account_keys, scorer=fuzz.ratio, score_cutoff=93)
    return account_names[hit[0]] if hit else None


def _completeness(row, roles):
    return sum(1 for r, c in roles.items() if r not in ("id", "created") and str(row[c]).strip())


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


def run(frames: dict[str, pd.DataFrame], high: float = M.HIGH, review: float = M.REVIEW) -> Result:
    raw = {m: frames[m].fillna("").astype(str) for m in MODULES if m in frames and frames[m] is not None}
    roles = {m: detect_roles(df) for m, df in raw.items()}
    cleaned: dict[str, pd.DataFrame] = {}
    changes: list[dict] = []
    clusters: list[Cluster] = []

    # 1. Accounts first, so people can be aligned to their canonical names.
    account_names: dict[str, str] = {}
    if "Accounts" in raw:
        r = roles["Accounts"]
        acc, ch = _clean_module(raw["Accounts"], "Accounts", r)
        cleaned["Accounts"], changes = acc, changes + ch
        recs = []
        for _, row in acc.iterrows():
            name = str(row.get(r.get("account", ""), ""))
            recs.append(M.AccountRec(
                module="Accounts", rid=str(row[r["id"]]) if "id" in r else "",
                display=name, key=N.company_key(name),
                phone=N.phone_digits(str(row[r["phone"]])) if "phone" in r else "",
                domain=N.website_domain(str(row[r["website"]])) if "website" in r else "",
                completeness=_completeness(row, r),
                created=str(row[r["created"]]) if "created" in r else "",
            ))
        acc_clusters = _build_clusters(recs, M.account_blocking_keys, M.score_accounts,
                                       "Accounts", high, review, start=1)
        clusters += acc_clusters
        by_ref = {rec.ref: rec for rec in recs}
        for rec in recs:
            if rec.key:
                account_names.setdefault(rec.key, rec.display)
        for c in acc_clusters:  # every name variant in a duplicate group points at the master
            for ref in c.members:
                account_names[by_ref[ref].key] = by_ref[c.master].display

    # 2. Leads and Contacts.
    people: list[M.PersonRec] = []
    keys = list(account_names)
    for module in ("Leads", "Contacts"):
        if module not in raw:
            continue
        r = roles[module]
        df, ch = _clean_module(raw[module], module, r, account_names, keys)
        cleaned[module], changes = df, changes + ch
        comp_col = r.get("company") or r.get("account")
        for _, row in df.iterrows():
            first, last = str(row.get(r.get("first", ""), "")), str(row.get(r.get("last", ""), ""))
            phones = {N.phone_digits(str(row[r[x]])) for x in ("phone", "mobile") if x in r} - {""}
            people.append(M.PersonRec(
                module=module, rid=str(row[r["id"]]) if "id" in r else "",
                display=f"{first} {last}".strip(),
                first=N.canonical_first(first), last=N.name_key(last),
                email=str(row[r["email"]]) if "email" in r else "",
                phones=phones,
                company_key=N.company_key(str(row[comp_col])) if comp_col else "",
                completeness=_completeness(row, r),
                created=str(row[r["created"]]) if "created" in r else "",
            ))
    clusters += _build_clusters(people, M.person_blocking_keys, M.score_people,
                                "People", high, review, start=len(clusters) + 1)

    issues = []
    for module, df in cleaned.items():
        issues += find_issues(df, module, roles[module])

    change_cols = ["Module", "Record Id", "Field", "Before", "After", "Rule"]
    issue_cols = ["Module", "Record Id", "Record", "Field", "Issue", "Severity", "Value"]
    return Result(raw=raw, cleaned=cleaned, roles=roles,
                  changes=pd.DataFrame(changes, columns=change_cols),
                  issues=pd.DataFrame(issues, columns=issue_cols),
                  clusters=clusters, high=high, review=review)


def _build_clusters(recs, key_fn, score_fn, kind, high, review, start):
    pairs = M.find_pairs(recs, key_fn, score_fn, threshold=review)
    by_ref = {r.ref: r for r in recs}
    out = []
    for i, members in enumerate(sorted(M.cluster(pairs), key=lambda g: g[0]), start=start):
        mset = set(members)
        inner = [p for p in pairs if p.a in mset and p.b in mset]
        best = {ref: max((p.score for p in inner if ref in (p.a, p.b)), default=0) for ref in members}
        confidence = min(best.values())

        def rank(ref):
            rec = by_ref[ref]
            module_pref = 0 if rec.module in ("Contacts", "Accounts") else 1
            return (module_pref, -rec.completeness, rec.created or "9999", rec.rid)

        master = min(members, key=rank)
        top = max(inner, key=lambda p: p.score)
        out.append(Cluster(
            cid=i, kind=kind, members=members, master=master, confidence=confidence,
            band="High" if confidence >= high else "Review",
            reasons=top.reasons, labels={ref: by_ref[ref].display for ref in members},
        ))
    return out


# --------------------------------------------------------------------------- #
# Data-quality score
# --------------------------------------------------------------------------- #


def quality(frames, roles, duplicate_refs) -> dict:
    """Share of field-level checks that pass, plus a per-check breakdown."""
    tally: dict[str, list[int]] = {}

    def check(name, ok):
        t = tally.setdefault(name, [0, 0])
        t[0] += int(bool(ok))
        t[1] += 1

    for module, df in frames.items():
        r = roles[module]
        for _, row in df.iterrows():
            val = lambda role: str(row[r[role]]) if role in r else ""  # noqa: E731
            for role in ("first", "last", "account", "company", "city"):
                if val(role):
                    check("Consistent casing & spacing", N.is_well_cased(val(role)) and val(role) == N.squash(val(role)))
            if val("email"):
                check("Valid email", N.is_valid_email(val("email")) and val("email") == N.norm_email(val("email")))
            for role in ("phone", "mobile"):
                if val(role):
                    check("Standard phone format", bool(N.PHONE_CANON_RE.match(val(role))) or val(role).startswith("+"))
            if val("state"):
                check("Standard state/province", val("state") in N.REGION_CODES)
            if val("zip"):
                check("Standard postal/ZIP", N.is_canonical_postal(val("zip")))
            if val("country"):
                check("Standard country", val("country") in ("Canada", "United States"))
            if "id" in r:
                check("Not a duplicate", (module, val("id")) not in duplicate_refs)

    passed = sum(t[0] for t in tally.values())
    total = sum(t[1] for t in tally.values())
    return {
        "score": round(100 * passed / total, 1) if total else 100.0,
        "breakdown": {k: round(100 * v[0] / v[1], 1) for k, v in sorted(tally.items())},
    }
