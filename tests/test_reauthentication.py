"""Regression tests for reloads with an expired YongKeHui session."""

from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.yongkehui.api import (
    CannotConnect,
    CaptchaRequired,
    InvalidAuth,
    YongKeHuiApiClient,
)
from custom_components.yongkehui.config_flow import (
    CONF_HOUSE_KEY,
    CONF_IMG_CODE,
    CONF_REFRESH_CAPTCHA,
)
from custom_components.yongkehui.const import (
    AUTH_URL,
    CONF_COMMUNITY_ID,
    CONF_COOKIES,
    CONF_CUST_ID,
    CONF_DEVICE_ID,
    DOMAIN,
    DOOR_LIST_URL,
    PROFILE_URL,
)
from custom_components.yongkehui.coordinator import YongKeHuiDataUpdateCoordinator

EXPIRED = {"code": 1, "message": "用户未登录， 请重新登录!"}
OK = {"code": 0}
PROFILE = {
    "code": 0,
    "data": {
        "userId": "user",
        "houseList": [
            {
                "communityId": "community",
                "custId": "customer",
                "houseName": "测试小区",
            }
        ],
    },
}
DOORS = {
    "code": 0,
    "data": [{"doorId": "door", "doorIdStr": "encrypted-door", "name": "测试门禁"}],
}


@pytest.mark.parametrize("cached_doors", [False, True])
async def test_expired_session_logs_in_once(api, door, cached_doors):
    """Reload and polling both recover and rediscover the configured doors."""

    if cached_doors:
        api._doors = {door.unique_id: door}
    request = api._transport.async_json_request
    request.side_effect = [EXPIRED, OK, PROFILE, DOORS]

    doors = await api.async_refresh()

    assert list(doors) == ["community.door"]
    assert [call.args[1] for call in request.await_args_list] == [
        PROFILE_URL,
        AUTH_URL,
        PROFILE_URL,
        DOOR_LIST_URL,
    ]
    assert request.await_args_list[-1].kwargs["params"] == {
        "communityId": "community",
        "custId": "customer",
    }


async def test_expired_door_list_also_recovers(api):
    api._transport.async_json_request.side_effect = [
        PROFILE,
        EXPIRED,
        OK,
        PROFILE,
        DOORS,
    ]
    assert list(await api.async_refresh()) == ["community.door"]


async def test_valid_session_does_not_login_or_fetch_cached_doors(api, door):
    api._doors = {door.unique_id: door}
    api._transport.async_json_request.return_value = PROFILE
    assert await api.async_refresh() == {door.unique_id: door}
    api._transport.async_json_request.assert_awaited_once()


@pytest.mark.parametrize(
    ("responses", "exception"),
    [
        ([EXPIRED, {"code": 20010}], CaptchaRequired),
        ([EXPIRED, {"code": 20020}], CaptchaRequired),
        ([EXPIRED, EXPIRED], InvalidAuth),
        ([EXPIRED, OK, EXPIRED], InvalidAuth),
    ],
)
async def test_failed_recovery_propagates_auth_error_without_loop(
    api, responses, exception
):
    request = api._transport.async_json_request
    request.side_effect = responses
    with pytest.raises(exception):
        await api.async_refresh()
    assert request.await_count == len(responses)


async def test_network_failure_does_not_attempt_login(api):
    request = api._transport.async_json_request
    request.side_effect = CannotConnect("offline")
    with pytest.raises(CannotConnect):
        await api.async_refresh()
    request.assert_awaited_once()


async def test_refresh_persists_new_cookies(hass, entry, api):
    api._transport.async_json_request.side_effect = [EXPIRED, OK, PROFILE, DOORS]
    api._transport._cookies = {"session": "renewed"}
    coordinator = YongKeHuiDataUpdateCoordinator(hass, api, entry)

    await coordinator._async_update_data()

    assert entry.data[CONF_COOKIES] == {"session": "renewed"}
    assert entry.data[CONF_COMMUNITY_ID] == "community"
    assert entry.data[CONF_DEVICE_ID] == "persistent-device"


