"""Finished runs, saved so a report has a shareable link (/r/<runId>).

With DATABASE_URL (Aiven for PostgreSQL) a report is one row: profile and events as JSONB, plus one
row per shortlisted investor, so reports can be queried across founders ("who else was this investor
shortlisted for, and how did the audit rate it?"). Without it, or if the database is unreachable,
reports are JSON files under DATA_DIR, and reading checks both.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import store

RUN_ID = re.compile(r"^run-[0-9a-f]{10}$")
MAX_HISTORY_NAMES = 20


def _path(run_id: str) -> Path:
    folder = store.data_dir() / "runs"
    folder.mkdir(exist_ok=True)
    return folder / f"{run_id}.json"


def investor_key(name: str) -> str:
    return " ".join(name.lower().split())


def shortlist_rows(run_id: str, profile: dict[str, Any], events: list[dict[str, Any]]) -> list[tuple]:
    """One row per investor on the final shortlist (the last committee event of the run)."""
    committee = next((e["committee"] for e in reversed(events) if e.get("type") == "committee"), None)
    rows, seen = [], set()
    for target in (committee or {}).get("investorTargets") or []:
        name = str(target.get("name") or "").strip()
        key = investor_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        audit, verification = target.get("audit") or {}, target.get("verification") or {}
        rows.append((run_id, key, name, target.get("fitScore"), audit.get("verdict"),
                     verification.get("verified"), profile.get("sector"), profile.get("stage")))
    return rows


def _write_file(payload: dict[str, Any]) -> None:
    path = _path(payload["runId"])
    if path.exists():
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


async def _insert(pool: Any, payload: dict[str, Any]) -> bool:
    """Insert a report and its shortlist in one transaction; False if it was already stored."""
    saved_at = datetime.fromisoformat(payload["savedAt"])
    async with pool.acquire() as conn, conn.transaction():
        inserted = await conn.fetchval(
            "INSERT INTO reports (run_id, saved_at, profile, events) VALUES ($1, $2, $3::jsonb, $4::jsonb) "
            "ON CONFLICT (run_id) DO NOTHING RETURNING run_id",
            payload["runId"], saved_at, store.jsonb(payload["profile"]), store.jsonb(payload["events"]))
        if inserted:
            await conn.executemany(
                "INSERT INTO report_investors (run_id, investor, display_name, fit_score, verdict, verified, sector,"
                " stage) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING",
                shortlist_rows(payload["runId"], payload["profile"], payload["events"]))
    return bool(inserted)


async def save_run(run_id: str, profile: dict[str, Any], events: list[dict[str, Any]]) -> str:
    """Store a finished run; returns where it went ('postgres', 'files' or '' if rejected)."""
    if not RUN_ID.match(run_id):
        return ""
    payload = {"runId": run_id, "savedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "profile": profile, "events": events}
    try:
        pool = await store.pg_pool()
        if pool is not None:
            await _insert(pool, payload)
            return "postgres"
    except Exception as exc:  # never lose a report: fall back to a file
        store.mark_down("postgres", "Saving report to PostgreSQL", exc)
    _write_file(payload)
    return "files"


async def load_run(run_id: str) -> dict[str, Any] | None:
    if not RUN_ID.match(run_id):
        return None
    try:
        pool = await store.pg_pool()
        if pool is not None:
            row = await pool.fetchrow(
                "SELECT saved_at, profile::text AS profile, events::text AS events FROM reports WHERE run_id = $1",
                run_id)
            if row:
                return {"runId": run_id, "savedAt": row["saved_at"].isoformat(timespec="seconds"),
                        "profile": json.loads(row["profile"]), "events": json.loads(row["events"])}
    except Exception as exc:
        store.mark_down("postgres", "Loading report from PostgreSQL", exc)
    path = _path(run_id)  # saved before the database existed, or during an outage
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def investor_history(names: list[str], exclude_run: str = "") -> dict[str, Any]:
    """How often each investor was shortlisted in other reports, and how the Nemotron audit rated it."""
    keys = sorted({investor_key(n) for n in names if n.strip()})[:MAX_HISTORY_NAMES]
    try:
        pool = await store.pg_pool()
        if pool is None or not keys:
            return {"available": pool is not None, "investors": {}}
        rows = await pool.fetch(
            """SELECT ri.investor,
                      count(*) AS reports,
                      count(*) FILTER (WHERE ri.verdict = 'supported') AS supported,
                      count(*) FILTER (WHERE ri.verdict = 'weak') AS weak,
                      count(*) FILTER (WHERE ri.verdict = 'contradicted') AS contradicted,
                      (array_agg(DISTINCT ri.sector) FILTER (WHERE ri.sector IS NOT NULL))[1:3] AS sectors,
                      max(r.saved_at) AS last_seen
                 FROM report_investors ri JOIN reports r USING (run_id)
                WHERE ri.investor = ANY($1::text[]) AND ri.run_id <> $2
                GROUP BY ri.investor""",
            keys, exclude_run)
        total = await pool.fetchval("SELECT count(*) FROM reports")
    except Exception as exc:
        store.mark_down("postgres", "Reading investor history", exc)
        return {"available": False, "investors": {}}
    return {"available": True, "reportsStored": total, "investors": {
        r["investor"]: {"reports": r["reports"], "supported": r["supported"], "weak": r["weak"],
                        "contradicted": r["contradicted"], "sectors": list(r["sectors"] or []),
                        "lastSeen": r["last_seen"].date().isoformat()} for r in rows}}


async def import_files() -> tuple[int, int]:
    """Copy reports saved as files into PostgreSQL (run once after adding DATABASE_URL)."""
    pool = await store.pg_pool()
    if pool is None:
        raise SystemExit("DATABASE_URL is not set or the database is unreachable")
    added = skipped = 0
    for path in sorted((store.data_dir() / "runs").glob("run-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if RUN_ID.match(payload.get("runId", "")) and await _insert(pool, payload):
            added += 1
        else:
            skipped += 1
    await store.close()
    return added, skipped


if __name__ == "__main__":  # python -m app.runs import-files
    import asyncio

    if sys.argv[1:] != ["import-files"]:
        raise SystemExit("usage: python -m app.runs import-files")
    print("imported %d reports, %d already stored or invalid" % asyncio.run(import_files()))
