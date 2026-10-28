"""Write the cleaned exports, merge plan and logs, as files or as one zip."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .pipeline import Result


def summary_markdown(result: Result, approved: set[int] | None = None) -> str:
    approved = result.default_approved() if approved is None else approved
    before, after = result.quality_before(), result.quality_after(approved)
    plan = result.merge_plan(approved)
    n_records = sum(len(df) for df in result.cleaned.values())
    lines = [
        "# Zoho CRM cleanup summary",
        "",
        f"- Records scanned: **{n_records}** ({', '.join(f'{m}: {len(d)}' for m, d in result.cleaned.items())})",
        f"- Field fixes applied: **{len(result.changes)}**",
        f"- Duplicate groups found: **{len(result.clusters)}** (approved: {len(approved)})",
        f"- Duplicate records to merge: **{len(plan)}**",
        f"- Issues needing a human: **{len(result.issues)}**",
        f"- Data-quality score: **{before['score']}% -> {after['score']}%**",
        "",
        "## Score by check",
        "",
        "| Check | Before | After |",
        "|---|---|---|",
    ]
    for check, value in before["breakdown"].items():
        lines.append(f"| {check} | {value}% | {after['breakdown'].get(check, '-')}% |")
    lines += [
        "",
        "## Re-importing into Zoho",
        "",
        "1. Import each `cleaned_*.csv` with **Update existing records**, matching on **Record Id**.",
        "2. Work through `merge_plan.csv` using Zoho's merge tool, so notes, activities and deals",
        "   move onto the master record.",
        "3. Fix the records listed in `issues.csv` by hand.",
        "",
    ]
    return "\n".join(lines)


def outputs(result: Result, approved: set[int] | None = None) -> dict[str, bytes]:
    approved = result.default_approved() if approved is None else approved
    files: dict[str, bytes] = {}
    for module, df in result.cleaned.items():
        files[f"cleaned_{module}.csv"] = df.to_csv(index=False).encode("utf-8-sig")
    files["merge_plan.csv"] = result.merge_plan(approved).to_csv(index=False).encode("utf-8-sig")
    files["change_log.csv"] = result.changes.to_csv(index=False).encode("utf-8-sig")
    files["issues.csv"] = result.issues.to_csv(index=False).encode("utf-8-sig")
    files["SUMMARY.md"] = summary_markdown(result, approved).encode("utf-8")
    files["summary.json"] = json.dumps({
        "quality_before": result.quality_before(),
        "quality_after": result.quality_after(approved),
        "changes": len(result.changes), "issues": len(result.issues),
        "clusters": len(result.clusters), "approved_clusters": sorted(approved),
    }, indent=2).encode("utf-8")
    return files


def write_outputs(result: Result, out_dir: str | Path, approved: set[int] | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in outputs(result, approved).items():
        (out / name).write_bytes(data)
    return out


def build_zip(result: Result, approved: set[int] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in outputs(result, approved).items():
            zf.writestr(name, data)
    return buf.getvalue()
