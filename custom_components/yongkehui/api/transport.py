"""HTTP transport and request logging for YongKeHui APIs."""

from __future__ import annotations

import asyncio
import json as json_lib
import logging
from http.cookies import Morsel
import time
from typing import Any, Callable
from urllib.parse import urlsplit

import aiohttp

from ..const import DEFAULT_HEADERS
from .exceptions import CannotConnect
from .parsing import api_code, api_message

_LOGGER = logging.getLogger(__name__)
_EXPECTED_NONZERO_CODES = {20010, 20020}
ApiFailureNotifier = Callable[[dict[str, Any]], None]


class YongKeHuiTransport:
    """Make app-like YongKeHui HTTP requests and retain returned cookies."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        device_id: str,
        cookies: dict[str, str] | None = None,
        api_failure_notifier: ApiFailureNotifier | None = None,
    ) -> None:
        self._session = session
        self._device_id = device_id
        self._cookies: dict[str, str] = dict(cookies) if cookies else {}
        self._api_failure_notifier = api_failure_notifier

    @property
    def cookies(self) -> dict[str, str]:
        """Return a copy of the current cookie jar."""

        return dict(self._cookies)

    async def async_text_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        community_id: str | None = None,
        timeout: int = 10,
    ) -> str:
        """Make a request and return text for static API support assets."""

        method = method.upper()
        endpoint = _api_endpoint(url)
        started_at = time.monotonic()
        request_headers = self._headers(community_id=community_id)
        if headers:
            request_headers.update(headers)

        try:
            response = await self._session.request(
                method,
                url,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            )
            async with response:
                text = await response.text()
                if response.status >= 400:
                    elapsed_ms = _elapsed_ms(started_at)
                    _LOGGER.warning(
                        (
                            "YongKeHui API text call failed: method=%s "
                            "endpoint=%s status=%s elapsed_ms=%s community_id=%s"
                        ),
                        method,
                        endpoint,
                        response.status,
                        elapsed_ms,
                        community_id or "-",
                    )
                    self._notify_api_failure(
                        method=method,
                        endpoint=endpoint,
                        status=response.status,
                        elapsed_ms=elapsed_ms,
                        community_id=community_id,
                        error=f"HTTP {response.status}",
                    )
                    raise CannotConnect(f"HTTP {response.status}: {text[:120]}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            elapsed_ms = _elapsed_ms(started_at)
            _LOGGER.warning(
                (
                    "YongKeHui API text call failed: method=%s endpoint=%s "
                    "elapsed_ms=%s community_id=%s error=%s"
                ),
                method,
                endpoint,
                elapsed_ms,
                community_id or "-",
                err,
            )
            self._notify_api_failure(
                method=method,
                endpoint=endpoint,
                elapsed_ms=elapsed_ms,
                community_id=community_id,
                error=str(err),
            )
            raise CannotConnect(str(err)) from err

        _LOGGER.debug(
            (
                "YongKeHui API text call succeeded: method=%s endpoint=%s "
                "status=%s elapsed_ms=%s community_id=%s"
            ),
            method,
            endpoint,
            response.status,
            _elapsed_ms(started_at),
            community_id or "-",
        )
        return text

    async def async_json_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        use_cookie: bool = False,
        community_id: str | None = None,
        timeout: int = 10,
    ) -> Any:
        """Make a request and parse JSON without trusting content-type headers."""

        method = method.upper()
        endpoint = _api_endpoint(url)
        started_at = time.monotonic()
        response_status: int | None = None
        request_headers = self._headers(community_id=community_id)
        if headers:
            request_headers.update(headers)
        if use_cookie:
            cookie = self._cookie_header()
            if cookie:
                request_headers["Cookie"] = cookie

        try:
            response = await self._session.request(
                method,
                url,
                params=params,
                data=data,
                json=json,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            )
            async with response:
                self._store_cookies(response.cookies)
                response_status = response.status
                text = await response.text()
                if response.status >= 400:
                    elapsed_ms = _elapsed_ms(started_at)
                    _LOGGER.warning(
                        (
                            "YongKeHui API call failed: method=%s endpoint=%s "
                            "status=%s elapsed_ms=%s community_id=%s "
                            "use_cookie=%s params=%s data_keys=%s json_keys=%s"
                        ),
                        method,
                        endpoint,
                        response.status,
                        elapsed_ms,
                        community_id or "-",
                        use_cookie,
                        _dict_keys(params),
                        _dict_keys(data),
                        _dict_keys(json),
                    )
                    self._notify_api_failure(
                        method=method,
                        endpoint=endpoint,
                        status=response.status,
                        elapsed_ms=elapsed_ms,
                        community_id=community_id,
                        error=f"HTTP {response.status}",
                    )
                    raise CannotConnect(f"HTTP {response.status}: {text[:120]}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            elapsed_ms = _elapsed_ms(started_at)
            _LOGGER.warning(
                (
                    "YongKeHui API call failed: method=%s endpoint=%s "
                    "elapsed_ms=%s community_id=%s use_cookie=%s params=%s "
                    "data_keys=%s json_keys=%s error=%s"
                ),
                method,
                endpoint,
                elapsed_ms,
                community_id or "-",
                use_cookie,
                _dict_keys(params),
                _dict_keys(data),
                _dict_keys(json),
                err,
            )
            self._notify_api_failure(
                method=method,
                endpoint=endpoint,
                elapsed_ms=elapsed_ms,
                community_id=community_id,
                error=str(err),
            )
            raise CannotConnect(str(err)) from err

        try:
            payload = json_lib.loads(text) if text else {}
        except json_lib.JSONDecodeError as err:
            elapsed_ms = _elapsed_ms(started_at)
            _LOGGER.warning(
                (
                    "YongKeHui API call failed: method=%s endpoint=%s "
                    "status=%s elapsed_ms=%s community_id=%s use_cookie=%s "
                    "params=%s data_keys=%s json_keys=%s error=non_json_response"
                ),
                method,
                endpoint,
                response_status or "-",
                elapsed_ms,
                community_id or "-",
                use_cookie,
                _dict_keys(params),
                _dict_keys(data),
                _dict_keys(json),
            )
            self._notify_api_failure(
                method=method,
                endpoint=endpoint,
                status=response_status,
                elapsed_ms=elapsed_ms,
                community_id=community_id,
                error="non_json_response",
            )
            raise CannotConnect("永客会返回了非 JSON 响应") from err

        code = api_code(payload)
        message = api_message(payload) if code not in (None, 0) else "-"
        if code in (None, 0):
            outcome = "succeeded"
            log_method = _LOGGER.debug
        elif code in _EXPECTED_NONZERO_CODES:
            outcome = "requires_action"
            log_method = _LOGGER.debug
        else:
            outcome = "failed"
            log_method = _LOGGER.warning
        elapsed_ms = _elapsed_ms(started_at)
        log_method(
            (
                "YongKeHui API call %s: method=%s endpoint=%s status=%s "
                "code=%s message=%s elapsed_ms=%s community_id=%s "
                "use_cookie=%s params=%s data_keys=%s json_keys=%s"
            ),
            outcome,
            method,
            endpoint,
            response_status or "-",
            code if code is not None else "-",
            message,
            elapsed_ms,
            community_id or "-",
            use_cookie,
            _dict_keys(params),
            _dict_keys(data),
            _dict_keys(json),
        )
        if outcome == "failed":
            self._notify_api_failure(
                method=method,
                endpoint=endpoint,
                status=response_status,
                code=code,
                message=message,
                elapsed_ms=elapsed_ms,
                community_id=community_id,
            )
        return payload

    def _headers(self, *, community_id: str | None = None) -> dict[str, str]:
        """Build app-like request headers."""

        headers = dict(DEFAULT_HEADERS)
        headers["deviceid"] = self._device_id
        if community_id:
            headers["communityid"] = community_id
        return headers

    def _cookie_header(self) -> str:
        """Render stored cookies as a request header."""

        return "; ".join(
            f"{key}={value}"
            for key, value in self._cookies.items()
        )

    def _store_cookies(self, cookies: dict[str, Morsel[str]]) -> None:
        """Persist cookies returned by YongKeHui."""

        for key, morsel in cookies.items():
            self._cookies[key] = morsel.value

    def _notify_api_failure(self, **details: Any) -> None:
        """Send API failure details to Home Assistant if a notifier is configured."""

        if self._api_failure_notifier is not None:
            try:
                self._api_failure_notifier(details)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Could not create YongKeHui API failure notification",
                    exc_info=True,
                )


def _api_endpoint(url: str) -> str:
    parts = urlsplit(url)
    return parts.path or url


def _dict_keys(value: dict[str, Any] | None) -> str:
    if not value:
        return "-"
    return ",".join(sorted(str(key) for key in value))


def _elapsed_ms(started_at: float) -> int:
    return round((time.monotonic() - started_at) * 1000)
