from __future__ import annotations


class BaixaAquiError(Exception):
    """Base class for expected product-level failures."""


class CookieRequiredError(BaixaAquiError):
    """Raised when a platform requires authenticated cookies."""


class PlatformBlockedError(BaixaAquiError):
    """Raised when a platform blocks the VPS/network temporarily."""


class DrmProtectedError(BaixaAquiError):
    """Raised when a platform only exposes DRM-protected media."""


class UnsupportedUrlError(BaixaAquiError):
    """Raised when a URL is invalid or not supported."""


class DownloadTimeoutError(BaixaAquiError):
    """Raised when an external download process times out."""


class UploadFailedError(BaixaAquiError):
    """Raised when Telegram upload fails after controlled retries."""


class MissingDependencyError(BaixaAquiError):
    """Raised when an optional production dependency is missing."""


class RateLimitedError(BaixaAquiError):
    """Raised when a user, group, or platform limit is hit."""
