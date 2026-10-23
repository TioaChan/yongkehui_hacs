"""Async client for the YongKeHui mobile API."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from ..const import (
    APP_VERSION,
    AUTH_URL,
    CAPTCHA_URL,
    DOOR_LIST_URL,
    PROFILE_URL,
    RSA_PUBLIC_KEY_URL,
    UNLOCK_URL,
)
from .crypto import encode_password, parse_public_key
from .exceptions import (
    CannotConnect,
    CannotUnlock,
    CaptchaRequired,
    InvalidAuth,
    NoLocksFound,
    YongKeHuiError,
)
from .models import YongKeHuiContext, YongKeHuiDoor, YongKeHuiHouse
from .parsing import (
    api_code,
    api_message,
    coerce_str,
    door_name,
    door_unique_id,
    extract_contexts,
    extract_houses,
    iter_door_dicts,
    value_for_keys,
)
from .transport import ApiFailureNotifier, YongKeHuiTransport

_LOGGER = logging.getLogger(__name__)


class YongKeHuiApiClient:
    """Client that mirrors the flow used by the YongKeHui mobile app."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        device_id: str,
        cookies: dict[str, str] | None = None,
        community_id: str | None = None,
        cust_id: str | None = None,
        user_id: str | None = None,
        api_failure_notifier: ApiFailureNotifier | None = None,
    ) -> None:
        self._transport = YongKeHuiTransport(
            session,
            device_id,
            cookies,
            api_failure_notifier,
        )
        self._username = username
        self._password = password
        self._selected_context = (
            YongKeHuiContext(community_id, cust_id, user_id)
            if community_id and cust_id
            else None
        )
        self._contexts: list[YongKeHuiContext] = []
        self._payloads: list[Any] = []
        self._doors: dict[str, YongKeHuiDoor] = {}
        self._password_public_key: str | None = None
        self._password_public_key_loaded = False

    @property
    def cookies(self) -> dict[str, str]:
        """Return a copy of the current cookie jar."""

        return self._transport.cookies

    @property
    def doors(self) -> dict[str, YongKeHuiDoor]:
        """Return a copy of the currently discovered doors."""

        return dict(self._doors)

    async def async_initialize(self) -> dict[str, YongKeHuiDoor]:
        """Login and fetch the initial door list."""

        await self.async_login()
        await self.async_profile()
        return await self.async_get_doors()

    async def async_refresh(self) -> dict[str, YongKeHuiDoor]:
        """Keep the session alive, logging in once if the saved session expired."""

        try:
            await self.async_profile()
            if not self._doors:
                return await self.async_get_doors()
        except InvalidAuth:
            _LOGGER.debug("YongKeHui session expired; attempting to log in again")
            return await self.async_initialize()
        return dict(self._doors)

    async def async_login(
        self,
        *,
        img_code: str | None = None,
        random_token: str | None = None,
    ) -> None:
        """Perform the full username/password login."""

        public_key = await self._async_password_public_key()
        data = {
            "tel": self._username,
            "password": encode_password(self._password, public_key),
        }
        if img_code and random_token:
            data["imgCode"] = img_code
            data["randomToken"] = random_token

        payload = await self._transport.async_json_request(
            "POST",
            AUTH_URL,
            data=data,
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        code = api_code(payload)
        if code in (20010, 20020):
            message = api_message(payload)
            if message == "永客会 API 返回失败":
                message = "需要图片验证码"
            raise CaptchaRequired(message)
        self._raise_for_api_code(payload, InvalidAuth)
        self._remember_payload(payload)
        self._contexts = extract_contexts(*self._payloads)

    async def async_get_captcha(self) -> tuple[str, str]:
        """Fetch an image captcha as base64 JPEG plus its random token."""

        payload = await self._transport.async_json_request(
            "GET",
            CAPTCHA_URL,
            use_cookie=True,
            timeout=15,
        )
        self._raise_for_api_code(payload, InvalidAuth)
        self._remember_payload(payload)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise InvalidAuth("永客会没有返回验证码")
        img_code = coerce_str(data.get("imgCode"))
        random_token = coerce_str(data.get("randomToken"))
        if not img_code or not random_token:
            raise InvalidAuth("永客会验证码响应不完整")
        return img_code, random_token

    async def async_profile(self) -> Any:
        """Refresh account cookies and load the active user/community context."""

        payload = await self._transport.async_json_request(
            "GET",
            PROFILE_URL,
            use_cookie=True,
            timeout=15,
        )
        self._raise_for_api_code(payload, InvalidAuth)
        self._remember_payload(payload)
        self._contexts = extract_contexts(*self._payloads)
        return payload

    def get_houses_from_profile(self, payload: Any) -> list[YongKeHuiHouse]:
        """Return selectable houses from a profile payload."""

        return extract_houses(payload)

    def select_context(
        self, community_id: str, cust_id: str, user_id: str | None = None
    ) -> None:
        """Select the configured community/cust context."""

        self._selected_context = YongKeHuiContext(community_id, cust_id, user_id)

    async def async_get_doors(self) -> dict[str, YongKeHuiDoor]:
        """Fetch all doors visible to the current account."""

        if self._selected_context is not None:
            contexts = [self._selected_context]
        else:
            contexts = self._contexts
        if not contexts:
            self._contexts = extract_contexts(*self._payloads)
            contexts = self._contexts
        if not contexts:
            raise NoLocksFound("无法从登录响应中解析 communityId/custId")

        doors: dict[str, YongKeHuiDoor] = {}
        for context in contexts:
            payload = await self._transport.async_json_request(
                "GET",
                DOOR_LIST_URL,
                params={
                    "communityId": context.community_id,
                    "custId": context.cust_id,
                },
                use_cookie=True,
                community_id=context.community_id,
                timeout=15,
            )
            self._raise_for_api_code(payload, InvalidAuth)
            self._remember_payload(payload)

            for raw_door in iter_door_dicts(payload):
                door_id = value_for_keys(raw_door, "doorId", "id")
                door_id_str = value_for_keys(raw_door, "doorIdStr", "doorIdString")
                if not door_id or not door_id_str:
                    continue

                door_context = YongKeHuiContext(
                    community_id=value_for_keys(raw_door, "communityId")
                    or context.community_id,
                    cust_id=value_for_keys(raw_door, "custId") or context.cust_id,
                    user_id=value_for_keys(raw_door, "userId") or context.user_id,
                )
                door_unique = door_unique_id(door_context.community_id, door_id)
                doors[door_unique] = YongKeHuiDoor(
                    unique_id=door_unique,
                    door_id=door_id,
                    door_id_str=door_id_str,
                    name=door_name(raw_door, door_id),
                    community_id=door_context.community_id,
                    cust_id=door_context.cust_id,
                    user_id=door_context.user_id,
                    raw=raw_door,
                )

        self._contexts = extract_contexts(*self._payloads)
        if not doors:
            raise NoLocksFound("永客会没有返回可用门禁")
        self._doors = doors
        return doors

    async def async_unlock(self, door: YongKeHuiDoor) -> None:
        """Open a door through the YongKeHui API."""

        last_error: Exception | None = None
        request_body: dict[str, Any] = {
            "custId": door.cust_id,
            "communityId": door.community_id,
            "appType": "2",
            "appVersion": APP_VERSION,
            "doorId": door.door_id,
            "doorIdStr": door.door_id_str,
        }
        if door.user_id:
            request_body["userId"] = door.user_id

        for attempt in range(2):
            try:
                payload = await self._transport.async_json_request(
                    "POST",
                    UNLOCK_URL,
                    json=request_body,
                    use_cookie=True,
                    community_id=door.community_id,
                    headers={"content-type": "application/json"},
                    timeout=5,
                )
                self._raise_for_api_code(payload, CannotUnlock)
                return
            except (CannotConnect, InvalidAuth, CannotUnlock) as err:
                last_error = err
                _LOGGER.debug("Unlock attempt %s failed: %s", attempt + 1, err)

        raise CannotUnlock(str(last_error) if last_error else "开门失败")

    def _remember_payload(self, payload: Any) -> None:
        """Keep recent payloads so context can be inferred from nested data."""

        self._payloads.append(payload)
        self._payloads = self._payloads[-8:]

    async def _async_password_public_key(self) -> str | None:
        """Fetch and cache the Web RSA public key, falling back to bundled key."""

        if self._password_public_key_loaded:
            return self._password_public_key

        self._password_public_key_loaded = True
        try:
            script = await self._transport.async_text_request(
                "GET",
                RSA_PUBLIC_KEY_URL,
                timeout=15,
            )
        except CannotConnect as err:
            _LOGGER.warning(
                "Could not fetch YongKeHui RSA public key, using bundled key: %s",
                err,
            )
            return None

        public_key = parse_public_key(script)
        if public_key is None:
            _LOGGER.warning(
                "Could not parse YongKeHui RSA public key, using bundled key"
            )
            return None

        self._password_public_key = public_key
        _LOGGER.info(
            "Using YongKeHui RSA public key from sg-rsa.js: %s",
            public_key,
        )
        return public_key

    @staticmethod
    def _raise_for_api_code(
        payload: Any, exception_type: type[YongKeHuiError]
    ) -> None:
        """Raise if the API response has a non-zero code."""

        code = api_code(payload)
        if code is not None and code != 0:
            raise exception_type(api_message(payload))
