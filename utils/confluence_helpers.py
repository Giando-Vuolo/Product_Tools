import requests
import traceback
from html.parser import HTMLParser

class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
    def handle_data(self, d):
        self.text.append(d)
    def get_data(self):
        return ''.join(self.text)

def strip_tags(html):
    if not html:
        return ""
    s = MLStripper()
    s.feed(html)
    return s.get_data().strip()

def search_confluence_pages(server, token, auth_type, email, cql):
    """
    Search Confluence using CQL and return simplified results.
    """
    if not server or not token:
        return {"error": "Confluence server or token not configured"}
        
    try:
        base_url = server.rstrip("/")
        if "atlassian.net" in base_url and not base_url.endswith("/wiki"):
            base_url = base_url + "/wiki"
            
        url = f"{base_url}/rest/api/content/search"
        
        headers = {"Accept": "application/json"}
        auth = None
        token_clean = token.strip().removeprefix("Bearer ").strip()
        
        if auth_type in ["Corporate Login (Username + Password)", "Jira Cloud/Server Basic (Email/User + Token)"]:
            auth = (email.strip(), token_clean)
        else:
            headers["Authorization"] = f"Bearer {token_clean}"
            
        params = {
            "cql": cql,
            "limit": 30,
            "expand": "body.view"
        }
        
        resp = requests.get(url, headers=headers, auth=auth, params=params, timeout=15)
        
        if resp.status_code != 200:
            return {"error": f"Confluence API returned {resp.status_code}: {resp.text}"}
            
        data = resp.json()
        results = []
        for item in data.get("results", []):
            title = item.get("title", "")
            webui = item.get("_links", {}).get("webui", "")
            page_url = f"{base_url}{webui}" if webui else ""
            
            body_html = item.get("body", {}).get("view", {}).get("value", "")
            body_text = strip_tags(body_html)
            # truncate to 500 characters
            if len(body_text) > 500:
                body_text = body_text[:500] + "..."
                
            results.append({
                "title": title,
                "url": page_url,
                "excerpt": body_text
            })
            
        return {"results": results}
        
    except Exception as e:
        return {"error": f"Exception during Confluence search: {e}\n{traceback.format_exc()}"}


def _confluence_base_and_auth(server, token, auth_type, email):
    base_url = server.rstrip("/")
    if "atlassian.net" in base_url and not base_url.endswith("/wiki"):
        base_url = base_url + "/wiki"
    headers = {"Accept": "application/json"}
    auth = None
    token_clean = token.strip().removeprefix("Bearer ").strip()
    if auth_type in ["Corporate Login (Username + Password)", "Jira Cloud/Server Basic (Email/User + Token)"]:
        auth = ((email or "").strip(), token_clean)
    else:
        headers["Authorization"] = f"Bearer {token_clean}"
    return base_url, headers, auth


def get_confluence_page(server, token, auth_type, email, page_id):
    """Read a page (storage body, version, space, ancestors). Never raises."""
    if not server or not token:
        return {"error": "Confluence server or token not configured"}
    try:
        base_url, headers, auth = _confluence_base_and_auth(server, token, auth_type, email)
        url = f"{base_url}/rest/api/content/{page_id}"
        resp = requests.get(url, headers=headers, auth=auth, timeout=15,
                            params={"expand": "body.storage,version,space,ancestors"})
        if resp.status_code == 404:
            return {"error": f"Page {page_id} not found"}
        if resp.status_code != 200:
            return {"error": f"Confluence API returned {resp.status_code}: {resp.text}"}
        data = resp.json()
        ancestor_ids = [str(a.get("id")) for a in data.get("ancestors", [])]
        return {
            "id": str(data.get("id", page_id)),
            "title": data.get("title", ""),
            "space_key": (data.get("space") or {}).get("key"),
            "version": (data.get("version") or {}).get("number", 0),
            "parent_id": ancestor_ids[-1] if ancestor_ids else None,
            "ancestor_ids": ancestor_ids,
            "storage": ((data.get("body") or {}).get("storage") or {}).get("value", ""),
        }
    except Exception as e:
        return {"error": f"Exception while reading Confluence page: {e}"}


def list_child_pages(server, token, auth_type, email, parent_id, page_size=50, max_pages=50):
    """List DIRECT child pages of parent_id, following pagination. Never raises.

    Returns {"results": [{"id", "title", "url"}]} or {"error": str}.
    """
    if not server or not token:
        return {"error": "Confluence server or token not configured"}
    try:
        base_url, headers, auth = _confluence_base_and_auth(server, token, auth_type, email)
        results = []
        start = 0
        for _ in range(max_pages):
            resp = requests.get(f"{base_url}/rest/api/content/{parent_id}/child/page", headers=headers,
                                auth=auth, timeout=15, params={"start": start, "limit": page_size})
            if resp.status_code == 404:
                return {"error": f"Parent page {parent_id} not found"}
            if resp.status_code != 200:
                return {"error": f"Confluence API returned {resp.status_code}: {resp.text}"}
            data = resp.json()
            batch = data.get("results") or []
            links = data.get("_links") or {}
            for c in batch:
                webui = (c.get("_links") or {}).get("webui", "")
                results.append({"id": str(c.get("id", "")), "title": c.get("title", ""),
                                "url": f"{base_url}{webui}" if webui else ""})
            if not batch or "next" not in links:
                break
            start += len(batch)
        return {"results": results}
    except Exception as e:
        return {"error": f"Exception while listing child pages: {e}"}


def update_confluence_page(server, token, auth_type, email, page_id, title, new_version, storage):
    """PUT a page with version=new_version. Never raises."""
    if not server or not token:
        return {"error": "Confluence server or token not configured"}
    try:
        base_url, headers, auth = _confluence_base_and_auth(server, token, auth_type, email)
        headers["Content-Type"] = "application/json"
        payload = {
            "id": str(page_id),
            "type": "page",
            "title": title,
            "version": {"number": new_version},
            "body": {"storage": {"value": storage, "representation": "storage"}},
        }
        resp = requests.put(f"{base_url}/rest/api/content/{page_id}", headers=headers, auth=auth,
                            json=payload, timeout=30)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text}"}
        return {"ok": True, "version": new_version}
    except Exception as e:
        return {"error": f"Exception while updating Confluence page: {e}"}
