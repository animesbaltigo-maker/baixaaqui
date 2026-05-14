from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    default_language: str
    api_id: int
    api_hash: str
    bot_token: str
    app_dir: Path
    data_dir: Path
    download_dir: Path
    max_file_size: int
    request_timeout: int
    progress_interval: float
    send_backend: str
    bot_api_base_url: str
    bot_api_timeout_seconds: int
    fast_url_upload: bool
    turbo_mode: bool
    turbo_aria2_connections: int
    turbo_aria2_split: int
    turbo_aria2_min_split_size: str
    max_concurrent_jobs: int
    max_concurrent_inspections: int
    max_concurrent_downloads: int
    max_concurrent_uploads: int
    max_jobs_per_user: int
    social_download_enabled: bool
    ytdlp_format: str
    ytdlp_cookies_file: str
    ytdlp_cookies_from_browser: str
    ytdlp_platform_cookies: dict[str, str]
    ytdlp_cookies_max_age_hours: int
    ytdlp_extractors_args: str
    ytdlp_user_agent: str
    ytdlp_concurrent_fragments: int
    gallery_dl_config: str
    parallel_upload_enabled: bool
    parallel_upload_threshold: int
    parallel_upload_workers: int
    file_id_cache_enabled: bool
    file_id_cache_max_age_days: int
    google_drive_enabled: bool
    google_drive_public_only: bool
    admin_ids: set[int]
    public_base_url: str
    public_files_dir: Path
    link_server_enabled: bool
    local_link_storage_enabled: bool
    link_server_host: str
    link_server_port: int
    default_link_ttl_hours: int
    metadata_cache_ttl_seconds: int
    session_ttl_seconds: int
    temp_ttl_hours: int
    purge_media_on_start: bool
    rate_limit_window_seconds: int
    rate_limit_max_events: int
    allow_private_downloads: bool
    group_silent_mode: bool
    group_reply_on_error: bool
    group_allowed_chats: set[int]
    group_blocked_chats: set[int]
    group_whitelist_mode: bool
    group_auto_download: bool
    group_max_file_size: int
    group_rate_limit_window_seconds: int
    group_rate_limit_max_events: int
    pending_targets_limit: int
    job_timeout_seconds: int
    log_dir: Path
    log_level: str
    log_format: str
    bot_brand_name: str
    bot_support_username: str
    bot_footer_text: str
    required_channels: tuple[str, ...]
    required_channels_url: str

    @property
    def is_local_bot_api(self) -> bool:
        base = self.bot_api_base_url.lower()
        return "api.telegram.org" not in base


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _path_from_env(app_dir: Path, name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = app_dir / path
    return path.resolve()


def _bool_from_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_from_env(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    return max(value, minimum)


def _ids_from_env(name: str) -> set[int]:
    raw = os.getenv(name, "").strip()
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.add(int(chunk))
    return ids


def _strings_from_env(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default).strip()
    values = [chunk.strip() for chunk in raw.replace(";", ",").split(",") if chunk.strip()]
    return tuple(dict.fromkeys(values))


def load_settings() -> Settings:
    app_dir = Path(__file__).resolve().parent.parent
    load_dotenv(app_dir / ".env")

    api_id_raw = _required("API_ID")
    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise RuntimeError("API_ID must be a number") from exc

    max_file_size_mb = int(os.getenv("MAX_FILE_SIZE_MB", "4096"))
    request_timeout = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))
    progress_interval = float(os.getenv("PROGRESS_UPDATE_SECONDS", "8"))
    send_backend = os.getenv("SEND_BACKEND", "telethon").strip().lower()
    if send_backend not in {"auto", "telethon", "bot_api"}:
        send_backend = "auto"

    data_dir = _path_from_env(app_dir, "DATA_DIR", "data")
    download_dir = _path_from_env(app_dir, "DOWNLOAD_DIR", "downloads")
    public_files_dir = _path_from_env(app_dir, "PUBLIC_FILES_DIR", "public_files")
    log_dir = _path_from_env(app_dir, "LOG_DIR", "logs")

    data_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    public_files_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        default_language=os.getenv("DEFAULT_LANGUAGE", "pt").strip().lower() or "pt",
        api_id=api_id,
        api_hash=_required("API_HASH"),
        bot_token=_required("BOT_TOKEN"),
        app_dir=app_dir,
        data_dir=data_dir,
        download_dir=download_dir,
        max_file_size=max_file_size_mb * 1024 * 1024,
        request_timeout=request_timeout,
        progress_interval=progress_interval,
        send_backend=send_backend,
        bot_api_base_url=os.getenv("BOT_API_BASE_URL", "https://api.telegram.org").strip().rstrip("/"),
        bot_api_timeout_seconds=_int_from_env("BOT_API_TIMEOUT_SECONDS", 900),
        fast_url_upload=_bool_from_env("FAST_URL_UPLOAD", True),
        turbo_mode=_bool_from_env("TURBO_MODE", False),
        turbo_aria2_connections=_int_from_env("TURBO_ARIA2_CONNECTIONS", 16),
        turbo_aria2_split=_int_from_env("TURBO_ARIA2_SPLIT", 16),
        turbo_aria2_min_split_size=os.getenv("TURBO_ARIA2_MIN_SPLIT_SIZE", "1M").strip() or "1M",
        max_concurrent_jobs=_int_from_env("MAX_CONCURRENT_JOBS", 40),
        max_concurrent_inspections=_int_from_env("MAX_CONCURRENT_INSPECTIONS", 60),
        max_concurrent_downloads=_int_from_env("MAX_CONCURRENT_DOWNLOADS", 25),
        max_concurrent_uploads=_int_from_env("MAX_CONCURRENT_UPLOADS", 8),
        max_jobs_per_user=_int_from_env("MAX_JOBS_PER_USER", 3),
        social_download_enabled=_bool_from_env("SOCIAL_DOWNLOAD_ENABLED", False),
        ytdlp_format=os.getenv(
            "YTDLP_FORMAT",
            "best[ext=mp4][acodec!=none]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        ).strip()
        or "best[ext=mp4][acodec!=none]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        ytdlp_cookies_file=os.getenv("YTDLP_COOKIES_FILE", "").strip(),
        ytdlp_cookies_from_browser=os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip(),
        ytdlp_platform_cookies={
            "youtube": os.getenv("YTDLP_COOKIES_YOUTUBE", "").strip(),
            "instagram": os.getenv("YTDLP_COOKIES_INSTAGRAM", os.getenv("INSTAGRAM_COOKIES_FILE", "")).strip(),
            "tiktok": os.getenv("YTDLP_COOKIES_TIKTOK", os.getenv("TIKTOK_COOKIES_FILE", "")).strip(),
            "x": os.getenv("YTDLP_COOKIES_TWITTER", "").strip(),
            "twitter": os.getenv("YTDLP_COOKIES_TWITTER", "").strip(),
            "facebook": os.getenv("YTDLP_COOKIES_FACEBOOK", "").strip(),
        },
        ytdlp_cookies_max_age_hours=_int_from_env("YTDLP_COOKIES_MAX_AGE_HOURS", 72),
        ytdlp_extractors_args=os.getenv("YTDLP_EXTRACTOR_ARGS", "").strip(),
        ytdlp_user_agent=os.getenv(
            "YTDLP_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        ).strip(),
        ytdlp_concurrent_fragments=_int_from_env("YTDLP_CONCURRENT_FRAGMENTS", 4),
        gallery_dl_config=os.getenv("GALLERY_DL_CONFIG", "").strip(),
        parallel_upload_enabled=_bool_from_env("PARALLEL_UPLOAD_ENABLED", True),
        parallel_upload_threshold=_int_from_env("PARALLEL_UPLOAD_THRESHOLD_MB", 10) * 1024 * 1024,
        parallel_upload_workers=_int_from_env("PARALLEL_UPLOAD_WORKERS", 8),
        file_id_cache_enabled=_bool_from_env("FILE_ID_CACHE_ENABLED", True),
        file_id_cache_max_age_days=_int_from_env("FILE_ID_CACHE_MAX_AGE_DAYS", 30),
        google_drive_enabled=_bool_from_env("GOOGLE_DRIVE_ENABLED", True),
        google_drive_public_only=_bool_from_env("GOOGLE_DRIVE_PUBLIC_ONLY", True),
        admin_ids=_ids_from_env("ADMIN_IDS"),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8080/files").strip().rstrip("/"),
        public_files_dir=public_files_dir,
        link_server_enabled=_bool_from_env("LINK_SERVER_ENABLED", True),
        local_link_storage_enabled=_bool_from_env("LOCAL_LINK_STORAGE_ENABLED", True),
        link_server_host=os.getenv("LINK_SERVER_HOST", "0.0.0.0").strip(),
        link_server_port=_int_from_env("LINK_SERVER_PORT", 8080),
        default_link_ttl_hours=_int_from_env("DEFAULT_LINK_TTL_HOURS", 168),
        metadata_cache_ttl_seconds=_int_from_env("METADATA_CACHE_TTL_SECONDS", 1800),
        session_ttl_seconds=_int_from_env("SESSION_TTL_SECONDS", 900),
        temp_ttl_hours=_int_from_env("TEMP_TTL_HOURS", 6),
        purge_media_on_start=_bool_from_env("PURGE_MEDIA_ON_START", False),
        rate_limit_window_seconds=_int_from_env("RATE_LIMIT_WINDOW_SECONDS", 60),
        rate_limit_max_events=_int_from_env("RATE_LIMIT_MAX_EVENTS", 20),
        allow_private_downloads=_bool_from_env("ALLOW_PRIVATE_DOWNLOADS", False),
        group_silent_mode=_bool_from_env("GROUP_SILENT_MODE", True),
        group_reply_on_error=_bool_from_env("GROUP_REPLY_ON_ERROR", False),
        group_allowed_chats=_ids_from_env("GROUP_ALLOWED_CHATS"),
        group_blocked_chats=_ids_from_env("GROUP_BLOCKED_CHATS"),
        group_whitelist_mode=_bool_from_env("GROUP_WHITELIST_MODE", False),
        group_auto_download=_bool_from_env("GROUP_AUTO_DOWNLOAD", True),
        group_max_file_size=_int_from_env("GROUP_MAX_FILE_SIZE_MB", 50) * 1024 * 1024,
        group_rate_limit_window_seconds=_int_from_env("GROUP_RATE_LIMIT_WINDOW_SECONDS", 60),
        group_rate_limit_max_events=_int_from_env("GROUP_RATE_LIMIT_MAX_EVENTS", 6),
        pending_targets_limit=_int_from_env("PENDING_TARGETS_LIMIT", 10000),
        job_timeout_seconds=_int_from_env("JOB_TIMEOUT_SECONDS", 7200),
        log_dir=log_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        log_format=os.getenv("LOG_FORMAT", "text").strip().lower() or "text",
        bot_brand_name=os.getenv("BOT_BRAND_NAME", "Baixa Aqui").strip() or "Baixa Aqui",
        bot_support_username=os.getenv("BOT_SUPPORT_USERNAME", "").strip(),
        bot_footer_text=os.getenv("BOT_FOOTER_TEXT", "Baixa Aqui | @Baixa_aquibot").strip()
        or "Baixa Aqui | @Baixa_aquibot",
        required_channels=_strings_from_env("REQUIRED_CHANNELS", "@Baixa_Aqui,@QG_BALTIGO"),
        required_channels_url=os.getenv(
            "REQUIRED_CHANNEL_FOLDER_URL",
            "https://t.me/addlist/sCT9DE3EP2RmYTJh",
        ).strip(),
    )
