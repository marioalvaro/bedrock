import httpx
import pytest

from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import SourceUnavailable


class FakeTime:
    """A clock that only moves when `sleep` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(transport: httpx.MockTransport, fake: FakeTime) -> RateLimitedClient:
    return RateLimitedClient(
        "me@example.com", clock=fake.clock, sleep=fake.sleep, transport=transport
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


def test_the_user_agent_header_is_sent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, json={"ok": True})

    client = _client(httpx.MockTransport(handler), FakeTime())

    assert client.get_json("https://data.sec.gov/x") == {"ok": True}
    assert seen == ["Bedrock me@example.com"]


def test_get_returns_the_raw_body() -> None:
    client = _client(
        httpx.MockTransport(lambda request: httpx.Response(200, content=b'{"a": 1}')),
        FakeTime(),
    )

    assert client.get("https://data.sec.gov/x") == b'{"a": 1}'


def test_the_eleventh_request_in_one_second_waits() -> None:
    fake = FakeTime()
    client = _client(httpx.MockTransport(_ok), fake)

    for _ in range(10):
        client.get_json("https://data.sec.gov/x")
    assert fake.sleeps == []

    client.get_json("https://data.sec.gov/x")
    assert fake.sleeps == [pytest.approx(0.1)]


def test_requests_spread_over_time_do_not_wait() -> None:
    fake = FakeTime()
    client = _client(httpx.MockTransport(_ok), fake)

    for _ in range(30):
        client.get_json("https://data.sec.gov/x")
        fake.now += 0.1

    assert fake.sleeps == []


def test_503_503_200_succeeds_after_backing_off_half_a_second_then_one() -> None:
    statuses = iter([503, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), json={"ok": True})

    fake = FakeTime()
    client = _client(httpx.MockTransport(handler), fake)

    assert client.get_json("https://data.sec.gov/x") == {"ok": True}
    assert fake.sleeps == [0.5, 1.0]


def test_four_429s_raise_source_unavailable() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429)

    fake = FakeTime()
    client = _client(httpx.MockTransport(handler), fake)

    with pytest.raises(SourceUnavailable):
        client.get_json("https://data.sec.gov/x")
    assert len(calls) == 4  # the first try and three retries
    assert fake.sleeps == [0.5, 1.0, 2.0]


def test_a_404_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    client = _client(httpx.MockTransport(handler), FakeTime())

    with pytest.raises(SourceUnavailable, match="404"):
        client.get_json("https://data.sec.gov/x")
    assert len(calls) == 1


def test_a_transport_error_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = _client(httpx.MockTransport(handler), FakeTime())

    with pytest.raises(SourceUnavailable):
        client.get_json("https://data.sec.gov/x")


def test_a_body_that_is_not_json_raises_source_unavailable() -> None:
    client = _client(
        httpx.MockTransport(lambda request: httpx.Response(200, text="<html>")), FakeTime()
    )

    with pytest.raises(SourceUnavailable):
        client.get_json("https://data.sec.gov/x")
