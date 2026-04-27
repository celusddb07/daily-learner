import base64
import json
import requests
from pathlib import Path


class GitHubStorage:
    """Read/write user_data.json in the GitHub repo via Contents API."""

    def __init__(self, owner: str, repo: str, branch: str, pat: str):
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self._headers = {
            "Authorization": f"token {pat}",
            "Accept": "application/vnd.github.v3+json",
        }
        self._sha_cache: dict[str, str] = {}

    def _url(self, path: str) -> str:
        return f"https://api.github.com/repos/{self.owner}/{self.repo}/contents/{path}"

    def load(self, path: str = "data/user_data.json") -> dict:
        resp = requests.get(
            self._url(path),
            headers=self._headers,
            params={"ref": self.branch},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._sha_cache[path] = data["sha"]
        return json.loads(base64.b64decode(data["content"]).decode())

    def save(self, obj: dict, path: str = "data/user_data.json", msg: str = "update user data"):
        content = base64.b64encode(json.dumps(obj, indent=2).encode()).decode()
        payload = {
            "message": msg,
            "content": content,
            "sha": self._sha_cache.get(path, ""),
            "branch": self.branch,
        }
        resp = requests.put(self._url(path), headers=self._headers, json=payload, timeout=15)
        if resp.status_code == 409:
            # Stale SHA: re-fetch current state and retry once
            self.load(path)
            payload["sha"] = self._sha_cache[path]
            resp = requests.put(self._url(path), headers=self._headers, json=payload, timeout=15)
        resp.raise_for_status()
        self._sha_cache[path] = resp.json()["content"]["sha"]

    def load_topics(self) -> list:
        topics_path = Path(__file__).parent.parent / "config" / "topics.json"
        return json.loads(topics_path.read_text(encoding="utf-8"))
