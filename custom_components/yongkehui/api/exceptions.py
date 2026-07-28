"""Exceptions for the YongKeHui API client."""

from __future__ import annotations


class YongKeHuiError(Exception):
    """Base exception for YongKeHui API errors."""


class CannotConnect(YongKeHuiError):
    """Raised when Home Assistant cannot reach YongKeHui."""


class InvalidAuth(YongKeHuiError):
    """Raised when credentials or cookies are rejected."""


class CaptchaRequired(InvalidAuth):
    """Raised when YongKeHui requires an image captcha."""


class NoLocksFound(YongKeHuiError):
    """Raised when no usable lock/door data is returned."""


class CannotUnlock(YongKeHuiError):
    """Raised when the unlock request fails."""
