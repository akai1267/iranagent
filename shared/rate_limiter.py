import time
from collections import deque


class RateLimiter:
    """Sliding-window per-model rate limiter for 60-second windows."""

    def __init__(self, models_config: dict, threshold: float = 1.0):
        self.threshold = threshold
        self.limits: dict[str, dict[str, int]] = {}
        self.req_log: dict[str, deque[float]] = {}
        self.tok_log: dict[str, deque[tuple[float, int]]] = {}

        for alias, cfg in models_config.items():
            self.limits[alias] = {
                "rpm": int(cfg.get("rpm_limit", 30)),
                "tpm": int(cfg.get("tpm_limit", 6000)),
            }
            self.req_log[alias] = deque()
            self.tok_log[alias] = deque()

    def _evict(self, alias: str) -> None:
        cutoff = time.time() - 60.0
        while self.req_log[alias] and self.req_log[alias][0] < cutoff:
            self.req_log[alias].popleft()
        while self.tok_log[alias] and self.tok_log[alias][0][0] < cutoff:
            self.tok_log[alias].popleft()

    def can_call(self, alias: str, tokens_estimate: int = 500) -> bool:
        if alias not in self.limits:
            return True

        self._evict(alias)
        lim = self.limits[alias]
        rpm_cap = lim["rpm"] * self.threshold
        tpm_cap = lim["tpm"] * self.threshold

        current_reqs = len(self.req_log[alias])
        current_toks = sum(t for _, t in self.tok_log[alias])
        return current_reqs < rpm_cap and (current_toks + tokens_estimate) < tpm_cap

    def record_call(self, alias: str, tokens_used: int) -> None:
        if alias not in self.limits:
            return
        now = time.time()
        self.req_log[alias].append(now)
        self.tok_log[alias].append((now, int(tokens_used)))

    def seconds_until_reset(self, alias: str) -> float:
        if alias not in self.limits:
            return 0.0

        self._evict(alias)
        oldest_req = self.req_log[alias][0] if self.req_log[alias] else None
        oldest_tok = self.tok_log[alias][0][0] if self.tok_log[alias] else None
        candidates = [ts for ts in (oldest_req, oldest_tok) if ts is not None]
        if not candidates:
            return 0.0

        oldest = min(candidates)
        wait = (oldest + 60.0) - time.time()
        return max(0.0, wait)

    def usage_fraction(self, alias: str) -> float:
        if alias not in self.limits:
            return 0.0

        self._evict(alias)
        lim = self.limits[alias]
        req_frac = len(self.req_log[alias]) / max(1, lim["rpm"])
        tok_frac = sum(t for _, t in self.tok_log[alias]) / max(1, lim["tpm"])
        return max(req_frac, tok_frac)


