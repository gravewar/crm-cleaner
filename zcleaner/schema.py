"""Column detection for Zoho CRM exports.

Zoho lets admins rename field labels, and the three core modules use different
labels for the same idea (``State`` vs ``Mailing State`` vs ``Billing State``).
Instead of hard-coding one layout, each column is mapped to a *role* so the rest
of the pipeline never has to care which label a particular org uses.
"""

from __future__ import annotations

import pandas as pd

MODULES = ("Leads", "Contacts", "Accounts")

ROLE_CANDIDATES: dict[str, list[str]] = {
    "id": ["Record Id", "Id", "Lead Id", "Contact Id", "Account Id"],
    "first": ["First Name"],
    "last": ["Last Name"],
    "email": ["Email", "Email Address"],
    "phone": ["Phone", "Work Phone"],
    "mobile": ["Mobile", "Mobile Phone"],
    "company": ["Company"],
    "account": ["Account Name"],
    "city": ["City", "Mailing City", "Billing City"],
    "state": ["State", "Mailing State", "Billing State", "Province", "State/Province"],
    "zip": ["Zip Code", "Mailing Zip", "Billing Code", "Zip", "Postal Code"],
    "country": ["Country", "Mailing Country", "Billing Country"],
    "website": ["Website"],
    "created": ["Created Time"],
}


def detect_roles(df: pd.DataFrame) -> dict[str, str]:
    """Return ``{role: column_name}`` for every role found in ``df``."""
    lookup = {str(c).strip().lower(): c for c in df.columns}
    roles: dict[str, str] = {}
    for role, candidates in ROLE_CANDIDATES.items():
        for cand in candidates:
            col = lookup.get(cand.lower())
            if col is not None:
                roles[role] = col
                break
    return roles


def read_export(source, filename: str | None = None) -> pd.DataFrame:
    """Read a Zoho export (CSV or Excel) with every value kept as text.

    Reading as text matters: otherwise pandas turns ``02108`` into ``2108`` and
    phone numbers into floats, which is exactly the damage we're trying to undo.
    """
    name = (filename or getattr(source, "name", "") or str(source)).lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(source, dtype=str)
    else:
        df = pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df = df.fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def guess_module(df: pd.DataFrame) -> str | None:
    """Best guess at which Zoho module an export came from, based on its headers."""
    roles = detect_roles(df)
    if "company" in roles and "last" in roles:
        return "Leads"
    if "last" in roles:
        return "Contacts"
    if "account" in roles:
        return "Accounts"
    return None
