"""Constants for the YongKeHui integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "yongkehui"
NAME = "永客会"

CONF_DEVICE_ID = "device_id"
CONF_COOKIES = "cookies"
CONF_COMMUNITY_ID = "community_id"
CONF_CUST_ID = "cust_id"
CONF_USER_ID = "user_id"
CONF_HOUSE_NAME = "house_name"

AUTO_RELOCK_SECONDS = 5
TOKEN_REFRESH_INTERVAL = timedelta(hours=6)

AUTH_URL = "https://www.uhomecp.com/authc-restapi/v1/user/auth/login"
CAPTCHA_URL = "https://www.uhomecp.com/authc-restapi/v1/auth/code/getImgCode"
RSA_PUBLIC_KEY_URL = "https://www.uhomecp.com/web/sassLogin/lib/sg-rsa.js"
PROFILE_URL = "https://www.uhomecp.com/uhomecp-sso/v3/userApp/profile"
DOOR_LIST_URL = "https://www.uhomecp.com/door-restapi/v1/userapp/doorList"
UNLOCK_URL = "https://www.uhomecp.com/door-restapi/v1/userapp/opendoor/submit.json"

APP_VERSION = "1.3.0"

DEFAULT_HEADERS = {
    "systemversioncode": "26.5.1",
    "phonemodel": "iPhone18,2",
    "version": APP_VERSION,
    "accept": "*/*",
    "source": "2",
    "accept-language": "zh-Hans-CN;q=1, en-US;q=0.9",
    "accept-encoding": "gzip, deflate, br",
    "platform": "yongwei",
    "clienttype": "yongwei",
    "user-agent": "YongWei/1.3.0 (iPhone; iOS 26.5.1; Scale/3.00)",
    "versioncode": "77",
    "priority": "u=3, i",
}
