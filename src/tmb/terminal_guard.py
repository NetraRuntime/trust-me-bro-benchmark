"""Durable request accounting for the bounded Terminal-Bench study.

Reservations are committed BEFORE network I/O. Unknown billing never releases
one. This is an accounting component, not a provider billing attestation.
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from decimal import ROUND_CEILING, Decimal


class BudgetStop(RuntimeError):
    """No request may be sent under the current policy."""


def nano_usd(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise ValueError("Money must be finite and nonnegative")
    return int((value * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))


def token_cost(input_tokens, output_tokens, input_price, output_price):
    return nano_usd(
        (input_tokens * Decimal(str(input_price)) + output_tokens * Decimal(str(output_price))) / 1_000_000
    )


def positive_int(value):
    if type(value) is not int or value < 1:
        raise ValueError("Expected a positive integer")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Ledger:
    def __init__(self, path, *, total_usd="30", withheld_usd="7.469848", pilot_usd="2"):
        self.path = str(path)
        policy = {
            "total": nano_usd(total_usd),
            "withheld": nano_usd(withheld_usd),
            "pilot": nano_usd(pilot_usd),
        }
        if not 0 < policy["total"] <= nano_usd(30):
            raise ValueError("Campaign ceiling must be positive and at most $30")
        if policy["withheld"] + policy["pilot"] >= policy["total"]:
            raise ValueError("No budget remains for main collection")
        self.policy = policy
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, body TEXT, halt TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS episodes "
                "(id TEXT PRIMARY KEY, config TEXT NOT NULL, phase TEXT NOT NULL, closed INTEGER DEFAULT 0)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, episode TEXT NOT NULL, "
                "input_bound INTEGER NOT NULL, output_bound INTEGER NOT NULL, reserved INTEGER NOT NULL, "
                "charged INTEGER NOT NULL, input_used INTEGER NOT NULL, output_used INTEGER NOT NULL, "
                "state TEXT NOT NULL, request_hash TEXT NOT NULL, response_hash TEXT, "
                "created TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            row = db.execute("SELECT body FROM policy WHERE id=1").fetchone()
            if row is None:
                db.execute("INSERT INTO policy VALUES (1, ?, NULL)", (canonical(policy),))
            elif row[0] != canonical(policy):
                raise BudgetStop("Existing campaign policy cannot be changed on resume")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def episode(self, episode_id, route, *, phase="pilot", input_limit=150_000, output_limit=20_000):
        if not episode_id or phase not in {"pilot", "main"}:
            raise ValueError("Episode ID and valid phase required")
        positive_int(input_limit)
        positive_int(output_limit)
        if input_limit > 150_000 or output_limit > 20_000:
            raise ValueError("Episode exceeds the approved candidate limits")
        for key in ("input_per_million", "output_per_million"):
            nano_usd(route[key])
        config = canonical({"route": route, "input_limit": input_limit, "output_limit": output_limit})
        with self.transaction() as db:
            old = db.execute(
                "SELECT config, phase, closed FROM episodes WHERE id=?", (episode_id,)
            ).fetchone()
            if old is None:
                db.execute(
                    "INSERT INTO episodes (id, config, phase) VALUES (?, ?, ?)", (episode_id, config, phase)
                )
            elif old != (config, phase, 0):
                raise BudgetStop("Episode cannot be reset, reopened, or reconfigured")

    def reserve(self, episode_id, input_bound, requested_output, request_hash):
        positive_int(input_bound)
        positive_int(requested_output)
        with self.transaction() as db:
            halt = db.execute("SELECT halt FROM policy WHERE id=1").fetchone()[0]
            if halt:
                raise BudgetStop(halt)
            row = db.execute(
                "SELECT config, phase, closed FROM episodes WHERE id=?", (episode_id,)
            ).fetchone()
            if row is None or row[2]:
                raise BudgetStop("Episode is absent or closed")
            config, phase = json.loads(row[0]), row[1]
            used_in, used_out = db.execute(
                "SELECT coalesce(sum(input_used),0), coalesce(sum(output_used),0) "
                "FROM attempts WHERE episode=?",
                (episode_id,),
            ).fetchone()
            output_bound = min(requested_output, 8192, config["output_limit"] - used_out)
            if used_in + input_bound > config["input_limit"] or output_bound < 1:
                raise BudgetStop("Episode token allowance exhausted")
            route = config["route"]
            cost = token_cost(
                input_bound, output_bound, route["input_per_million"], route["output_per_million"]
            )
            total = db.execute("SELECT coalesce(sum(charged),0) FROM attempts").fetchone()[0]
            phase_used = db.execute(
                "SELECT coalesce(sum(a.charged),0) FROM attempts a JOIN episodes e ON a.episode=e.id "
                "WHERE e.phase=?",
                (phase,),
            ).fetchone()[0]
            api_cap = self.policy["total"] - self.policy["withheld"]
            phase_cap = self.policy["pilot"] if phase == "pilot" else api_cap - self.policy["pilot"]
            if total + cost > api_cap or phase_used + cost > phase_cap:
                raise BudgetStop("Campaign or phase dollar allowance exhausted")
            cursor = db.execute(
                "INSERT INTO attempts (episode,input_bound,output_bound,reserved,charged,input_used,"
                "output_used,state,request_hash) VALUES (?,?,?,?,?,?,?,'reserved',?)",
                (episode_id, input_bound, output_bound, cost, cost, input_bound, output_bound, request_hash),
            )
            return cursor.lastrowid, output_bound

    def settle(self, attempt_id, usage=None, *, response_hash=None, halt=None):
        """Usage includes reasoning within completion_tokens; caches are not subtracted."""
        with self.transaction() as db:
            row = db.execute(
                "SELECT a.episode,a.input_bound,a.output_bound,a.reserved,a.state,e.config FROM attempts a "
                "JOIN episodes e ON e.id=a.episode WHERE a.id=?",
                (attempt_id,),
            ).fetchone()
            if row is None or row[4] != "reserved":
                raise BudgetStop("Attempt has already settled or does not exist")
            inp, out, charged, state = row[1], row[2], row[3], "unknown"
            if usage is not None:
                actual_in, actual_out = usage.get("prompt_tokens"), usage.get("completion_tokens")
                if all(type(x) is int and x >= 0 for x in (actual_in, actual_out)):
                    route = json.loads(row[5])["route"]
                    cost = token_cost(
                        actual_in, actual_out, route["input_per_million"], route["output_per_million"]
                    )
                    reported_cost = usage.get("cost")
                    if reported_cost is not None:
                        cost = max(cost, nano_usd(reported_cost))
                    if actual_in > inp or actual_out > out or cost > charged:
                        halt = "Provider usage or cost exceeded its reservation"
                        inp, out, charged = max(inp, actual_in), max(out, actual_out), max(charged, cost)
                        state = "overrun"
                    else:
                        inp, out, charged, state = actual_in, actual_out, cost, "settled"
            db.execute(
                "UPDATE attempts SET input_used=?,output_used=?,charged=?,state=?,response_hash=? WHERE id=?",
                (inp, out, charged, state, response_hash, attempt_id),
            )
            if halt:
                db.execute("UPDATE policy SET halt=? WHERE id=1", (halt,))
        if halt:
            raise BudgetStop(halt)

    def close(self, episode_id):
        with self.transaction() as db:
            db.execute("UPDATE episodes SET closed=1 WHERE id=?", (episode_id,))

    def snapshot(self):
        with self.transaction() as db:
            db.row_factory = sqlite3.Row
            return {
                "policy": self.policy,
                "money_unit": "nanodollar",
                "halt": db.execute("SELECT halt FROM policy WHERE id=1").fetchone()[0],
                "attempts": [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY id")],
            }


def prepare_request(body, route):
    """Conservative text-only byte bound plus template overhead, checked on settlement.

    This bound must be validated for each provider in the disjoint pilot. Hidden
    provider-injected prompts cannot be bounded from the public API alone.
    """
    allowed = {
        "model",
        "messages",
        "max_tokens",
        "max_completion_tokens",
        "stream",
        "n",
        "temperature",
        "top_p",
        "seed",
        "reasoning_effort",
        "response_format",
    }
    if not isinstance(body, dict) or set(body) - allowed:
        raise ValueError("Unsupported request fields")
    if body.get("model") != "tmb" or body.get("stream", False) is not False or body.get("n", 1) != 1:
        raise ValueError("Only the tmb alias, nonstreaming requests and n=1 are supported")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Messages are required")
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message["role"] not in {"system", "user", "assistant"}
            or not isinstance(message["content"], str)
        ):
            raise ValueError("Only plain text chat messages are supported")
    requested = positive_int(body.get("max_completion_tokens", body.get("max_tokens", 8192)))
    bound = len(canonical(body).encode("utf-8")) + 4096 + 256 * len(messages)
    payload = {**body, "model": route["model"], "stream": False, "max_tokens": min(requested, 8192)}
    payload.pop("max_completion_tokens", None)
    if route.get("provider"):
        payload["provider"] = {
            "only": [route["provider"]],
            "allow_fallbacks": False,
            "require_parameters": True,
        }
    return payload, bound, requested, hashlib.sha256(canonical(payload).encode()).hexdigest()
