# -*- coding: utf-8 -*-
"""
資料持久化：把本機資料夾（~/.quant_radar_data）和一個「私人 GitHub 資料專案」同步。
  - 啟動時（boot_pull）：把遠端檔案抓回本機；本機有未同步的修改就保留。
  - 之後（push）：只上傳有變動的檔案；本機刪掉的（曾經同步過的）檔案也會從遠端刪掉。
  - 安全設計：沒有成功 pull 過之前，絕不 push，避免空的本機資料蓋掉遠端。
不依賴 Streamlit；store 可以換成 MemoryStore 做測試。
"""
import base64
import hashlib
import json
import os
import threading
import time
from urllib.parse import quote

try:
    import requests
except ImportError:
    requests = None

EXCLUDE_DIRS = {"__pycache__", "wanglai_demo"}          # 示範資料不同步
EXCLUDE_SUFFIX = (".tmp", ".conflict", ".pyc")
MANIFEST = ".sync_manifest.json"


def blob_sha(content: bytes) -> str:
    """和 git 一樣的檔案雜湊（blob sha），可以直接跟 GitHub 回傳的 sha 比較，不用下載就能知道有沒有變動。"""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


# ------------------------------------------------------------------ 儲存後端
class MemoryStore:
    """測試用：把檔案放在記憶體裡，行為和 GitHubStore 一致。"""

    def __init__(self):
        self.files = {}
        self.calls = []

    def tree(self):
        return {p: blob_sha(c) for p, c in self.files.items()}

    def read(self, path, sha=None):
        return self.files[path]

    def write(self, path, content, sha=None, message="update"):
        self.calls.append(("write", path))
        self.files[path] = content

    def delete(self, path, sha, message="delete"):
        self.calls.append(("delete", path))
        self.files.pop(path, None)


class GitHubStore:
    """用 GitHub REST API 讀寫一個私人專案裡的檔案（Contents／Trees／Blobs API）。"""

    def __init__(self, token, repo, branch="main", prefix="data/", session=None, timeout=30):
        self.repo, self.branch, self.prefix, self.timeout = repo, branch, prefix, timeout
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "quant-radar-sync"})
        self.base = f"https://api.github.com/repos/{repo}"

    def _check(self, r, ok=(200, 201)):
        if r.status_code not in ok:
            raise RuntimeError(f"GitHub API {r.status_code}: {r.text[:160]}")
        return r

    def tree(self):
        r = self.s.get(f"{self.base}/git/trees/{self.branch}?recursive=1", timeout=self.timeout)
        if r.status_code in (404, 409):                    # 空專案或分支不存在
            return {}
        data = self._check(r).json()
        return {t["path"]: t["sha"] for t in data.get("tree", []) if t["type"] == "blob" and t["path"].startswith(self.prefix)}

    def read(self, path, sha=None):
        r = self._check(self.s.get(f"{self.base}/git/blobs/{sha}", timeout=self.timeout))
        return base64.b64decode(r.json()["content"])

    def write(self, path, content, sha=None, message="update"):
        body = {"message": message, "content": base64.b64encode(content).decode("ascii"), "branch": self.branch}
        if sha:
            body["sha"] = sha
        self._check(self.s.put(f"{self.base}/contents/{quote(path)}", json=body, timeout=self.timeout))

    def delete(self, path, sha, message="delete"):
        self._check(self.s.delete(f"{self.base}/contents/{quote(path)}", json={"message": message, "sha": sha, "branch": self.branch}, timeout=self.timeout))


