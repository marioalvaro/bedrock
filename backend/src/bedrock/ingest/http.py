import json
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from bedrock.ingest.protocol import SourceUnavailable

_RETRYABLE = {429, 500, 502, 503, 504}
_TIMEOUT_SECONDS = 30.0


class RateLimitedClient:
    """HTTP GET with the SEC's identification, a token bucket and retries with backoff."""

    def __init__(
        self,
        user_agent: str,
        *,
        max_per_second: int = 10,
        retries: int = 3,
        backoff: tuple[float, ...] = (0.5, 1.0, 2.0),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._rate = float(max_per_second)
        self._retries = retries
        self._backoff = backoff
        self._clock = clock
        self._sleep = sleep
        self._tokens = self._rate
        self._last = clock()
        self._lock = threading.Lock()
        self._client = httpx.Client(
            headers={"User-Agent": f"Bedrock {user_agent}"},
            transport=transport,
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> bytes:
        """The response body. Retries 429/5xx; anything else that fails is `SourceUnavailable`."""
        for attempt in range(self._retries + 1):
            self._acquire()
            try:
                response = self._client.get(url)
            except httpx.HTTPError as error:
                raise SourceUnavailable(f"{url}: {error}") from error
            if response.status_code == 200:
                return response.content
            if response.status_code not in _RETRYABLE:
                raise SourceUnavailable(f"{url}: HTTP {response.status_code}")
            if attempt == self._retries:
                raise SourceUnavailable(
                    f"{url}: HTTP {response.status_code} after {self._retries} retries"
                )
            self._sleep(self._backoff[min(attempt, len(self._backoff) - 1)])
        raise AssertionError("unreachable")  # pragma: no cover

    def get_json(self, url: str) -> Any:
        body = self.get(url)
        try:
            return json.loads(body)
        except ValueError as error:
            raise SourceUnavailable(f"{url}: response is not JSON") from error

    def _acquire(self) -> None:
        with self._lock:
            self._refill()
            if self._tokens < 1:
                self._sleep((1 - self._tokens) / self._rate)
                self._refill()
            self._tokens -= 1

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
        self._last = now
