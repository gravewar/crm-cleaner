"""Streamlit front end: upload Zoho exports, review duplicates, download clean files.

    streamlit run app.py
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from zcleaner import match as M
from zcleaner.pipeline import run
from zcleaner.report import build_zip, summary_markdown
from zcleaner.schema import MODULES, read_export

SAMPLE_DIR = Path(__file__).parent / "sample_data"

st.set_page_config(page_title="Zoho CRM Cleaner", page_icon="🧹", layout="wide")


@st.cache_data(show_spinner="Cleaning your data…")
def process(payload: tuple, high: float, review: float):
    frames = {module: read_export(io.BytesIO(data), filename=name) for module, name, data in payload}
    return run(frames, high=high, review=review)


# --------------------------------------------------------------------------- #
# Sidebar: data source and thresholds
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("1 · Load exports")
    source = st.radio("Data", ["Sample data", "Upload my exports"], label_visibility="collapsed")
    payload = []
    if source == "Sample data":
        for module in MODULES:
            path = SAMPLE_DIR / f"{module}.csv"
            if path.exists():
                payload.append((module, path.name, path.read_bytes()))
        st.caption("Fake Zoho exports with planted duplicates and typical mess. "
                   "Every person, company, email and phone number is invented.")
    else:
        for module in MODULES:
            f = st.file_uploader(f"{module} export", type=["csv", "xlsx"], key=f"up_{module}")
            if f is not None:
                payload.append((module, f.name, f.getvalue()))
        st.caption("Export from Zoho via **Setup → Data Administration → Export**. "
                   "Files are processed in memory and aren't stored.")

    st.header("2 · Matching")
    high = st.slider("Auto-approve at", 70, 100, int(M.HIGH),
                     help="Groups at or above this confidence start out approved.")
    review = st.slider("Show for review from", 40, high, int(M.REVIEW),
                       help="Lower = catch more duplicates, but more to check by hand.")

st.title("🧹 Zoho CRM Cleaner")
st.caption("Standardize fields, find duplicates across Leads, Contacts and Accounts, "
           "and export files that re-import cleanly into Zoho.")

if not payload:
    st.info("Upload at least one export in the sidebar, or switch to the sample data.")
    st.stop()

result = process(tuple(payload), float(high), float(review))

# Approvals live in session state and reset whenever the data or thresholds change.
signature = (tuple((m, n, len(d)) for m, n, d in payload), high, review)
if st.session_state.get("signature") != signature:
    st.session_state.signature = signature
    st.session_state.approved = result.default_approved()
    st.session_state.editor_gen = 0
approved: set[int] = st.session_state.approved

lookup = {}
for module, df in result.cleaned.items():
    id_col = result.roles[module].get("id")
    if id_col:
        lookup.update({(module, str(rid)): row for rid, row in df.set_index(id_col).iterrows()})

tab_overview, tab_dupes, tab_fixes, tab_issues, tab_export = st.tabs(
    ["📊 Overview", f"👯 Duplicates ({len(result.clusters)})", f"🔧 Fixes ({len(result.changes)})",
     f"⚠️ Issues ({len(result.issues)})", "📦 Export"])

# --------------------------------------------------------------------------- #
with tab_overview:
    before, after = result.quality_before(), result.quality_after(approved)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Records", f"{sum(len(d) for d in result.cleaned.values()):,}")
    c2.metric("Field fixes", f"{len(result.changes):,}")
    c3.metric("Duplicate groups", len(result.clusters), f"{len(approved)} approved", delta_color="off")
    c4.metric("Need a human", len(result.issues))
    c5.metric("Data quality", f"{after['score']}%", f"{after['score'] - before['score']:+.1f} pts")

    st.subheader("Quality by check")
    chart = pd.DataFrame({"Before": before["breakdown"], "After": after["breakdown"]})
    st.bar_chart(chart, horizontal=True, stack=False, height=320, color=["#c8ccd4", "#2f7d6d"])
    st.caption("Share of fields passing each check. *Not a duplicate* counts duplicates that "
               "aren't in an approved merge yet, so it updates as you review.")

# --------------------------------------------------------------------------- #
with tab_dupes:
    if not result.clusters:
        st.success("No duplicates found at these thresholds.")
    else:
        view = st.segmented_control("Show", ["All", "Needs review", "High confidence", "Cross-module"],
                                    default="All")
        b1, b2, _ = st.columns([1, 1, 4])
        if b1.button("Approve all high"):
            st.session_state.approved = approved | {c.cid for c in result.clusters if c.band == "High"}
            st.session_state.editor_gen += 1
            st.rerun()
        if b2.button("Clear approvals"):
            st.session_state.approved = set()
            st.session_state.editor_gen += 1
            st.rerun()

        shown = [c for c in result.clusters
                 if view in (None, "All")
                 or (view == "Needs review" and c.band == "Review")
                 or (view == "High confidence" and c.band == "High")
                 or (view == "Cross-module" and c.cross_module)]
        table = pd.DataFrame([{
            "Approve": c.cid in approved,
            "Group": c.cid,
            "Type": c.kind,
            "Confidence": c.confidence,
            "Band": c.band,
            "Master (kept)": c.labels[c.master],
            "Modules": c.modules,
            "Records": len(c.members),
            "Why": " · ".join(c.reasons),
        } for c in shown])
        edited = st.data_editor(
            table, hide_index=True, width="stretch",
            disabled=[col for col in table.columns if col != "Approve"],
            column_config={
                "Approve": st.column_config.CheckboxColumn("Merge?", width="small"),
                "Group": st.column_config.NumberColumn(width="small"),
                "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            },
            key=f"editor_{view}_{st.session_state.editor_gen}",
        )
        shown_ids = {c.cid for c in shown}
        new_approved = (approved - shown_ids) | set(edited.loc[edited["Approve"], "Group"])
        if new_approved != approved:
            st.session_state.approved = new_approved
            st.rerun()

        st.subheader("Compare records")
        pick = st.selectbox(
            "Group", [c.cid for c in shown],
            format_func=lambda cid: next(f"#{c.cid} · {c.labels[c.master]} · {c.modules} · {c.confidence:.0f}%"
                                         for c in result.clusters if c.cid == cid))
        cluster = next(c for c in result.clusters if c.cid == pick)
        rows = []
        for ref in sorted(cluster.members, key=lambda r: r != cluster.master):
            module, rid = ref
            rec = lookup.get(ref)
            if rec is None:
                continue
            roles = result.roles[module]
            get = lambda role: str(rec[roles[role]]) if role in roles and roles[role] in rec else ""  # noqa: E731
            rows.append({
                "Role": "⭐ Master" if ref == cluster.master else "Duplicate",
                "Module": module, "Record Id": rid,
                "Name": get("account") if module == "Accounts" else f"{get('first')} {get('last')}",
                "Company": get("company") or ("" if module == "Accounts" else get("account")),
                "Email": get("email"), "Phone": get("phone"), "Mobile": get("mobile"),
                "Website": get("website"), "City": get("city"), "State": get("state"),
                "Created": get("created"),
            })
        detail = pd.DataFrame(rows)
        detail = detail.loc[:, (detail != "").any(axis=0)]
        st.dataframe(detail, hide_index=True, width="stretch")
        st.caption("The master is the Contact (over a Lead), then the most complete record, then the oldest. "
                   "Zoho's own merge tool will let you pick field-by-field values.")

# --------------------------------------------------------------------------- #
with tab_fixes:
    if result.changes.empty:
        st.success("Nothing needed fixing.")
    else:
        counts = result.changes["Rule"].value_counts()
        st.bar_chart(counts, horizontal=True, height=300, color="#2f7d6d")
        rules = st.multiselect("Filter by fix", list(counts.index))
        fixes = result.changes if not rules else result.changes[result.changes["Rule"].isin(rules)]
        st.dataframe(fixes, hide_index=True, width="stretch", height=420)

# --------------------------------------------------------------------------- #
with tab_issues:
    if result.issues.empty:
        st.success("No issues found.")
    else:
        st.write("These can't be fixed automatically. Each one needs someone to look it up or decide.")
        sev = st.segmented_control("Severity", ["Error", "Warning"], selection_mode="multi",
                                   default=["Error", "Warning"])
        issues = result.issues[result.issues["Severity"].isin(sev or [])]
        st.dataframe(issues, hide_index=True, width="stretch", height=420)

# --------------------------------------------------------------------------- #
with tab_export:
    plan = result.merge_plan(approved)
    left, right = st.columns([2, 3])
    with left:
        st.download_button("⬇️ Download everything (.zip)", build_zip(result, approved),
                           file_name="zoho_cleanup.zip", mime="application/zip", type="primary")
        st.markdown(
            "- `cleaned_*.csv`: your exports, fixed, with **Record Id** kept so Zoho updates "
            "existing records instead of creating new ones\n"
            f"- `merge_plan.csv`: {len(plan)} duplicate records to merge, master first\n"
            "- `change_log.csv`: every change, before and after\n"
            "- `issues.csv`: what still needs a human\n"
            "- `SUMMARY.md`: the numbers and re-import steps")
    with right:
        with st.expander("Summary preview", expanded=True):
            preview = summary_markdown(result, approved).split("\n", 2)[2]  # drop the H1
            st.markdown(preview.replace("## ", "##### "))
    st.subheader("Merge plan")
    st.dataframe(plan, hide_index=True, width="stretch")