# ------------------------------------------------------------------ 同步邏輯
class Sync:
    def __init__(self, store, local_dir, prefix="data/", min_age=3.0):
        self.store, self.dir, self.prefix, self.min_age = store, local_dir, prefix, min_age
        self.lock = threading.Lock()
        self.pulled = False
        self.last_push = None
        self.last_error = None
        self.notes = []
        self.counts = {"down": 0, "up": 0, "deleted": 0, "conflict": 0}

    # ---- 本機檔案掃描
    def _local_files(self):
        out = {}
        for root, dirs, files in os.walk(self.dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f == MANIFEST or f.endswith(EXCLUDE_SUFFIX):
                    continue
                full = os.path.join(root, f)
                out[os.path.relpath(full, self.dir).replace(os.sep, "/")] = full
        return out

    def _manifest(self):
        try:
            with open(os.path.join(self.dir, MANIFEST), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_manifest(self, m):
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, MANIFEST), "w", encoding="utf-8") as f:
            json.dump(m, f)

    @staticmethod
    def _read(path):
        with open(path, "rb") as f:
            return f.read()

    # ---- 啟動時：遠端 → 本機
    def boot_pull(self):
        with self.lock:
            try:
                os.makedirs(self.dir, exist_ok=True)
                remote = {p[len(self.prefix):]: sha for p, sha in self.store.tree().items()}
                local = self._local_files()
                manifest = self._manifest()
                for rel, rsha in remote.items():
                    dest = os.path.join(self.dir, rel.replace("/", os.sep))
                    if rel in local:
                        lsha = blob_sha(self._read(local[rel]))
                        if lsha == rsha:
                            manifest[rel] = rsha
                            continue
                        if manifest.get(rel) == rsha:      # 遠端沒變、本機有未同步的修改 → 保留本機，稍後上傳
                            continue
                        if manifest.get(rel) != lsha:      # 兩邊都改過 → 遠端為準，本機版本另存備查
                            os.replace(local[rel], dest + ".conflict")
                            self.counts["conflict"] += 1
                            self.notes.append(f"{rel}：本機與遠端都有修改，已採用遠端版本，本機版本另存為 .conflict")
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    content = self.store.read(self.prefix + rel, rsha)
                    with open(dest, "wb") as f:
                        f.write(content)
                    manifest[rel] = rsha
                    self.counts["down"] += 1
                self._save_manifest(manifest)
                self.pulled = True
                self.last_error = None
            except Exception as e:
                self.last_error = f"啟動同步失敗：{type(e).__name__}: {str(e)[:120]}"
            return self.pulled

    # ---- 之後：本機 → 遠端
    def push(self):
        if not self.pulled:                                  # 還沒成功 pull 過，絕不上傳或刪除
            return False
        with self.lock:
            try:
                remote = {p[len(self.prefix):]: sha for p, sha in self.store.tree().items()}
                local = self._local_files()
                manifest = self._manifest()
                now = time.time()
                for rel, full in local.items():
                    if now - os.path.getmtime(full) < self.min_age:   # 剛寫入中，下一輪再傳
                        continue
                    content = self._read(full)
                    sha = blob_sha(content)
                    if remote.get(rel) == sha:
                        manifest[rel] = sha
                        continue
                    self.store.write(self.prefix + rel, content, sha=remote.get(rel), message=f"sync {rel}")
                    manifest[rel] = sha
                    self.counts["up"] += 1
                for rel in list(manifest):                    # 曾經同步過、但本機已刪除 → 刪遠端
                    if rel not in local and rel in remote:
                        self.store.delete(self.prefix + rel, remote[rel], message=f"delete {rel}")
                        self.counts["deleted"] += 1
                    if rel not in local:
                        manifest.pop(rel, None)
                self._save_manifest(manifest)
                self.last_push = time.strftime("%H:%M:%S")
                self.last_error = None
                return True
            except Exception as e:
                self.last_error = f"同步失敗：{type(e).__name__}: {str(e)[:120]}"
                return False

    def start_background(self, interval=60):
        def loop():
            while True:
                time.sleep(interval)
                try:
                    if not self.pulled:                      # 啟動時抓取失敗：先重試，成功後才會開始上傳
                        self.boot_pull()
                    else:
                        self.push()
                except Exception as e:                       # 背景執行緒不能因為例外而結束
                    self.last_error = f"{type(e).__name__}: {str(e)[:100]}"
        t = threading.Thread(target=loop, daemon=True, name="persist-sync")
        t.start()
        return t


def make_sync(local_dir, token, repo, branch="main"):
    """有 token 和 repo 才建立同步物件；否則回傳 None（沒設定時，資料維持原本的暫存行為）。"""
    if not token or not repo:
        return None
    if requests is None:
        raise RuntimeError("沒有安裝 requests")
    return Sync(GitHubStore(token, repo, branch), local_dir)
