import os

import requests

# Column name used in the dashboard, the Confluence table and the charts.
SBOM_KPI = "Dependencies Findings"


def sbom_configured():
    return all(os.getenv(k) for k in ("SBOM_SERVER", "SBOM_API_KEY", "SBOM_API_SECRET", "SBOM_NAMESPACE_ID", "SBOM_APP_ID"))


def fetch_dependency_findings():
    """Returns the current CVE findings of SBOM_APP_ID, counted like the SBOM Inventory UI.

    The API has no history, so this is always today's value, whatever the sprint dates.
    """
    server = os.getenv("SBOM_SERVER", "").rstrip("/")
    auth = (os.getenv("SBOM_API_KEY", ""), os.getenv("SBOM_API_SECRET", ""))
    resp = requests.get(f"{server}/ns/{os.getenv('SBOM_NAMESPACE_ID')}/apps", auth=auth, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"SBOM Inventory API Error {resp.status_code}: {resp.text}")
    return count_findings(resp.json(), os.getenv("SBOM_APP_ID"))


def count_findings(payload, app_id):
    # cve_rating counts every vulnerable component once per stage (dev + prod), same total as the UI app card
    app = next((a for a in payload.get("apps", []) if a.get("guid") == app_id), None)
    if app is None:
        raise Exception(f"App {app_id} not found in the SBOM Inventory namespace")
    return sum(app.get("cve_rating", {}).values())


if __name__ == "__main__":
    sample = {"apps": [
        {"guid": "other", "cve_rating": {"critical": 9}},
        {"guid": "a1", "cve_rating": {"critical": 280, "high": 886, "medium": 812, "low": 82, "info": 0, "none": 0}},
    ]}
    assert count_findings(sample, "a1") == 2060
    try:
        count_findings(sample, "missing")
        raise AssertionError("missing app must raise")
    except Exception as e:
        assert "not found" in str(e), e
    print("sbom_helpers OK")
