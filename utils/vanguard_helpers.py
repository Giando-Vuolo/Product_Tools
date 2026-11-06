import os
import re
from uuid import UUID

import requests


VANGUARD_KPI = "Security findings, platform"

# Accounts in scope by default: findings of other accounts of the project are not counted
DEFAULT_ACCOUNTS = "PROD,PRELIVE"
# Per-account counts shown on the dashboard
ACCOUNT_COUNTS = ("must", "overdue", "in-escalation")


def scope_accounts():
    """Account labels in scope (VANGUARD_ACCOUNTS, comma separated), e.g. ["PROD", "PRELIVE"]."""
    raw = os.getenv("VANGUARD_ACCOUNTS", "").strip() or DEFAULT_ACCOUNTS
    return [label.strip() for label in raw.split(",") if label.strip()]


def _scope_label(account_name, labels):
    """The label an account name belongs to: the label as a whole word of the name ("recall2-PROD" -> "PROD")."""
    words = {w.upper() for w in re.split(r"[^A-Za-z0-9]+", account_name or "") if w}
    return next((label for label in labels if label.upper() in words), None)


def _account_of(finding):
    reference = finding.get("reference") if isinstance(finding.get("reference"), dict) else {}
    guid = reference.get("account_guid")
    if not guid:
        tags = reference.get("tags") if isinstance(reference.get("tags"), list) else []
        guid = next((t.get("value") for t in tags if isinstance(t, dict) and t.get("key") == "account_guid"), None)
    return guid if isinstance(guid, str) and guid else None


def _counts_of(finding):
    """Which of ACCOUNT_COUNTS a finding adds to (classification.severity and evaluation of the VWS Customer API)."""
    classification = finding.get("classification") if isinstance(finding.get("classification"), dict) else {}
    severity, evaluation = classification.get("severity"), finding.get("evaluation")
    return {"must": str(severity).lower() == "must", "overdue": str(evaluation).lower() == "overdue",
            "in-escalation": str(evaluation).lower() == "in-escalation"}


def _auth_url():
    return os.getenv("VANGUARD_AUTH_URL", "").strip() or "https://auth.api.your-company.com/oauth2/token"


def _project_url(project_id):
    base = os.getenv("VANGUARD_API_URL", "").strip().rstrip("/") or "https://api.your-company.com"
    return f"{base}/projects/{project_id}"


def _findings_url(project_id):
    return f"{_project_url(project_id)}/findings"


def _account_names(project_id, headers):
    """{account id: account name} of the project (needed to know which findings are in scope)."""
    project = _read_json(requests.get(_project_url(project_id), headers=headers, timeout=30,
                                      allow_redirects=False), "project query")
    accounts = project.get("accounts") if isinstance(project.get("accounts"), list) else []
    return {a["id"]: a.get("name") or a["id"] for a in accounts if isinstance(a, dict) and isinstance(a.get("id"), str)}


def vanguard_configured():
    return all(os.getenv(key, "").strip() for key in (
        "VANGUARD_PROJECT_ID", "VANGUARD_CLIENT_ID", "VANGUARD_CLIENT_SECRET"
    ))


def _read_json(response, stage):
    # Never expose response bodies: authentication errors may contain credentials.
    if response.status_code != 200:
        raise ValueError(f"Vanguard {stage} failed (HTTP {response.status_code}).")
    try:
        payload = response.json()
    except ValueError:
        raise ValueError(f"Vanguard {stage} returned invalid JSON.") from None
    if not isinstance(payload, dict):
        raise ValueError(f"Vanguard {stage} returned an unexpected response.")
    return payload


def check_vanguard_connection(project_id, client_id, client_secret, timeout=8):
    """Returns (ok, message): authenticates and reads one findings page of the project."""
    if not all(v.strip() for v in (project_id, client_id, client_secret)):
        return False, "Project ID, client ID or client secret empty"
    try:
        project_id = str(UUID(project_id.strip()))
    except ValueError:
        return False, "Project ID must be a UUID"
    try:
        auth = _read_json(requests.post(
            _auth_url(),
            data={"grant_type": "client_credentials", "client_id": client_id.strip(), "client_secret": client_secret.strip()},
            timeout=timeout, allow_redirects=False,
        ), "authentication")
        token = auth.get("access_token")
        if not isinstance(token, str) or not token.strip():
            return False, "Authentication returned no access token"
        _read_json(requests.get(
            _findings_url(project_id),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"state": "open", "preview": "false", "page_size": 1}, timeout=timeout, allow_redirects=False,
        ), "findings query")
    except ValueError as e:
        return False, str(e)
    except requests.RequestException:
        return False, "Vanguard could not be reached"
    return True, "Connected to project"


