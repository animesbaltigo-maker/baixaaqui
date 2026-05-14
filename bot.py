from __future__ import annotations

import asyncio
import base64
import io
import hashlib
import ipaddress
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from zoneinfo import ZoneInfo

from aiohttp import web
from telethon import Button, TelegramClient, events, utils
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import UserNotParticipantError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import DocumentAttributeVideo

from urluploader.bot_api import BotApiClient
from urluploader.cleanup import cleanup_dir_contents, cleanup_old_dirs, directory_size
from urluploader.config import load_settings
from urluploader.conversion import ConversionError, convert_document, ensure_mp4_video
from urluploader.content import (
    ContentProfile,
    profile_for_direct,
    profile_for_social,
    profile_for_telegram,
)
from urluploader.database import PremiumStore
from urluploader.downloader import DownloadError, FileTooLargeError, RemoteDownloader
from urluploader.drive import DriveDownloadError, GoogleDriveDownloader, is_drive_url
from urluploader.diagnostics import render_diagnostics, run_diagnostics
from urluploader.errors import (
    BaixaAquiError,
    CookieRequiredError,
    DownloadTimeoutError,
    DrmProtectedError,
    MissingDependencyError,
    MusicMatchingError,
    PlatformBlockedError,
    SpotifyNotConfiguredError,
    UploadFailedError,
)
from urluploader.html_text import h, preserve
from urluploader.http_client import close_shared_http_session
from urluploader.image_host import ImageHostError, TelegraphImageHost
from urluploader.link_storage import LocalLinkStorage
from urluploader.media_probe import MediaProbe
from urluploader.models import DownloadResult, RemoteFileInfo, UploadMode
from urluploader.names import (
    contains_url,
    extract_url,
    is_audio_filename,
    is_social_url,
    is_video_filename,
    normalize_shared_url,
    sanitize_filename,
    unique_path,
)
from urluploader.parallel_upload import should_parallel_upload, upload_big_file_parallel, upload_workers_for_size
from urluploader.plans import ADMIN_PLAN, PLANS, Plan, normalize_plan_key, plan_catalog_text, plan_for_key
from urluploader.premium_i18n import normalize_language, tx
from urluploader.progress import ProgressEditor, human_size, render_progress
from urluploader.runtime import RateLimiter, SessionManager
from urluploader.logging_setup import setup_logging
from urluploader.security import is_public_http_url
from urluploader.social import MissingYtDlpError, SocialDownloadError, SocialDownloader, SocialInfo


settings = load_settings()
setup_logging(settings.log_dir, settings.log_level, settings.log_format)
logger = logging.getLogger("urlupload.bot")
client = TelegramClient(str(settings.data_dir / "urlupload_bot"), settings.api_id, settings.api_hash)
bot_api = BotApiClient(settings.bot_token, settings.bot_api_base_url, settings.bot_api_timeout_seconds)
store = PremiumStore(settings.data_dir / "premium.sqlite3")
sessions = SessionManager(settings.session_ttl_seconds)
rate_limiter = RateLimiter(settings.rate_limit_window_seconds, settings.rate_limit_max_events)
callback_rate_limiter = RateLimiter(window_seconds=5, max_events=10)
start_rate_limiter = RateLimiter(window_seconds=30, max_events=2)
link_storage = LocalLinkStorage(settings.public_files_dir, settings.public_base_url, settings.default_link_ttl_hours)

