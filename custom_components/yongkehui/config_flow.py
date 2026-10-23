"""Config flow for the YongKeHui integration."""

from __future__ import annotations

import base64
import logging
import uuid
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CannotConnect,
    CaptchaRequired,
    InvalidAuth,
    NoLocksFound,
    YongKeHuiApiClient,
    YongKeHuiHouse,
)
from .const import (
    CONF_COMMUNITY_ID,
    CONF_COOKIES,
    CONF_CUST_ID,
    CONF_DEVICE_ID,
    CONF_HOUSE_NAME,
    CONF_USER_ID,
    DOMAIN,
    NAME,
)
from .notifications import async_notify_api_failure

_LOGGER = logging.getLogger(__name__)

CONF_IMG_CODE = "img_code"
CONF_REFRESH_CAPTCHA = "refresh_captcha"
CONF_HOUSE_KEY = "house_key"
DATA_PENDING_APIS = "pending_apis"


def _user_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )


def _captcha_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_IMG_CODE): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(CONF_REFRESH_CAPTCHA, default=False): selector.BooleanSelector(),
        }
    )


def _reauth_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )


def _house_schema(houses: list[YongKeHuiHouse]) -> vol.Schema:
    options = {_house_key(index, house): house.name for index, house in enumerate(houses)}
    return vol.Schema({vol.Required(CONF_HOUSE_KEY): vol.In(options)})


def _write_captcha_file(captcha_dir: str, filename: str, img_code: str) -> str:
    if "," in img_code and img_code.startswith("data:"):
        img_code = img_code.split(",", 1)[1]

    path = Path(captcha_dir)
    path.mkdir(exist_ok=True)
    captcha_path = path / filename
    captcha_path.write_bytes(base64.b64decode(img_code))
    return str(captcha_path)


async def _register_captcha_image(hass: HomeAssistant, img_code: str) -> str:
    filename = f"{uuid.uuid4().hex}.jpg"
    captcha_path = await hass.async_add_executor_job(
        _write_captcha_file,
        hass.config.path(".yongkehui_captcha"),
        filename,
        img_code,
    )
    captcha_url = f"/yongkehui_captcha/{filename}"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(captcha_url, captcha_path, cache_headers=False)]
    )
    return captcha_url


def _new_api(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    device_id: str,
    cookies: dict[str, str] | None = None,
) -> YongKeHuiApiClient:
    api = YongKeHuiApiClient(
        async_get_clientsession(hass),
        user_input[CONF_USERNAME],
        user_input[CONF_PASSWORD],
        device_id,
        cookies,
        api_failure_notifier=partial(async_notify_api_failure, hass),
    )
    return api


def _pending_apis(hass: HomeAssistant) -> dict[str, YongKeHuiApiClient]:
    return hass.data.setdefault(DOMAIN, {}).setdefault(DATA_PENDING_APIS, {})


async def _validate_api(
    api: YongKeHuiApiClient,
    *,
    img_code: str | None = None,
    random_token: str | None = None,
) -> list[YongKeHuiHouse]:
    await api.async_login(img_code=img_code, random_token=random_token)
    profile = await api.async_profile()
    houses = api.get_houses_from_profile(profile)
    if not houses:
        raise NoLocksFound("永客会 profile 没有返回 houseList")
    return houses


def _house_key(index: int, house: YongKeHuiHouse) -> str:
    return f"{index}:{house.community_id}:{house.cust_id}"


class YongKeHuiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a YongKeHui config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._pending_user_input: dict[str, Any] | None = None
        self._pending_device_id: str | None = None
        self._pending_random_token: str | None = None
        self._pending_captcha_url: str | None = None
        self._pending_api: YongKeHuiApiClient | None = None
        self._pending_houses: list[YongKeHuiHouse] = []
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Recover authentication for an existing entry."""

        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Retry the saved credentials, or accept an updated password."""

        if user_input is not None:
            entry = self._get_reauth_entry()
            return await self.async_step_user(
                {
                    CONF_USERNAME: entry.data[CONF_USERNAME],
                    CONF_PASSWORD: user_input.get(CONF_PASSWORD)
                    or entry.data[CONF_PASSWORD],
                }
            )
        return self._show_login_form({})

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""

        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = (
                self._reauth_entry.data[CONF_DEVICE_ID]
                if self._reauth_entry is not None
                else str(uuid.uuid4()).upper()
            )
            api = _new_api(self.hass, user_input, device_id)

            try:
                houses = await _validate_api(api)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except CaptchaRequired:
                try:
                    img_code, random_token = await api.async_get_captcha()
                    captcha_url = await _register_captcha_image(self.hass, img_code)
                except Exception:
                    _LOGGER.exception("Could not fetch YongKeHui captcha")
                    errors["base"] = "captcha_required"
                else:
                    self._pending_user_input = user_input
                    self._pending_device_id = device_id
                    self._pending_random_token = random_token
                    self._pending_captcha_url = captcha_url
                    self._pending_api = api
                    return await self.async_step_captcha()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except NoLocksFound:
                errors["base"] = "no_locks_found"
            except Exception:
                _LOGGER.exception("Unexpected exception while configuring YongKeHui")
                errors["base"] = "unknown"
            else:
                self._pending_user_input = user_input
                self._pending_device_id = device_id
                self._pending_api = api
                return await self._async_login_complete(houses)

        return self._show_login_form(errors)

    def _show_login_form(
        self, errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult:
        if self._reauth_entry is not None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=_reauth_schema(),
                errors=errors,
                description_placeholders={
                    "username": self._reauth_entry.data[CONF_USERNAME],
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )

    async def async_step_captcha(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle image captcha input."""

        if (
            self._pending_user_input is None
            or self._pending_device_id is None
            or self._pending_random_token is None
            or self._pending_api is None
        ):
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_REFRESH_CAPTCHA):
                try:
                    await self._async_refresh_captcha()
                except Exception:
                    _LOGGER.exception("Could not refresh YongKeHui captcha")
                    errors["base"] = "captcha_required"
                else:
                    return self._show_captcha_form(errors)

            img_code = (user_input.get(CONF_IMG_CODE) or "").strip()
            if not img_code:
                errors[CONF_IMG_CODE] = "captcha_missing"
                return self._show_captcha_form(errors)

            try:
                houses = await _validate_api(
                    self._pending_api,
                    img_code=img_code,
                    random_token=self._pending_random_token,
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except CaptchaRequired:
                errors["base"] = "captcha_required"
                try:
                    await self._async_refresh_captcha()
                except Exception:
                    _LOGGER.exception("Could not refresh YongKeHui captcha")
            except InvalidAuth:
                if self._reauth_entry is not None:
                    return self._show_login_form({"base": "invalid_auth"})
                errors["base"] = "invalid_auth"
            except NoLocksFound:
                errors["base"] = "no_locks_found"
            except Exception:
                _LOGGER.exception("Unexpected exception while configuring YongKeHui")
                errors["base"] = "unknown"
            else:
                return await self._async_login_complete(houses)

        return self._show_captcha_form(errors)

    def _show_captcha_form(
        self, errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult:
        captcha_url = self._pending_captcha_url or ""
        return self.async_show_form(
            step_id="captcha",
            data_schema=_captcha_schema(),
            errors=errors,
            description_placeholders={
                "captcha_image": f"![captcha]({captcha_url})",
            },
        )

    async def _async_refresh_captcha(self) -> None:
        if self._pending_api is None:
            return

        img_code, random_token = await self._pending_api.async_get_captcha()
        self._pending_random_token = random_token
        self._pending_captcha_url = await _register_captcha_image(self.hass, img_code)

    async def _async_login_complete(
        self, houses: list[YongKeHuiHouse]
    ) -> config_entries.ConfigFlowResult:
        """Keep the configured house when renewing an existing entry."""

        self._pending_houses = houses
        if self._reauth_entry is not None:
            entry_data = self._reauth_entry.data
            for index, house in enumerate(houses):
                if (
                    house.community_id == entry_data[CONF_COMMUNITY_ID]
                    and house.cust_id == entry_data[CONF_CUST_ID]
                ):
                    return await self.async_step_house(
                        {CONF_HOUSE_KEY: _house_key(index, house)}
                    )
            return self.async_abort(reason="reauth_house_not_found")
        return await self.async_step_house()

    async def async_step_house(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle house/community selection."""

        if (
            self._pending_user_input is None
            or self._pending_device_id is None
            or self._pending_api is None
            or not self._pending_houses
        ):
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            house = self._house_from_key(user_input[CONF_HOUSE_KEY])
            if house is None:
                errors["base"] = "unknown"
            else:
                self._pending_api.select_context(
                    house.community_id,
                    house.cust_id,
                    house.user_id,
                )
                try:
                    await self._pending_api.async_get_doors()
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except NoLocksFound:
                    errors["base"] = "no_locks_found"
                except Exception:
                    _LOGGER.exception("Unexpected exception while selecting house")
                    errors["base"] = "unknown"
                else:
                    if self._reauth_entry is not None:
                        if self._reauth_entry.unique_id:
                            _pending_apis(self.hass)[
                                self._reauth_entry.unique_id
                            ] = self._pending_api
                        return self.async_update_reload_and_abort(
                            self._reauth_entry,
                            data_updates={
                                CONF_PASSWORD: self._pending_user_input[CONF_PASSWORD],
                                CONF_COOKIES: self._pending_api.cookies,
                                CONF_USER_ID: house.user_id,
                            },
                        )
                    username = self._pending_user_input[CONF_USERNAME]
                    unique_id = f"{username}_{house.community_id}_{house.cust_id}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    _pending_apis(self.hass)[unique_id] = self._pending_api
                    return self.async_create_entry(
                        title=f"{NAME} {house.name}",
                        data={
                            CONF_USERNAME: username,
                            CONF_PASSWORD: self._pending_user_input[CONF_PASSWORD],
                            CONF_DEVICE_ID: self._pending_device_id,
                            CONF_COOKIES: self._pending_api.cookies,
                            CONF_COMMUNITY_ID: house.community_id,
                            CONF_CUST_ID: house.cust_id,
                            CONF_USER_ID: house.user_id,
                            CONF_HOUSE_NAME: house.name,
                        },
                    )

        if self._reauth_entry is not None:
            return self._show_login_form(errors)

        return self.async_show_form(
            step_id="house",
            data_schema=_house_schema(self._pending_houses),
            errors=errors,
        )

    def _house_from_key(self, key: str) -> YongKeHuiHouse | None:
        for index, house in enumerate(self._pending_houses):
            if key == _house_key(index, house):
                return house
        return None