@pytest.mark.parametrize("error", [InvalidAuth("expired"), CaptchaRequired("captcha")])
async def test_coordinator_reports_auth_failure(hass, entry, api, error):
    coordinator = YongKeHuiDataUpdateCoordinator(hass, api, entry)
    with (
        patch.object(api, "async_refresh", side_effect=error),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coordinator._async_update_data()


async def test_cookie_rotation_does_not_mutate_entry_before_save(hass, entry, door):
    api = YongKeHuiApiClient(
        AsyncMock(),
        "test-user",
        "saved-password",
        "persistent-device",
        entry.data[CONF_COOKIES],
    )
    api._transport._store_cookies(SimpleCookie("session=renewed"))
    assert entry.data[CONF_COOKIES] == {"session": "expired"}

    coordinator = YongKeHuiDataUpdateCoordinator(hass, api, entry)
    with patch.object(api, "async_refresh", return_value={door.unique_id: door}):
        await coordinator._async_update_data()
    assert entry.data[CONF_COOKIES] == {"session": "renewed"}


async def test_coordinator_keeps_network_failures_retryable(hass, entry, api):
    coordinator = YongKeHuiDataUpdateCoordinator(hass, api, entry)
    with (
        patch.object(api, "async_refresh", side_effect=CannotConnect("offline")),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()


async def test_setup_auth_failure_starts_reauth(hass, entry, api):
    api._transport.async_json_request.side_effect = [EXPIRED, {"code": 20010}]
    with patch("custom_components.yongkehui.YongKeHuiApiClient", return_value=api):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == entry.entry_id


async def test_reload_recovers_session_and_preserves_entity(hass, entry, api):
    request = api._transport.async_json_request
    request.side_effect = [PROFILE, DOORS]
    with patch("custom_components.yongkehui.YongKeHuiApiClient", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id("lock", DOMAIN, "community.door")
        assert entity_id is not None
        assert hass.states.get(entity_id).state == "locked"

        # A real reload creates a client with no cached doors and an expired cookie.
        api._doors = {}
        request.reset_mock()
        request.side_effect = [EXPIRED, OK, PROFILE, DOORS]
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert registry.async_get_entity_id("lock", DOMAIN, "community.door") == entity_id
    assert hass.states.get(entity_id).state == "locked"
    assert [call.args[1] for call in request.await_args_list] == [
        PROFILE_URL,
        AUTH_URL,
        PROFILE_URL,
        DOOR_LIST_URL,
    ]


async def test_polling_auth_failure_starts_reauth(hass, entry, api):
    api._transport.async_json_request.side_effect = [PROFILE, DOORS]
    with patch("custom_components.yongkehui.YongKeHuiApiClient", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        api._transport.async_json_request.side_effect = [EXPIRED, {"code": 20010}]
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    assert not entry.runtime_data.coordinator.last_update_success
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["entry_id"] == entry.entry_id


async def test_reload_captcha_reauth_restores_original_entity(hass, entry, api):
    request = api._transport.async_json_request
    request.side_effect = [PROFILE, DOORS]
    with (
        patch("custom_components.yongkehui.YongKeHuiApiClient", return_value=api),
        patch("custom_components.yongkehui.config_flow._new_api", return_value=api),
        patch.object(api, "async_get_captcha", return_value=("image", "token")),
        patch(
            "custom_components.yongkehui.config_flow._register_captcha_image",
            return_value="/captcha.jpg",
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id("lock", DOMAIN, "community.door")
        api._doors = {}
        request.reset_mock()
        request.side_effect = [
            EXPIRED,
            {"code": 20010},
            {"code": 20010},
            OK,
            PROFILE,
            DOORS,
        ]
        assert not await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
        assert result["step_id"] == "captcha"
        api._transport._cookies = {"session": "renewed"}
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_IMG_CODE: "correct"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert registry.async_get_entity_id("lock", DOMAIN, "community.door") == entity_id
    assert hass.states.get(entity_id).state == "locked"
    assert entry.data[CONF_COOKIES] == {"session": "renewed"}
    assert request.await_count == 6
    assert not hass.data[DOMAIN]["pending_apis"]


async def _start_reauth(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    return result


@pytest.mark.parametrize("new_password", [None, "updated-password"])
async def test_reauth_updates_original_entry_and_reloads(
    hass, entry, api, new_password
):
    original_data = dict(entry.data)
    original_unique_id = entry.unique_id
    api._transport._cookies = {"session": "renewed"}
    api._transport.async_json_request.side_effect = [OK, PROFILE, DOORS]
    result = await _start_reauth(hass, entry)

    with (
        patch(
            "custom_components.yongkehui.config_flow._new_api", return_value=api
        ) as new_api,
        patch.object(hass.config_entries, "async_reload", return_value=True) as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: new_password} if new_password else {}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.unique_id == original_unique_id
    for key in (CONF_USERNAME, CONF_COMMUNITY_ID, CONF_CUST_ID, CONF_DEVICE_ID):
        assert entry.data[key] == original_data[key]
    assert entry.data[CONF_PASSWORD] == (new_password or "saved-password")
    assert entry.data[CONF_COOKIES] == {"session": "renewed"}
    assert new_api.call_args.args[2] == "persistent-device"
    assert new_api.call_args.args[1][CONF_USERNAME] == "test-user"
    assert new_api.call_args.args[1][CONF_PASSWORD] == (
        new_password or "saved-password"
    )
    reload.assert_awaited_once_with(entry.entry_id)
    assert hass.data[DOMAIN]["pending_apis"][entry.unique_id] is api


async def test_reauth_captcha_refresh_wrong_code_and_success(hass, entry, api):
    request = api._transport.async_json_request
    request.side_effect = [{"code": 20010}, {"code": 20020}, OK, PROFILE, DOORS]
    api._transport._cookies = {"session": "renewed"}
    result = await _start_reauth(hass, entry)
    with (
        patch("custom_components.yongkehui.config_flow._new_api", return_value=api),
        patch.object(
            api, "async_get_captcha", return_value=("image", "token")
        ) as captcha,
        patch(
            "custom_components.yongkehui.config_flow._register_captcha_image",
            return_value="/captcha.jpg",
        ),
        patch.object(hass.config_entries, "async_reload", return_value=True) as reload,
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "captcha"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REFRESH_CAPTCHA: True}
        )
        assert result["step_id"] == "captcha"
        assert request.await_count == 1
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IMG_CODE: "wrong"}
        )
        assert result["errors"] == {"base": "captcha_required"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_IMG_CODE: "correct"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert captcha.await_count == 3
    assert request.await_args_list[2].kwargs["data"]["imgCode"] == "correct"
    assert request.await_args_list[2].kwargs["data"]["randomToken"] == "token"
    reload.assert_awaited_once_with(entry.entry_id)
    assert hass.config_entries.async_entries(DOMAIN) == [entry]


@pytest.mark.parametrize(
    ("response", "error"),
    [(EXPIRED, "invalid_auth"), (CannotConnect("offline"), "cannot_connect")],
)
async def test_reauth_errors_leave_entry_unchanged(hass, entry, api, response, error):
    original_data = dict(entry.data)
    api._transport.async_json_request.side_effect = [response]
    result = await _start_reauth(hass, entry)
    with patch("custom_components.yongkehui.config_flow._new_api", return_value=api):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": error}
    assert dict(entry.data) == original_data


async def test_reauth_cannot_switch_to_another_house(hass, entry, api):
    profile = {
        "code": 0,
        "data": {"houseList": [{"communityId": "other", "custId": "customer"}]},
    }
    api._transport.async_json_request.side_effect = [OK, profile]
    original_data = dict(entry.data)
    result = await _start_reauth(hass, entry)
    with patch("custom_components.yongkehui.config_flow._new_api", return_value=api):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reauth_house_not_found"
    assert dict(entry.data) == original_data
    assert hass.config_entries.async_entries(DOMAIN) == [entry]


async def test_initial_configuration_still_selects_house(hass, api):
    api._transport.async_json_request.side_effect = [OK, PROFILE, DOORS]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with (
        patch("custom_components.yongkehui.config_flow._new_api", return_value=api),
        patch("custom_components.yongkehui.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "new-user", CONF_PASSWORD: "password"}
        )
        assert result["step_id"] == "house"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOUSE_KEY: "0:community:customer"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_COMMUNITY_ID] == "community"
