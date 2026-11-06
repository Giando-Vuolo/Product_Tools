import os
import re

import requests

# Column name used in the dashboard, the Confluence table and the charts.
SBOM_KPI = "Dependencies Findings"

# Severity categories of the SBOM Inventory cve_rating, most severe first
SBOM_SEVERITIES = ("critical", "high", "medium", "low", "info", "none")

# Stages shown one by one under the KPI (SBOM_STAGES, comma separated)
DEFAULT_STAGES = "PROD,PRELIVE"
# Severities listed per stage
STAGE_SEVERITIES = ("critical", "high", "medium", "low")


def sbom_configured():
    return all(os.getenv(k) for k in ("SBOM_SERVER", "SBOM_API_KEY", "SBOM_API_SECRET", "SBOM_NAMESPACE_ID", "SBOM_APP_ID"))


def fetch_dependency_findings():
    """Returns the current CVE findings of SBOM_APP_ID, counted like the SBOM Inventory UI.

    The API has no history, so this is always today's value, whatever the sprint dates.
    """
    return sum(fetch_dependency_findings_by_severity().values())


def fetch_dependency_findings_by_severity():
    """Same findings as fetch_dependency_findings, per severity ({"critical": n, "high": n, ...})."""
    server = os.getenv("SBOM_SERVER", "").rstrip("/")
    auth = (os.getenv("SBOM_API_KEY", ""), os.getenv("SBOM_API_SECRET", ""))
    resp = requests.get(f"{server}/ns/{os.getenv('SBOM_NAMESPACE_ID')}/apps", auth=auth, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"SBOM Inventory API Error {resp.status_code}: {resp.text}")
    return findings_by_severity(resp.json(), os.getenv("SBOM_APP_ID"))


def scope_stages():
    """Stage labels shown per stage, e.g. ["PROD", "PRELIVE"]."""
    raw = os.getenv("SBOM_STAGES", "").strip() or DEFAULT_STAGES
    return [label.strip() for label in raw.split(",") if label.strip()]


def _stage_label(stage_name, labels):
    """The label a stage name belongs to: equal to it or a whole word of it ("recall2-prod" -> "PROD")."""
    words = {w.upper() for w in re.split(r"[^A-Za-z0-9]+", stage_name or "") if w}
    return next((label for label in labels if label.upper() in words), None)


def _stage_names(cve):
    # /ns/... returns stage names; the scope endpoints return {"name": ..., "status": ...} objects
    stages = cve.get("stages") if isinstance(cve.get("stages"), list) else []
    return [st.get("name") if isinstance(st, dict) else st for st in stages if st]


def fetch_findings_by_stage():
    """CVEs of SBOM_APP_ID per stage and severity: {"stages": {label: {"critical": n, ...}}, "stage_names": [...]}.

    Reads GET /ns/{namespace}/apps/{app}/cves (every page): each CVE of a component lists the stages where that
    component is active, so it counts once in each of them. stage_names lists every stage seen, matched or not.
    """
    server = os.getenv("SBOM_SERVER", "").rstrip("/")
    auth = (os.getenv("SBOM_API_KEY", ""), os.getenv("SBOM_API_SECRET", ""))
    url = f"{server}/ns/{os.getenv('SBOM_NAMESPACE_ID')}/apps/{os.getenv('SBOM_APP_ID')}/cves"
    labels = scope_stages()
    stages = {label: {sev: 0 for sev in STAGE_SEVERITIES} for label in labels}
    stage_names, cursors, params = set(), set(), {}
    for _ in range(1000):
        resp = requests.get(url, auth=auth, params=dict(params), timeout=30, allow_redirects=False)
        if resp.status_code != 200:
            raise Exception(f"SBOM Inventory CVE list failed (HTTP {resp.status_code})")
        payload = resp.json()
        for cve in payload.get("data") or []:
            severity = str(cve.get("severity") or "").lower()
            for name in _stage_names(cve):
                stage_names.add(name)
                label = _stage_label(name, labels)
                if label and severity in stages[label]:
                    stages[label][severity] += 1
        next_cursor = payload.get("next")
        if not next_cursor:
            return {"stages": stages, "stage_names": sorted(stage_names)}
        if next_cursor in cursors:
            raise Exception("SBOM Inventory CVE list pagination did not complete")
        cursors.add(next_cursor)
        params["next"] = next_cursor
    raise Exception("SBOM Inventory CVE list pagination limit reached")


