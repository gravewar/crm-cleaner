"""Record-level checks that can't be fixed automatically and need a human."""

from __future__ import annotations

import pandas as pd

from . import normalize as N


def find_issues(df: pd.DataFrame, module: str, roles: dict[str, str]) -> list[dict]:
    """Return one dict per problem found in an already-cleaned module."""
    issues: list[dict] = []
    get = lambda row, role: str(row[roles[role]]) if role in roles else ""  # noqa: E731

    for _, row in df.iterrows():
        rid = get(row, "id")
        if module == "Accounts":
            label = get(row, "account")
        else:
            label = f"{get(row, 'first')} {get(row, 'last')}".strip()

        def add(field: str, issue: str, severity: str, value: str = "") -> None:
            issues.append({
                "Module": module, "Record Id": rid, "Record": label, "Field": field,
                "Issue": issue, "Severity": severity, "Value": value,
            })

        email = get(row, "email")
        if email:
            if not N.is_valid_email(email):
                add("Email", "Email address is malformed", "Error", email)
            elif module != "Accounts" and N.is_role_email(email):
                add("Email", "Shared role-based inbox, not a personal address", "Warning", email)

        for role, label_ in (("phone", "Phone"), ("mobile", "Mobile")):
            val = get(row, role)
            if val and not N.is_valid_phone(val):
                add(label_, "Phone number can't be parsed", "Error", val)

        state = get(row, "state")
        if state and state not in N.REGION_CODES:
            add("State/Province", "Unrecognized state or province", "Warning", state)

        zip_ = get(row, "zip")
        if zip_ and not N.is_canonical_postal(zip_):
            add("Postal/ZIP", "Postal or ZIP code doesn't look valid", "Warning", zip_)

        if module == "Accounts":
            if not get(row, "account"):
                add("Account Name", "Account Name is empty (required in Zoho)", "Error")
            continue

        if "last" in roles and not get(row, "last"):
            add("Last Name", "Last Name is empty (required in Zoho)", "Error")
        has_phone = any(N.is_valid_phone(get(row, r)) for r in ("phone", "mobile"))
        if not N.is_valid_email(email) and not has_phone:
            add("Email/Phone", "No usable email or phone, so this person can't be reached", "Warning")

    return issues