def fetch_platform_findings():
    """Count current open findings, excluding previews, of the accounts in scope (PROD and PRELIVE by default).

    Only authenticates and reads findings from the configured One.Cloud endpoints. There
    is no historical reconstruction: this is the value at calculation time.
    """
    return fetch_platform_findings_summary()["total"]


def fetch_platform_findings_summary():
    """Same findings as fetch_platform_findings: {"total": n, "accounts": {label: {"total", "must", "overdue",
    "in-escalation"}}}, one entry per label of scope_accounts() in that order.

    Findings are read across every page, then kept only if their account (named as in the project) matches a label.
    """
    if not vanguard_configured():
        raise ValueError("Configure the Vanguard project ID, client ID and client secret.")
    try:
        project_id = str(UUID(os.environ["VANGUARD_PROJECT_ID"].strip()))
    except ValueError:
        raise ValueError("VANGUARD_PROJECT_ID must be a project UUID.") from None
    labels = scope_accounts()

    try:
        auth = _read_json(requests.post(
            _auth_url(),
            data={
                "grant_type": "client_credentials",
                "client_id": os.environ["VANGUARD_CLIENT_ID"].strip(),
                "client_secret": os.environ["VANGUARD_CLIENT_SECRET"].strip(),
            },
            timeout=30,
            allow_redirects=False,
        ), "authentication")
        token = auth.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Vanguard authentication returned no access token.")

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        names = _account_names(project_id, headers)
        scope = {guid: _scope_label(name, labels) for guid, name in names.items()}
        if not any(scope.values()):
            raise ValueError(f"No Vanguard account of the project matches {', '.join(labels)} "
                             f"(accounts: {', '.join(sorted(names.values())) or 'none'}). No count was saved.")

        params = {"state": "open", "preview": "false", "page_size": 100}
        findings_in_scope, cursors = {}, set()
        # A safety ceiling fails explicitly rather than returning a partial KPI.
        for _ in range(1000):
            payload = _read_json(requests.get(
                _findings_url(project_id),
                headers=headers, params=dict(params), timeout=30, allow_redirects=False,
            ), "findings query")
            findings = payload.get("findings")
            if not isinstance(findings, list):
                raise ValueError("Vanguard returned an invalid findings list.")
            for finding in findings:
                if (not isinstance(finding, dict)
                        or not isinstance(finding.get("id"), str) or not finding["id"]
                        or finding.get("state") != "open"):
                    raise ValueError("Vanguard returned an invalid open finding.")
                label = scope.get(_account_of(finding))
                if label:
                    findings_in_scope[finding["id"]] = (label, _counts_of(finding))

            last_key = payload.get("last_key")
            if last_key is None or last_key == "":
                accounts = {label: {"total": 0, **{c: 0 for c in ACCOUNT_COUNTS}} for label in labels}
                for label, counts in findings_in_scope.values():
                    accounts[label]["total"] += 1
                    for c in ACCOUNT_COUNTS:
                        accounts[label][c] += counts[c]
                return {"total": len(findings_in_scope), "accounts": accounts}
            if not isinstance(last_key, str) or last_key in cursors:
                raise ValueError("Vanguard pagination did not complete. No count was saved.")
            cursors.add(last_key)
            params["last_key"] = last_key
        raise ValueError("Vanguard pagination limit reached. No count was saved.")
    except requests.RequestException:
        raise ValueError("Vanguard could not be reached. No count was saved; try again.") from None


def format_platform_breakdown(summary):
    """One line per account for the dashboard, e.g. "PROD: Must 10 · Overdue 3 · In escalation 1"."""
    return "  \n".join(f"{label}: Must {s['must']} · Overdue {s['overdue']} · In escalation {s['in-escalation']}"
                        for label, s in summary["accounts"].items())
