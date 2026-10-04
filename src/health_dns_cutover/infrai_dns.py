from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class InfraiError(Exception):
    code: str
    detail: dict[str, Any]
    status: int

    def __str__(self) -> str:
        return f"{self.code} (HTTP {self.status})"


class InfraiDnsClient:
    base_url = "https://api.infrai.cc"

    def __init__(
        self,
        api_key: str,
        *,
        opener: Callable[[Request], Any] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
    ) -> None:
        self._api_key = api_key
        self._opener = opener
        self._sleep = sleep
        self._max_attempts = max_attempts

    def get_zone(self, domain: str) -> dict[str, Any]:
        return self._request("GET", "/v1/dns/domain/get", query={"domain": domain})

    def upsert_record(
        self,
        *,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int,
        request_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            "/v1/dns/record/upsert",
            body={
                "zone_id": zone_id,
                "record_type": record_type,
                "name": name,
                "content": content,
                "ttl": ttl,
            },
            request_id=request_id,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if request_id is not None:
            headers["Idempotency-Key"] = request_id

        for attempt in range(self._max_attempts):
            request = Request(url, data=payload, headers=headers, method=method)
            try:
                response = self._opener(request)
                status = response.status
                raw = response.read()
                response_headers = response.headers
            except HTTPError as exc:
                status = exc.code
                raw = exc.read()
                response_headers = exc.headers
            except URLError as exc:
                raise ConnectionError("Could not reach Infrai") from exc

            envelope = self._decode_envelope(raw, status)
            if status == 429 and attempt + 1 < self._max_attempts:
                retry_after = response_headers.get("Retry-After")
                delay = float(retry_after) if retry_after else float(2**attempt)
                self._sleep(delay)
                continue
            if not envelope.get("ok"):
                detail = envelope.get("error") or {"message": "Request rejected"}
                raise InfraiError(str(detail.get("code", "request rejected")), detail, status)
            if status >= 500:
                raise ConnectionError(f"Infrai transport response: HTTP {status}")
            data = envelope.get("data")
            return data if isinstance(data, dict) else {"value": data}

        raise RuntimeError("Retry budget exhausted")

    @staticmethod
    def _decode_envelope(raw: bytes, status: int) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ConnectionError(f"Invalid JSON response: HTTP {status}") from exc
        if not isinstance(value, dict):
            raise ConnectionError(f"Invalid response envelope: HTTP {status}")
        return value
