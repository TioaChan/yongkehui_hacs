"""Shared fixtures for YongKeHui integration tests."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yongkehui.api import YongKeHuiApiClient, YongKeHuiDoor
from custom_components.yongkehui.const import (
    CONF_COMMUNITY_ID,
    CONF_COOKIES,
    CONF_CUST_ID,
    CONF_DEVICE_ID,
    CONF_HOUSE_NAME,
    CONF_USER_ID,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def custom_integration(enable_custom_integrations):
    """Allow Home Assistant to load this repository's integration."""


@pytest.fixture
def entry(hass):
    """An existing integration with a saved, expired session."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="永客会 测试小区",
        unique_id="test-user_community_customer",
        data={
            CONF_USERNAME: "test-user",
            CONF_PASSWORD: "saved-password",
            CONF_DEVICE_ID: "persistent-device",
            CONF_COOKIES: {"session": "expired"},
            CONF_COMMUNITY_ID: "community",
            CONF_CUST_ID: "customer",
            CONF_USER_ID: "user",
            CONF_HOUSE_NAME: "测试小区",
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def api(entry):
    """Use the real API client with only HTTP requests mocked."""

    client = YongKeHuiApiClient(
        AsyncMock(),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_DEVICE_ID],
        dict(entry.data[CONF_COOKIES]),
        entry.data[CONF_COMMUNITY_ID],
        entry.data[CONF_CUST_ID],
        entry.data[CONF_USER_ID],
    )
    with (
        patch.object(client._transport, "async_json_request", new_callable=AsyncMock),
        patch.object(client, "_async_password_public_key", return_value=None),
    ):
        yield client


@pytest.fixture
def door():
    return YongKeHuiDoor(
        unique_id="community.door",
        door_id="door",
        door_id_str="encrypted-door",
        name="测试门禁",
        community_id="community",
        cust_id="customer",
        user_id="user",
        raw={},
    )