CONTROL_SECRET = os.getenv("CONTROL_SECRET", "")
CONTROL_AGENT_ENABLED = os.getenv("CONTROL_AGENT_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
CONTROL_BOT_ID = os.getenv("CONTROL_BOT_ID", "baixaaqui").strip() or "baixaaqui"
CONTROL_BOT_NAME = os.getenv("CONTROL_BOT_NAME", "BaixaAqui_Bot").strip() or CONTROL_BOT_ID
CONTROL_CHANNEL_USERNAME = os.getenv("CONTROL_CHANNEL_USERNAME", "@QG_BALTIGO").strip()
CONTROL_STATE: dict[str, object] = {"broadcast_running": False, "started_at": int(time.time())}
BALTIGO_UNIVERSE_WEBAPP_URL = os.getenv(
    "BALTIGO_UNIVERSE_WEBAPP_URL",
    "https://rough-double-remarkable-north.trycloudflare.com/miniapp/bots/index.html",
).strip()
BAIXAAQUI_START_BANNER_URL = os.getenv(
    "BAIXAAQUI_START_BANNER_URL",
    "https://photo.chelpbot.me/AgACAgEAAxkBa-wWUmn-ZxC0PcVCR7H0MzIQBWHNBuSmAALgC2sb2U34Rw9ZH6RnNX6PAQADAgADeQADOwQ/photo.jpg",
).strip()

image_host = TelegraphImageHost()
media_probe = MediaProbe()
remote_downloader = RemoteDownloader(
    settings.max_file_size,
    settings.request_timeout,
    allow_private_downloads=settings.allow_private_downloads,
    aria2_connections=settings.turbo_aria2_connections if settings.turbo_mode else 8,
    aria2_split=settings.turbo_aria2_split if settings.turbo_mode else 8,
    aria2_min_split_size=settings.turbo_aria2_min_split_size if settings.turbo_mode else "1M",
    proxy=settings.download_proxy,
)
drive_downloader = GoogleDriveDownloader(settings.max_file_size, settings.request_timeout)
social_downloader = SocialDownloader(
    settings.max_file_size,
    settings.ytdlp_format,
    cookies_file=settings.ytdlp_cookies_file,
    cookies_from_browser=settings.ytdlp_cookies_from_browser,
    extractor_args=settings.ytdlp_extractors_args,
    user_agent=settings.ytdlp_user_agent,
    platform_cookies=settings.ytdlp_platform_cookies,
    cookies_max_age_hours=settings.ytdlp_cookies_max_age_hours,
    concurrent_fragments=settings.ytdlp_concurrent_fragments,
    aria2_connections=settings.turbo_aria2_connections if settings.turbo_mode else 8,
    aria2_split=settings.turbo_aria2_split if settings.turbo_mode else 8,
    aria2_min_split_size=settings.turbo_aria2_min_split_size if settings.turbo_mode else "1M",
    gallery_config=settings.gallery_dl_config,
    proxy=settings.download_proxy,
    spotify_client_id=settings.spotify_client_id,
    spotify_client_secret=settings.spotify_client_secret,
    music_collection_limit=settings.music_collection_limit,
)

job_slots = asyncio.Semaphore(settings.max_concurrent_jobs)
inspect_slots = asyncio.Semaphore(settings.max_concurrent_inspections)
download_slots = asyncio.Semaphore(settings.max_concurrent_downloads)
upload_slots = asyncio.Semaphore(settings.max_concurrent_uploads)

active_tasks: dict[int, set[asyncio.Task[None]]] = {}
pending_targets: "OrderedDict[str, PendingTarget]" = OrderedDict()
maintenance_mode = False
BRANDING = settings.bot_footer_text
STARTED_AT = time.time()
group_rate_limiter = RateLimiter(settings.group_rate_limit_window_seconds, settings.group_rate_limit_max_events)
download_dedupe: dict[str, asyncio.Lock] = {}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
CONVERTIBLE_SUFFIXES = {".pdf", ".cbz", ".epub"}
IMAGE_LINK_CACHE_TTL_SECONDS = max(60, min(300, settings.metadata_cache_ttl_seconds))
LOCAL_IMAGE_LINK_TTL_SECONDS = 600
REQUIRED_CHANNEL_CACHE: dict[int, tuple[bool, float]] = {}
REQUIRED_CHANNEL_MEMBER_TTL = 300
REQUIRED_CHANNEL_NON_MEMBER_TTL = 60


@dataclass(frozen=True)
class PendingTarget:
    token: str
    user_id: int
    chat_id: int
    source: str
    message_id: int | None = None
    url: str | None = None
    filename: str | None = None
    caption: str | None = None
    thumb_path: str | None = None
    format_selector: str | None = None
    conversion: str | None = None
    direct_info: RemoteFileInfo | None = None
    social_info: SocialInfo | None = None
    created_at: float = 0

    def expired(self) -> bool:
        return self.created_at + settings.session_ttl_seconds < time.time()


def token() -> str:
    return uuid.uuid4().hex[:12]


def actor_id(event) -> int:
    return int(event.sender_id or event.chat_id)


def is_private_chat(event) -> bool:
    return bool(getattr(event, "is_private", False))


async def public_rate_guard(event, language: str) -> None:
    if rate_limiter.allow(actor_id(event)):
        return
    if is_private_chat(event):
        await answer(event, "rate_limited", language)
    raise events.StopPropagation


async def callback_guard(event) -> bool:
    await event.answer()
    if callback_rate_limiter.allow(actor_id(event)):
        return True
    await event.answer("Devagar! Aguarde um momento.", alert=False)
    return False


async def delete_private_command(event) -> None:
    if not is_private_chat(event):
        return
    try:
        await event.delete()
    except Exception:
        return


def user_url_dedupe_key(user_id: int, url: str | None) -> str | None:
    if not url:
        return None
    digest = hashlib.md5(normalize_shared_url(url).encode("utf-8")).hexdigest()[:16]
    return f"user-url:{user_id}:{digest}"


def is_youtube_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname in {"youtube.com", "m.youtube.com", "youtu.be"} or hostname.endswith(".youtube.com")


def is_youtube_music_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname == "music.youtube.com"


def _legacy_humanize_provider_error(language: str, exc: Exception) -> str:
    if isinstance(exc, CookieRequiredError):
        text = str(exc)
        if "[instagram-auth-required]" in text:
            return tx(language, "instagram_auth_required")
        if "[facebook-auth-required]" in text:
            return tx(language, "facebook_auth_required")
        if "[youtube-auth-required]" in text:
            return tx(language, "youtube_auth_required")
        if "[crunchyroll-auth-required]" in text:
            return tx(language, "crunchyroll_auth_required")
        return tx(language, "auth_required")
    if isinstance(exc, PlatformBlockedError):
        return tx(language, "platform_blocked")
    if isinstance(exc, DrmProtectedError):
        return tx(language, "drm_protected")
    if isinstance(exc, DownloadTimeoutError):
        return tx(language, "download_timeout")
    if isinstance(exc, UploadFailedError):
        return tx(language, "upload_failed")
    if isinstance(exc, SpotifyNotConfiguredError):
        return tx(language, "spotify_not_configured")
    if isinstance(exc, MissingDependencyError):
        return tx(language, "missing_music_dependency")
    if isinstance(exc, MusicMatchingError):
        return tx(language, "music_matching_failed", reason=h(str(exc)))
    text = str(exc).strip()
    lowered = text.lower()
    if "confirm youâ€™re not a bot" in lowered or "confirm you're not a bot" in lowered or "--cookies-from-browser" in lowered:
        return tx(language, "youtube_auth_required")
    if "facebook.com/login/" in lowered or "unsupported url:" in lowered and "facebook" in lowered:
        return tx(language, "facebook_auth_required")
    if "ffprobe and ffmpeg not found" in lowered or "--ffmpeg-location" in lowered:
        return tx(language, "ffmpeg_missing")
    return text


def is_image_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_SUFFIXES


def conversion_targets(filename: str) -> list[str]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".cbz":
        return ["pdf", "epub"]
    if suffix == ".epub":
        return ["cbz", "pdf"]
    if suffix == ".pdf":
        return ["epub", "cbz"]
    return []


def humanize_provider_error(language: str, exc: Exception) -> str:
    if isinstance(exc, CookieRequiredError):
        text = str(exc)
        if "[instagram-auth-required]" in text:
            return tx(language, "instagram_auth_required")
        if "[facebook-auth-required]" in text:
            return tx(language, "facebook_auth_required")
        if "[youtube-auth-required]" in text:
            return tx(language, "youtube_auth_required")
        if "[crunchyroll-auth-required]" in text:
            return tx(language, "crunchyroll_auth_required")
        return tx(language, "auth_required")
    if isinstance(exc, PlatformBlockedError):
        return tx(language, "platform_blocked")
    if isinstance(exc, DrmProtectedError):
        return tx(language, "drm_protected")
    if isinstance(exc, DownloadTimeoutError):
        return tx(language, "download_timeout")
    if isinstance(exc, UploadFailedError):
        return tx(language, "upload_failed")
    text = str(exc).strip()
    lowered = text.lower()
    if "[instagram-auth-required]" in lowered:
        return tx(language, "instagram_auth_required")
    if "[facebook-auth-required]" in lowered:
        return tx(language, "facebook_auth_required")
    if "[youtube-auth-required]" in lowered:
        return tx(language, "youtube_auth_required")
    if "[crunchyroll-auth-required]" in lowered:
        return tx(language, "crunchyroll_auth_required")
    if "[drm-protected]" in lowered or "known to use drm protection" in lowered:
        return tx(language, "drm_protected")
    if "confirm you're not a bot" in lowered or "--cookies-from-browser" in lowered:
        return tx(language, "youtube_auth_required")
    if "facebook.com/login/" in lowered or ("unsupported url:" in lowered and "facebook" in lowered):
        return tx(language, "facebook_auth_required")
    if "instagram.com/accounts/login" in lowered or "redirect to login page" in lowered and "instagram" in lowered:
        return tx(language, "instagram_auth_required")
    if "authenticated cookies needed" in lowered and "instagram" in lowered:
        return tx(language, "instagram_auth_required")
    if "ffprobe and ffmpeg not found" in lowered or "--ffmpeg-location" in lowered:
        return tx(language, "ffmpeg_missing")
    return text


def format_selector_for_quality(height: str) -> str:
    if height == "best":
        return (
            "best[ext=mp4][acodec!=none][vcodec!=none]/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/best[ext=mp4]/best"
        )
    return (
        f"best[height={height}][ext=mp4][acodec!=none][vcodec!=none]/"
        f"bestvideo[height={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height={height}]+bestaudio/"
        f"best[height={height}]"
    )


async def language_for(event) -> str:
    user_id = actor_id(event)
    sender = await event.get_sender()
    fallback = normalize_language(getattr(sender, "lang_code", None), settings.default_language)
    store.ensure_user(user_id, fallback)
    return store.get_language(user_id, fallback)


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


def user_plan(user_id: int) -> Plan:
    if is_admin(user_id):
        return ADMIN_PLAN
    return plan_for_key(store.get_plan(user_id))


def plan_limit_text(size: int | None) -> str:
    return "Ilimitado" if size is None else human_size(size)


def seconds_until_daily_reset() -> int:
    now = int(time.time())
    return 86400 - (now % 86400)


def format_reset_countdown(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h, {minutes}m, {secs}s"


def render_plan_status(user_id: int, name: str, plan_key: str | None = None) -> str:
    plan = user_plan(user_id) if plan_key is None else plan_for_key(plan_key)
    used = store.daily_usage_bytes(user_id)
    daily = "Ilimitado" if plan.daily_quota is None else f"{human_size(used)} / {human_size(plan.daily_quota)}"
    timeout = "Sem tempo limite" if plan.timeout_seconds is None else f"{plan.timeout_seconds // 60} minutos"
    cooldown = "Nao" if plan.cooldown_seconds <= 0 else "Sim"
    max_file = plan_limit_text(plan.max_file_size)
    lines = [
        f"<b>ID do utilizador:</b> <code>{user_id}</code>",
        f"<b>Nome:</b> {h(name)}",
        "",
        f"<b>ðŸ’  {plan.name}</b>",
        "",
    ]
    if plan.high_priority:
        lines.append("âœ“ Alta prioridade")
    return (
        "\n".join(
            lines
            + [
                f"âœ“ Carregar ficheiros de {max_file}",
                f"âœ“ Carregamento diario: {daily}",
                f"âœ“ Processo paralelo: {plan.parallel_jobs}",
                f"âœ“ {timeout}",
                f"âœ“ Intervalo de tempo: {cooldown}",
                "âœ“ Validade: Para sempre",
                "",
                f"<b>O limite sera redefinido em {format_reset_countdown(seconds_until_daily_reset())}</b>",
                "",
                f"<b>Preco mensal:</b> {plan.price}",
            ]
        )
    )


def plan_buttons() -> list[list[Button]]:
    return [
        [Button.inline("ðŸ’  Free", b"plan:view:free"), Button.inline("ðŸ’  Basic", b"plan:view:basico")],
        [Button.inline("ðŸ’  Standard", b"plan:view:standard"), Button.inline("ðŸ’  Pro", b"plan:view:pro")],
        [Button.inline("ðŸ’« Refresh", b"plan:refresh")],
    ]


def plan_detail_buttons(plan_key: str) -> list[list[Button]]:
    return [
        [Button.inline("ðŸ’° Opcoes de pagamento", f"plan:pay:{plan_key}".encode())],
        [Button.inline("â‡", b"plan:refresh")],
    ]


def plan_rejection(user_id: int, size: int | None = None) -> str | None:
    if is_admin(user_id):
        return None
    plan = user_plan(user_id)
    if active_count(user_id) >= plan.parallel_jobs:
        return f"Seu plano permite {plan.parallel_jobs} processo(s) paralelo(s). Aguarde a tarefa atual terminar."
    if size is not None and plan.max_file_size is not None and size > plan.max_file_size:
        return f"Seu plano aceita arquivos ate {human_size(plan.max_file_size)}. Este arquivo tem {human_size(size)}."
    if size is not None and plan.daily_quota is not None:
        used = store.daily_usage_bytes(user_id)
        if used + size > plan.daily_quota:
            return f"Seu limite diario e {human_size(plan.daily_quota)}. Hoje voce ja usou {human_size(used)}."
    if plan.cooldown_seconds > 0:
        last_job = store.last_job_created_at(user_id)
        if last_job:
            remaining = plan.cooldown_seconds - (int(time.time()) - last_job)
            if remaining > 0:
                return f"Seu plano gratuito tem intervalo entre tarefas. Aguarde {remaining}s."
    return None


async def estimated_target_size(target: PendingTarget) -> int | None:
    if target.direct_info and target.direct_info.size:
        return int(target.direct_info.size)
    if target.source == "telegram_file" and target.message_id:
        try:
            message = await client.get_messages(target.chat_id, ids=target.message_id)
            return message_size(message) if message else None
        except Exception:
            return None
    return None


def group_allowed(chat_id: int) -> bool:
    if not settings.group_auto_download or not settings.group_silent_mode:
        return settings.group_auto_download
    if chat_id in settings.group_blocked_chats:
        return False
    stored = store.group_status(chat_id)
    if stored == "blocked":
        return False
    if stored == "allowed":
        return True
    if settings.group_whitelist_mode:
        return chat_id in settings.group_allowed_chats
    return not settings.group_allowed_chats or chat_id in settings.group_allowed_chats


def remember(target: PendingTarget) -> PendingTarget:
    pending_targets[target.token] = target
    pending_targets.move_to_end(target.token)
    while len(pending_targets) > settings.pending_targets_limit:
        pending_targets.popitem(last=False)
    return target



def control_authorized(request) -> bool:
    return bool(CONTROL_SECRET) and request.headers.get("X-Control-Secret") == CONTROL_SECRET


def user_blocked(user_id: int) -> bool:
    with store.connection() as db:
        row = db.execute("SELECT is_blocked FROM users WHERE user_id=?", (int(user_id),)).fetchone()
    return bool(row and int(row["is_blocked"] or 0) == 1)


async def control_block_guard(event) -> None:
    user_id = actor_id(event)
    if is_admin(user_id) or not user_blocked(user_id):
        return
    await event.respond(
        "?? <b>Acesso bloqueado</b>\n\n"
        "Voc? foi bloqueado de usar este bot.\n"
        "Se acredita que isso foi um erro, entre em contato com o suporte.",
        parse_mode="html",
    )
    raise events.StopPropagation


def control_buttons(rows):
    built = []
    for row in rows or []:
        line = []
        for button in row:
            text = str(button.get("text") or "Bot?o")[:64]
            value = str(button.get("value") or button.get("url") or "")
            if value.startswith("t.me/"):
                value = "https://" + value
            if value.startswith(("http://", "https://", "tg://")):
                line.append(Button.url(text, value))
        if line:
            built.append(line)
    return built or None


def control_media(payload):
    media = payload.get("media") if isinstance(payload, dict) else None
    if not isinstance(media, dict) or not media.get("data"):
        return None
    try:
        raw = base64.b64decode(str(media.get("data") or ""))
    except Exception:
        return None
    file_obj = io.BytesIO(raw)
    file_obj.name = str(media.get("filename") or "broadcast.bin")
    return file_obj


async def control_send_one(user_id: int, payload: dict) -> tuple[bool, bool]:
    text = str(payload.get("text") or "").strip()
    buttons = control_buttons(payload.get("button_rows") if isinstance(payload.get("button_rows"), list) else [])
    media_file = control_media(payload)
    try:
        if media_file:
            sent = await client.send_file(user_id, media_file, caption=text or None, parse_mode="html", buttons=buttons)
        else:
            sent = await client.send_message(user_id, text or "??", parse_mode="html", buttons=buttons, link_preview=False)
        if payload.get("pin") and sent:
            try:
                await client.pin_message(user_id, sent, notify=False)
            except Exception:
                pass
        return True, False
    except FloodWaitError as exc:
        await asyncio.sleep(min(int(exc.seconds), 60))
        return False, False
    except Exception as exc:
        lowered = str(exc).lower()
        return False, any(part in lowered for part in ("blocked", "user is deactivated", "chat not found", "forbidden"))


async def control_broadcast_task(payload: dict) -> None:
    CONTROL_STATE["broadcast_running"] = True
    counters = {"sent": 0, "failed": 0, "removed": 0, "total": 0, "started_at": int(time.time())}
    CONTROL_STATE["last_broadcast"] = counters
    try:
        users = broadcast_user_ids()
        counters["total"] = len(users)
        for user_id in users:
            ok, should_remove = await control_send_one(int(user_id), payload)
            if ok:
                counters["sent"] += 1
            else:
                counters["failed"] += 1
                if should_remove:
                    broadcast_remove_user(int(user_id))
                    counters["removed"] += 1
            await asyncio.sleep(BROADCAST_DELAY)
    finally:
        counters["finished_at"] = int(time.time())
        CONTROL_STATE["broadcast_running"] = False


async def control_health(request):
    if not control_authorized(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        me = await client.get_me()
        username = getattr(me, "username", None) or CONTROL_BOT_NAME
    except Exception:
        username = CONTROL_BOT_NAME
    return web.json_response({"ok": True, "bot_id": CONTROL_BOT_ID, "name": CONTROL_BOT_NAME, "username": username, "online": True, "broadcast_running": bool(CONTROL_STATE.get("broadcast_running")), "uptime_seconds": int(time.time()) - int(CONTROL_STATE.get("started_at", time.time()))})


def control_premium_metrics() -> dict[str, object]:
    with store.connection() as db:
        rows = db.execute(
            """
            SELECT plan, COUNT(*) AS total
            FROM users
            WHERE is_blocked = 0
            GROUP BY plan
            ORDER BY total DESC, plan
            """
        ).fetchall()

    plans: list[dict[str, object]] = []
    active_total = 0
    total_records = 0
    for row in rows:
        code = normalize_plan_key(row["plan"])
        total = int(row["total"] or 0)
        is_premium = code != "free"
        if is_premium:
            active_total += total
        total_records += total
        plan = plan_for_key(code)
        plans.append({
            "code": code,
            "name": plan.name,
            "active": total if is_premium else 0,
            "total": total,
        })
    return {"available": True, "active_total": active_total, "total_records": total_records, "plans": plans}


def ensure_channel_metrics_table() -> None:
    with store.connection() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                username TEXT,
                title TEXT,
                subscribers INTEGER NOT NULL,
                captured_at INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_channel_snapshots_lookup
            ON channel_snapshots(channel_id, captured_at)
            """
        )


def control_channel_delta(db, channel_id: int, current_count: int, current_at: int, seconds: int) -> int | None:
    row = db.execute(
        """
        SELECT subscribers
        FROM channel_snapshots
        WHERE channel_id = ? AND captured_at <= ?
        ORDER BY captured_at DESC
        LIMIT 1
        """,
        (channel_id, current_at - seconds),
    ).fetchone()
    if row is None:
        row = db.execute(
            """
            SELECT subscribers
            FROM channel_snapshots
            WHERE channel_id = ?
            ORDER BY captured_at ASC
            LIMIT 1
            """,
            (channel_id,),
        ).fetchone()
    return current_count - int(row["subscribers"]) if row else None


async def control_channel_metrics() -> dict[str, object]:
    username = CONTROL_CHANNEL_USERNAME
    if not username:
        return {"available": False}
    try:
        entity = await client.get_entity(username)
        full = await client(GetFullChannelRequest(entity))
        subscribers = int(getattr(full.full_chat, "participants_count", 0) or 0)
        now = int(time.time())
        channel_id = int(getattr(entity, "id", 0) or 0)
        title = str(getattr(entity, "title", "") or username)
        public_username = str(getattr(entity, "username", "") or username.lstrip("@"))
        ensure_channel_metrics_table()
        with store.connection() as db:
            db.execute(
                """
                INSERT INTO channel_snapshots (channel_id, username, title, subscribers, captured_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (channel_id, public_username, title, subscribers, now),
            )
            deltas = {
                "24h": control_channel_delta(db, channel_id, subscribers, now, 86400),
                "7d": control_channel_delta(db, channel_id, subscribers, now, 604800),
                "30d": control_channel_delta(db, channel_id, subscribers, now, 2592000),
            }
        return {
            "available": True,
            "id": channel_id,
            "username": public_username,
            "title": title,
            "subscribers": subscribers,
            "deltas": deltas,
            "captured_at": now,
        }
    except Exception as exc:
        return {"available": False, "username": username, "error": str(exc)}


async def control_metrics(request):
    if not control_authorized(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    with store.connection() as db:
        active = int(db.execute("SELECT COUNT(*) FROM users WHERE is_blocked=0").fetchone()[0] or 0)
        banned = int(db.execute("SELECT COUNT(*) FROM users WHERE is_blocked=1").fetchone()[0] or 0)
    return web.json_response({"ok": True, "bot_id": CONTROL_BOT_ID, "name": CONTROL_BOT_NAME, "users_active": active, "users_inactive": 0, "users_banned": banned, "admins": len(settings.admin_ids), "premium": control_premium_metrics(), "channel": await control_channel_metrics(), "broadcast_running": bool(CONTROL_STATE.get("broadcast_running")), "last_broadcast": CONTROL_STATE.get("last_broadcast") or {}})


async def control_block(request):
    if not control_authorized(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    payload = await request.json()
    user_id = int(payload.get("user_id") or 0)
    if user_id <= 0:
        return web.json_response({"ok": False, "error": "invalid_user_id"}, status=400)
    now = int(time.time())
    with store.connection() as db:
        db.execute("INSERT INTO users(user_id, created_at, updated_at, is_blocked) VALUES(?, ?, ?, 1) ON CONFLICT(user_id) DO UPDATE SET is_blocked=1, updated_at=excluded.updated_at", (user_id, now, now))
    return web.json_response({"ok": True, "user_id": user_id, "blocked": True})


async def control_broadcast(request):
    if not control_authorized(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    payload = await request.json()
    if CONTROL_STATE.get("broadcast_running"):
        return web.json_response({"ok": False, "error": "broadcast_running"}, status=409)
    if not str(payload.get("text") or "").strip() and not isinstance(payload.get("media"), dict):
        return web.json_response({"ok": False, "error": "empty_broadcast"}, status=400)
    asyncio.create_task(control_broadcast_task(payload))
    return web.json_response({"ok": True, "started": True, "target_users": broadcast_total_users()})

def get_target(token_value: str, user_id: int) -> PendingTarget | None:
    target = pending_targets.get(token_value)
    if not target or target.user_id != user_id or target.expired():
        pending_targets.pop(token_value, None)
        return None
    pending_targets.move_to_end(token_value)
    return target


async def send_html(chat_id: int, text: str, *, buttons=None, reply_to: int | None = None, link_preview: bool = False):
    try:
        return await client.send_message(
            chat_id,
            text,
            parse_mode="html",
            buttons=buttons,
            reply_to=reply_to,
            link_preview=link_preview,
        )
    except TypeError:
        return await client.send_message(chat_id, text, parse_mode="html", buttons=buttons, link_preview=link_preview)


async def edit_html(message, text: str, *, buttons=None, link_preview: bool = False) -> None:
    try:
        await message.edit(text, parse_mode="html", buttons=buttons, link_preview=link_preview)
    except FloodWaitError as exc:
        await asyncio.sleep(min(exc.seconds, 10))
    except Exception:
        return


async def answer(event, key: str, language: str, *, buttons=None, **values):
    return await event.respond(tx(language, key, **values), parse_mode="html", buttons=buttons, link_preview=False)


def main_menu(language: str):
    return [
        [Button.inline(tx(language, "btn_menu_download"), b"menu:download"), Button.inline(tx(language, "btn_menu_upload"), b"menu:upload")],
        [Button.inline(tx(language, "btn_menu_tools"), b"menu:tools"), Button.inline(tx(language, "btn_menu_links"), b"menu:links")],
        [Button.inline(tx(language, "btn_menu_tasks"), b"menu:tasks"), Button.inline(tx(language, "btn_menu_settings"), b"menu:settings")],
        [Button.inline(tx(language, "btn_menu_premium"), b"menu:premium")],
        [Button.inline(tx(language, "btn_menu_thumb"), b"menu:thumb"), Button.inline(tx(language, "btn_menu_help"), b"menu:help")],
        [Button.url("⚔️ Universo Baltigo", BALTIGO_UNIVERSE_WEBAPP_URL)],
    ]


def settings_buttons(language: str):
    return [
        [Button.inline(tx(language, "btn_language"), b"settings:language"), Button.inline(tx(language, "btn_cover_settings"), b"settings:thumb")],
        [Button.inline(tx(language, "btn_back"), b"menu:home")],
    ]


def language_buttons(language: str):
    return [
        [Button.inline(tx(language, "btn_lang_pt"), b"lang:pt")],
        [Button.inline(tx(language, "btn_lang_en"), b"lang:en")],
        [Button.inline(tx(language, "btn_lang_es"), b"lang:es")],
        [Button.inline(tx(language, "btn_back"), b"settings:home")],
    ]


def back_buttons(language: str):
    return [[Button.inline(tx(language, "btn_back"), b"menu:home")]]


def thumb_menu_buttons(language: str):
    return [
        [Button.inline(tx(language, "btn_set_thumb"), b"thumb:set")],
        [Button.inline(tx(language, "btn_remove_thumb"), b"thumb:remove")],
        [Button.inline(tx(language, "btn_back"), b"menu:home")],
    ]


def recent_link_buttons(language: str, links: list[dict[str, object]]):
    rows = [[Button.url(str(item["filename"])[:40], str(item["public_url"]))] for item in links if is_public_button_url(str(item["public_url"]))]
    rows.append([Button.inline(tx(language, "btn_back"), b"menu:home")])
    return rows


def social_buttons(language: str, target: PendingTarget, profile: ContentProfile):
    data = target.token
    rows = []
    if profile.kind == "image":
        rows.append([Button.inline(tx(language, "btn_send_photo"), f"social:photo:{data}".encode()), Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
        rows.append([Button.inline(tx(language, "btn_generate_link"), f"social:link:{data}".encode())])
    elif profile.kind == "audio":
        rows.append([Button.inline(tx(language, "btn_audio_send"), f"social:audiofile:{data}".encode()), Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
    elif profile.kind == "album":
        rows.append([Button.inline(tx(language, "btn_download_media"), f"social:download:{data}".encode()), Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
    else:
        if target.url and is_youtube_music_url(target.url):
            rows.append([Button.inline(tx(language, "btn_audio"), f"social:audio:{data}".encode()), Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
            rows.append([Button.inline(tx(language, "btn_download_media"), f"social:video:{data}".encode())])
        else:
            rows.append([Button.inline(tx(language, "btn_download_media"), f"social:video:{data}".encode()), Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
        if profile.can_extract_audio and not (target.url and is_youtube_music_url(target.url)):
            rows.append([Button.inline(tx(language, "btn_audio"), f"social:audio:{data}".encode())])
    rows.append([Button.inline(tx(language, "btn_caption"), f"target:caption:{data}".encode()), Button.inline(tx(language, "btn_rename"), f"target:rename:{data}".encode())])
    rows.append([Button.inline(tx(language, "btn_cancel"), f"target:cancel:{data}".encode())])
    return rows


def quality_buttons(language: str, target: PendingTarget):
    data = target.token
    rows = []
    qualities = list(target.social_info.qualities if target.social_info else ())
    for first, second in zip(qualities[0::2], qualities[1::2]):
        rows.append(
            [
                Button.inline(f"ðŸŽ¬ {first}p", f"quality:{first}:{data}".encode()),
                Button.inline(f"ðŸŽ¬ {second}p", f"quality:{second}:{data}".encode()),
            ]
        )
    if len(qualities) % 2:
        rows.append([Button.inline(f"ðŸŽ¬ {qualities[-1]}p", f"quality:{qualities[-1]}:{data}".encode())])
    rows.append([Button.inline(tx(language, "btn_best_quality"), f"quality:best:{data}".encode())])
    rows.append([Button.inline(tx(language, "btn_cancel"), f"target:cancel:{data}".encode())])
    return rows


def main_menu(language: str):
    return [
        [Button.inline(tx(language, "btn_menu_download"), b"menu:download"), Button.inline(tx(language, "btn_menu_settings"), b"menu:settings")],
        [Button.inline(tx(language, "btn_menu_tasks"), b"menu:tasks"), Button.inline(tx(language, "btn_menu_help"), b"menu:help")],
        [Button.url(tx(language, "btn_menu_universe"), BALTIGO_UNIVERSE_WEBAPP_URL)],
    ]


def social_buttons(language: str, target: PendingTarget, profile: ContentProfile):
    data = target.token
    rows = []
    if profile.kind == "image":
        rows.append([Button.inline(tx(language, "btn_send_photo"), f"social:photo:{data}".encode())])
        if local_image_link_available():
            rows.append([Button.inline(tx(language, "btn_generate_link"), f"social:link:{data}".encode())])
    elif profile.kind == "audio":
        rows.append([Button.inline(tx(language, "btn_audio_send"), f"social:audiofile:{data}".encode())])
        rows.append([Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
        rows.append([Button.inline(tx(language, "btn_caption"), f"target:caption:{data}".encode())])
    elif profile.kind == "album":
        rows.append([Button.inline(tx(language, "btn_download_media"), f"social:download:{data}".encode())])
        rows.append([Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
        rows.append([Button.inline(tx(language, "btn_caption"), f"target:caption:{data}".encode()), Button.inline(tx(language, "btn_rename"), f"target:rename:{data}".encode())])
    else:
        if target.url and is_youtube_music_url(target.url):
            rows.append([Button.inline(tx(language, "btn_audio_send"), f"social:audio:{data}".encode())])
            rows.append([Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
            rows.append([Button.inline(tx(language, "btn_caption"), f"target:caption:{data}".encode())])
        else:
            first_row = [Button.inline(tx(language, "btn_download_media"), f"social:video:{data}".encode())]
            if profile.can_extract_audio:
                first_row.append(Button.inline(tx(language, "btn_audio"), f"social:audio:{data}".encode()))
            rows.append(first_row)
            rows.append([Button.inline(tx(language, "btn_file"), f"social:file:{data}".encode())])
            rows.append([Button.inline(tx(language, "btn_caption"), f"target:caption:{data}".encode()), Button.inline(tx(language, "btn_rename"), f"target:rename:{data}".encode())])
    rows.append([Button.inline(tx(language, "btn_cancel"), f"target:cancel:{data}".encode())])
    return rows


def direct_buttons(language: str, target: PendingTarget, profile: ContentProfile):
    data = target.token
    rows = []
    if profile.can_send_photo:
        rows.append([Button.inline(tx(language, "btn_send_photo"), f"direct:photo:{data}".encode())])
        rows.append([Button.inline(tx(language, "btn_file"), f"direct:file:{data}".encode())])
        if local_image_link_available():
            rows.append([Button.inline(tx(language, "btn_generate_link"), f"direct:link:{data}".encode())])
    elif profile.can_send_video:
        rows.append([Button.inline(tx(language, "btn_video"), f"direct:video:{data}".encode()), Button.inline(tx(language, "btn_file"), f"direct:file:{data}".encode())])
    elif profile.can_send_audio:
        rows.append([Button.inline(tx(language, "btn_audio_send"), f"direct:audio:{data}".encode()), Button.inline(tx(language, "btn_file"), f"direct:file:{data}".encode())])
    else:
        rows.append([Button.inline(tx(language, "btn_file"), f"direct:file:{data}".encode())])
    if profile.can_set_thumb:
        rows.append([Button.inline(tx(language, "btn_thumb"), f"target:thumb:{data}".encode())])
    rows.append([Button.inline(tx(language, "btn_caption"), f"target:caption:{data}".encode()), Button.inline(tx(language, "btn_rename"), f"target:rename:{data}".encode())])
    rows.append([Button.inline(tx(language, "btn_cancel"), f"target:cancel:{data}".encode())])
    return rows


def file_buttons(language: str, target: PendingTarget, profile: ContentProfile):
    data = target.token
    rows = [
        [Button.inline(tx(language, "btn_rename"), f"target:rename:{data}".encode()), Button.inline(tx(language, "btn_caption"), f"target:caption:{data}".encode())],
    ]
    if profile.can_send_photo:
        rows.append([Button.inline(tx(language, "btn_send_photo"), f"file:photo:{data}".encode()), Button.inline(tx(language, "btn_file"), f"file:file:{data}".encode())])
        if local_image_link_available():
            rows.append([Button.inline(tx(language, "btn_generate_link"), f"file:link:{data}".encode())])
    elif profile.can_send_video:
        rows.append([Button.inline(tx(language, "btn_video"), f"file:video:{data}".encode()), Button.inline(tx(language, "btn_file"), f"file:file:{data}".encode())])
    elif profile.can_send_audio:
        rows.append([Button.inline(tx(language, "btn_audio_send"), f"file:audio:{data}".encode()), Button.inline(tx(language, "btn_file"), f"file:file:{data}".encode())])
    else:
        rows.append([Button.inline(tx(language, "btn_file"), f"file:file:{data}".encode())])
    if profile.can_set_thumb:
        rows.append([Button.inline(tx(language, "btn_thumb"), f"target:thumb:{data}".encode())])
    for target_format in conversion_targets(target.filename or ""):
        key = f"btn_convert_{target_format}"
        rows.append([Button.inline(tx(language, key), f"file:{target_format}:{data}".encode())])
    rows.append([Button.inline(tx(language, "btn_cancel"), f"target:cancel:{data}".encode())])
    return rows


def link_buttons(language: str, link_id: str, public_url: str):
    rows = []
    if is_public_button_url(public_url):
        rows.append([Button.url(tx(language, "btn_open"), public_url)])
    rows.append([Button.inline(tx(language, "btn_delete_link"), f"link:delete:{link_id}".encode())])
    return rows


def cancel_button(language: str, job_id: str):
    return [[Button.inline(tx(language, "btn_cancel"), f"job:cancel:{job_id}".encode())]]


def cancel_target_button(language: str, target_token: str):
    return [[Button.inline(tx(language, "btn_cancel"), f"target:cancel:{target_token}".encode())]]


def is_image_message(message) -> bool:
    if getattr(message, "photo", None):
        return True
    mime = getattr(getattr(message, "file", None), "mime_type", None)
    return bool(mime and str(mime).startswith("image/"))


def is_media_message(message) -> bool:
    return bool(getattr(message, "media", None))


def message_filename(message) -> str:
    file_info = getattr(message, "file", None)
    name = sanitize_filename(getattr(file_info, "name", None))
    if name:
        return name
    ext = getattr(file_info, "ext", None)
    if not ext:
        ext = ".jpg" if is_image_message(message) else ".bin"
    return sanitize_filename(f"arquivo{ext}") or "arquivo.bin"


def message_size(message) -> int | None:
    size = getattr(getattr(message, "file", None), "size", None)
    return int(size) if size else None


def detect_kind(language: str, filename: str, mime: str | None = None) -> str:
    mime = (mime or mimetypes.guess_type(filename)[0] or "").lower()
    if mime.startswith("video/") or is_video_filename(filename):
        return tx(language, "kind_video")
    if mime.startswith("audio/") or is_audio_filename(filename):
        return tx(language, "kind_audio")
    if mime.startswith("image/"):
        return tx(language, "kind_image")
    return tx(language, "kind_file")


def profile_for_target(target: PendingTarget) -> ContentProfile:
    if target.social_info:
        return profile_for_social(target.social_info)
    if target.direct_info:
        return profile_for_direct(target.direct_info)
    filename = target.filename or "arquivo.bin"
    mime = mimetypes.guess_type(filename)[0]
    return profile_for_telegram(filename, mime, is_image_message=is_image_filename(filename))


def format_duration(language: str, seconds: float | None) -> str:
    if not seconds:
        return tx(language, "unknown_value")
    total = int(seconds)
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def language_label(language: str) -> str:
    return {
        "pt": "PortuguÃªs",
        "en": "English",
        "es": "EspaÃ±ol",
    }.get(normalize_language(language), language.upper())


def is_public_button_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "0.0.0.0", "seu-dominio.com", "example.com"} or hostname.endswith(".local"):
        return False
    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        return "." in hostname
    return not (host_ip.is_private or host_ip.is_loopback or host_ip.is_unspecified or host_ip.is_reserved or host_ip.is_link_local)


def describe_target(language: str, target: PendingTarget) -> str:
    if target.source.startswith("social") and target.social_info:
        return social_card(language, target.social_info)
    if target.source.startswith("direct") and target.direct_info:
        return direct_card(language, target.direct_info)
    filename = target.filename or tx(language, "unknown_title")
    return tx(
        language,
        "file_card",
        filename=filename,
        size=tx(language, "unknown_value"),
        kind=detect_kind(language, filename),
    )


def display_size(language: str, size: int | float | None) -> str:
    return human_size(size) if size is not None else tx(language, "unknown_value")


def job_status_label(language: str, status: str) -> str:
    mapping = {
        "queued": tx(language, "job_status_queued"),
        "running": tx(language, "job_status_running"),
        "done": tx(language, "job_status_done"),
        "failed": tx(language, "job_status_failed"),
        "cancelled": tx(language, "job_status_cancelled"),
    }
    return mapping.get(status, status)


def task_panel(language: str, user_id: int) -> str:
    jobs = store.recent_jobs(user_id)
    if not jobs:
        return tx(language, "empty_tasks")
    lines = [tx(language, "tasks_title")]
    for item in jobs:
        title = str(item.get("title") or item.get("kind") or tx(language, "unknown_title"))
        status = job_status_label(language, str(item.get("status") or "queued"))
        lines.append(tx(language, "task_item", title=title[:48], status=status))
    return "\n".join(lines)


def _social_kind(language: str, media_type: str) -> str:
    mapping = {
        "vÃ­deo": "kind_video",
        "video": "kind_video",
        "Ã¡udio": "kind_audio",
        "audio": "kind_audio",
        "imagem": "kind_image",
        "image": "kind_image",
        "arquivo": "kind_file",
        "file": "kind_file",
        "Ã¡lbum": "kind_album",
        "album": "kind_album",
    }
    key = mapping.get(media_type.lower())
    return tx(language, key) if key else media_type


def format_progress(current: int, total: int | None, started_at: float) -> str:
    return render_progress("Download", current, total, started_at)


def cleanup_targets() -> None:
    for key, target in list(pending_targets.items()):
        if target.expired():
            pending_targets.pop(key, None)


def active_count(user_id: int) -> int:
    tasks = active_tasks.setdefault(user_id, set())
    done = {task for task in tasks if task.done()}
    tasks.difference_update(done)
    return len(tasks)


def required_channel_cache_get(user_id: int) -> bool | None:
    item = REQUIRED_CHANNEL_CACHE.get(user_id)
    if not item:
        return None
    allowed, expires_at = item
    if time.time() >= expires_at:
        REQUIRED_CHANNEL_CACHE.pop(user_id, None)
        return None
    return allowed


def required_channel_cache_set(user_id: int, allowed: bool) -> None:
    ttl = REQUIRED_CHANNEL_MEMBER_TTL if allowed else REQUIRED_CHANNEL_NON_MEMBER_TTL
    REQUIRED_CHANNEL_CACHE[user_id] = (allowed, time.time() + ttl)


async def missing_required_channels(user_id: int) -> list[str]:
    if not settings.required_channels:
        return []

    cached = required_channel_cache_get(user_id)
    if cached is True:
        return []

    missing: list[str] = []
    for channel in settings.required_channels:
        try:
            await client.get_permissions(channel, user_id)
        except UserNotParticipantError:
            missing.append(channel)
        except Exception:
            logger.exception("required_channel_check_failed channel=%s user_id=%s", channel, user_id)
            missing.append(channel)

    required_channel_cache_set(user_id, not missing)
    return missing


async def is_member_of_required_channels(user_id: int) -> bool:
    return not await missing_required_channels(user_id)


def required_channel_gate_text(name: str) -> str:
    return (
        f"🛑 <b>Calma aí, {h(name or 'amigo')}</b>\n\n"
        "Para usar este comando, você precisa entrar nos canais oficiais primeiro.\n\n"
        "É por lá que eu aviso novidades, recursos e atualizações importantes.\n\n"
        "Entre nos canais abaixo e envie o comando novamente."
    )


REQUIRED_CHANNEL_LABELS = {
    "@Baixa_Aqui": "📥 Baixa Aqui",
    "@QG_BALTIGO": "🏠 QG Baltigo",
}


def required_channel_url(channel: str) -> str:
    channel = str(channel or "").strip()
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}"
    if channel.startswith(("http://", "https://")):
        return channel
    return f"https://t.me/{channel.lstrip('@')}"


def required_channel_label(channel: str) -> str:
    channel = str(channel or "").strip()
    return REQUIRED_CHANNEL_LABELS.get(
        channel,
        f"📢 {channel.lstrip('@').replace('_', ' ').replace('-', ' ').title() or 'Canal'}",
    )


def required_channel_buttons(channels: list[str]) -> list[list[Button]]:
    buttons = [
        Button.url(required_channel_label(channel), required_channel_url(channel))
        for channel in channels
    ]
    return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]


def required_channel_gate_text(language: str, channels: list[str]) -> str:
    channel_lines = "\n".join(f"• {h(required_channel_label(channel))}" for channel in channels)
    return tx(language, "channels_required", channels=channel_lines)


def required_channel_buttons(language: str, channels: list[str]) -> list[list[Button]]:
    rows = [
        [Button.url(f"➕ Entrar em {required_channel_label(channel)}", required_channel_url(channel))]
        for channel in channels
    ]
    rows.append([Button.inline(tx(language, "check_channels_btn"), b"check_channels")])
    return rows


async def ensure_required_channels(event) -> bool:
    user_id = actor_id(event)
    if is_admin(user_id):
        return True
    missing_channels = await missing_required_channels(user_id)
    if not missing_channels:
        return True

    language = await language_for(event)
    await send_html(
        event.chat_id,
        required_channel_gate_text(language, missing_channels),
        buttons=required_channel_buttons(language, missing_channels),
    )
    return False


def cancel_tasks_for_target(target_token: str) -> int:
    cancelled = 0
    for tasks in active_tasks.values():
        for task in list(tasks):
            if getattr(task, "target_token", None) == target_token:
                task.cancel()
                cancelled += 1
    return cancelled


@client.on(events.NewMessage(incoming=True))
async def control_block_guard_handler(event) -> None:
    await control_block_guard(event)


@client.on(events.NewMessage(pattern=r"(?i)^/"))
async def required_channel_command_guard(event) -> None:
    if re.match(r"(?i)^/(start|iniciar)(?:@\w+)?$", event.raw_text or "") and not start_rate_limiter.allow(actor_id(event)):
        raise events.StopPropagation
    if not await ensure_required_channels(event):
        raise events.StopPropagation


@client.on(events.NewMessage(pattern=r"(?i)^/(start|iniciar)(?:@\w+)?$"))
async def start_handler(event) -> None:
    language = await language_for(event)
    await public_rate_guard(event, language)
    if not await ensure_required_channels(event):
        return
    sender = await event.get_sender()
    name = getattr(sender, "first_name", None) or "tudo bem"
    await client.send_file(
        event.chat_id,
        BAIXAAQUI_START_BANNER_URL,
        caption=tx(language, "welcome", name=name),
        parse_mode="html",
        buttons=main_menu(language),
    )
    await delete_private_command(event)


@client.on(events.NewMessage(pattern=r"(?i)^/(ajuda|help)(?:@\w+)?$"))
async def help_handler(event) -> None:
    language = await language_for(event)
    await public_rate_guard(event, language)
    if not await ensure_required_channels(event):
        return
    await answer(event, "help", language, buttons=main_menu(language))
    await delete_private_command(event)


@client.on(events.NewMessage(pattern=r"(?i)^/(mp3|audio)(?:@\w+)?(?:\s+(.+))?$"))
async def mp3_handler(event) -> None:
    language = await language_for(event)
    await public_rate_guard(event, language)
    if not await ensure_required_channels(event):
        return
    if not settings.social_download_enabled:
        await answer(event, "social_disabled", language)
        return
    raw = event.pattern_match.group(2) or ""
    url = extract_url(raw)
    if not url:
        await answer(event, "mp3_usage", language)
        return
    url = normalize_shared_url(url)
    if not is_social_url(url):
        await answer(event, "direct_link_required", language)
        return

    status = await answer(event, "analyzing_link", language)
    try:
        info = await inspect_social(url)
        target = remember(
            PendingTarget(
                token=token(),
                user_id=actor_id(event),
                chat_id=int(event.chat_id),
                source=f"social:{info.media_type}",
                url=url,
                filename=info.title,
                social_info=info,
                created_at=time.time(),
            )
        )
        await schedule_job(event, target, mode="audio", status=status)
    except Exception as exc:
        logger.warning("mp3_command_failed chat_id=%s url=%s reason=%s", event.chat_id, url, exc)
        await edit_html(status, tx(language, "error_human", reason=humanize_provider_error(language, exc)))


@client.on(events.NewMessage(pattern=r"(?i)^/(config|settings)(?:@\w+)?$"))
async def settings_handler(event) -> None:
    language = await language_for(event)
    await public_rate_guard(event, language)
    if not await ensure_required_channels(event):
        return
    thumb = store.get_thumb(actor_id(event))
    await answer(
        event,
        "settings",
        language,
        buttons=settings_buttons(language),
        lang_name=language_label(language),
        thumb=tx(language, "state_on") if thumb else tx(language, "state_off"),
    )
    await delete_private_command(event)


@client.on(events.NewMessage(pattern=r"(?i)^/(cancelar|cancel|limpar)(?:@\w+)?$"))
async def cancel_handler(event) -> None:
    language = await language_for(event)
    await public_rate_guard(event, language)
    if not await ensure_required_channels(event):
        return
    user_id = actor_id(event)
    had_session = user_id in sessions._sessions
    sessions.clear(user_id)
    keys_to_remove = [key for key, value in pending_targets.items() if value.user_id == user_id]
    for key in keys_to_remove:
        pending_targets.pop(key, None)
    for task in active_tasks.get(user_id, set()):
        task.cancel()
    active_tasks.pop(user_id, None)
    await answer(event, "context_cleaned" if had_session else "nothing_to_cancel", language)
    await delete_private_command(event)


@client.on(events.NewMessage(pattern=r"(?i)^/(status|minhastarefas)(?:@\w+)?$"))
async def tasks_handler(event) -> None:
    language = await language_for(event)
    await public_rate_guard(event, language)
    if not await ensure_required_channels(event):
        return
    await send_html(event.chat_id, task_panel(language, actor_id(event)), buttons=back_buttons(language))


@client.on(events.NewMessage(pattern=r"(?i)^/(planos|plans|premium)(?:@\w+)?$"))
async def plans_handler(event) -> None:
    language = await language_for(event)
    await public_rate_guard(event, language)
    if not await ensure_required_channels(event):
        return
    await send_html(event.chat_id, plan_catalog_text(), buttons=back_buttons(language))


@client.on(events.NewMessage(pattern=r"(?i)^/(plano|myplan)(?:@\w+)?$"))
async def my_plan_handler(event) -> None:
    language = await language_for(event)
    await public_rate_guard(event, language)
    if not await ensure_required_channels(event):
        return
    sender = await event.get_sender()
    name = getattr(sender, "first_name", None) or "Usuario"
    await send_html(event.chat_id, render_plan_status(actor_id(event), name), buttons=plan_buttons())


@client.on(events.NewMessage(pattern=r"(?i)^/(liberar|release|setplan)(?:@\w+)?\s+(\d+)\s+([a-zA-Z0-9_-]+)"))
async def release_plan_handler(event) -> None:
    language = await language_for(event)
    admin_id = actor_id(event)
    if not is_admin(admin_id):
        await answer(event, "not_admin", language)
        return
    target_user_id = int(event.pattern_match.group(2))
    requested = event.pattern_match.group(3)
    if requested.lower() not in PLANS:
        await send_html(event.chat_id, "Plano invalido. Use: free, basico, standard ou pro.")
        return
    plan_key = normalize_plan_key(requested)
    store.set_plan(target_user_id, plan_key, admin_id)
    plan = plan_for_key(plan_key)
    await send_html(event.chat_id, f"<b>Plano liberado</b>\nUsuario: <code>{target_user_id}</code>\nPlano: <code>{plan.name}</code>")




BROADCAST_SESSIONS: dict[int, dict[str, object]] = {}
BROADCAST_ALERTS: dict[str, str] = {}
BROADCAST_RUNNING = False
BROADCAST_CONTROL: dict[str, object] = {"paused": False, "cancelled": False}
BROADCAST_WORKERS = 3
BROADCAST_DELAY = 0.12
BROADCAST_STATUS_EVERY = 50
BROADCAST_STATUS_INTERVAL = 2.0
BROADCAST_PIN_WARN_USERS = 20
BROADCAST_PIN_LIMIT = 100
BROADCAST_TEMPLATE_LIMIT = 12
BROADCAST_TEMPLATES_PATH = settings.data_dir / "broadcast_templates.json"

try:
    BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    BRASILIA_TZ = timezone(timedelta(hours=-3), "America/Sao_Paulo")


def broadcast_blank() -> dict[str, object]:
    return {
        "mode": None,
        "target_user_id": None,
        "text": "",
        "media_chat_id": None,
        "media_message_id": None,
        "button_rows": [],
        "pin": False,
        "schedule_at": None,
        "confirm_pin": False,
        "step": "",
        "panel_chat_id": None,
        "panel_message_id": None,
    }


def broadcast_data(user_id: int) -> dict[str, object]:
    data = BROADCAST_SESSIONS.get(user_id)
    if not isinstance(data, dict):
        data = broadcast_blank()
        BROADCAST_SESSIONS[user_id] = data
    return data


def broadcast_yes_no(value: bool) -> str:
    return "Sim" if value else "Não"


def broadcast_mode_label(mode: object) -> str:
    if mode == "all":
        return "Todos os usuários"
    if mode == "single":
        return "Usuário específico"
    return "Não definido"


def broadcast_user_ids() -> list[int]:
    with store.connection() as db:
        rows = db.execute("SELECT user_id FROM users WHERE is_blocked=0 ORDER BY user_id").fetchall()
    return [int(row["user_id"]) for row in rows]


def broadcast_total_users() -> int:
    with store.connection() as db:
        row = db.execute("SELECT COUNT(*) FROM users WHERE is_blocked=0").fetchone()
    return int(row[0] or 0)


def broadcast_remove_user(user_id: int) -> None:
    with store.connection() as db:
        db.execute("UPDATE users SET is_blocked=1, updated_at=? WHERE user_id=?", (int(time.time()), int(user_id)))


def broadcast_button_rows_data(data: dict[str, object]) -> list[list[dict[str, str]]]:
    rows = data.get("button_rows")
    return rows if isinstance(rows, list) else []  # type: ignore[return-value]


def broadcast_button_count(data: dict[str, object]) -> int:
    return sum(len(row) for row in broadcast_button_rows_data(data))


def broadcast_ready(data: dict[str, object]) -> bool:
    return bool(str(data.get("text") or "").strip() or data.get("media_message_id"))


def broadcast_schedule_label(data: dict[str, object]) -> str:
    value = data.get("schedule_at")
    if not value:
        return "Não"
    try:
        return datetime.fromtimestamp(float(value), BRASILIA_TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return "Sim"


def broadcast_parse_when(raw: str) -> float | None:
    text = raw.strip().lower()
    now = datetime.now(BRASILIA_TZ)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt.timestamp()
    match = re.fullmatch("(hoje|amanh[\u00e3a?])\\s+(\\d{1,2}):(\\d{2})", text)
    if match:
        hour, minute = int(match.group(2)), int(match.group(3))
        if hour > 23 or minute > 59:
            return None
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if match.group(1).startswith("amanh"):
            dt += timedelta(days=1)
        if dt <= now:
            return None
        return dt.timestamp()
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=BRASILIA_TZ)
        except ValueError:
            continue
        if dt > now:
            return dt.timestamp()
    return None

def broadcast_parse_buttons(raw: str) -> tuple[list[list[dict[str, str]]], str | None]:
    rows: list[list[dict[str, str]]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        row: list[dict[str, str]] = []
        for part in re.split(r"\s+&&\s+", line):
            match = re.match(r"^(.+?)\s+-\s+(.+)$", part.strip())
            if not match:
                return [], "Use o formato: Texto do botão - link"
            label = match.group(1).strip()
            value = match.group(2).strip()
            if not label or len(label) > 64:
                return [], "O texto de cada botão precisa ter até 64 caracteres."
            lowered = value.lower()
            if lowered.startswith(("popup:", "alert:")):
                payload = value.split(":", 1)[1].strip()
                if not payload:
                    return [], "O popup precisa ter um texto."
                row.append({"type": "alert", "text": label, "value": payload[:180]})
            elif lowered.startswith("share:"):
                payload = value.split(":", 1)[1].strip()
                if not payload:
                    return [], "O botão de compartilhamento precisa ter texto ou link."
                row.append({"type": "url", "text": label, "value": "https://t.me/share/url?url=" + quote_plus(payload)})
            else:
                if value.startswith("t.me/"):
                    value = "https://" + value
                if not value.startswith(("http://", "https://", "tg://")):
                    return [], "Links precisam começar com http://, https://, tg:// ou t.me/"
                row.append({"type": "url", "text": label, "value": value})
        rows.append(row)
    if not rows:
        return [], "Envie pelo menos um botão."
    if sum(len(row) for row in rows) > 16:
        return [], "Use no máximo 16 botões."
    return rows, None


def broadcast_buttons_for_message(data: dict[str, object]):
    rows = []
    for row in broadcast_button_rows_data(data):
        built = []
        for button in row:
            label = str(button.get("text") or "")[:64]
            value = str(button.get("value") or "")
            if button.get("type") == "alert":
                token_value = uuid.uuid5(uuid.NAMESPACE_URL, value).hex[:12]
                BROADCAST_ALERTS[token_value] = value[:180]
                built.append(Button.inline(label, f"bc_pub:{token_value}".encode()))
            else:
                built.append(Button.url(label, value))
        if built:
            rows.append(built)
    return rows or None


def broadcast_load_templates() -> list[dict[str, object]]:
    try:
        raw = json.loads(BROADCAST_TEMPLATES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def broadcast_save_templates(templates: list[dict[str, object]]) -> None:
    BROADCAST_TEMPLATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BROADCAST_TEMPLATES_PATH.write_text(json.dumps(templates[:BROADCAST_TEMPLATE_LIMIT], ensure_ascii=False, indent=2), encoding="utf-8")


def broadcast_template_payload(data: dict[str, object], name: str) -> dict[str, object]:
    return {
        "name": name,
        "text": str(data.get("text") or ""),
        "media_chat_id": data.get("media_chat_id"),
        "media_message_id": data.get("media_message_id"),
        "button_rows": broadcast_button_rows_data(data),
        "pin": bool(data.get("pin")),
    }


def broadcast_apply_template(data: dict[str, object], template: dict[str, object]) -> None:
    for key in ("text", "media_chat_id", "media_message_id", "button_rows", "pin"):
        data[key] = template.get(key, broadcast_blank().get(key))


def broadcast_event_html(event) -> str:
    try:
        from telethon.extensions import html as telethon_html

        return telethon_html.unparse(event.message.message or "", event.message.entities or []).strip()
    except Exception:
        return h(event.raw_text or "").strip()


def broadcast_menu_text(data: dict[str, object], *, note: str | None = None) -> str:
    mode = data.get("mode")
    target_user_id = data.get("target_user_id")
    has_media = bool(data.get("media_message_id"))
    has_text = bool(str(data.get("text") or "").strip())
    pin = bool(data.get("pin"))
    status = "Broadcast em andamento" if BROADCAST_RUNNING else "Parado"
    lines = ["\U0001f4e3 <b>Painel de transmiss\u00e3o</b>", "", f"\u26aa\ufe0f <b>Status do sistema:</b> <code>{h(status)}</code>", "", "Configure e envie uma mensagem para os usu\u00e1rios do bot.", ""]
    if note:
        lines.extend([f"<blockquote>{note}</blockquote>", ""])
    details = [
        f"\U0001f30d <b>Destino:</b> <code>{h(broadcast_mode_label(mode))}</code>",
        f"\U0001f5bc\ufe0f <b>M\u00eddia:</b> <code>{broadcast_yes_no(has_media)}</code>",
        f"\U0001f520 <b>Texto:</b> <code>{broadcast_yes_no(has_text)}</code>",
        f"\u2328\ufe0f <b>Bot\u00f5es:</b> <code>{broadcast_button_count(data)}</code>",
        f"\U0001f4cc <b>Fixar:</b> <code>{broadcast_yes_no(pin)}</code>",
    ]
    if mode == "single" and target_user_id:
        details.insert(1, f"\U0001f194 <b>ID alvo:</b> <code>{h(target_user_id)}</code>")
    lines.append("<blockquote>" + "\n".join(details) + "</blockquote>")
    lines.extend(["", f"<blockquote>\U0001f465 <b>Total salvo no bot:</b> <code>{broadcast_total_users()}</code></blockquote>", "", "<i>Escolha uma op\u00e7\u00e3o abaixo.</i>"])
    return "\n".join(lines)

def broadcast_menu_buttons(data: dict[str, object]):
    pin_label = "\u2705 Sim" if bool(data.get("pin")) else "\u274c N\u00e3o"
    return [
        [Button.inline("\U0001f30d Destino", b"bc:set_mode")],
        [Button.inline("\U0001f5bc\ufe0f M\u00eddia", b"bc:set_media"), Button.inline("\U0001f440 Ver", b"bc:view_media")],
        [Button.inline("\U0001f520 Texto", b"bc:set_text"), Button.inline("\U0001f440 Ver", b"bc:view_text")],
        [Button.inline("\u2328\ufe0f Bot\u00f5es", b"bc:set_buttons"), Button.inline("\U0001f440 Ver", b"bc:view_buttons")],
        [Button.inline("\U0001f4cc Fixar", b"bc:toggle_pin"), Button.inline(pin_label, b"bc:toggle_pin")],
        [Button.inline("\U0001f440 Visualiza\u00e7\u00e3o completa", b"bc:full_preview")],
        [Button.inline("\U0001f519 Voltar", b"bc:close"), Button.inline("Pr\u00f3ximo \u27a1\ufe0f", b"bc:next")],
    ]

def broadcast_running_buttons():
    first = Button.inline("\u25b6\ufe0f Continuar", b"bc:resume") if BROADCAST_CONTROL.get("paused") else Button.inline("\u23f8 Pausar", b"bc:pause")
    return [[first, Button.inline("\U0001f6d1 Cancelar", b"bc:cancel_running")]]

def broadcast_mode_buttons():
    return [[Button.inline("\U0001f30d Todos", b"bc:mode_all")], [Button.inline("\U0001f464 Usu\u00e1rio espec\u00edfico", b"bc:mode_single")], [Button.inline("\U0001f519 Voltar", b"bc:menu")]]

def broadcast_prompt_buttons(remove_action: str | None = None):
    rows = []
    if remove_action:
        labels = {"remove_media": "\U0001f5d1 Remover m\u00eddia", "remove_text": "\U0001f5d1 Remover texto", "remove_buttons": "\U0001f5d1 Remover bot\u00f5es", "remove_schedule": "\U0001f5d1 Remover agendamento"}
        rows.append([Button.inline(labels.get(remove_action, "\U0001f5d1 Remover"), f"bc:{remove_action}".encode())])
    rows.append([Button.inline("\U0001f519 Voltar", b"bc:menu")])
    return rows

def broadcast_templates_buttons(templates: list[dict[str, object]]):
    rows = []
    for index, template in enumerate(templates[:BROADCAST_TEMPLATE_LIMIT]):
        rows.append([Button.inline(f"📌 {str(template.get('name') or f'Modelo {index + 1}')[:32]}", f"bc:load_template:{index}".encode())])
    rows.append([Button.inline("🔙 Voltar", b"bc:menu")])
    return rows


def broadcast_buttons_summary(data: dict[str, object]) -> str:
    rows = data.get("button_rows") if isinstance(data.get("button_rows"), list) else []
    if not rows:
        return "Nenhum bot\u00e3o configurado."
    lines = []
    for row in rows:
        parts = []
        for button in row:
            text = h(str(button.get("text") or "Bot\u00e3o"))
            value = h(str(button.get("url") or button.get("data") or ""))
            parts.append(f"<b>{text}</b> - <code>{value}</code>" if value else f"<b>{text}</b>")
        lines.append(" && ".join(parts))
    return "\n".join(lines)


def broadcast_view_text(title: str, body: str) -> str:
    return f"{title}\n\n<blockquote>{body}</blockquote>"


def broadcast_preview_text(data: dict[str, object]) -> str:
    text = str(data.get("text") or "").strip()
    lines = [
        "👀 <b>Prévia da transmissão</b>",
        "",
        f"<b>Destino:</b> <code>{h(broadcast_mode_label(data.get('mode')))}</code>",
        f"<b>Mídia:</b> <code>{broadcast_yes_no(bool(data.get('media_message_id')))}</code>",
        f"<b>Botões:</b> <code>{broadcast_button_count(data)}</code>",
        f"<b>Fixar:</b> <code>{broadcast_yes_no(bool(data.get('pin')))}</code>",
        f"<b>Agendado:</b> <code>{h(broadcast_schedule_label(data))}</code>",
    ]
    if data.get("mode") == "single" and data.get("target_user_id"):
        lines.insert(3, f"<b>ID alvo:</b> <code>{h(data.get('target_user_id'))}</code>")
    return "\n".join(lines) + "\n\n" + (text or "<i>Sem texto.</i>")


def broadcast_preview_buttons():
    return [[Button.inline("\U0001f9ea Enviar teste", b"bc:test_send")], [Button.inline("Pr\u00f3ximo \u27a1\ufe0f", b"bc:next")], [Button.inline("\U0001f519 Voltar", b"bc:menu")]]

def broadcast_confirm_buttons():
    return [[Button.inline("\u274c Cancelar", b"bc:menu"), Button.inline("\u2705 Confirmar", b"bc:confirm_send")], [Button.inline("\U0001f5d3 Agendar", b"bc:schedule")]]

async def broadcast_remember_panel(admin_id: int, message) -> None:
    data = broadcast_data(admin_id)
    data["panel_chat_id"] = int(message.chat_id)
    data["panel_message_id"] = int(message.id)


async def broadcast_render_panel(admin_id: int, chat_id: int, text: str, buttons):
    data = broadcast_data(admin_id)
    panel_chat_id = data.get("panel_chat_id")
    panel_message_id = data.get("panel_message_id")
    if panel_chat_id and panel_message_id:
        try:
            await client.edit_message(int(panel_chat_id), int(panel_message_id), text, parse_mode="html", buttons=buttons, link_preview=False)
            return
        except Exception:
            pass
    sent = await send_html(chat_id, text, buttons=buttons)
    await broadcast_remember_panel(admin_id, sent)


async def broadcast_show_menu(admin_id: int, chat_id: int, *, note: str | None = None):
    data = broadcast_data(admin_id)
    data["step"] = ""
    await broadcast_render_panel(admin_id, chat_id, broadcast_menu_text(data, note=note), broadcast_menu_buttons(data))


async def broadcast_delete_event(event) -> None:
    try:
        await event.delete()
    except Exception:
        pass


async def broadcast_send_one(user_id: int, data: dict[str, object], should_pin: bool) -> tuple[bool, bool]:
    try:
        buttons = broadcast_buttons_for_message(data)
        text = str(data.get("text") or "").strip()
        media_chat_id = data.get("media_chat_id")
        media_message_id = data.get("media_message_id")
        if media_chat_id and media_message_id:
            source = await client.get_messages(int(media_chat_id), ids=int(media_message_id))
            sent = await client.send_file(user_id, source.media, caption=text or None, parse_mode="html", buttons=buttons)
        else:
            sent = await client.send_message(user_id, text or "📢", parse_mode="html", buttons=buttons, link_preview=False)
        if should_pin and sent:
            try:
                await client.pin_message(user_id, sent, notify=False)
            except Exception:
                pass
        return True, False
    except FloodWaitError as exc:
        await asyncio.sleep(min(int(exc.seconds) + 1, 60))
        return False, False
    except Exception as exc:
        lowered = str(exc).lower()
        return False, any(part in lowered for part in ("blocked", "user is deactivated", "chat not found", "forbidden"))


async def broadcast_send_test(admin_id: int, data: dict[str, object]) -> tuple[bool, str]:
    if not broadcast_ready(data):
        return False, "Defina uma mensagem ou mídia antes do teste."
    ok, _ = await broadcast_send_one(admin_id, data, False)
    return ok, "Teste enviado para você." if ok else "Não consegui enviar o teste."


async def broadcast_execute(admin_chat_id: int, reply_to: int | None, data: dict[str, object]) -> None:
    global BROADCAST_RUNNING, BROADCAST_CONTROL
    try:
        mode = str(data.get("mode") or "")
        has_content = broadcast_ready(data)
        requested_pin = bool(data.get("pin"))
        if mode not in {"all", "single"}:
            await send_html(admin_chat_id, "Defina o destino primeiro.", reply_to=reply_to)
            return
        if not has_content:
            await send_html(admin_chat_id, "Defina pelo menos uma mensagem ou mídia.", reply_to=reply_to)
            return
        if mode == "single":
            target_user_id = data.get("target_user_id")
            if not isinstance(target_user_id, int):
                await send_html(admin_chat_id, "Envie um ID numérico válido.", reply_to=reply_to)
                return
            ok, should_remove = await broadcast_send_one(target_user_id, data, requested_pin)
            if should_remove:
                broadcast_remove_user(target_user_id)
            await send_html(admin_chat_id, f"✅ Envio finalizado.\n\n📤 <b>Enviadas:</b> <code>{1 if ok else 0}</code>\n❌ <b>Falhas:</b> <code>{0 if ok else 1}</code>", reply_to=reply_to)
            return

        users = broadcast_user_ids()
        if not users:
            await send_html(admin_chat_id, "Não há usuários salvos ainda.", reply_to=reply_to)
            return
        total = len(users)
        should_pin = requested_pin and total <= BROADCAST_PIN_LIMIT
        pin_warning = ""
        if requested_pin and not should_pin:
            pin_warning = f"\n📌 <b>Fixar foi desativado automaticamente</b> para listas acima de <code>{BROADCAST_PIN_LIMIT}</code> usuários."
        status = await send_html(admin_chat_id, f"🚀 Iniciando transmissão...\n\n👥 <b>Total alvo:</b> <code>{total}</code>{pin_warning}", buttons=broadcast_running_buttons(), reply_to=reply_to)
        queue: asyncio.Queue[int | None] = asyncio.Queue()
        counters = {"sent": 0, "failed": 0, "processed": 0, "removed": 0, "last": time.monotonic()}
        for user_id in users:
            await queue.put(user_id)
        for _ in range(BROADCAST_WORKERS):
            await queue.put(None)

        async def update_status() -> None:
            remaining = max(0, total - int(counters["processed"]))
            title = "\u23f8 <b>Transmiss\u00e3o pausada</b>" if BROADCAST_CONTROL.get("paused") else "\U0001f6d1 <b>Cancelando transmiss\u00e3o...</b>" if BROADCAST_CONTROL.get("cancelled") else "\U0001f680 <b>Transmiss\u00e3o em andamento...</b>"
            try:
                await edit_html(status, f"{title}\n\n\u2705 <b>Enviadas:</b> <code>{counters['sent']}</code>\n\u274c <b>Falhas:</b> <code>{counters['failed']}</code>\n\U0001f4e6 <b>Processadas:</b> <code>{counters['processed']}/{total}</code>\n\u23f3 <b>Restantes:</b> <code>{remaining}</code>", buttons=broadcast_running_buttons())
            except Exception:
                logger.debug("Falha ao atualizar status do broadcast", exc_info=True)

        async def worker() -> None:
            while True:
                user_id = await queue.get()
                try:
                    if user_id is None:
                        return
                    while BROADCAST_CONTROL.get("paused") and not BROADCAST_CONTROL.get("cancelled"):
                        await asyncio.sleep(1)
                    if BROADCAST_CONTROL.get("cancelled"):
                        counters["processed"] += 1
                        continue
                    ok, should_remove = await broadcast_send_one(int(user_id), data, should_pin)
                    if ok:
                        counters["sent"] += 1
                    else:
                        counters["failed"] += 1
                        if should_remove:
                            broadcast_remove_user(int(user_id))
                            counters["removed"] += 1
                    counters["processed"] += 1
                    now = time.monotonic()
                    if counters["processed"] % BROADCAST_STATUS_EVERY == 0 or now - counters["last"] >= BROADCAST_STATUS_INTERVAL:
                        counters["last"] = now
                        await update_status()
                    await asyncio.sleep(BROADCAST_DELAY)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(BROADCAST_WORKERS)]
        await queue.join()
        await asyncio.gather(*workers, return_exceptions=True)
        final_title = "🛑 <b>Transmissão cancelada.</b>" if BROADCAST_CONTROL.get("cancelled") else "✅ <b>Transmissão finalizada.</b>"
        await edit_html(status, f"{final_title}\n\n📤 <b>Enviadas:</b> <code>{counters['sent']}</code>\n❌ <b>Falhas:</b> <code>{counters['failed']}</code>\n🧹 <b>Removidos:</b> <code>{counters['removed']}</code>\n👥 <b>Total processado:</b> <code>{counters['processed']}</code>")
    finally:
        BROADCAST_RUNNING = False
        BROADCAST_CONTROL = {"paused": False, "cancelled": False}


async def broadcast_schedule_runner(admin_chat_id: int, reply_to: int | None, data: dict[str, object], when_ts: float) -> None:
    global BROADCAST_RUNNING, BROADCAST_CONTROL
    await asyncio.sleep(max(0, when_ts - time.time()))
    BROADCAST_RUNNING = True
    BROADCAST_CONTROL = {"paused": False, "cancelled": False}
    await broadcast_execute(admin_chat_id, reply_to, data)


async def broadcast_start_send(event, data: dict[str, object], message) -> None:
    global BROADCAST_RUNNING, BROADCAST_CONTROL
    chat_id = int(event.chat_id)
    if BROADCAST_RUNNING:
        await event.answer("Já existe uma transmissão em andamento.", alert=True)
        return
    if data.get("mode") not in {"all", "single"}:
        await event.answer("Defina o destino primeiro.", alert=True)
        return
    if not broadcast_ready(data):
        await event.answer("Defina uma mensagem ou mídia antes de enviar.", alert=True)
        return
    total = 1 if data.get("mode") == "single" else broadcast_total_users()
    if data.get("pin") and total > BROADCAST_PIN_LIMIT:
        data["pin"] = False
    if data.get("pin") and total > BROADCAST_PIN_WARN_USERS and not data.get("confirm_pin"):
        data["confirm_pin"] = True
        await edit_html(message, f"📌 <b>Fixar mensagem exige cuidado</b>\n\n<blockquote>Você está tentando fixar para <code>{total}</code> usuários. Confirma mesmo assim?</blockquote>", buttons=broadcast_confirm_buttons())
        return
    safe = dict(data)
    safe["confirm_pin"] = False
    data["confirm_pin"] = False
    if safe.get("schedule_at") and float(safe["schedule_at"]) > time.time():
        asyncio.create_task(broadcast_schedule_runner(chat_id, int(message.id), safe, float(safe["schedule_at"])))
        await broadcast_show_menu(actor_id(event), chat_id, note=f"Transmissão agendada para <code>{h(broadcast_schedule_label(data))}</code>.")
        return
    BROADCAST_RUNNING = True
    BROADCAST_CONTROL = {"paused": False, "cancelled": False}
    asyncio.create_task(broadcast_execute(chat_id, int(message.id), safe))
    await broadcast_show_menu(actor_id(event), chat_id, note="Broadcast iniciado. Acompanhe pelo chat.")


@client.on(events.NewMessage(pattern=r"(?i)^/(broadcast|bc)(?:@\w+)?$"))
async def broadcast_handler(event) -> None:
    language = await language_for(event)
    admin_id = actor_id(event)
    if not is_admin(admin_id):
        await answer(event, "not_admin", language)
        return
    broadcast_data(admin_id)
    await broadcast_show_menu(admin_id, int(event.chat_id))
    await broadcast_delete_event(event)


@client.on(events.CallbackQuery(pattern=b"^bc_pub:"))
async def broadcast_public_callback(event) -> None:
    token_value = event.data.decode("utf-8").split(":", 1)[1]
    await event.answer(BROADCAST_ALERTS.get(token_value, "Aviso indisponível."), alert=True)


@client.on(events.CallbackQuery(pattern=b"^bc:"))
async def broadcast_callback(event) -> None:
    global BROADCAST_RUNNING, BROADCAST_CONTROL
    admin_id = actor_id(event)
    language = await language_for(event)
    if not is_admin(admin_id):
        await event.answer(tx(language, "not_admin"), alert=True)
        return
    data = broadcast_data(admin_id)
    parts = event.data.decode("utf-8").split(":")
    action = parts[1] if len(parts) > 1 else ""
    await event.answer()
    message = await event.get_message()
    await broadcast_remember_panel(admin_id, message)
    chat_id = int(event.chat_id)

    if action == "pause":
        BROADCAST_CONTROL["paused"] = True
        await event.answer("Transmissão pausada.")
    elif action == "resume":
        BROADCAST_CONTROL["paused"] = False
        await event.answer("Transmissão retomada.")
    elif action == "cancel_running":
        BROADCAST_CONTROL["cancelled"] = True
        BROADCAST_CONTROL["paused"] = False
        await event.answer("Cancelamento solicitado.")
    elif action == "menu":
        await broadcast_show_menu(admin_id, chat_id)
    elif action == "close":
        BROADCAST_SESSIONS.pop(admin_id, None)
        try:
            await message.delete()
        except Exception:
            pass
    elif action == "reset":
        BROADCAST_SESSIONS[admin_id] = broadcast_blank()
        await broadcast_show_menu(admin_id, chat_id)
    elif action == "set_mode":
        data["step"] = ""
        await edit_html(message, "\U0001f3af <b>Escolha o destino</b>\n\n<i>Toque em uma das op\u00e7\u00f5es abaixo.</i>", buttons=broadcast_mode_buttons())
    elif action == "mode_all":
        data["mode"] = "all"
        data["target_user_id"] = None
        await broadcast_show_menu(admin_id, chat_id, note="Destino definido para todos os usuários.")
    elif action == "mode_single":
        data["mode"] = "single"
        data["step"] = "awaiting_target_user_id"
        await edit_html(message, "\U0001f464 <b>Envie o ID do usu\u00e1rio</b>\n\n<i>O pr\u00f3ximo texto enviado ser\u00e1 usado como destino.</i>", buttons=broadcast_prompt_buttons())
    elif action == "set_media":
        data["step"] = "awaiting_media"
        await edit_html(message, "\U0001f5bc\ufe0f <b>Envie a m\u00eddia da publica\u00e7\u00e3o!</b>\n<i>Tipos permitidos: fotos, v\u00eddeos, arquivos, figurinhas, GIFs, \u00e1udio, mensagens de voz e v\u00eddeos redondos.</i>", buttons=broadcast_prompt_buttons("remove_media"))
    elif action == "set_text":
        data["step"] = "awaiting_text"
        await edit_html(message, "\U0001f520 <b>Envie a mensagem da postagem</b>\n<i>Voc\u00ea pode usar negrito, it\u00e1lico e links feitos pelo pr\u00f3prio Telegram. HTML simples tamb\u00e9m funciona.</i>\n\n\u2022 <b>Nome:</b> <code>%firstname%</code>\n\u2022 <b>Usu\u00e1rio:</b> <code>%username%</code>", buttons=broadcast_prompt_buttons("remove_text"))
    elif action == "set_buttons":
        data["step"] = "awaiting_buttons"
        await edit_html(message, "\u2328\ufe0f <b>Defina os bot\u00f5es da postagem</b>\n\n<blockquote>Texto do bot\u00e3o - https://t.me/Exemplo\nOutro bot\u00e3o - https://site.com</blockquote>\n\n<blockquote>Site - https://site.com && Canal - https://t.me/canal</blockquote>\n\n<blockquote>Aviso - popup:Texto do popup\nCompartilhar - share:Texto para compartilhar</blockquote>", buttons=broadcast_prompt_buttons("remove_buttons"))
    elif action == "schedule":
        data["step"] = "awaiting_schedule"
        await edit_html(message, "\U0001f5d3 <b>Agendar transmiss\u00e3o</b>\n\n<i>Envie o hor\u00e1rio desejado.</i>\n\n<blockquote>20:00\nhoje 20:00\namanh\u00e3 12:00\n25/12/2026 08:30</blockquote>", buttons=broadcast_prompt_buttons("remove_schedule"))
    elif action == "remove_media":
        data["media_chat_id"] = None
        data["media_message_id"] = None
        await broadcast_show_menu(admin_id, chat_id, note="Mídia removida.")
    elif action == "remove_text":
        data["text"] = ""
        await broadcast_show_menu(admin_id, chat_id, note="Texto removido.")
    elif action == "remove_buttons":
        data["button_rows"] = []
        await broadcast_show_menu(admin_id, chat_id, note="Botões removidos.")
    elif action == "remove_schedule":
        data["schedule_at"] = None
        await broadcast_show_menu(admin_id, chat_id, note="Agendamento removido.")
    elif action == "toggle_pin":
        data["pin"] = not bool(data.get("pin"))
        data["confirm_pin"] = False
        await broadcast_show_menu(admin_id, chat_id, note="Fixar ativado. Haverá trava automática para listas grandes." if data["pin"] else "Fixar desativado.")
    elif action == "view_media":
        body = "M\u00eddia configurada." if bool(data.get("media_message_id")) else "Nenhuma m\u00eddia configurada."
        await edit_html(message, broadcast_view_text("\U0001f5bc\ufe0f <b>M\u00eddia</b>", body), buttons=broadcast_prompt_buttons())
    elif action == "view_text":
        body = str(data.get("text") or "").strip() or "Nenhum texto configurado."
        await edit_html(message, broadcast_view_text("\U0001f520 <b>Texto</b>", body), buttons=broadcast_prompt_buttons())
    elif action == "view_buttons":
        await edit_html(message, broadcast_view_text("\u2328\ufe0f <b>Bot\u00f5es</b>", broadcast_buttons_summary(data)), buttons=broadcast_prompt_buttons())
    elif action in {"preview", "full_preview"}:
        _, note = await broadcast_send_test(admin_id, data)
        await broadcast_show_menu(admin_id, chat_id, note=note)
    elif action == "test_send":
        _, note = await broadcast_send_test(admin_id, data)
        await broadcast_show_menu(admin_id, chat_id, note=note)
    elif action in {"send", "next"}:
        if not broadcast_ready(data):
            await event.answer("Defina texto ou m\u00eddia antes de continuar.", alert=True)
            return
        total = 1 if data.get("mode") == "single" else broadcast_total_users()
        await broadcast_send_test(admin_id, data)
        await edit_html(
            message,
            "\U0001f4ec <b>Confirma\u00e7\u00e3o</b>\n\n"
            "A mensagem acima foi enviada para voc\u00ea como pr\u00e9via. Confirme, cancele ou agende o envio.\n\n"
            f"<blockquote>Destino: <b>{h(broadcast_mode_label(data.get('mode')))}</b>\n"
            f"Usu\u00e1rios: <b>{total}</b>\n"
            f"M\u00eddia: <b>{broadcast_yes_no(bool(data.get('media_message_id')))}</b>\n"
            f"Bot\u00f5es: <b>{broadcast_button_count(data)}</b>\n"
            f"Fixar: <b>{broadcast_yes_no(bool(data.get('pin')))}</b>\n"
            f"Agendado: <b>{h(broadcast_schedule_label(data))}</b></blockquote>",
            buttons=broadcast_confirm_buttons(),
        )
    elif action == "confirm_send":
        await broadcast_start_send(event, data, message)


async def handle_broadcast_input(event, language: str) -> bool:
    admin_id = actor_id(event)
    data = BROADCAST_SESSIONS.get(admin_id)
    if not isinstance(data, dict) or not data.get("step"):
        return False
    step = str(data.get("step") or "")
    text = event.raw_text or ""
    chat_id = int(event.chat_id)

    if step == "awaiting_target_user_id":
        raw = text.strip()
        if not raw.isdigit():
            await broadcast_render_panel(admin_id, chat_id, "👤 <b>Envie o ID do usuário</b>\n\n<blockquote>Envie um ID numérico válido.</blockquote>", broadcast_prompt_buttons())
            await broadcast_delete_event(event)
            return True
        data["mode"] = "single"
        data["target_user_id"] = int(raw)
        await broadcast_show_menu(admin_id, chat_id, note=f"Usuário alvo salvo: <code>{h(raw)}</code>.")
        await broadcast_delete_event(event)
        return True
    if step == "awaiting_media":
        if not getattr(event.message, "media", None):
            await broadcast_render_panel(admin_id, chat_id, "🖼 <b>Envie uma mídia válida</b>\n\n<blockquote>Fotos, vídeos, arquivos, figurinhas, GIFs, áudios e mensagens de voz são aceitos.</blockquote>", broadcast_prompt_buttons("remove_media"))
            await broadcast_delete_event(event)
            return True
        data["media_chat_id"] = chat_id
        data["media_message_id"] = int(event.message.id)
        await broadcast_show_menu(admin_id, chat_id, note="Mídia salva com sucesso.")
        await broadcast_delete_event(event)
        return True
    if step == "awaiting_text":
        raw = broadcast_event_html(event)
        if not raw:
            await broadcast_render_panel(admin_id, chat_id, "📝 <b>Envie a mensagem da postagem</b>\n\n<blockquote>Envie um texto para continuar.</blockquote>", broadcast_prompt_buttons("remove_text"))
            await broadcast_delete_event(event)
            return True
        data["text"] = raw
        await broadcast_show_menu(admin_id, chat_id, note="Mensagem salva com formatação.")
        await broadcast_delete_event(event)
        return True
    if step == "awaiting_buttons":
        rows, error = broadcast_parse_buttons(text)
        if error:
            await broadcast_render_panel(admin_id, chat_id, f"🔘 <b>Defina os botões da postagem</b>\n\n<blockquote>{h(error)}</blockquote>", broadcast_prompt_buttons("remove_buttons"))
            await broadcast_delete_event(event)
            return True
        data["button_rows"] = rows
        await broadcast_show_menu(admin_id, chat_id, note=f"{broadcast_button_count(data)} botão(ões) salvo(s).")
        await broadcast_delete_event(event)
        return True
    if step == "awaiting_schedule":
        when_ts = broadcast_parse_when(text)
        if not when_ts:
            await broadcast_render_panel(admin_id, chat_id, "🗓 <b>Agendar transmissão</b>\n\n<blockquote>Não entendi esse horário. Envie uma data futura.</blockquote>", broadcast_prompt_buttons("remove_schedule"))
            await broadcast_delete_event(event)
            return True
        data["schedule_at"] = when_ts
        await broadcast_show_menu(admin_id, chat_id, note=f"Agendado para <code>{h(broadcast_schedule_label(data))}</code>.")
        await broadcast_delete_event(event)
        return True
    return False


@client.on(events.NewMessage(pattern=r"(?i)^/(admin|painel)(?:@\w+)?$"))
async def admin_handler(event) -> None:
    language = await language_for(event)
    user_id = actor_id(event)
    if not is_admin(user_id):
        await answer(event, "not_admin", language)
        return
    stats = store.stats()
    await answer(
        event,
        "admin_overview",
        language,
        users=stats["users"],
        jobs=stats["jobs"],
        links=stats["links"],
        temp_size=human_size(directory_size(settings.download_dir)),
        public_size=human_size(directory_size(settings.public_files_dir)),
        active=sum(len(tasks) for tasks in active_tasks.values()),
    )


@client.on(events.NewMessage(pattern=r"(?i)^/(health|debug|diagnostico|diagnÃ³stico)(?:@\w+)?$"))
async def diagnostics_handler(event) -> None:
    language = await language_for(event)
    user_id = actor_id(event)
    if not is_admin(user_id):
        await answer(event, "not_admin", language)
        return
    status = await answer(event, "stage_analyzing", language)
    results = await run_diagnostics(settings)
    await edit_html(status, render_diagnostics(results))


@client.on(events.NewMessage(pattern=r"(?i)^/allowgroup(?:@\w+)?\s+(-?\d+)"))
async def allow_group_handler(event) -> None:
    language = await language_for(event)
    if not is_admin(actor_id(event)):
        await answer(event, "not_admin", language)
        return
    chat_id = int(event.pattern_match.group(1))
    store.set_group_status(chat_id, "allowed", actor_id(event))
    await answer(event, "group_allowed", language, chat_id=chat_id)


@client.on(events.NewMessage(pattern=r"(?i)^/(bangroup|blockgroup)(?:@\w+)?\s+(-?\d+)"))
async def ban_group_handler(event) -> None:
    language = await language_for(event)
    if not is_admin(actor_id(event)):
        await answer(event, "not_admin", language)
        return
    chat_id = int(event.pattern_match.group(2))
    store.set_group_status(chat_id, "blocked", actor_id(event))
    await answer(event, "group_blocked", language, chat_id=chat_id)


@client.on(events.CallbackQuery(pattern=b"^check_channels$"))
async def check_channels_callback(event) -> None:
    if not await callback_guard(event):
        return
    user_id = actor_id(event)
    REQUIRED_CHANNEL_CACHE.pop(user_id, None)
    language = await language_for(event)
    if not await is_member_of_required_channels(user_id):
        await event.answer(tx(language, "channels_still_missing"), alert=True)
        return
    await edit_html(await event.get_message(), tx(language, "channels_verified"))
    await asyncio.sleep(1)
    sender = await event.get_sender()
    name = getattr(sender, "first_name", None) or "você"
    await client.send_file(
        event.chat_id,
        BAIXAAQUI_START_BANNER_URL,
        caption=tx(language, "welcome", name=name),
        parse_mode="html",
        buttons=main_menu(language),
    )


@client.on(events.CallbackQuery(pattern=b"^menu:"))
async def menu_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    user_id = actor_id(event)
    action = event.data.decode("utf-8").split(":", 1)[1]
    message = await event.get_message()
    if action == "home":
        sessions.clear(user_id)
        await edit_html(message, tx(language, "menu_title"), buttons=main_menu(language))
    elif action == "download":
        sessions.set_step(user_id, "await_direct_url", {}, language)
        await edit_html(message, tx(language, "menu_download"), buttons=back_buttons(language))
    elif action == "upload":
        sessions.set_step(user_id, "await_direct_url", {}, language)
        await edit_html(message, tx(language, "menu_upload"), buttons=back_buttons(language))
    elif action == "tools":
        sessions.set_step(user_id, "await_media_tool", {}, language)
        await edit_html(message, tx(language, "menu_tools"), buttons=back_buttons(language))
    elif action == "thumb":
        sessions.clear(user_id)
        thumb = store.get_thumb(actor_id(event))
        await edit_html(message, tx(language, "menu_thumb", thumb=tx(language, "state_on") if thumb else tx(language, "state_off")), buttons=thumb_menu_buttons(language))
    elif action == "links":
        sessions.clear(user_id)
        links = store.recent_links(actor_id(event))
        items = "\n".join(tx(language, "link_item", filename=item["filename"], size=human_size(int(item["size"]))) for item in links) if links else tx(language, "link_empty")
        await edit_html(message, tx(language, "menu_links", items=items), buttons=recent_link_buttons(language, links))
    elif action == "premium":
        sessions.clear(user_id)
        sender = await event.get_sender()
        name = getattr(sender, "first_name", None) or "Usuario"
        await edit_html(message, render_plan_status(user_id, name), buttons=plan_buttons())
    elif action == "help":
        sessions.clear(user_id)
        await edit_html(message, tx(language, "help"), buttons=back_buttons(language))
    elif action == "settings":
        sessions.clear(user_id)
        thumb = store.get_thumb(actor_id(event))
        await edit_html(
            message,
            tx(language, "settings", lang_name=language_label(language), thumb=tx(language, "state_on") if thumb else tx(language, "state_off")),
            buttons=settings_buttons(language),
        )
    elif action == "tasks":
        sessions.clear(user_id)
        await edit_html(message, task_panel(language, actor_id(event)), buttons=back_buttons(language))
    else:
        await edit_html(message, tx(language, "menu_title"), buttons=main_menu(language))


@client.on(events.CallbackQuery(pattern=b"^plan:"))
async def plan_callback(event) -> None:
    if not await callback_guard(event):
        return
    user_id = actor_id(event)
    sender = await event.get_sender()
    name = getattr(sender, "first_name", None) or "Usuario"
    parts = event.data.decode("utf-8").split(":")
    action = parts[1] if len(parts) > 1 else "refresh"
    message = await event.get_message()
    if action == "view" and len(parts) >= 3:
        plan_key = normalize_plan_key(parts[2])
        await edit_html(message, render_plan_status(user_id, name, plan_key), buttons=plan_detail_buttons(plan_key))
        return
    if action == "pay" and len(parts) >= 3:
        plan = plan_for_key(parts[2])
        support = settings.bot_support_username or "admin"
        await edit_html(
            message,
            (
                f"<b>Pagamento - {plan.name}</b>\n\n"
                f"Preco mensal: <code>{plan.price}</code>\n\n"
                f"Para liberar manualmente, chame {h(support)} e envie seu ID:\n"
                f"<code>{user_id}</code>"
            ),
            buttons=[[Button.inline("â‡", f"plan:view:{plan.key}".encode())]],
        )
        return
    await edit_html(message, render_plan_status(user_id, name), buttons=plan_buttons())


@client.on(events.CallbackQuery(pattern=b"^settings:"))
async def settings_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    action = event.data.decode("utf-8").split(":", 1)[1]
    message = await event.get_message()
    if action == "language":
        await edit_html(message, tx(language, "settings_language"), buttons=language_buttons(language))
        return
    if action == "thumb":
        thumb = store.get_thumb(actor_id(event))
        await edit_html(message, tx(language, "menu_thumb", thumb=tx(language, "state_on") if thumb else tx(language, "state_off")), buttons=thumb_menu_buttons(language))
        return
    thumb = store.get_thumb(actor_id(event))
    await edit_html(
        message,
        tx(language, "settings", lang_name=language_label(language), thumb=tx(language, "state_on") if thumb else tx(language, "state_off")),
        buttons=settings_buttons(language),
    )


@client.on(events.CallbackQuery(pattern=b"^lang:"))
async def language_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = normalize_language(event.data.decode("utf-8").split(":", 1)[1], settings.default_language)
    store.set_language(actor_id(event), language)
    thumb = store.get_thumb(actor_id(event))
    await edit_html(
        await event.get_message(),
        tx(language, "settings", lang_name=language_label(language), thumb=tx(language, "state_on") if thumb else tx(language, "state_off")),
        buttons=settings_buttons(language),
    )


@client.on(events.CallbackQuery(pattern=b"^thumb:"))
async def thumb_menu_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    action = event.data.decode("utf-8").split(":", 1)[1]
    user_id = actor_id(event)
    message = await event.get_message()
    if action == "set":
        sessions.set_step(user_id, "save_default_thumb", {}, language)
        await edit_html(message, tx(language, "thumb_default_request"), buttons=thumb_menu_buttons(language))
        return
    if action == "remove":
        thumb = get_default_thumb(user_id)
        if thumb and thumb.exists():
            thumb.unlink(missing_ok=True)
        store.set_thumb(user_id, None)
        await edit_html(message, tx(language, "thumb_removed"), buttons=thumb_menu_buttons(language))
        return


@client.on(events.CallbackQuery(pattern=b"^target:"))
async def target_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    user_id = actor_id(event)
    _, action, target_token = event.data.decode("utf-8").split(":", 2)
    target = get_target(target_token, user_id)
    if not target:
        await edit_html(await event.get_message(), tx(language, "expired"))
        return

    if action == "cancel":
        pending_targets.pop(target_token, None)
        sessions.clear(user_id)
        cancel_tasks_for_target(target_token)
        await edit_html(await event.get_message(), tx(language, "cancelled"))
        return
    if action == "rename":
        sessions.set_step(user_id, "rename_target", {"token": target_token}, language)
        await send_html(event.chat_id, tx(language, "rename_request"))
        return
    if action == "caption":
        sessions.set_step(user_id, "caption_target", {"token": target_token}, language)
        await send_html(event.chat_id, tx(language, "caption_request"))
        return
    if action == "thumb":
        sessions.set_step(user_id, "thumb_target", {"token": target_token}, language)
        await send_html(event.chat_id, tx(language, "thumb_request"))


@client.on(events.CallbackQuery(pattern=b"^direct:"))
async def direct_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    user_id = actor_id(event)
    _, action, target_token = event.data.decode("utf-8").split(":", 2)
    target = get_target(target_token, user_id)
    if not target:
        await edit_html(await event.get_message(), tx(language, "expired"))
        return
    if action == "link":
        await schedule_link_job(event, target, status=await event.get_message())
        return
    mode: UploadMode = {"file": "document", "video": "video", "audio": "audio", "photo": "photo"}.get(action, "document")  # type: ignore[assignment]
    await schedule_job(event, replace(target, source="direct", filename=target.filename), mode=mode, status=await event.get_message())


@client.on(events.CallbackQuery(pattern=b"^social:"))
async def social_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    user_id = actor_id(event)
    _, action, target_token = event.data.decode("utf-8").split(":", 2)
    target = get_target(target_token, user_id)
    if not target:
        await edit_html(await event.get_message(), tx(language, "expired"))
        return
    if action == "link":
        await schedule_link_job(event, replace(target, source="social:link"), status=await event.get_message())
        return
    mode: UploadMode = {
        "download": "auto",
        "audio": "audio",
        "audiofile": "audio",
        "video": "video",
        "file": "document",
        "photo": "photo",
    }.get(action, "auto")
    await schedule_job(event, replace(target, source=f"social:{action}"), mode=mode, status=await event.get_message())


@client.on(events.CallbackQuery(pattern=b"^quality:"))
async def quality_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    user_id = actor_id(event)
    _, quality, target_token = event.data.decode("utf-8").split(":", 2)
    target = get_target(target_token, user_id)
    if not target:
        await edit_html(await event.get_message(), tx(language, "expired"))
        return

    await schedule_job(
        event,
        replace(target, source="social:video", format_selector=format_selector_for_quality(quality)),
        mode="video",
        status=await event.get_message(),
        ephemeral=True,
    )


@client.on(events.CallbackQuery(pattern=b"^file:"))
async def file_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    user_id = actor_id(event)
    _, action, target_token = event.data.decode("utf-8").split(":", 2)
    target = get_target(target_token, user_id)
    if not target:
        await edit_html(await event.get_message(), tx(language, "expired"))
        return

    if action == "link":
        await schedule_link_job(event, target, status=await event.get_message())
        return
    if action == "photo":
        await schedule_job(event, replace(target, source="telegram_file"), mode="photo", status=await event.get_message())
        return
    if action == "video":
        await schedule_job(event, replace(target, source="telegram_file"), mode="video", status=await event.get_message())
        return
    if action == "audio":
        await schedule_job(event, replace(target, source="telegram_file"), mode="audio", status=await event.get_message())
        return
    if action == "file":
        await schedule_job(event, replace(target, source="telegram_file"), mode="document", status=await event.get_message())
        return
    if action in {"pdf", "cbz", "epub"}:
        await schedule_job(
            event,
            replace(target, source="telegram_file", conversion=action),
            mode="document",
            status=await event.get_message(),
        )
        return
    if action == "savethumb":
        await save_default_thumbnail(target, language, await event.get_message())
        return
    if action == "tempthumb":
        sessions.set_step(user_id, "temp_thumb_saved", {"thumb_message_id": target.message_id}, language)
        await edit_html(await event.get_message(), tx(language, "thumb_saved"))


@client.on(events.CallbackQuery(pattern=b"^link:delete:"))
async def delete_link_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    link_id = event.data.decode("utf-8").split(":", 2)[2]
    path = store.delete_link(link_id, actor_id(event))
    if path:
        link_storage.delete(Path(path))
    await edit_html(await event.get_message(), tx(language, "link_deleted"))


@client.on(events.CallbackQuery(pattern=b"^job:cancel:"))
async def cancel_job_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    job_id = event.data.decode("utf-8").split(":", 2)[2]
    for tasks in active_tasks.values():
        for task in tasks:
            if getattr(task, "job_id", None) == job_id:
                task.cancel()
    await edit_html(await event.get_message(), tx(language, "cancelled"))


@client.on(events.CallbackQuery(pattern=b"^retry:"))
async def retry_callback(event) -> None:
    if not await callback_guard(event):
        return
    language = await language_for(event)
    user_id = actor_id(event)
    target_token = event.data.decode("utf-8").split(":", 1)[1]
    target = get_target(target_token, user_id)
    if not target:
        await edit_html(await event.get_message(), tx(language, "expired"))
        return

    status = await event.get_message()
    if target.source == "link":
        await schedule_link_job(event, target, status=status)
        return
    mode_map: dict[str, UploadMode] = {
        ":audio": "audio",
        ":audiofile": "audio",
        ":video": "video",
        ":photo": "photo",
        ":file": "document",
    }
    mode: UploadMode = "auto"
    for suffix, retry_mode in mode_map.items():
        if target.source.endswith(suffix):
            mode = retry_mode
            break
    if mode == "auto" and target.direct_info and is_audio_filename(target.filename or ""):
        mode = "audio"
    await schedule_job(event, target, mode=mode, status=status)


@client.on(events.NewMessage(pattern=r"(?i)^/(?!start|iniciar|help|ajuda|mp3|audio|cancelar|cancel|limpar|config|settings|status|minhastarefas|planos|plans|premium|plano|myplan|liberar|release|setplan|broadcast|bc|health|debug|diagnostico|diagnóstico|allowgroup|bangroup|blockgroup)"))
async def unknown_command_handler(event) -> None:
    if not is_private_chat(event):
        return
    language = await language_for(event)
    await public_rate_guard(event, language)
    await send_html(event.chat_id, tx(language, "unknown_command"))
    await delete_private_command(event)


@client.on(events.NewMessage(incoming=True))
async def route_message(event) -> None:
    if not event.message:
        return
    if getattr(event, "out", False):
        return
    language = await language_for(event)
    user_id = actor_id(event)
    private_chat = is_private_chat(event)
    sender = await event.get_sender()
    if not private_chat and getattr(sender, "bot", False):
        return
    if private_chat and not await ensure_required_channels(event):
        return
    if maintenance_mode and not is_admin(user_id):
        await answer(event, "maintenance", language)
        return
    if not private_chat and not group_rate_limiter.allow(int(event.chat_id)):
        return
    if not rate_limiter.allow(user_id):
        if not private_chat:
            return
        await answer(event, "rate_limited", language)
        return

    text = event.raw_text or ""
    if is_admin(user_id) and await handle_broadcast_input(event, language):
        return
    if text.startswith("/"):
        return

    session = sessions.get(user_id, language)
    if session.step and await handle_session_input(event, session, language):
        return

    if not private_chat:
        if not settings.group_auto_download or not group_allowed(int(event.chat_id)):
            return
        if contains_url(text):
            url = extract_url(text) or text.strip()
            url = normalize_shared_url(url)
            if is_social_url(url) or is_drive_url(url) or is_public_http_url(url):
                await analyze_link(event, url, language)
        return

    if contains_url(text):
        await analyze_link(event, normalize_shared_url(extract_url(text) or text.strip()), language)
        return

    if is_media_message(event.message):
        await show_file_actions(event, language)
        return

    if private_chat:
        await answer(event, "menu_title", language, buttons=main_menu(language))


async def handle_session_input(event, session, language: str) -> bool:
    user_id = actor_id(event)
    text = event.raw_text or ""

    if session.step == "await_social_link":
        if contains_url(text):
            sessions.clear(user_id)
            return False
        await answer(event, "menu_download", language, buttons=back_buttons(language))
        return True

    if session.step == "await_direct_url":
        if contains_url(text):
            sessions.clear(user_id)
            return False
        await answer(event, "menu_upload", language, buttons=back_buttons(language))
        return True

    if session.step == "await_media_tool":
        if is_media_message(event.message):
            sessions.clear(user_id)
            return False
        await answer(event, "menu_tools", language, buttons=back_buttons(language))
        return True

    if session.step == "rename_target" and text.strip():
        target = get_target(session.payload.get("token", ""), user_id)
        filename = sanitize_filename(text.strip())
        if not target or not filename:
            await answer(event, "invalid_name", language)
            return True
        direct_info = replace(target.direct_info, filename=filename) if target.direct_info else None
        new_target = remember(replace(target, filename=filename, direct_info=direct_info, created_at=time.time()))
        sessions.clear(user_id)
        await send_html(
            event.chat_id,
            describe_target(language, new_target),
            buttons=target_buttons_for(language, new_target),
        )
        return True

    if session.step == "caption_target":
        target = get_target(session.payload.get("token", ""), user_id)
        if not target:
            await answer(event, "expired", language)
            return True
        clean_caption = None if text.strip().lower() in {"limpar", "clear", "borrar"} else preserve(text, 1000)
        remember(replace(target, caption=clean_caption, created_at=time.time()))
        sessions.clear(user_id)
        await answer(event, "done", language, buttons=target_buttons_for(language, target))
        return True

    if session.step == "thumb_target" and is_image_message(event.message):
        target = get_target(session.payload.get("token", ""), user_id)
        if not target:
            await answer(event, "expired", language)
            return True
        thumb_path = await download_message_to_temp(event.message, user_id, suffix=".jpg")
        updated_target = remember(replace(target, thumb_path=str(thumb_path), created_at=time.time()))
        sessions.clear(user_id)
        await answer(event, "thumb_saved", language, buttons=target_buttons_for(language, updated_target))
        return True

    if session.step == "save_default_thumb" and is_image_message(event.message):
        thumb_path = await download_message_to_temp(event.message, user_id, suffix=".jpg", persistent=True)
        store.set_thumb(user_id, str(thumb_path))
        sessions.clear(user_id)
        await answer(event, "thumb_saved", language)
        return True

    return False


def target_buttons_for(language: str, target: PendingTarget):
    profile = profile_for_target(target)
    if target.source.startswith("social"):
        return social_buttons(language, target, profile)
    if target.source.startswith("direct"):
        return direct_buttons(language, target, profile)
    return file_buttons(language, target, profile)


async def analyze_link(event, url: str, language: str) -> None:
    status = None
    url = normalize_shared_url(url)
    try:
        if is_social_url(url):
            if not settings.social_download_enabled:
                if is_private_chat(event):
                    await send_html(event.chat_id, tx(language, "social_disabled"))
                return
            status = None if not is_private_chat(event) else await answer(event, "analyzing_link", language)
            info = await inspect_social(url)
            target = remember(
                PendingTarget(
                    token=token(),
                    user_id=actor_id(event),
                    chat_id=int(event.chat_id),
                    source=f"social:{info.media_type}",
                    url=url,
                    filename=info.title,
                    social_info=info,
                    created_at=time.time(),
                )
            )
            if is_private_chat(event):
                await edit_html(status, social_card(language, info), buttons=social_buttons(language, target, profile_for_social(info)))
            else:
                await schedule_job(event, target, mode="auto", status=None, silent=True, ephemeral=True)
            return

        if is_drive_url(url):
            if not settings.google_drive_enabled:
                raise DriveDownloadError(tx(language, "drive_disabled"))
            if not settings.google_drive_public_only:
                raise DriveDownloadError(tx(language, "drive_public_only"))
            status = None if not is_private_chat(event) else await answer(event, "analyzing_link", language)
            info = await inspect_drive(url)
            target = remember(
                PendingTarget(
                    token=token(),
                    user_id=actor_id(event),
                    chat_id=int(event.chat_id),
                    source="direct:drive",
                    url=url,
                    filename=info.filename,
                    direct_info=info,
                    created_at=time.time(),
                )
            )
            if is_private_chat(event):
                await edit_html(status, direct_card(language, info), buttons=direct_buttons(language, target, profile_for_direct(info)))
            else:
                await schedule_job(event, target, mode="auto", status=None, silent=True, ephemeral=True)
            return

        status = await answer(event, "analyzing_link", language)
        info = await inspect_direct(url)
        target = remember(
            PendingTarget(
                token=token(),
                user_id=actor_id(event),
                chat_id=int(event.chat_id),
                source="direct",
                url=info.url,
                filename=info.filename,
                direct_info=info,
                created_at=time.time(),
            )
        )
        await edit_html(status, direct_card(language, info), buttons=direct_buttons(language, target, profile_for_direct(info)))
    except Exception as exc:
        if is_private_chat(event):
            logger.warning("direct_link_analyze_failed chat_id=%s url=%s reason=%s", event.chat_id, url, exc)
            text = tx(language, "error_human", reason=tx(language, "direct_link_required"))
            if status:
                await edit_html(status, text)
            else:
                await send_html(event.chat_id, text)


async def inspect_direct(url: str) -> RemoteFileInfo:
    cache_key = f"direct:{url}"
    cached = store.cache_get(cache_key)
    if cached:
        return RemoteFileInfo.from_dict(cached)
    async with inspect_slots:
        info = await remote_downloader.inspect(url)
    store.cache_set(cache_key, info.to_dict(), settings.metadata_cache_ttl_seconds)
    return info


async def inspect_drive(url: str) -> RemoteFileInfo:
    cache_key = f"drive:{url}"
    cached = store.cache_get(cache_key)
    if cached:
        return RemoteFileInfo.from_dict(cached)
    async with inspect_slots:
        info = await drive_downloader.inspect(url)
    store.cache_set(cache_key, info.to_dict(), settings.metadata_cache_ttl_seconds)
    return info


async def inspect_social(url: str) -> SocialInfo:
    cache_key = f"social:v7:{url}"
    cached = store.cache_get(cache_key)
    if cached:
        return SocialInfo.from_dict(cached)
    async with inspect_slots:
        info = await social_downloader.inspect(url)
    store.cache_set(cache_key, info.to_dict(), settings.metadata_cache_ttl_seconds)
    return info


def social_card(language: str, info: SocialInfo) -> str:
    lines = [f"<b>{tx(language, 'social_card_title')}</b>"]
    kind = _social_kind(language, info.media_type)
    if kind:
        lines.append(f"🎬 {h(kind)}")
    if info.title:
        lines.append(f"📌 {h(info.title)}")
    if info.author:
        lines.append(f"👤 {h(info.author)}")
    if info.duration:
        lines.append(f"⏱️ {format_duration(language, info.duration)}")
    if info.quality:
        lines.append(f"🎞️ {h(info.quality)}")
    if info.item_count and info.item_count > 1:
        lines.append(f"📦 {info.item_count} itens")
    return "\n".join(lines)


def direct_card(language: str, info: RemoteFileInfo) -> str:
    return tx(
        language,
        "direct_card",
        filename=info.filename,
        size=display_size(language, info.size),
        kind=detect_kind(language, info.filename, info.mime_type),
    )


async def show_file_actions(event, language: str) -> None:
    filename = message_filename(event.message)
    mime = getattr(getattr(event.message, "file", None), "mime_type", None)
    profile = profile_for_telegram(filename, mime, is_image_message=is_image_message(event.message))
    target = remember(
        PendingTarget(
            token=token(),
            user_id=actor_id(event),
            chat_id=int(event.chat_id),
            source="telegram_file",
            message_id=event.message.id,
            filename=filename,
            created_at=time.time(),
        )
    )
    key = "photo_card" if is_image_message(event.message) else "file_card"
    text = tx(
        language,
        key,
        filename=filename,
        size=display_size(language, message_size(event.message)),
        kind=detect_kind(language, filename, mime),
    )
    await event.respond(text, parse_mode="html", buttons=file_buttons(language, target, profile), link_preview=False)


async def schedule_job(event, target: PendingTarget, mode: UploadMode, status=None, *, silent: bool = False, ephemeral: bool = False) -> None:
    language = await language_for(event)
    user_id = actor_id(event)
    estimated_size = await estimated_target_size(target)
    rejection = plan_rejection(user_id, estimated_size)
    if rejection:
        if not silent:
            await edit_or_send(event, status, f"<b>Limite do plano</b>\n{h(rejection)}")
        return
    if active_count(user_id) >= max(settings.max_jobs_per_user, user_plan(user_id).parallel_jobs) and not is_admin(user_id):
        if not silent:
            await edit_or_send(event, status, tx(language, "rate_limited"))
        return
    dedupe_key = user_url_dedupe_key(user_id, target.url)
    if dedupe_key:
        current_lock = download_dedupe.get(dedupe_key)
        if current_lock and not current_lock.locked():
            download_dedupe.pop(dedupe_key, None)
            current_lock = None
        if current_lock:
            if not silent:
                await edit_or_send(event, status, tx(language, "already_downloading"))
            return
        current_lock = asyncio.Lock()
        await current_lock.acquire()
        download_dedupe[dedupe_key] = current_lock

    job_id = uuid.uuid4().hex[:12]
    logger.info("job_queue kind=%s user_id=%s chat_id=%s job_id=%s", target.source, user_id, target.chat_id, job_id)
    store.create_job(job_id, user_id, target.source, target.filename)
    status = status or (None if silent else await answer(event, "queued", language, buttons=cancel_button(language, job_id)))
    timeout = user_plan(user_id).timeout_seconds
    task = asyncio.create_task(run_job_with_timeout(job_id, run_media_job(job_id, target, mode, status, language, ephemeral=ephemeral, silent=silent), timeout))
    task.job_id = job_id  # type: ignore[attr-defined]
    task.target_token = target.token  # type: ignore[attr-defined]
    active_tasks.setdefault(user_id, set()).add(task)
    task.add_done_callback(lambda done: active_tasks.get(user_id, set()).discard(done))


async def schedule_link_job(event, target: PendingTarget, status=None) -> None:
    language = await language_for(event)
    user_id = actor_id(event)
    estimated_size = await estimated_target_size(target)
    rejection = plan_rejection(user_id, estimated_size)
    if rejection:
        await edit_or_send(event, status, f"<b>Limite do plano</b>\n{h(rejection)}")
        return
    if active_count(user_id) >= max(settings.max_jobs_per_user, user_plan(user_id).parallel_jobs) and not is_admin(user_id):
        await edit_or_send(event, status, tx(language, "rate_limited"))
        return
    job_id = uuid.uuid4().hex[:12]
    logger.info("link_queue user_id=%s chat_id=%s job_id=%s", user_id, target.chat_id, job_id)
    store.create_job(job_id, user_id, "link", target.filename)
    status = status or await answer(event, "queued", language, buttons=cancel_button(language, job_id))
    timeout = user_plan(user_id).timeout_seconds
    task = asyncio.create_task(run_job_with_timeout(job_id, run_link_job(job_id, target, status, language), timeout))
    task.job_id = job_id  # type: ignore[attr-defined]
    task.target_token = target.token  # type: ignore[attr-defined]
    active_tasks.setdefault(user_id, set()).add(task)
    task.add_done_callback(lambda done: active_tasks.get(user_id, set()).discard(done))


async def run_job_with_timeout(job_id: str, coro, timeout_seconds: int | None = None) -> None:
    try:
        if timeout_seconds is None:
            await coro
        else:
            await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        store.update_job(job_id, "failed", error="job timeout")
        logger.error("job_timeout job_id=%s timeout=%s", job_id, timeout_seconds)
    except Exception:
        raise


async def edit_or_send(event, status, text: str) -> None:
    if status:
        await edit_html(status, text)
    else:
        await send_html(event.chat_id, text)


async def edit_status(status, text: str, *, buttons=None) -> None:
    if status:
        await edit_html(status, text, buttons=buttons)


async def delete_status(status) -> None:
    if not status:
        return
    try:
        await status.delete()
    except Exception:
        return


@dataclass(frozen=True)
class FastImageLinkResult:
    public_url: str
    filename: str
    size: int
    mime_type: str | None


def image_link_cache_key(target: PendingTarget, message) -> str | None:
    if target.source != "telegram_file" or not target.message_id:
        return None
    file_info = getattr(message, "file", None)
    file_id = getattr(file_info, "id", None) or getattr(file_info, "name", None)
    if not file_id:
        return None
    return f"image-link:{target.user_id}:{target.chat_id}:{file_id}"


def local_image_link_available() -> bool:
    return settings.local_link_storage_enabled and is_public_button_url(settings.public_base_url)


async def try_fast_image_link(target: PendingTarget, status, language: str, job_id: str) -> FastImageLinkResult | None:
    if target.source != "telegram_file" or not target.message_id:
        return None

    message = await client.get_messages(target.chat_id, ids=target.message_id)
    if not message or not is_image_message(message):
        return None

    cache_key = image_link_cache_key(target, message)
    cached = store.cache_get(cache_key) if cache_key else None
    cached_url = str(cached.get("url") or "").strip() if cached else ""
    cached_size = int(cached.get("size") or 0) if cached and cached.get("size") else message_size(message) or 0
    cached_mime = str(cached.get("mime_type") or "").strip() if cached else getattr(getattr(message, "file", None), "mime_type", None)
    if cached_url and is_public_button_url(cached_url):
        filename = sanitize_filename(target.filename or message_filename(message)) or "imagem.jpg"
        return FastImageLinkResult(cached_url, filename, cached_size, cached_mime or None)

    progress = ProgressEditor(
        status,
        tx(language, "label_download"),
        min(max(settings.progress_interval, 1), 3),
        wrapper=lambda body: tx(language, "stage_downloading", progress=body),
    )
    raw = await message.download_media(file=bytes, progress_callback=progress.as_callback())
    if not raw:
        raise DownloadError(tx(language, "telegram_file_download_failed"))

    if isinstance(raw, (bytes, bytearray, memoryview)):
        payload = bytes(raw)
    else:
        payload = Path(str(raw)).read_bytes()
    filename = sanitize_filename(target.filename or message_filename(message)) or "imagem.jpg"
    mime_type = getattr(getattr(message, "file", None), "mime_type", None) or mimetypes.guess_type(filename)[0]
    await edit_status(status, tx(language, "stage_linking"), buttons=cancel_button(language, job_id))
    if local_image_link_available():
        stored = await link_storage.store_bytes(
            payload,
            filename,
            mime_type=mime_type,
            ttl_seconds=LOCAL_IMAGE_LINK_TTL_SECONDS,
        )
        if cache_key:
            store.cache_set(
                cache_key,
                {"url": stored.public_url, "size": stored.size, "mime_type": stored.mime_type},
                IMAGE_LINK_CACHE_TTL_SECONDS,
            )
        return FastImageLinkResult(stored.public_url, stored.filename, stored.size, stored.mime_type)
    public_url = await image_host.upload_bytes(filename, payload, mime_type)
    if cache_key:
        store.cache_set(
            cache_key,
            {"url": public_url, "size": len(payload), "mime_type": mime_type},
            IMAGE_LINK_CACHE_TTL_SECONDS,
        )
    return FastImageLinkResult(public_url, filename, len(payload), mime_type)


def fast_remote_send_allowed(target: PendingTarget, send_mode: UploadMode) -> bool:
    if not settings.fast_url_upload or not target.source.startswith("direct") or not target.url or send_mode not in {"photo", "video", "document"}:
        return False
    if target.conversion or target.thumb_path:
        return False
    if send_mode in {"video", "document"} and get_default_thumb(target.user_id):
        return False
    if target.direct_info and target.filename and target.filename != target.direct_info.filename:
        return False
    return bot_api.can_try_remote_url(target.url, send_mode)


async def try_fast_remote_send(target: PendingTarget, mode: UploadMode) -> bool:
    filename = target.filename or (target.direct_info.filename if target.direct_info else None) or "download.bin"
    send_mode = resolve_send_mode(mode, filename)
    if not fast_remote_send_allowed(target, send_mode):
        return False
    dummy = DownloadResult(path=Path(filename), filename=filename, size=0, mime_type=None, caption=None)
    caption = caption_for_result(target, dummy)
    try:
        await bot_api.send_remote_url(target.chat_id, target.url or "", caption=caption, mode=send_mode)
        return True
    except Exception as exc:
        logger.warning("direct_remote_send_fallback chat_id=%s url=%s reason=%s", target.chat_id, target.url, exc)
        return False


async def video_results_have_audio(results: list[DownloadResult]) -> bool:
    checked = False
    for result in results:
        if not is_video_filename(result.filename):
            continue
        checked = True
        info = await media_probe.inspect(result.path)
        if not info.has_audio:
            return False
    return True


async def run_media_job(job_id: str, target: PendingTarget, mode: UploadMode, status, language: str, *, ephemeral: bool = False, silent: bool = False) -> None:
    job_dir = Path(tempfile.mkdtemp(prefix=f"{job_id}_", dir=settings.download_dir))
    started_at = time.perf_counter()
    download_ms = 0.0
    upload_ms = 0.0
    dedupe_key = user_url_dedupe_key(target.user_id, target.url)
    try:
        logger.info("job_start job_id=%s kind=%s user_id=%s mode=%s", job_id, target.source, target.user_id, mode)
        store.update_job(job_id, "running")
        async with job_slots:
            await edit_status(status, tx(language, "stage_preparing"), buttons=cancel_button(language, job_id))
            if await try_cached_file_send(job_id, target, mode, status, language, ephemeral):
                return
            if await try_fast_remote_send(target, mode):
                fast_size = int(target.direct_info.size or 0) if target.direct_info else 0
                store.update_job(job_id, "done", bytes_in=fast_size, bytes_out=fast_size)
                logger.info("job_done_fast job_id=%s kind=%s user_id=%s total_ms=%d", job_id, target.source, target.user_id, int((time.perf_counter() - started_at) * 1000))
                await delete_status(status)
                pending_targets.pop(target.token, None)
                return
            await edit_status(
                status,
                tx(language, "stage_downloading", progress=render_progress(tx(language, "label_download"), 0, None, time.monotonic())),
                buttons=cancel_button(language, job_id),
            )
            async with download_slots:
                download_started = time.perf_counter()
                results = await materialize(target, mode, job_dir, status, language, buttons=cancel_button(language, job_id))
                download_ms = (time.perf_counter() - download_started) * 1000
                total_in = sum(result.size for result in results)
                if ephemeral and total_in > settings.group_max_file_size:
                    raise FileTooLargeError(
                        f"Arquivo acima do limite para grupos: {human_size(total_in)}. Limite: {human_size(settings.group_max_file_size)}."
                    )
                rejection = plan_rejection(target.user_id, total_in)
                if rejection:
                    raise FileTooLargeError(rejection)
                store.update_job(job_id, "running", bytes_in=total_in)
                if target.conversion:
                    convert_started = time.perf_counter()
                    await edit_status(status, tx(language, "stage_converting"), buttons=cancel_button(language, job_id))
                    results = [await convert_document(result, target.conversion, job_dir, turbo=settings.turbo_mode) for result in results]
                    converted_size = sum(result.size for result in results)
                    convert_elapsed = time.perf_counter() - convert_started
                    logger.info(
                        "convert_done job_id=%s target=%s files=%d size=%s elapsed_ms=%d mbps=%.2f turbo=%s",
                        job_id,
                        target.conversion,
                        len(results),
                        converted_size,
                        int(convert_elapsed * 1000),
                        (converted_size / 1024 / 1024) / convert_elapsed if convert_elapsed > 0 else 0.0,
                        settings.turbo_mode,
                    )
                    converted_rejection = plan_rejection(target.user_id, converted_size)
                    if converted_rejection:
                        raise FileTooLargeError(converted_rejection)
            await edit_status(
                status,
                tx(language, "stage_uploading", progress=render_progress(tx(language, "label_upload"), 0, sum(result.size for result in results), time.monotonic())),
                buttons=cancel_button(language, job_id),
            )
            async with upload_slots:
                upload_started = time.perf_counter()
                for result in results:
                    await send_result(target, result, mode, status, language, buttons=cancel_button(language, job_id))
                upload_ms = (time.perf_counter() - upload_started) * 1000
        store.update_job(job_id, "done", bytes_out=sum(result.size for result in results))
        logger.info(
            "job_done job_id=%s kind=%s user_id=%s total_ms=%d download_ms=%d upload_ms=%d",
            job_id,
            target.source,
            target.user_id,
            int((time.perf_counter() - started_at) * 1000),
            int(download_ms),
            int(upload_ms),
        )
        await delete_status(status)
        pending_targets.pop(target.token, None)
    except asyncio.CancelledError:
        store.update_job(job_id, "cancelled")
        logger.warning("job_cancelled job_id=%s kind=%s user_id=%s", job_id, target.source, target.user_id)
        await edit_status(status, tx(language, "cancelled"))
        raise
    except (BaixaAquiError, DownloadError, FileTooLargeError, MissingYtDlpError, SocialDownloadError, ConversionError, DriveDownloadError) as exc:
        store.update_job(job_id, "failed", error=str(exc))
        store.record_error(user_id=target.user_id, chat_id=target.chat_id, job_id=job_id, platform=target.source, stage="media", message=str(exc))
        logger.warning("job_failed job_id=%s kind=%s user_id=%s reason=%s", job_id, target.source, target.user_id, exc)
        if not silent:
            await edit_status(
                status,
                tx(language, "error_human", reason=humanize_provider_error(language, exc)),
                buttons=[[Button.inline(tx(language, "btn_retry"), f"retry:{target.token}".encode())]],
            )
    except Exception as exc:
        store.update_job(job_id, "failed", error=str(exc))
        store.record_error(user_id=target.user_id, chat_id=target.chat_id, job_id=job_id, platform=target.source, stage="media", message=str(exc))
        logger.exception("job_crash job_id=%s kind=%s user_id=%s", job_id, target.source, target.user_id)
        if not silent:
            await edit_status(status, tx(language, "error_human", reason=tx(language, "unexpected_media_error")))
    finally:
        if dedupe_key:
            lock = download_dedupe.get(dedupe_key)
            if lock and lock.locked():
                lock.release()
            download_dedupe.pop(dedupe_key, None)
        shutil.rmtree(job_dir, ignore_errors=True)


async def try_cached_file_send(job_id: str, target: PendingTarget, mode: UploadMode, status, language: str, ephemeral: bool) -> bool:
    if not settings.file_id_cache_enabled or not target.url or target.conversion or target.format_selector:
        return False
    cache_key = file_id_cache_key(target, mode)
    cached = store.file_id_get(cache_key)
    if not cached:
        return False
    try:
        await client.send_file(
            target.chat_id,
            cached["file_id"],
            caption=caption_for_cached(target),
            parse_mode="html",
        )
        store.update_job(job_id, "done")
        logger.info("job_file_id_cache_hit job_id=%s kind=%s user_id=%s mode=%s", job_id, target.source, target.user_id, cached["mode"])
        await delete_status(status)
        pending_targets.pop(target.token, None)
        return True
    except Exception as exc:
        store.file_id_delete(cache_key)
        logger.warning("job_file_id_cache_invalid job_id=%s reason=%s", job_id, exc)
        return False


def file_id_cache_key(target: PendingTarget, mode: UploadMode) -> str:
    raw = f"{target.url or ''}|{mode}|{target.format_selector or ''}|{target.conversion or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def caption_for_cached(target: PendingTarget) -> str:
    raw = target.caption or (target.social_info.description if target.social_info else None) or target.filename or BRANDING
    caption = preserve(raw, 900)
    if target.source.startswith("social"):
        caption = f"{caption.rstrip()}\n\n{BRANDING}" if caption.strip() else BRANDING
    return h(caption)


async def run_link_job(job_id: str, target: PendingTarget, status, language: str) -> None:
    job_dir = Path(tempfile.mkdtemp(prefix=f"{job_id}_", dir=settings.download_dir))
    started_at = time.perf_counter()
    try:
        logger.info("link_start job_id=%s user_id=%s", job_id, target.user_id)
        store.update_job(job_id, "running")
        async with job_slots:
            await edit_status(status, tx(language, "stage_linking"), buttons=cancel_button(language, job_id))
            fast_result = None
            try:
                fast_result = await try_fast_image_link(target, status, language, job_id)
            except ImageHostError as exc:
                logger.warning("link_image_host_fallback job_id=%s user_id=%s reason=%s", job_id, target.user_id, exc)
                if not settings.local_link_storage_enabled:
                    raise DownloadError(tx(language, "image_link_error"))
            if fast_result:
                public_url = fast_result.public_url
                store.record_link(
                    link_id=job_id,
                    user_id=target.user_id,
                    public_url=public_url,
                    internal_path="",
                    filename=target.filename or fast_result.filename,
                    mime_type=fast_result.mime_type,
                    size=fast_result.size,
                    sha256="",
                    expires_at=None,
                )
                text = tx(language, "link_done", url=public_url)
                buttons = link_buttons(language, job_id, public_url)
                if status:
                    await edit_html(status, text, buttons=buttons, link_preview=is_public_button_url(public_url))
                else:
                    await send_html(target.chat_id, text, buttons=buttons, link_preview=is_public_button_url(public_url))
                store.update_job(job_id, "done", bytes_in=fast_result.size, bytes_out=fast_result.size)
                logger.info(
                    "link_done job_id=%s user_id=%s provider=local_ephemeral total_ms=%d",
                    job_id,
                    target.user_id,
                    int((time.perf_counter() - started_at) * 1000),
                )
                pending_targets.pop(target.token, None)
                return
            async with download_slots:
                result = (await materialize(target, "document", job_dir, status, language))[0]
                rejection = plan_rejection(target.user_id, result.size)
                if rejection:
                    raise FileTooLargeError(rejection)
                store.update_job(job_id, "running", bytes_in=result.size)
            if is_image_filename(result.filename):
                try:
                    public_url = await image_host.upload(result.path)
                    store.record_link(
                        link_id=job_id,
                        user_id=target.user_id,
                        public_url=public_url,
                        internal_path="",
                        filename=target.filename or result.filename,
                        mime_type=result.mime_type,
                        size=result.size,
                        sha256="",
                        expires_at=None,
                    )
                    text = tx(language, "link_done", url=public_url)
                    buttons = link_buttons(language, job_id, public_url)
                    if status:
                        await edit_html(status, text, buttons=buttons, link_preview=is_public_button_url(public_url))
                    else:
                        await send_html(target.chat_id, text, buttons=buttons, link_preview=is_public_button_url(public_url))
                    store.update_job(job_id, "done", bytes_out=result.size)
                    logger.info("link_done job_id=%s user_id=%s provider=image_host total_ms=%d", job_id, target.user_id, int((time.perf_counter() - started_at) * 1000))
                    pending_targets.pop(target.token, None)
                    return
                except ImageHostError as exc:
                    logger.warning("link_image_host_fallback job_id=%s user_id=%s reason=%s", job_id, target.user_id, exc)
                    if not settings.local_link_storage_enabled:
                        raise DownloadError(tx(language, "image_link_error"))

            if not settings.local_link_storage_enabled:
                raise DownloadError(tx(language, "link_local_disabled"))

            stored = await link_storage.store(result.path, target.filename or result.filename)
            if not is_public_button_url(stored.public_url):
                link_storage.delete(stored.internal_path)
                if is_image_filename(result.filename):
                    raise DownloadError(tx(language, "image_link_error"))
                raise DownloadError(tx(language, "link_requires_public_base"))
            store.record_link(
                link_id=stored.link_id,
                user_id=target.user_id,
                public_url=stored.public_url,
                internal_path=str(stored.internal_path),
                filename=stored.filename,
                mime_type=stored.mime_type,
                size=stored.size,
                sha256=stored.sha256,
                expires_at=stored.expires_at,
            )
            store.update_job(job_id, "done", bytes_out=stored.size)
            logger.info("link_done job_id=%s user_id=%s provider=local total_ms=%d", job_id, target.user_id, int((time.perf_counter() - started_at) * 1000))
            text = tx(language, "link_done", url=stored.public_url)
            buttons = link_buttons(language, stored.link_id, stored.public_url)
            preview = is_public_button_url(stored.public_url)
            if status:
                await edit_html(status, text, buttons=buttons, link_preview=preview)
            else:
                await send_html(target.chat_id, text, buttons=buttons, link_preview=preview)
        pending_targets.pop(target.token, None)
    except (BaixaAquiError, DownloadError, FileTooLargeError, SocialDownloadError, ConversionError, ImageHostError) as exc:
        store.update_job(job_id, "failed", error=str(exc))
        store.record_error(user_id=target.user_id, chat_id=target.chat_id, job_id=job_id, platform=target.source, stage="link", message=str(exc))
        logger.warning("link_failed job_id=%s user_id=%s reason=%s", job_id, target.user_id, exc)
        text = tx(language, "error_human", reason=humanize_provider_error(language, exc))
        if status:
            await edit_html(status, text)
        else:
            await send_html(target.chat_id, text)
    except Exception as exc:
        store.update_job(job_id, "failed", error=str(exc))
        store.record_error(user_id=target.user_id, chat_id=target.chat_id, job_id=job_id, platform=target.source, stage="link", message=str(exc))
        logger.exception("link_crash job_id=%s user_id=%s", job_id, target.user_id)
        text = tx(language, "error_human", reason=tx(language, "link_generation_failed"))
        if status:
            await edit_html(status, text)
        else:
            await send_html(target.chat_id, text)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


async def materialize(target: PendingTarget, mode: UploadMode, job_dir: Path, status, language: str, *, buttons=None) -> list[DownloadResult]:
    progress_editor = ProgressEditor(
        status,
        tx(language, "label_download"),
        min(max(settings.progress_interval, 1), 2),
        wrapper=lambda body: tx(language, "stage_downloading", progress=body),
        buttons=buttons,
        percent_step=2,
    )

    async def update(current: int, total: int | None) -> None:
        await progress_editor.update(current, total)

    if target.source.startswith("direct"):
        key = f"direct:{target.url}:{target.filename or ''}"
        lock = download_dedupe.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                if target.source.startswith("direct:drive"):
                    result = await drive_downloader.download(
                        target.url or "",
                        job_dir,
                        target.filename,
                        update,
                    )
                else:
                    result = await remote_downloader.download(
                        target.url or "",
                        job_dir,
                        target.filename,
                        update,
                    )
        finally:
            download_dedupe.pop(key, None)
        return [result]
    if target.source.startswith("social"):
        last = 0.0
        last_text = ""

        async def social_update(text: str) -> None:
            nonlocal last, last_text
            if not status:
                return
            now = time.monotonic()
            if text == last_text:
                return
            if now - last < max(settings.progress_interval, 0.75) and not text.startswith("100"):
                return
            last = now
            last_text = text
            await edit_html(status, tx(language, "stage_downloading", progress=h(text)), buttons=buttons)

        key = f"social:{target.url}:{mode}:{target.format_selector or ''}"
        lock = download_dedupe.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                results = await social_downloader.download(
                    target.url or "",
                    job_dir,
                    target.filename,
                    mode,
                    social_update,
                    target.format_selector,
                    target.social_info,
                )
        finally:
            download_dedupe.pop(key, None)
        if target.url and is_youtube_url(target.url) and mode != "audio" and not await video_results_have_audio(results):
            logger.warning("youtube_audio_retry url=%s filename=%s", target.url, target.filename)
            fallback_dir = job_dir / "youtube_audio_retry"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            results = await social_downloader.download(
                target.url,
                fallback_dir,
                target.filename,
                mode,
                social_update,
                "best[ext=mp4][acodec!=none]/best[acodec!=none]/best",
                target.social_info,
            )
            if not await video_results_have_audio(results):
                raise SocialDownloadError(tx(language, "youtube_audio_missing"))
        elif mode != "audio" and not await video_results_have_audio(results):
            raise SocialDownloadError(tx(language, "youtube_audio_missing"))
        if target.caption:
            results = [replace_result_caption(item, target.caption) for item in results]
        return results
    return [await download_telegram_file(target, job_dir, status, language, buttons=buttons)]


def replace_result_caption(result: DownloadResult, caption: str) -> DownloadResult:
    return DownloadResult(result.path, result.filename, result.size, result.mime_type, caption)


async def download_telegram_file(target: PendingTarget, job_dir: Path, status, language: str, *, buttons=None) -> DownloadResult:
    message = await client.get_messages(target.chat_id, ids=target.message_id)
    if not message:
        raise DownloadError(tx(language, "original_file_missing"))
    progress = ProgressEditor(
        status,
        tx(language, "label_download"),
        min(max(settings.progress_interval, 1), 3),
        wrapper=lambda body: tx(language, "stage_downloading", progress=body),
        buttons=buttons,
    )
    started = time.perf_counter()
    downloaded = await message.download_media(file=str(job_dir), progress_callback=progress.as_callback())
    if not downloaded:
        raise DownloadError(tx(language, "telegram_file_download_failed"))
    path = Path(downloaded)
    filename = sanitize_filename(target.filename or message_filename(message)) or path.name
    if filename != path.name:
        new_path = unique_path(job_dir, filename)
        path.replace(new_path)
        path = new_path
    size = path.stat().st_size
    elapsed = time.perf_counter() - started
    logger.info(
        "telegram_download_done chat_id=%s file=%s size=%s elapsed_ms=%d mbps=%.2f turbo=%s",
        target.chat_id,
        path.name,
        size,
        int(elapsed * 1000),
        (size / 1024 / 1024) / elapsed if elapsed > 0 else 0.0,
        settings.turbo_mode,
    )
    return DownloadResult(path, path.name, size, getattr(getattr(message, "file", None), "mime_type", None), target.caption)


def caption_for_result(target: PendingTarget, result: DownloadResult) -> str:
    raw_caption = target.caption if target.caption is not None else (result.caption or result.filename)
    limit = 900 if target.source.startswith("social") else 1000
    caption = preserve(raw_caption, limit)
    if target.source.startswith("social"):
        caption = f"{caption.rstrip()}\n\n{BRANDING}" if caption.strip() else BRANDING
    return h(caption)


async def send_result(target: PendingTarget, result: DownloadResult, mode: UploadMode, status, language: str, *, buttons=None) -> None:
    send_mode = resolve_send_mode(mode, result.filename)
    if send_mode == "video" and not is_video_filename(result.filename):
        send_mode = resolve_send_mode("auto", result.filename)
    if send_mode == "audio" and not is_audio_filename(result.filename):
        send_mode = "document"
    caption = caption_for_result(target, result)
    probe_needed = (send_mode == "video" or is_video_filename(result.filename)) and not (
        settings.turbo_mode and not target.source.startswith("social") and not target.thumb_path
    )
    info = await media_probe.inspect(result.path) if probe_needed else None
    if send_mode == "video" and target.source.startswith("social") and info and not info.has_audio:
        raise SocialDownloadError(tx(language, "youtube_audio_missing"))
    if (
        send_mode == "video"
        and target.source.startswith("social")
        and info
        and info.duration
        and info.duration > 2
        and info.frame_count is not None
        and info.frame_count <= 3
    ):
        if is_instagram_target(target):
            static_photo = await media_probe.thumbnail(result.path, result.path.with_suffix(".jpg"))
            if static_photo and static_photo.exists():
                result = DownloadResult(
                    path=static_photo,
                    filename=static_photo.name,
                    size=static_photo.stat().st_size,
                    mime_type="image/jpeg",
                    caption=result.caption,
                )
                send_mode = "photo"
                info = None
            else:
                send_mode = "document"
        else:
            send_mode = "document"
    thumb = Path(target.thumb_path) if target.thumb_path else get_default_thumb(target.user_id)
    thumb = await normalize_thumb_path(thumb) if thumb else None
    generated_thumb = None
    if send_mode in {"video", "document"} and info and info.has_video and not thumb and not settings.turbo_mode:
        generated_thumb = await media_probe.thumbnail(result.path, result.path.with_suffix(".jpg"))
        thumb = generated_thumb

    await edit_status(status, tx(language, "stage_uploading", progress=render_progress(tx(language, "label_upload"), 0, result.size, time.monotonic())), buttons=buttons)
    is_social_upload = target.source.startswith("social")
    progress = ProgressEditor(
        status,
        tx(language, "label_upload"),
        min(max(settings.progress_interval, 1), 2 if is_social_upload else 4),
        wrapper=lambda body: tx(language, "stage_uploading", progress=body),
        buttons=buttons,
        percent_step=2 if is_social_upload else 5,
    )
    upload_progress_callback = progress.as_callback() if status else None
    force_document = send_mode == "document" and not (target.source.startswith("social") and is_image_filename(result.filename))

    def upload_mbps(elapsed_seconds: float) -> float:
        if elapsed_seconds <= 0:
            return 0.0
        return round((result.size / 1024 / 1024) / elapsed_seconds, 2)

    def log_upload_done(backend: str, elapsed_seconds: float, *, workers: int | None = None) -> None:
        logger.info(
            "upload_done backend=%s chat_id=%s file=%s size=%s elapsed_ms=%d mbps=%.2f workers=%s local_bot_api=%s send_mode=%s turbo=%s",
            backend,
            target.chat_id,
            result.filename,
            result.size,
            int(elapsed_seconds * 1000),
            upload_mbps(elapsed_seconds),
            workers if workers is not None else "-",
            bot_api.is_local,
            send_mode,
            settings.turbo_mode,
        )

    async def upload_with_telethon(file_arg):
        attrs = []
        if send_mode == "video" and info and info.width and info.height:
            attrs.append(
                DocumentAttributeVideo(
                    duration=int(info.duration or 0),
                    w=info.width,
                    h=info.height,
                    supports_streaming=True,
                )
            )
        last_error = None
        for attempt, delay in enumerate((0, 5, 15), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                sent = await client.send_file(
                    target.chat_id,
                    file_arg,
                    caption=caption,
                    parse_mode="html",
                    force_document=force_document,
                    thumb=str(thumb) if send_mode in {"video", "document"} and thumb and thumb.exists() else None,
                    supports_streaming=send_mode == "video",
                    attributes=attrs or None,
                    progress_callback=upload_progress_callback,
                )
                remember_file_id(target, mode, send_mode, sent)
                return
            except FloodWaitError as exc:
                last_error = exc
                await asyncio.sleep(min(exc.seconds, 60))
            except Exception as exc:
                last_error = exc
                logger.warning("upload_retry chat_id=%s file=%s attempt=%s reason=%s", target.chat_id, result.filename, attempt, exc)
        raise UploadFailedError(str(last_error) if last_error else "upload failed")

    async def upload_with_bot_api() -> bool:
        if settings.send_backend == "telethon":
            return False
        if target.source.startswith("social") and not bot_api.is_local:
            return False
        if not bot_api.supports_local_size(result.path):
            return False
        try:
            started = time.perf_counter()
            response = await bot_api.send_local_file(
                target.chat_id,
                result.path,
                filename=result.filename,
                caption=caption,
                mode=send_mode,
                thumbnail=thumb if send_mode in {"video", "document"} and thumb and thumb.exists() else None,
            )
            log_upload_done("bot_api_local" if bot_api.is_local else "bot_api_public", time.perf_counter() - started)
            remember_bot_api_file_id(target, mode, send_mode, response)
            return True
        except Exception as exc:
            logger.warning("bot_api_upload_fallback chat_id=%s file=%s reason=%s", target.chat_id, result.filename, exc)
            return False

    try:
        if await upload_with_bot_api():
            return

        if send_mode != "photo" and should_parallel_upload(result.path, settings.parallel_upload_enabled, settings.parallel_upload_threshold):
            try:
                workers = upload_workers_for_size(result.size, settings.parallel_upload_workers)
                started = time.perf_counter()
                uploaded = await upload_big_file_parallel(
                    client,
                    result.path,
                    result.filename,
                    workers,
                    upload_progress_callback or (lambda _current, _total: None),
                )
                await upload_with_telethon(uploaded)
                log_upload_done("telethon_parallel", time.perf_counter() - started, workers=workers)
                return
            except Exception as exc:
                logger.warning(
                    "parallel_upload_failed_fallback_to_telethon chat_id=%s file=%s size=%s workers=%s reason=%s",
                    target.chat_id,
                    result.filename,
                    result.size,
                    workers,
                    exc,
                )

        started = time.perf_counter()
        await upload_with_telethon(str(result.path))
        log_upload_done("telethon_normal", time.perf_counter() - started)
    finally:
        if generated_thumb:
            generated_thumb.unlink(missing_ok=True)


def remember_file_id(target: PendingTarget, requested_mode: UploadMode, send_mode: UploadMode, sent) -> None:
    if not settings.file_id_cache_enabled or not target.url or target.conversion or target.format_selector:
        return
    media = getattr(sent, "media", None)
    document = getattr(media, "document", None)
    photo = getattr(media, "photo", None)
    try:
        file_id = utils.pack_bot_file_id(document or photo)
    except Exception:
        file_id = None
    if not file_id:
        return
    try:
        store.file_id_set(file_id_cache_key(target, requested_mode), file_id, send_mode)
    except Exception:
        logger.exception("file_id_cache_store_failed url=%s", target.url)


def remember_bot_api_file_id(target: PendingTarget, requested_mode: UploadMode, send_mode: UploadMode, response: dict) -> None:
    if not settings.file_id_cache_enabled or not target.url or target.conversion or target.format_selector:
        return
    file_id = extract_bot_api_file_id(response)
    if not file_id:
        return
    try:
        store.file_id_set(file_id_cache_key(target, requested_mode), file_id, send_mode)
    except Exception:
        logger.exception("file_id_cache_store_failed url=%s", target.url)


def extract_bot_api_file_id(response: dict) -> str | None:
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    for key in ("video", "audio", "document", "photo"):
        value = result.get(key)
        if isinstance(value, dict) and isinstance(value.get("file_id"), str):
            return value["file_id"]
        if isinstance(value, list) and value:
            item = value[-1]
            if isinstance(item, dict) and isinstance(item.get("file_id"), str):
                return item["file_id"]
    return None


def is_instagram_target(target: PendingTarget) -> bool:
    hostname = (urlparse(target.url or "").hostname or "").lower()
    return "instagram" in hostname


def resolve_send_mode(mode: UploadMode, filename: str) -> UploadMode:
    if mode != "auto":
        return mode
    if is_image_filename(filename):
        return "photo"
    if is_video_filename(filename):
        return "video"
    if is_audio_filename(filename):
        return "audio"
    return "document"


def get_default_thumb(user_id: int) -> Path | None:
    raw = store.get_thumb(user_id)
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


async def normalize_thumb_path(path: Path) -> Path | None:
    if not path.exists():
        return None
    try:
        return await asyncio.to_thread(_normalize_thumb_path_sync, path)
    except Exception:
        return path if path.exists() else None


def _normalize_thumb_path_sync(path: Path) -> Path:
    from PIL import Image

    with Image.open(path) as image:
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((320, 320))
        target = path.with_suffix(".jpg")
        image.save(target, format="JPEG", quality=88, optimize=True)
    if target != path and path.exists():
        path.unlink(missing_ok=True)
    return target


async def save_default_thumbnail(target: PendingTarget, language: str, status) -> None:
    message = await client.get_messages(target.chat_id, ids=target.message_id)
    if not message or not is_image_message(message):
        await edit_html(status, tx(language, "unsupported"))
        return
    thumb_path = await download_message_to_temp(message, target.user_id, suffix=".jpg", persistent=True)
    store.set_thumb(target.user_id, str(thumb_path))
    await edit_html(status, tx(language, "thumb_saved"))


async def download_message_to_temp(message, user_id: int, suffix: str = "", persistent: bool = False) -> Path:
    root = settings.data_dir / "thumbnails" if persistent else settings.download_dir / f"thumb_{user_id}_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{uuid.uuid4().hex}{suffix or '.bin'}"
    saved = await message.download_media(file=str(path))
    if not saved:
        raise DownloadError("NÃ£o consegui salvar a imagem.")
    return await normalize_thumb_path(Path(saved)) or Path(saved)


async def cleanup_loop() -> None:
    while True:
        try:
            sessions.cleanup()
            cleanup_targets()
            cleanup_old_dirs(settings.download_dir, settings.temp_ttl_hours)
            for internal_path in store.cleanup_expired_links():
                if internal_path:
                    link_storage.delete(Path(internal_path))
            store.cleanup_cache()
            if settings.file_id_cache_enabled:
                store.file_id_cleanup(settings.file_id_cache_max_age_days)
        except Exception:
            logger.exception("cleanup_failed")
        await asyncio.sleep(900)


def purge_ephemeral_media() -> None:
    removed_downloads = cleanup_dir_contents(settings.download_dir) if settings.purge_media_on_start else 0
    removed_public = cleanup_dir_contents(settings.public_files_dir) if settings.purge_media_on_start else 0
    if removed_downloads or removed_public:
        logger.info(
            "startup_media_purge downloads=%s public_files=%s",
            removed_downloads,
            removed_public,
        )


async def start_link_server() -> None:
    if not settings.link_server_enabled and not CONTROL_AGENT_ENABLED:
        return
    if CONTROL_AGENT_ENABLED and not CONTROL_SECRET:
        raise RuntimeError("CONTROL_SECRET precisa estar configurado para ativar o control agent.")
    app = web.Application()
    async def health(_request):
        return web.json_response(
            {
                "status": "ok",
                "jobs_active": sum(len(tasks) for tasks in active_tasks.values()),
                "pending_targets": len(pending_targets),
                "uptime_seconds": int(time.time() - STARTED_AT),
            }
        )
    app.router.add_get("/health", health)
    app.router.add_get("/control/health", control_health)
    app.router.add_get("/control/metrics", control_metrics)
    app.router.add_post("/control/block", control_block)
    app.router.add_post("/control/broadcast", control_broadcast)
    if settings.link_server_enabled:
        app.router.add_static("/files", settings.public_files_dir, show_index=False)
    runner = web.AppRunner(app)
    await runner.setup()
    control_port = int(os.getenv("CONTROL_AGENT_PORT", "8787"))
    site_port = control_port if CONTROL_AGENT_ENABLED else settings.link_server_port
    site = web.TCPSite(runner, settings.link_server_host, site_port)
    await site.start()


async def main() -> None:
    purge_ephemeral_media()
    diagnostics = await run_diagnostics(settings)
    for item in diagnostics:
        level = logger.info if item.ok else logger.warning
        level("startup_check name=%s ok=%s detail=%s", item.name, item.ok, item.detail)
    if settings.local_link_storage_enabled and not is_public_http_url(settings.public_base_url):
        logger.warning("public_base_url_not_public value=%s", settings.public_base_url)
    await client.start(bot_token=settings.bot_token)
    await start_link_server()
    asyncio.create_task(cleanup_loop())
    me = await client.get_me()
    print(
        f"@{me.username or me.id} online. "
        f"Backend={settings.send_backend}. "
        f"Link server={settings.link_server_enabled}. "
        f"Local link storage={settings.local_link_storage_enabled}. "
        f"Purge on start={settings.purge_media_on_start}."
    )
    try:
        await client.run_until_disconnected()
    finally:
        await close_shared_http_session()


if __name__ == "__main__":
    asyncio.run(main())
