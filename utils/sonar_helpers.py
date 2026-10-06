import os
from datetime import datetime, timedelta

import requests

# Sonar metric key -> column name used in the dashboard, the Confluence table and the charts.
SONAR_KPIS = {
    "code_smells": "Code Smells",
    "vulnerabilities": "Security Issues",
    "coverage": "Coverage %",
}


def sonar_configured():
    return all(os.getenv(k) for k in ("SONAR_SERVER", "SONAR_TOKEN", "SONAR_COMPONENT"))


def fetch_sonar_kpis(as_of=None):
    """Returns {column name: value} for SONAR_COMPONENT on the as_of date (today if None).

    Reads the measure history, so a sprint published days later still gets its end-of-sprint values.
    """
    server = os.getenv("SONAR_SERVER", "").rstrip("/")
    to_date = (as_of or datetime.now()).date()
    params = {
        "component": os.getenv("SONAR_COMPONENT", ""),
        "metrics": ",".join(SONAR_KPIS),
        # ponytail: 90-day window fits in one page (one point per analysis); widen it if the component goes 90 days without analysis
        "from": (to_date - timedelta(days=90)).isoformat(),
        "to": to_date.isoformat(),
        "ps": 1000,
    }
    headers = {"Authorization": f"Bearer {os.getenv('SONAR_TOKEN', '')}"}
    resp = requests.get(f"{server}/api/measures/search_history", headers=headers, params=params, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"SonarQube API Error {resp.status_code}: {resp.text}")
    return latest_values(resp.json())


def latest_values(payload):
    values = {}
    for measure in payload.get("measures", []):
        points = [p["value"] for p in measure.get("history", []) if p.get("value") is not None]
        if points:
            values[SONAR_KPIS[measure["metric"]]] = float(points[-1])
    return values


def format_kpi_value(name, value):
    if value is None or value == "":
        return ""
    return f"{value:.1f}%" if name == SONAR_KPIS["coverage"] else str(int(value))


if __name__ == "__main__":
    sample = {"measures": [
        {"metric": "code_smells", "history": [{"date": "d1", "value": "3089"}, {"date": "d2", "value": "3029"}]},
        {"metric": "coverage", "history": [{"date": "d1", "value": "90.3"}, {"date": "d2"}]},
        {"metric": "vulnerabilities", "history": []},
    ]}
    values = latest_values(sample)
    assert values == {"Code Smells": 3029.0, "Coverage %": 90.3}, values
    assert format_kpi_value("Coverage %", 90.3) == "90.3%"
    assert format_kpi_value("Code Smells", 3029.0) == "3029"
    assert format_kpi_value("Security Issues", None) == ""
    print("sonar_helpers OK")
