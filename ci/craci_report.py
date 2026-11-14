"""Collect CRACI's SBOM and network trace for every job of a finished CI run.

For each job it downloads the CycloneDX SBOM and the network trace through the CRACI API, saves
them as files (uploaded as a workflow artifact), and writes a summary table: components found,
network accesses, hosts contacted and anything the network policy blocked. It exits non-zero if a
job contacted a host outside the expected registries, which the deny-by-default policy should
already have stopped: a second, independent check.

Env: CRACI_API_TOKEN, GITHUB_TOKEN, GITHUB_REPOSITORY, RUN_ID; optional GITHUB_STEP_SUMMARY.
Standard library only.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CRACI = "https://api.craci.com"
OUT = Path("supply-chain")
# Registries and services the CI jobs are expected to reach (suffix match on the host name).
EXPECTED = ("github.com", "githubusercontent.com", "pypi.org", "pythonhosted.org", "npmjs.org", "npmjs.com",
            "docker.io", "docker.com", "craci.com")


def get(url: str, token: str, scheme: str = "Bearer") -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"Authorization": f"{scheme} {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def craci(path: str, repo: str, job_id: str, token: str) -> tuple[int, bytes]:
    query = urllib.parse.urlencode({"provider": "github", "repo": repo, "job_id": job_id})
    for _ in range(10):  # 409 until CRACI has finalised the job's records
        status, body = get(f"{CRACI}{path}?{query}", token)
        if status != 409:
            return status, body
        time.sleep(6)
    return status, body


def hosts_of(trace: dict) -> tuple[set[str], list[str], int]:
    """Hosts contacted, policy denials, and the number of observations."""
    hosts, denied = set(), []
    observations = trace.get("observations") or []
    for item in observations:
        detail = item.get(item.get("protocol", ""), {}) or {}
        if item.get("protocol") == "http":
            host = urllib.parse.urlparse(detail.get("originUrl", "")).hostname or ""
            blocked = detail.get("policyDenied")
        elif item.get("protocol") == "tcp":
            host = detail.get("tlsServerName") or ",".join(detail.get("resolvedHosts") or []) or detail.get("remoteIp", "")
            blocked = detail.get("allowed") is False
        else:
            continue
        if host:
            hosts.add(host)
        if blocked:
            denied.append(f"{host} ({detail.get('denyReason') or 'denied'})")
    return hosts, denied, len(observations)


def main() -> int:
    token, gh_token = os.getenv("CRACI_API_TOKEN"), os.environ["GITHUB_TOKEN"]
    repo, run_id = os.environ["GITHUB_REPOSITORY"], os.environ["RUN_ID"]
    lines = ["## Supply chain (CRACI)", ""]
    if not token:
        lines.append("Set the `CRACI_API_TOKEN` repository secret (CRACI → Settings → API tokens) to collect SBOMs "
                     "and network traces.")
        summarize(lines)
        return 0
    status, body = get(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=50", gh_token)
    if status != 200:
        print(f"GitHub jobs API returned {status}: {body[:200]!r}")
        return 1
    OUT.mkdir(exist_ok=True)
    lines += ["| Job | SBOM components | Network accesses | Hosts | Blocked |", "|---|---|---|---|---|"]
    unexpected = []
    for job in json.loads(body)["jobs"]:
        job_id, name = str(job["id"]), job["name"]
        safe = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        status, sbom = craci("/v1preview1/sbom", repo, job_id, token)
        components = "n/a"
        if status == 200:
            (OUT / f"{safe}.cdx.json").write_bytes(sbom)
            components = str(len(json.loads(sbom).get("components") or []))
        status, raw = craci("/v1preview1/network-trace", repo, job_id, token)
        if status != 200:
            lines.append(f"| {name} | {components} | trace unavailable (HTTP {status}) | | |")
            continue
        (OUT / f"{safe}.trace.json").write_bytes(raw)
        hosts, denied, count = hosts_of(json.loads(raw))
        odd = sorted(h for h in hosts if not any(h == e or h.endswith("." + e) for e in EXPECTED)
                     and not h.replace(".", "").isdigit())
        unexpected += [f"{name}: {h}" for h in odd]
        lines.append(f"| {name} | {components} | {count} | {len(hosts)} | {len(denied)} |")
        for item in denied[:10]:
            lines.append(f"|  ↳ blocked | | | {item} | |")
    lines += ["", "SBOMs (CycloneDX) and traces are attached to this run as the `supply-chain` artifact."]
    if unexpected:
        lines += ["", "**Hosts outside the expected registries:**", *[f"- {u}" for u in unexpected]]
    summarize(lines)
    return 1 if unexpected else 0


def summarize(lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    print(text)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    sys.exit(main())
