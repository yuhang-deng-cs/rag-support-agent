"""Fixed-window rate limiting.

Two places need it: `/auth/login` (password guessing) and `/chat/stream` (every call can cost an LLM
request). The in-memory backend is enough for a single API process; with several replicas, set
`RATE_LIMIT_BACKEND=redis` so they share one counter per key.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, Request, status

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after: int  # seconds until the current window resets


class Limiter(Protocol):
    async def hit(self, key: str, limit: int, window: int = 60) -> Decision: ...


class MemoryLimiter:
    """Per-process counters, one bucket per key and time window."""

    _MAX_KEYS = 50_000

    def __init__(self) -> None:
        self._hits: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    async def hit(self, key: str, limit: int, window: int = 60) -> Decision:
        now = int(time.time())
        bucket = now // window
        with self._lock:
            seen_bucket, count = self._hits.get(key, (bucket, 0))
            if seen_bucket != bucket:
                count = 0
            count += 1
            self._hits[key] = (bucket, count)
            if len(self._hits) > self._MAX_KEYS:  # drop counters from finished windows
                self._hits = {k: v for k, v in self._hits.items() if v[0] == bucket}
        return Decision(count <= limit, (bucket + 1) * window - now)


class RedisLimiter:
    """Shared counters for multiple API replicas (`INCR` + `EXPIRE` per key and window)."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # installed with the `celery` extra

        self._redis = redis.from_url(url)

    async def hit(self, key: str, limit: int, window: int = 60) -> Decision:
        now = int(time.time())
        bucket = now // window
        redis_key = f"ratelimit:{key}:{bucket}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, window + 1)
            count, _ = await pipe.execute()
        return Decision(int(count) <= limit, (bucket + 1) * window - now)


def build_limiter(settings: Settings) -> Limiter:
    if settings.rate_limit_backend == "redis":
        return RedisLimiter(settings.redis_url)
    return MemoryLimiter()


def client_ip(request: Request) -> str:
    # X-Forwarded-For is deliberately ignored: it is client-controlled unless a trusted proxy
    # rewrites it. Behind a proxy, run uvicorn with --proxy-headers so request.client is correct.
    return request.client.host if request.client else "unknown"


async def enforce(request: Request, key: str, limit: int) -> None:
    """Raise 429 with Retry-After once `key` has used `limit` requests in the current minute."""
    services = request.app.state.services
    if not services.settings.rate_limit_enabled:
        return
    decision = await services.limiter.hit(key, limit)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests, please slow down",
            headers={"Retry-After": str(max(1, decision.retry_after))},
        )
