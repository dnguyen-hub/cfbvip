from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BASE_URL = "https://api.collegefootballdata.com"


class CfbdError(RuntimeError):
    """Raised when the CFBD feed cannot satisfy a request."""


class CfbdClient:
    """Small CFBD client with file caching and no third-party dependencies."""

    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: str | Path = "var/cache",
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ.get("CFBD_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout

    def get_plays(
        self,
        *,
        year: int,
        week: int,
        offense: str | None = None,
        defense: str | None = None,
        classification: str | None = "fbs",
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "year": year,
            "week": week,
            "seasonType": "regular",
        }
        if offense:
            params["offense"] = offense
        if defense:
            params["defense"] = defense
        if classification:
            params["classification"] = classification

        result = self._get("/plays", params=params, refresh=refresh)
        if not isinstance(result, list):
            raise CfbdError("Unexpected CFBD response: /plays did not return a list")
        return result

    def _get(self, path: str, *, params: dict[str, Any], refresh: bool) -> Any:
        query = urllib.parse.urlencode(params)
        url = f"{BASE_URL}{path}?{query}"
        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        cache_path = self.cache_dir / f"{cache_key}.json"

        if cache_path.exists() and not refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        if not self.api_key:
            raise CfbdError(
                "CFBD_API_KEY is not set and this week is not cached. "
                "Rotate any exposed key, then export the replacement locally."
            )

        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "CFB-VIP/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise CfbdError(f"CFBD returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CfbdError(f"Could not reach CFBD: {exc.reason}") from exc

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        time.sleep(0.05)
        return payload
