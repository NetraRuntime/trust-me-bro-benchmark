"""Loopback-only, one-episode OpenAI proxy; upstream credentials stay in this process."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from tmb.terminal_guard import BudgetStop, canonical, prepare_request


def validate_route(route):
    endpoints = {"https://openrouter.ai/api/v1", "https://api.netraruntime.com/v1"}
    if route.get("base_url") not in endpoints or not route.get("model"):
        raise ValueError("Unsupported upstream endpoint")
    checked = datetime.fromisoformat(route["price_checked_at_utc"])
    age = (datetime.now(UTC) - checked).total_seconds()
    if not 0 <= age < 86400:
        raise BudgetStop("Route prices and metadata must be refreshed within 24 hours")
    if route["base_url"].startswith("https://openrouter.ai"):
        if not route.get("provider") or not route.get("expected_response_provider"):
            raise ValueError("Pinned provider and expected response provider are required")
    elif route.get("provider"):
        raise ValueError("Direct Netra must not claim an OpenRouter provider")


class Gateway:
    def __init__(self, ledger, episode_id, route, upstream_key, *, client=None):
        validate_route(route)
        if not upstream_key:
            raise ValueError("Upstream credential missing")
        self.ledger, self.episode_id, self.route = ledger, episode_id, route
        self.upstream_key = upstream_key
        self.client = client or httpx.Client(timeout=180, follow_redirects=False, trust_env=False)

    def complete(self, body):
        validate_route(self.route)
        payload, bound, requested, digest = prepare_request(body, self.route)
        attempt, limit = self.ledger.reserve(self.episode_id, bound, requested, digest)
        payload["max_tokens"] = limit
        try:
            response = self.client.post(
                self.route["base_url"] + "/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + self.upstream_key},
            )
        except httpx.HTTPError:
            self.ledger.settle(attempt)
            return 502, {"error": {"message": "Upstream transport failure; reservation retained"}}
        digest = hashlib.sha256(response.content).hexdigest()
        if response.status_code != 200:
            halt = (
                "Upstream credential or account failure" if response.status_code in {401, 402, 403} else None
            )
            self.ledger.settle(attempt, response_hash=digest, halt=halt)
            # Never reflect upstream error bodies: they may include credentials.
            return 502, {"error": {"message": "Upstream HTTP failure; reservation retained"}}
        try:
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or not data["choices"]:
                raise ValueError("Malformed completion")
        except (ValueError, TypeError):
            self.ledger.settle(attempt, response_hash=digest)
            return 502, {"error": {"message": "Malformed completion; reservation retained"}}
        expected = self.route.get("expected_response_provider")
        if expected and data.get("provider") != expected:
            self.ledger.settle(
                attempt, response_hash=digest, halt="Returned provider did not match pinned route"
            )
        if data.get("model") != self.route["model"]:
            self.ledger.settle(attempt, response_hash=digest, halt="Returned model did not match pinned route")
        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = None
        try:
            self.ledger.settle(attempt, usage, response_hash=digest)
        except (ValueError, TypeError, ArithmeticError):
            self.ledger.settle(attempt, response_hash=digest, halt="Invalid provider billing metadata")
        return 200, data


def make_server(gateway, bearer):
    """Ephemeral token is passed only to the host agent, never to task containers."""
    if not bearer:
        raise ValueError("A local bearer token is required")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, data):
            content = canonical(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.reply(404, {"error": {"message": "Unknown endpoint"}})
                return
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + bearer):
                self.reply(401, {"error": {"message": "Unauthorized"}})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2_000_000 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Unsupported body size or encoding")
                self.connection.settimeout(15)
                body = json.loads(self.rfile.read(length))
                status, data = gateway.complete(body)
            except BudgetStop:
                status, data = 429, {"error": {"message": "Study budget or route gate stopped this request"}}
            except (ValueError, TypeError, KeyError):
                status, data = 400, {"error": {"message": "Invalid study request"}}
            except Exception:  # noqa: BLE001 -- never reflect credentials in arbitrary transport errors
                status, data = 500, {"error": {"message": "Accounting failure; no reservation released"}}
            self.reply(status, data)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)
