import os
from uuid import UUID

import requests


VANGUARD_KPI = "Security findings, platform"


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


def fetch_platform_findings():
    """Count current open findings, excluding previews, across every page.

    Only authenticates and reads findings from fixed One.Cloud endpoints. There
    is no historical reconstruction: this is the value at calculation time.
    """
    if not vanguard_configured():
        raise ValueError("Configure the Vanguard project ID, client ID and client secret.")
    try:
        project_id = str(UUID(os.environ["VANGUARD_PROJECT_ID"].strip()))
    except ValueError:
        raise ValueError("VANGUARD_PROJECT_ID must be a project UUID.") from None

    try:
        auth = _read_json(requests.post(
            "https://auth.api.vwapps.cloud/oauth2/token",
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
        params = {"state": "open", "preview": "false", "page_size": 100}
        finding_ids, cursors = set(), set()
        # A safety ceiling fails explicitly rather than returning a partial KPI.
        for _ in range(1000):
            payload = _read_json(requests.get(
                f"https://api.vwapps.cloud/projects/{project_id}/findings",
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
                finding_ids.add(finding["id"])

            last_key = payload.get("last_key")
            if last_key is None or last_key == "":
                return len(finding_ids)
            if not isinstance(last_key, str) or last_key in cursors:
                raise ValueError("Vanguard pagination did not complete. No count was saved.")
            cursors.add(last_key)
            params["last_key"] = last_key
        raise ValueError("Vanguard pagination limit reached. No count was saved.")
    except requests.RequestException:
        raise ValueError("Vanguard could not be reached. No count was saved; try again.") from None