def format_stage_breakdown(by_stage):
    """One line per stage, e.g. "PROD: Critical 12 · High 40 · Medium 30 · Low 5"; says so if a stage is not found."""
    lines = []
    for label, counts in by_stage["stages"].items():
        if not any(_stage_label(name, [label]) for name in by_stage["stage_names"]):
            lines.append(f"{label}: stage not found")
        else:
            lines.append(f"{label}: " + " · ".join(f"{sev.capitalize()} {n}" for sev, n in counts.items()))
    if any(line.endswith("stage not found") for line in lines) and by_stage["stage_names"]:
        lines.append("Stages in SBOM: " + ", ".join(by_stage["stage_names"]))
    return "  \n".join(lines)


def check_sbom_connection(server, api_key, api_secret, namespace_id, app_id, timeout=8):
    """Returns (ok, message): validates credentials, namespace and app in one call."""
    if not all((server, api_key, api_secret, namespace_id, app_id)):
        return False, "Server, credentials, namespace or app ID empty"
    try:
        resp = requests.get(f"{server.rstrip('/')}/ns/{namespace_id}/apps", auth=(api_key, api_secret), timeout=timeout,
                            allow_redirects=False)
    except requests.RequestException as e:
        return False, f"Connection Failed ({e})"
    # The web UI host redirects to the SSO login instead of accepting the API key
    if resp.is_redirect or "json" not in resp.headers.get("content-type", ""):
        return False, "Server is not the SBOM API (use the API host, not the ui. web URL)"
    if resp.status_code != 200:
        return False, f"Auth Failed (HTTP {resp.status_code})"
    try:
        return True, f"App found ({count_findings(resp.json(), app_id)} findings)"
    except Exception as e:
        return False, str(e)


def findings_by_severity(payload, app_id):
    """Findings of app_id per severity, in SBOM_SEVERITIES order (unknown categories go last)."""
    # cve_rating counts every vulnerable component once per stage (dev + prod), same total as the UI app card
    app = next((a for a in payload.get("apps", []) if a.get("guid") == app_id), None)
    if app is None:
        raise Exception(f"App {app_id} not found in the SBOM Inventory namespace")
    rating = app.get("cve_rating", {})
    ordered = {sev: rating.get(sev, 0) for sev in SBOM_SEVERITIES}
    ordered.update({sev: n for sev, n in rating.items() if sev not in ordered})
    return ordered


def count_findings(payload, app_id):
    return sum(findings_by_severity(payload, app_id).values())


def format_severity_breakdown(by_severity):
    """One-line summary like "Critical 280 · High 886 · Medium 812 · Low 82", skipping empty categories."""
    return " · ".join(f"{sev.capitalize()} {n}" for sev, n in by_severity.items() if n)


if __name__ == "__main__":
    sample = {"apps": [
        {"guid": "other", "cve_rating": {"critical": 9}},
        {"guid": "a1", "cve_rating": {"critical": 280, "high": 886, "medium": 812, "low": 82, "info": 0, "none": 0}},
    ]}
    assert count_findings(sample, "a1") == 2060
    assert list(findings_by_severity(sample, "a1"))[:4] == ["critical", "high", "medium", "low"]
    assert format_severity_breakdown(findings_by_severity(sample, "a1")) == "Critical 280 · High 886 · Medium 812 · Low 82"
    try:
        count_findings(sample, "missing")
        raise AssertionError("missing app must raise")
    except Exception as e:
        assert "not found" in str(e), e
    print("sbom_helpers OK")