class GlobalRateLimiter:
    """Shared Redis-backed fixed-window limiter with atomic reservations."""

    RESERVE_SCRIPT = """
local req_key = KEYS[1]
local tok_key = KEYS[2]
local rpm_cap = tonumber(ARGV[1])
local tpm_cap = tonumber(ARGV[2])
local req_cost = tonumber(ARGV[3])
local tok_cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local req = tonumber(redis.call('GET', req_key) or '0')
local tok = tonumber(redis.call('GET', tok_key) or '0')

if (req + req_cost > rpm_cap) or (tok + tok_cost > tpm_cap) then
  local current_ttl = redis.call('TTL', req_key)
  if current_ttl < 0 then
    current_ttl = ttl
  end
  return {0, req, tok, current_ttl}
end

req = redis.call('INCRBY', req_key, req_cost)
tok = redis.call('INCRBY', tok_key, tok_cost)
redis.call('EXPIRE', req_key, ttl)
redis.call('EXPIRE', tok_key, ttl)
return {1, req, tok, ttl}
"""

    ADJUST_SCRIPT = """
local tok_key = KEYS[1]
local delta = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', tok_key) or '0')
local updated = current + delta
if updated < 0 then
  updated = 0
end
redis.call('SET', tok_key, tostring(updated), 'EX', ttl)
return updated
"""

    PACE_SCRIPT = """
local pace_key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local interval_ms = tonumber(ARGV[2])
local next_allowed_ms = tonumber(redis.call('GET', pace_key) or '0')

if now_ms < next_allowed_ms then
  return next_allowed_ms - now_ms
end

local new_next_ms = now_ms + interval_ms
redis.call('SET', pace_key, tostring(new_next_ms), 'PX', interval_ms * 2)
return 0
"""

    def __init__(
        self,
        redis_client,
        models_config: dict,
        threshold: float = 1.0,
        window_seconds: int = 60,
        key_prefix: str = "global_rl",
    ):
        self.redis = redis_client
        self.threshold = max(0.1, float(threshold))
        self.window_seconds = max(10, int(window_seconds))
        self.key_prefix = key_prefix
        self.limits: dict[str, dict[str, int]] = {}

        for alias, cfg in models_config.items():
            self.limits[alias] = {
                "rpm": max(1, int(cfg.get("rpm_limit", 30))),
                "tpm": max(1, int(cfg.get("tpm_limit", 6000))),
            }

    def _keys(self, alias: str, bucket: int) -> tuple[str, str]:
        req_key = f"{self.key_prefix}:{alias}:{bucket}:req"
        tok_key = f"{self.key_prefix}:{alias}:{bucket}:tok"
        return req_key, tok_key

    def _pace_key(self, alias: str) -> str:
        return f"{self.key_prefix}:pace:{alias}"

    def effective_limits(self, alias: str) -> tuple[int, int]:
        if alias not in self.limits:
            return 1, 1
        lim = self.limits[alias]
        rpm_cap = max(1, int(lim["rpm"] * self.threshold))
        tpm_cap = max(1, int(lim["tpm"] * self.threshold))
        return rpm_cap, tpm_cap

    def effective_rpm(self, alias: str) -> int:
        rpm, _ = self.effective_limits(alias)
        return rpm

    def effective_tpm(self, alias: str) -> int:
        _, tpm = self.effective_limits(alias)
        return tpm

    def reservation_tokens(self, alias: str, tokens: int) -> int:
        token_cost = max(1, int(tokens))
        if alias not in self.limits:
            return token_cost
        tpm_cap = self.effective_tpm(alias)
        return min(token_cost, tpm_cap)

    async def reserve(self, alias: str, tokens: int) -> dict:
        if alias not in self.limits:
            return {"allowed": True, "retry_after": 0, "reserved_tokens": max(1, int(tokens))}

        rpm_cap, tpm_cap = self.effective_limits(alias)
        token_cost = self.reservation_tokens(alias, tokens)

        now = int(time.time())
        bucket = now // self.window_seconds
        req_key, tok_key = self._keys(alias, bucket)

        raw = await self.redis.eval(
            self.RESERVE_SCRIPT,
            2,
            req_key,
            tok_key,
            rpm_cap,
            tpm_cap,
            1,
            token_cost,
            self.window_seconds,
        )
        allowed = bool(int(raw[0]))
        retry_after = int(raw[3]) if len(raw) >= 4 else self.window_seconds
        return {"allowed": allowed, "retry_after": max(1, retry_after), "reserved_tokens": token_cost}

    async def adjust_tokens(self, alias: str, delta_tokens: int) -> None:
        if alias not in self.limits or delta_tokens == 0:
            return

        now = int(time.time())
        bucket = now // self.window_seconds
        _, tok_key = self._keys(alias, bucket)
        await self.redis.eval(
            self.ADJUST_SCRIPT,
            1,
            tok_key,
            int(delta_tokens),
            self.window_seconds,
        )

    async def acquire_pace_slot(self, alias: str, interval_seconds: float) -> float:
        interval_ms = max(1, int(float(interval_seconds) * 1000))
        now_ms = int(time.time() * 1000)
        wait_ms = await self.redis.eval(
            self.PACE_SCRIPT,
            1,
            self._pace_key(alias),
            now_ms,
            interval_ms,
        )
        wait = int(wait_ms) if wait_ms is not None else 0
        return max(0.0, wait / 1000.0)
