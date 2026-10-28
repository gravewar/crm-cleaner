import io
import zipfile

import pandas as pd

from zcleaner import run
from zcleaner.evaluate import evaluate
from zcleaner.report import build_zip
from zcleaner.synth import generate


def frames(**modules):
    return {k: pd.DataFrame(v) for k, v in modules.items()}


def test_cross_module_duplicate_prefers_contact_as_master():
    res = run(frames(
        Leads=[{"Record Id": "zcrm_1", "First Name": "bob", "Last Name": "SMITH", "Company": "Bluefin Labs Inc",
                "Email": "", "Phone": "416.555.0101"}],
        Contacts=[{"Record Id": "zcrm_2", "First Name": "Robert", "Last Name": "Smith",
                   "Account Name": "Bluefin Labs Inc.", "Email": "rsmith@bluefinlabs.example",
                   "Phone": "(416) 555-0101"}],
    ))
    assert len(res.clusters) == 1
    c = res.clusters[0]
    assert c.master == ("Contacts", "zcrm_2")
    assert c.band == "High"
    plan = res.merge_plan()
    assert plan.iloc[0]["Duplicate Record Id"] == "zcrm_1"
    assert "convert" in plan.iloc[0]["Suggested Action"].lower()


def test_colleagues_sharing_a_switchboard_are_not_merged():
    res = run(frames(Contacts=[
        {"Record Id": "a", "First Name": "Samuel", "Last Name": "Gagnon", "Account Name": "Sable Health",
         "Email": "", "Phone": "902-555-0150"},
        {"Record Id": "b", "First Name": "Leah", "Last Name": "Gagnon", "Account Name": "Sable Health",
         "Email": "", "Phone": "902-555-0150"},
        {"Record Id": "c", "First Name": "Owen", "Last Name": "Reid", "Account Name": "Sable Health",
         "Email": "", "Phone": "902-555-0150"},
    ]))
    assert res.clusters == []


def test_same_name_different_company_is_not_merged():
    res = run(frames(Contacts=[
        {"Record Id": "a", "First Name": "Sarah", "Last Name": "Chen", "Account Name": "Bluefin Labs",
         "Email": "sarah.chen@bluefinlabs.example"},
        {"Record Id": "b", "First Name": "Sarah", "Last Name": "Chen", "Account Name": "Granite Energy",
         "Email": "sarah.chen@graniteenergy.example"},
    ]))
    assert res.clusters == []


def test_role_inbox_does_not_create_a_match():
    res = run(frames(Leads=[
        {"Record Id": "a", "First Name": "Maya", "Last Name": "Park", "Company": "Cobalt Media", "Email": "info@cobalt.example"},
        {"Record Id": "b", "First Name": "Noah", "Last Name": "Osei", "Company": "Cobalt Media", "Email": "info@cobalt.example"},
    ]))
    assert res.clusters == []


def test_contacts_are_aligned_to_account_names_and_record_ids_kept():
    res = run(frames(
        Accounts=[{"Record Id": "acc1", "Account Name": "Research Lighthouse Inc.", "Phone": "6135550111"}],
        Contacts=[{"Record Id": "c1", "First Name": "Ava", "Last Name": "Roy",
                   "Account Name": "RESEARCH LIGHTHOUSE", "Email": "ava@rl.example"}],
    ))
    contacts = res.cleaned["Contacts"]
    assert contacts.loc[0, "Account Name"] == "Research Lighthouse Inc."
    assert contacts.loc[0, "Record Id"] == "c1"
    assert "Matched to existing Account name" in set(res.changes["Rule"])


def test_columns_are_preserved_exactly():
    leads, contacts, accounts, _ = generate(n_accounts=10, n_people=40, seed=1)
    res = run({"Leads": leads, "Contacts": contacts, "Accounts": accounts})
    for name, df in (("Leads", leads), ("Contacts", contacts), ("Accounts", accounts)):
        assert list(res.cleaned[name].columns) == list(df.columns)
        assert len(res.cleaned[name]) == len(df)


def test_quality_improves_and_zip_contains_everything():
    leads, contacts, accounts, _ = generate(n_accounts=15, n_people=80, seed=3)
    res = run({"Leads": leads, "Contacts": contacts, "Accounts": accounts})
    assert res.quality_after()["score"] > res.quality_before()["score"]
    names = set(zipfile.ZipFile(io.BytesIO(build_zip(res))).namelist())
    assert {"cleaned_Leads.csv", "cleaned_Contacts.csv", "cleaned_Accounts.csv", "merge_plan.csv",
            "change_log.csv", "issues.csv", "SUMMARY.md"} <= names


def test_matching_accuracy_on_synthetic_data():
    """Guards against regressions. Synthetic data is easier than real data, so
    these are floors, not a claim about real-world accuracy."""
    for seed in (11, 12):
        leads, contacts, accounts, truth = generate(seed=seed)
        res = run({"Leads": leads, "Contacts": contacts, "Accounts": accounts})
        scores = evaluate(res, truth).set_index("Clusters used")
        assert scores.loc["High confidence only", "Precision"] >= 0.97
        assert scores.loc["High + Review", "Recall"] >= 0.95
