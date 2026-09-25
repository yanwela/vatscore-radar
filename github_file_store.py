import base64
import urllib.parse
import requests
import re

class GitHubFileStore:
    def __init__(self, repo, token, branch="main", session=None):
        if not isinstance(repo, str):
            raise TypeError("repo must be a string")
        if not isinstance(token, str):
            raise TypeError("token must be a string")
        if not isinstance(branch, str):
            raise TypeError("branch must be a string")
        self.repo = repo
        self.token = token
        self.branch = branch
        self.session = session if session is not None else requests.Session()
        self.last_error = None

    def _make_headers(self, accept):
        return {
            "Authorization": "Bearer " + self.token,
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28"
        }

    def _make_url(self, path):
        if not isinstance(path, str):
            raise TypeError("path must be a string")
        quoted = urllib.parse.quote(path)
        return f"https://api.github.com/repos/{self.repo}/contents/{quoted}"

    def read(self, path):
        try:
            url = self._make_url(path)
            headers = self._make_headers("application/vnd.github+json")
            resp = self.session.get(url, headers=headers, params={"ref": self.branch}, timeout=15)
            if resp.status_code == 404:
                self.last_error = None
                return None
            if resp.status_code != 200:
                self.last_error = f"read HTTP {resp.status_code}"
                return None
            data = resp.json()
            content_b64 = data.get("content", "")
            size = data.get("size", 0)
            try:
                decoded_bytes = base64.b64decode(content_b64)
                text = decoded_bytes.decode("utf-8")
            except Exception:
                self.last_error = "read: content not valid base64/utf-8"
                return None
            if text == "" and isinstance(size, int) and size > 0:
                raw_headers = self._make_headers("application/vnd.github.raw+json")
                raw_resp = self.session.get(url, headers=raw_headers, params={"ref": self.branch}, timeout=15)
                if raw_resp.status_code == 200:
                    self.last_error = None
                    return raw_resp.text
                else:
                    self.last_error = f"read raw HTTP {raw_resp.status_code}"
                    return None
            self.last_error = None
            return text
        except Exception as e:
            self.last_error = f"read failed: {type(e).__name__}"
            return None

    def write(self, path, text, message):
        try:
            if not isinstance(text, str) or not isinstance(message, str):
                raise TypeError
            url = self._make_url(path)
            sha = None
            get_resp = self.session.get(url, headers=self._make_headers("application/vnd.github+json"), params={"ref": self.branch}, timeout=15)
            if get_resp.status_code == 200:
                sha = get_resp.json().get("sha")
            payload = {
                "message": message,
                "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
                "branch": self.branch
            }
            if sha:
                payload["sha"] = sha
            put_resp = self.session.put(url, headers=self._make_headers("application/vnd.github+json"), json=payload, timeout=15)
            if put_resp.status_code in (200, 201):
                self.last_error = None
                return True
            if put_resp.status_code in (409, 422):
                get_resp = self.session.get(url, headers=self._make_headers("application/vnd.github+json"), params={"ref": self.branch}, timeout=15)
                if get_resp.status_code == 200:
                    sha = get_resp.json().get("sha")
                    payload["sha"] = sha
                else:
                    payload.pop("sha", None)
                put_resp = self.session.put(url, headers=self._make_headers("application/vnd.github+json"), json=payload, timeout=15)
                if put_resp.status_code in (200, 201):
                    self.last_error = None
                    return True
            self.last_error = f"write HTTP {put_resp.status_code}"
            return False
        except Exception as e:
            self.last_error = f"write failed: {type(e).__name__}"
            return False

    def delete(self, path, message):
        try:
            if not isinstance(message, str):
                raise TypeError
            url = self._make_url(path)
            get_resp = self.session.get(url, headers=self._make_headers("application/vnd.github+json"), params={"ref": self.branch}, timeout=15)
            if get_resp.status_code == 404:
                self.last_error = None
                return True
            if get_resp.status_code != 200:
                self.last_error = f"delete lookup HTTP {get_resp.status_code}"
                return False
            sha = get_resp.json().get("sha")
            if not sha:
                self.last_error = "delete: no sha in response"
                return False
            payload = {
                "message": message,
                "sha": sha,
                "branch": self.branch
            }
            del_resp = self.session.delete(url, headers=self._make_headers("application/vnd.github+json"), json=payload, timeout=15)
            if del_resp.status_code == 200:
                self.last_error = None
                return True
            self.last_error = f"delete HTTP {del_resp.status_code}"
            return False
        except Exception as e:
            self.last_error = f"delete failed: {type(e).__name__}"
            return False