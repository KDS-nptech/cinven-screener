"""Provider-pool LLM client with JSON output, disk cache and per-provider rate limits.

Providers come from config.api.llm_providers (OpenAI-compatible chat endpoints: Gemini,
Mistral, Groq, Cerebras, OpenRouter, Ollama). Each has its own key (env or .env), its own
requests-per-second pacing and a cooldown that starts when it returns 429 or 5xx. Calls go
round-robin across the providers that hold a key and are not cooling down; when every
provider is cooling down the client sleeps until the earliest one frees up.

Batch mode (no key anywhere): requests are written to data/cache/llm_batch/pending/<key>.json
and answers are read back from data/cache/llm_batch/responses/<key>.json.

Every answer is cached in data/cache/llm/ keyed on (prompt_version, system, user), so a
re-run costs nothing and any provider may serve any prompt.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field

import httpx

from src.common import REPO, DiskCache, cfg, get_logger, now_iso, path

log = get_logger("llm")


@dataclass
class LLMResult:
    data: dict | None
    raw: str
    model: str
    provider: str
    cached: bool
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class Provider:
    name: str
    base_url: str
    model: str
    key: str
    rps: float
    headers: dict = field(default_factory=dict)
    last_call: float = 0.0
    cooldown_until: float = 0.0
    calls: int = 0
    errors: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def ready_at(self) -> float:
        return max(self.cooldown_until, self.last_call + 1.0 / max(self.rps, 1e-6))


def _dotenv(name: str) -> str | None:
    f = REPO / ".env"
    if not f.exists():
        return None
    for line in f.read_text().splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _env(name: str) -> str | None:
    return os.environ.get(name) or _dotenv(name)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", t, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


class LLM:
    def __init__(self, prompt_version: str, providers: list[str] | None = None):
        api = cfg()["api"]
        self.prompt_version = prompt_version
        self.temperature = api.get("llm_temperature", 0)
        self.max_tokens = api.get("llm_max_tokens", 1500)
        self.cache = DiskCache("llm")
        self.batch_dir = path("cache") / "llm_batch"
        self.providers: list[Provider] = []
        for p in api.get("llm_providers", []):
            if providers and p["name"] not in providers:
                continue
            if p.get("qa_only") and not providers:
                continue  # checker models are only used when asked for by name (src.qa)
            key = _env(p["key_env"])
            if key:
                extra = {}
                for hk, hv in (p.get("headers") or {}).items():
                    val = _env(hv[4:]) if str(hv).startswith("env:") else hv
                    if val:
                        extra[hk] = val
                self.providers.append(Provider(p["name"], p["base_url"].rstrip("/"), p["model"], key, float(p.get("requests_per_second", 0.5)), extra))
        # legacy single provider
        legacy_key = _env(api.get("llm_key_env", "LLM_API_KEY"))
        if legacy_key and _env("LLM_BASE_URL"):
            self.providers.append(Provider("custom", _env("LLM_BASE_URL").rstrip("/"), _env("LLM_MODEL") or "", legacy_key, 0.5))
        self.batch = not self.providers or os.environ.get("LLM_FORCE_BATCH") == "1"
        if self.batch:
            log.warning("batch mode (%s)", "forced" if self.providers else "no LLM keys found")
        else:
            log.info("providers: %s", ", ".join(f"{p.name}:{p.model}@{p.rps}/s" for p in self.providers))
        self.client = httpx.Client(timeout=120)
        self.rr = 0
        self.lock = threading.Lock()
        self.calls = 0
        self.cache_hits = 0

    @property
    def provider(self) -> str:
        return "batch" if self.batch else "+".join(p.name for p in self.providers)

    @property
    def model(self) -> str:
        return "batch" if self.batch else "+".join(p.model for p in self.providers)

    # ------------------------------------------------------------------ scheduling
    class QuotaExhausted(Exception):
        pass

    def _pick(self) -> Provider:
        """Round-robin over providers, waiting for the earliest-ready one when all are busy.
        Raises QuotaExhausted when every provider is parked for more than five minutes."""
        while True:
            with self.lock:
                now = time.monotonic()
                order = self.providers[self.rr:] + self.providers[:self.rr]
                self.rr = (self.rr + 1) % len(self.providers)
                ready = [p for p in order if p.ready_at() <= now]
                if ready:
                    p = ready[0]
                    p.last_call = now
                    return p
                wait = min(p.ready_at() for p in self.providers) - now
                if wait > 300:
                    raise LLM.QuotaExhausted(f"all providers parked for {wait / 60:.0f} min")
            time.sleep(max(0.05, min(wait, 30)))

    def exhausted(self) -> bool:
        now = time.monotonic()
        return bool(self.providers) and all(p.ready_at() - now > 300 for p in self.providers)

    # ------------------------------------------------------------------ public
    def complete_json(self, system: str, user: str, schema_hint: str | None = None, retries: int = 6) -> LLMResult:
        key_parts = (self.prompt_version, system, user)
        cached = self.cache.get(*key_parts)
        if cached is not None:
            self.cache_hits += 1
            return LLMResult(data=cached.get("data"), raw=cached.get("raw", ""), model=cached.get("model", ""),
                             provider=cached.get("provider", ""), cached=True)
        if self.batch:
            return self._batch(key_parts, system, user, schema_hint)
        last_err = None
        for attempt in range(retries):
            try:
                p = self._pick()
            except LLM.QuotaExhausted as e:
                return LLMResult(data=None, raw="", model="", provider="", cached=False, error="quota_exhausted")
            try:
                raw, usage = self._call(p, system, user)
                p.calls += 1
                self.calls += 1
                data = _extract_json(raw)
                if data is None:
                    last_err = f"no_json:{p.name}"
                    p.errors += 1
                    if attempt < retries - 1:
                        continue
                self.cache.put({"data": data, "raw": raw, "model": p.model, "provider": p.name, "fetched_at": now_iso(), "usage": usage}, *key_parts)
                return LLMResult(data=data, raw=raw, model=p.model, provider=p.name, cached=False,
                                 input_tokens=usage.get("in"), output_tokens=usage.get("out"), error=None if data is not None else "no_json")
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                last_err = f"http_{code}:{p.name}"
                p.errors += 1
                retry_after = e.response.headers.get("Retry-After")
                if code == 429:
                    cool = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else 60.0
                    body = e.response.text
                    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", body)
                    if m and (m.group(1) or m.group(2)):
                        cool = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)
                    if m and m.group(3) and not (m.group(1) or m.group(2)):
                        cool = max(5.0, float(m.group(3)))        # "retry in 9.8s": a per-minute window, not the day
                    if ("PerDay" in body or "per_day" in body.lower()) and cool < 600:
                        cool = max(cool, 600.0)   # daily cap: park for 10 minutes at least
                    elif "free_tier_requests" in body and "limit" in body and "PerMinute" not in body and not m and cool < 600:
                        cool = max(cool, 600.0)   # unparsed free-tier message: assume the daily cap
                    p.cooldown_until = time.monotonic() + min(cool, 12 * 3600)
                    log.warning("%s 429, cooling %.0fs", p.name, min(cool, 12 * 3600))
                    continue
                if code in (500, 502, 503, 504, 529):
                    p.cooldown_until = time.monotonic() + 20
                    log.warning("%s %s, cooling 20s", p.name, code)
                    continue
                if code in (400, 401, 403, 404):
                    log.error("%s %s: %s", p.name, code, e.response.text[:300])
                    p.cooldown_until = time.monotonic() + 600  # mis-configured provider: park it
                    continue
            except (httpx.TransportError, json.JSONDecodeError) as e:
                last_err = f"{type(e).__name__}:{p.name}"
                p.errors += 1
                time.sleep(min(20, 2 ** attempt))
        return LLMResult(data=None, raw="", model="", provider="", cached=False, error=last_err or "failed")

    # ------------------------------------------------------------------ transport
    def _call(self, p: Provider, system: str, user: str) -> tuple[str, dict]:
        body = {
            "model": p.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {p.key}", "Content-Type": "application/json", **p.headers}
        r = self.client.post(f"{p.base_url}/chat/completions", json=body, headers=headers)
        if r.status_code == 400 and "response_format" in r.text:
            body.pop("response_format")
            r = self.client.post(f"{p.base_url}/chat/completions", json=body, headers=headers)
        if r.status_code == 400 and "temperature" in r.text:
            body.pop("temperature", None)  # newer Anthropic models reject the parameter
            r = self.client.post(f"{p.base_url}/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        j = r.json()
        text = (j["choices"][0]["message"].get("content") or "") if j.get("choices") else ""
        u = j.get("usage") or {}
        return text, {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}

    def _batch(self, key_parts, system, user, schema_hint) -> LLMResult:
        k = self.cache.key(*key_parts)
        pending = self.batch_dir / "pending"
        responses = self.batch_dir / "responses"
        pending.mkdir(parents=True, exist_ok=True)
        responses.mkdir(parents=True, exist_ok=True)
        resp = responses / f"{k}.json"
        if resp.exists():
            data = json.loads(resp.read_text())
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            self.cache.put({"data": data, "raw": json.dumps(data), "model": "batch", "provider": "batch", "fetched_at": now_iso()}, *key_parts)
            (pending / f"{k}.json").unlink(missing_ok=True)
            return LLMResult(data=data, raw=json.dumps(data), model="batch", provider="batch", cached=False)
        req = pending / f"{k}.json"
        if not req.exists():
            req.write_text(json.dumps({"key": k, "prompt_version": self.prompt_version, "system": system, "user": user,
                                       "schema_hint": schema_hint, "created_at": now_iso()}))
        return LLMResult(data=None, raw="", model="batch", provider="batch", cached=False, error="pending_batch")

    def stats(self) -> dict:
        return {p.name: {"calls": p.calls, "errors": p.errors} for p in self.providers} | {"cache_hits": self.cache_hits}


def normalise_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    """Verbatim check tolerant of whitespace, case and curly quotes."""
    if not quote:
        return False
    tr = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
    q = normalise_ws(quote).translate(tr).strip(" .\"'")
    t = normalise_ws(text).translate(tr)
    return len(q) >= 8 and q in t
