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


class SpotifyNotConfiguredError(BaixaAquiError):
    """Raised when Spotify links are used without Spotify API credentials."""


class MusicMatchingError(BaixaAquiError):
    """Raised when a music platform cannot be matched to a downloadable source."""


class DeezerPreviewOnlyError(BaixaAquiError):
    """Raised when only a Deezer preview is available."""


class ShazamResolutionError(BaixaAquiError):
    """Raised when a Shazam track URL cannot be resolved."""


class RateLimitedError(BaixaAquiError):
    """Raised when a user, group, or platform limit is hit."""
