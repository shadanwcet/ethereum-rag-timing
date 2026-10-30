#!/usr/bin/env python3
"""Serve the Research Assurance local browser app on loopback only."""

import argparse
import base64
import binascii
import hashlib
import json
import mimetypes
import re
import sys
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

import engine


APP_DIR = Path(__file__).resolve().parent
MAX_REQUEST_BYTES = 25 * 1024 * 1024
MAX_OUTPUTS = 100
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class RequestError(ValueError):
    """Raised when an HTTP request fails local app validation."""


class ForbiddenRequest(RequestError):
    """Raised when a request does not originate from the local app origin."""


def _is_local_host_header(host_header, port):
    if not isinstance(host_header, str) or not host_header:
        return False
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit("//" + host_header)
        return parsed.hostname in LOCAL_HOSTS and parsed.port == port
    except ValueError:
        return False


def normalize_output_name(name):
    if not isinstance(name, str) or not name or "\x00" in name:
        raise RequestError("Every uploaded output needs a relative path")
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", normalized) or any(
        part in ("", ".", "..") for part in normalized.split("/")
    ):
        raise RequestError("Unsafe output path: {}".format(name))
    return path.as_posix()


def verify_uploaded_payload(payload):
    profile_base64 = payload.get("profile_base64")
    if not isinstance(profile_base64, str):
        raise RequestError("Select a profile JSON file")
    try:
        profile_bytes = base64.b64decode(profile_base64, validate=True)
        profile = json.loads(profile_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, binascii.Error, ValueError, json.JSONDecodeError) as exc:
        raise RequestError("Profile is not valid base64-encoded UTF-8 JSON: {}".format(exc)) from exc

    run = payload.get("run")
    if not isinstance(run, dict):
        raise RequestError("Select a run manifest JSON file")
    uploaded_files = payload.get("files", [])
    config_base64 = payload.get("config_base64")
    if not isinstance(config_base64, str):
        raise RequestError("Select the configuration file recorded by config_sha256")
    try:
        config_bytes = base64.b64decode(config_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RequestError("Configuration file is not valid base64") from exc
    if len(config_bytes) > MAX_REQUEST_BYTES:
        raise RequestError("Configuration file exceeds the {} byte limit".format(MAX_REQUEST_BYTES))
    actual_config_digest = hashlib.sha256(config_bytes).hexdigest()
    if run.get("config_sha256") != actual_config_digest:
        raise RequestError("Configuration file SHA-256 does not match the run manifest config_sha256")

    if not isinstance(uploaded_files, list) or len(uploaded_files) > MAX_OUTPUTS:
        raise RequestError("Output uploads must be a list of at most {} files".format(MAX_OUTPUTS))

    with tempfile.TemporaryDirectory(prefix="research-assurance-") as temp_dir:
        temp_root = Path(temp_dir)
        profile_path = temp_root / "profile.json"
        profile_path.write_bytes(profile_bytes)
        config_path = temp_root / "config.bin"
        config_path.write_bytes(config_bytes)
        output_paths = set()
        total_bytes = 0
        for item in uploaded_files:
            if not isinstance(item, dict):
                raise RequestError("Uploaded output records must be objects")
            relative_path = normalize_output_name(item.get("path"))
            if relative_path in output_paths:
                raise RequestError("Duplicate uploaded output path: {}".format(relative_path))
            output_paths.add(relative_path)
            content = item.get("content_base64")
            if not isinstance(content, str):
                raise RequestError("Output {} has no file content".format(relative_path))
            try:
                data = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RequestError("Output {} is not valid base64".format(relative_path)) from exc
            total_bytes += len(data)
            if total_bytes > MAX_REQUEST_BYTES:
                raise RequestError("Uploaded output files exceed the {} byte limit".format(MAX_REQUEST_BYTES))
            target = engine._safe_output_path(temp_root, relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        manifest_outputs = run.get("outputs", [])
        if not isinstance(manifest_outputs, list):
            raise RequestError("Run outputs must be a list")
        required_paths = set()
        for item in manifest_outputs:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise RequestError("Every run output must include a relative path")
            relative = normalize_output_name(item["path"])
            required_paths.add(relative)
        missing_paths = sorted(required_paths - output_paths)
        if missing_paths:
            raise RequestError("Select the output files listed in the manifest: {}".format(", ".join(missing_paths)))

        return engine.verify(profile, run, profile_path, temp_root / "run.json", config_path=config_path)


class ResearchAssuranceHandler(BaseHTTPRequestHandler):
    server_version = "ResearchAssurance"
    sys_version = ""

    def log_message(self, format_string, *args):
        sys.stderr.write("[research-assurance] {}\n".format(format_string % args))

    def _send_bytes(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _check_local_request(self):
        if not _is_local_host_header(self.headers.get("Host"), self.server.server_port):
            raise ForbiddenRequest("Request Host must be this app's loopback address")
        origin = self.headers.get("Origin")
        if origin:
            from urllib.parse import urlsplit

            parsed = urlsplit(origin)
            if parsed.hostname not in LOCAL_HOSTS or parsed.port != self.server.server_port:
                raise ForbiddenRequest("Cross-origin requests are not accepted")

    def do_GET(self):
        try:
            self._check_local_request()
        except RequestError as exc:
            self._send_json(403, {"error": str(exc)})
            return

        files = {
            "/": APP_DIR / "web" / "index.html",
            "/app.js": APP_DIR / "web" / "app.js",
            "/styles.css": APP_DIR / "web" / "styles.css",
        }
        if self.path == "/api/pilot-profile":
            try:
                self._send_json(200, engine.load_json(APP_DIR / "profiles" / "battery-estimation-pilot.json"))
            except engine.AssuranceError as exc:
                self._send_json(500, {"error": str(exc)})
            return
        path = files.get(self.path)
        if path is None or not path.is_file():
            self._send_json(404, {"error": "Not found"})
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self._send_bytes(200, content_type + "; charset=utf-8", path.read_bytes())

    def do_POST(self):
        try:
            self._check_local_request()
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise RequestError("Request body must be between 1 byte and {} bytes".format(MAX_REQUEST_BYTES))
            if self.headers.get_content_type() != "application/json":
                raise RequestError("Requests must use application/json")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise RequestError("Request body must be a JSON object")

            if self.path == "/api/search":
                result = engine.search_openalex(payload.get("query", ""), payload.get("limit", 10))
            elif self.path == "/api/verify":
                result = verify_uploaded_payload(payload)
            else:
                self._send_json(404, {"error": "Not found"})
                return
            self._send_json(200, result)
        except ForbiddenRequest as exc:
            self._send_json(403, {"error": str(exc)})
        except RequestError as exc:
            self._send_json(400, {"error": str(exc)})
        except engine.AssuranceError as exc:
            self._send_json(502, {"error": str(exc)})
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": "Invalid JSON request: {}".format(exc)})
        except (KeyError, TypeError, ValueError, OSError) as exc:
            self._send_json(400, {"error": "Invalid request: {}".format(exc)})

    def do_OPTIONS(self):
        self._send_json(405, {"error": "Method not allowed"})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the local Research Assurance app in a browser")
    parser.add_argument("--port", type=int, default=0, help="Loopback port; default selects an available port")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser")
    args = parser.parse_args(argv)
    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), ResearchAssuranceHandler)
    except OSError as exc:
        parser.error("Cannot start local server: {}".format(exc))
    url = "http://127.0.0.1:{}/".format(server.server_port)
    print("Research Assurance is available at {}".format(url), flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Research Assurance.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
