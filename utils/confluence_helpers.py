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
