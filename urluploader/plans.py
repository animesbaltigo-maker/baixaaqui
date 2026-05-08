from __future__ import annotations

from dataclasses import dataclass


GB = 1024 * 1024 * 1024
MB = 1024 * 1024


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price: str
    max_file_size: int | None
    daily_quota: int | None
    parallel_jobs: int
    timeout_seconds: int | None
    cooldown_seconds: int
    high_priority: bool
    default_caption: bool


PLANS: dict[str, Plan] = {
    "free": Plan(
        key="free",
        name="Gratuito",
        price="Gratuito",
        max_file_size=2 * GB,
        daily_quota=5 * GB,
        parallel_jobs=1,
        timeout_seconds=15 * 60,
        cooldown_seconds=60,
        high_priority=False,
        default_caption=False,
    ),
    "basico": Plan(
        key="basico",
        name="Basico",
        price="$1.99",
        max_file_size=4 * GB,
        daily_quota=20 * GB,
        parallel_jobs=1,
        timeout_seconds=None,
        cooldown_seconds=0,
        high_priority=True,
        default_caption=True,
    ),
    "basic": Plan(
        key="basico",
        name="Basico",
        price="$1.99",
        max_file_size=4 * GB,
        daily_quota=20 * GB,
        parallel_jobs=1,
        timeout_seconds=None,
        cooldown_seconds=0,
        high_priority=True,
        default_caption=True,
    ),
    "standard": Plan(
        key="standard",
        name="Standard",
        price="$2.99",
        max_file_size=4 * GB,
        daily_quota=50 * GB,
        parallel_jobs=2,
        timeout_seconds=None,
        cooldown_seconds=0,
        high_priority=True,
        default_caption=True,
    ),
    "pro": Plan(
        key="pro",
        name="Pro",
        price="$6.99",
        max_file_size=4 * GB,
        daily_quota=None,
        parallel_jobs=3,
        timeout_seconds=None,
        cooldown_seconds=0,
        high_priority=True,
        default_caption=True,
    ),
}


ADMIN_PLAN = Plan(
    key="admin",
    name="Admin",
    price="Livre",
    max_file_size=None,
    daily_quota=None,
    parallel_jobs=99,
    timeout_seconds=None,
    cooldown_seconds=0,
    high_priority=True,
    default_caption=True,
)


def normalize_plan_key(value: str | None) -> str:
    key = (value or "free").strip().lower()
    return PLANS.get(key, PLANS["free"]).key


def plan_for_key(value: str | None) -> Plan:
    return PLANS.get((value or "free").strip().lower(), PLANS["free"])


def plan_catalog_text() -> str:
    return (
        "<b>Planos</b>\n\n"
        "<b>Gratuito</b>\n"
        "- Arquivos ate 2 GB\n"
        "- 5 GB por dia\n"
        "- 1 processo paralelo\n"
        "- Timeout de 15 minutos\n"
        "- Intervalo entre tarefas\n"
        "Preco mensal: Gratuito\n\n"
        "<b>Basico</b>\n"
        "- Alta prioridade\n"
        "- Arquivos ate 4 GB\n"
        "- Legenda padrao\n"
        "- 20 GB por dia\n"
        "- 1 processo paralelo\n"
        "- Sem timeout e sem intervalo\n"
        "Preco mensal: $1.99\n\n"
        "<b>Standard</b>\n"
        "- Alta prioridade\n"
        "- Arquivos ate 4 GB\n"
        "- Legenda padrao\n"
        "- 50 GB por dia\n"
        "- 2 processos paralelos\n"
        "- Sem timeout e sem intervalo\n"
        "Preco mensal: $2.99\n\n"
        "<b>Pro</b>\n"
        "- Alta prioridade\n"
        "- Arquivos ate 4 GB\n"
        "- Legenda padrao\n"
        "- Uso diario ilimitado\n"
        "- 3 processos paralelos\n"
        "- Sem timeout e sem intervalo\n"
        "Preco mensal: $6.99"
    )
