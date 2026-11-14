"""End-to-end smoke test of the running stack (docker compose with docker-compose.ci.yml).

Goes through nginx like a browser: health, a recorded example run streamed over SSE, the saved
report from PostgreSQL, cross-report investor history, the Valkey rate limit and the pitch deck.
With --after-restart it only checks that a report saved earlier survived losing the backend
container and its data volume (it lives in PostgreSQL, not on the container's disk).
Standard library only. Usage: python ci/smoke.py [--after-restart RUN_ID] [--base URL]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def call(base: str, path: str, body: dict | None = None, timeout: float = 60) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def stream(base: str, profile: dict) -> list[dict]:
    status, raw = call(base, "/api/analyze", profile, timeout=120)
    if status != 200:
        raise AssertionError(f"analyze returned HTTP {status}: {raw[:200]!r}")
    return [json.loads(line[5:]) for line in raw.decode().splitlines() if line.startswith("data:")]


def check(ok: bool, message: str) -> None:
    print(("ok   " if ok else "FAIL ") + message)
    if not ok:
        sys.exit(1)


def wait_healthy(base: str) -> dict:
    for _ in range(60):
        try:
            status, raw = call(base, "/api/health", timeout=5)
            if status == 200:
                return json.loads(raw)
        except OSError:
            pass
        time.sleep(1)
    raise SystemExit("backend never became healthy")


def full(base: str) -> str:
    health = wait_healthy(base)
    check(health["storage"] == {"reports": "PostgreSQL", "cache": "Valkey"}, f"health names the storage: {health['storage']}")

    examples = json.loads(call(base, "/api/examples")[1])["examples"]
    example = next(e for e in examples if e["cached"])
    started = time.monotonic()
    events = stream(base, example["profile"])
    types = [e["type"] for e in events]
    check(types[0] == "start" and types[-1] == "done", f"example '{example['label']}' replayed {len(events)} events "
                                                       f"in {time.monotonic() - started:.1f} s")
    run_id = events[-1]["runId"]
    committee = next(e["committee"] for e in reversed(events) if e["type"] == "committee")
    names = [t["name"] for t in committee["investorTargets"]]
    check(len(names) >= 3, f"shortlist of {len(names)} investors")

    status, raw = call(base, f"/api/runs/{run_id}")
    check(status == 200 and len(json.loads(raw)["events"]) == len(events), f"report {run_id} saved and readable")

    query = urllib.parse.urlencode([("names", n) for n in names] + [("exclude", "run-0000000000")])
    history = json.loads(call(base, f"/api/investors/history?{query}")[1])
    found = history["investors"]
    check(history["available"] and len(found) == len(names), f"investor history from PostgreSQL covers {len(found)} investors")

    edited = {**example["profile"], "name": "Smoke Test Oy"}  # an edited example runs live (demo mode in CI)
    codes = []
    for _ in range(4):
        status, _ = call(base, "/api/analyze", edited, timeout=120)
        codes.append(status)
    check(codes == [200, 200, 200, 429], f"Valkey rate limit allows 3 live runs per hour, then 429: {codes}")

    status, raw = call(base, "/pitch/")
    check(status == 200 and b"Unicorn Oracle" in raw, "pitch deck is served")
    status, raw = call(base, f"/r/{run_id}")
    check(status == 200 and b'id="app"' in raw, "report link serves the app")
    return run_id


def after_restart(base: str, run_id: str) -> None:
    wait_healthy(base)
    status, _ = call(base, f"/api/runs/{run_id}")
    check(status == 200, f"report {run_id} survived a new backend container with an empty data volume")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--after-restart", metavar="RUN_ID")
    args = parser.parse_args()
    if args.after_restart:
        after_restart(args.base, args.after_restart)
    else:
        print(f"run_id={full(args.base)}")
