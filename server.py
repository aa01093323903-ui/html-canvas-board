#!/usr/bin/env python3
"""网页画板的本地服务（只用 Python 标准库）。

- 提供画板页面，并把画板自动保存到 board.json
- 保存 AI 生成或导入的每一页 HTML（output/parts/<页面id>.html）和拼好的整套页面（output/index.html）
- 保存导入网页时一起上传的图片等资源（output/assets/）
- 代为转发大模型请求（OpenAI 兼容接口，如 DeepSeek），API Key 只保存在本机 config.json
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PORT", 5178))
DIR = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.join(DIR, "board.json")
CONFIG = os.path.join(DIR, "config.json")
OUT = os.path.join(DIR, "output")
PARTS = os.path.join(OUT, "parts")
ASSETS = os.path.join(OUT, "assets")
PAGE = os.path.join(DIR, "index.html")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ASSET_RE = re.compile(r"^[^/\\\x00]{1,120}$")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".svg": "image/svg+xml", ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif",
         ".ico": "image/x-icon", ".mp4": "video/mp4", ".webm": "video/webm", ".mp3": "audio/mpeg",
         ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf"}
DEFAULT_CONFIG = {"baseUrl": "https://api.deepseek.com", "model": "deepseek-chat", "apiKey": ""}


def mtime():
    try:
        return os.stat(BOARD).st_mtime_ns
    except FileNotFoundError:
        return 0


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_file(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load_config():
    return {**DEFAULT_CONFIG, **read_json(CONFIG, {})}


def public_config(c):
    key = c.get("apiKey") or ""
    return {"baseUrl": c["baseUrl"], "model": c["model"], "hasKey": bool(key),
            "keyTail": key[-4:] if len(key) >= 8 else ""}


def upstream(c, path, payload=None):
    url = c["baseUrl"].rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", "Bearer " + (c.get("apiKey") or ""))
    if data:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=300)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def _upstream_error(self, e):
        if isinstance(e, urllib.error.HTTPError):
            detail = e.read().decode("utf-8", "replace")[:500]
            return self._json({"error": f"模型接口返回 {e.code}：{detail}"}, 502)
        return self._json({"error": f"连接模型接口失败：{e}"}, 502)

    # ---------- GET ----------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(PAGE, "rb") as f:
                return self._send(200, f.read(), TYPES[".html"])
        if path == "/api/board":
            return self._json({"board": read_json(BOARD, None), "mtime": mtime()})
        if path == "/api/mtime":
            return self._json({"mtime": mtime()})
        if path == "/api/config":
            return self._json(public_config(load_config()))
        if path == "/api/parts":
            parts = {}
            if os.path.isdir(PARTS):
                for name in os.listdir(PARTS):
                    if name.endswith(".html"):
                        with open(os.path.join(PARTS, name), encoding="utf-8") as f:
                            parts[name[:-5]] = f.read()
            return self._json(parts)
        if path == "/api/models":
            try:
                with upstream(load_config(), "/models") as r:
                    data = json.loads(r.read().decode("utf-8"))
                return self._json({"models": [m.get("id") for m in data.get("data", [])]})
            except Exception as e:  # noqa: BLE001
                return self._upstream_error(e)
        if path.startswith("/output/"):
            full = os.path.normpath(os.path.join(DIR, urllib.parse.unquote(path).lstrip("/")))
            if full.startswith(OUT + os.sep) and os.path.isfile(full):
                with open(full, "rb") as f:
                    return self._send(200, f.read(), TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream"))
        self._send(404, "not found", "text/plain")

    # ---------- POST ----------
    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            body = self._body()
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 400)

        if path == "/api/board":
            write_file(BOARD, json.dumps(body, ensure_ascii=False, indent=2))
            return self._json({"mtime": mtime()})

        if path == "/api/config":
            c = load_config()
            for k in ("baseUrl", "model"):
                if isinstance(body.get(k), str) and body[k].strip():
                    c[k] = body[k].strip()
            if isinstance(body.get("apiKey"), str) and body["apiKey"].strip():
                c["apiKey"] = body["apiKey"].strip()
            write_file(CONFIG, json.dumps(c, ensure_ascii=False, indent=2))
            return self._json(public_config(c))

        if path == "/api/part":
            pid = str(body.get("id", ""))
            if not ID_RE.match(pid):
                return self._json({"error": "bad id"}, 400)
            target = os.path.join(PARTS, pid + ".html")
            if body.get("html") is None:
                if os.path.exists(target):
                    os.remove(target)
            else:
                write_file(target, body["html"])
            return self._json({"ok": True})

        if path == "/api/asset":  # 导入网页时一起上传的图片、字体等，保存到 output/assets/
            name = str(body.get("name", ""))
            if not ASSET_RE.match(name) or name.startswith("."):
                return self._json({"error": "bad name"}, 400)
            os.makedirs(ASSETS, exist_ok=True)
            with open(os.path.join(ASSETS, name), "wb") as f:
                f.write(base64.b64decode(body.get("data", "")))
            return self._json({"url": "assets/" + name})

        if path == "/api/deck":
            write_file(os.path.join(OUT, "index.html"), body.get("html", ""))
            return self._json({"ok": True})

        if path == "/api/ai":
            return self._ai(body)

        self._send(404, "not found", "text/plain")

    def _ai(self, body):
        c = load_config()
        if not c.get("apiKey"):
            return self._json({"error": "还没有填写 API Key，请先在设置里接入模型"}, 400)
        payload = {"model": body.get("model") or c["model"], "messages": body.get("messages", []),
                   "stream": bool(body.get("stream"))}
        for k in ("temperature", "max_tokens"):
            if k in body:
                payload[k] = body[k]
        if body.get("json"):
            payload["response_format"] = {"type": "json_object"}
        try:
            r = upstream(c, "/chat/completions", payload)
        except Exception as e:  # noqa: BLE001
            return self._upstream_error(e)
        with r:
            if not payload["stream"]:
                return self._send(200, r.read())
            # 流式转发：HTTP/1.0 下不写 Content-Length，结束时关闭连接
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                for line in r:
                    self.wfile.write(line)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"网页画板: http://localhost:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
