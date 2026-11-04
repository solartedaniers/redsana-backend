import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.realtime_composition import get_realtime_hub
from app.routers import (
    admin_households,
    admin_metrics,
    admin_users,
    ai,
    alerts,
    chat_conversations,
    devices,
    health,
    me,
    network_metrics,
    realtime,
    security_assessments,
)

# uvicorn solo configura sus loggers: sin esto Python descartaba los INFO de la app (p. ej. el calentamiento de la IA).
logging.basicConfig(format="%(levelname)s:     %(name)s: %(message)s")
logging.getLogger("app").setLevel(logging.INFO)

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Solo prepara el bus; no programa tráfico: sin sockets abiertos no hay pings ni mensajes hacia el servicio.
    hub = get_realtime_hub()
    await hub.start()
    try:
        yield
    finally:
        await hub.stop()


app = FastAPI(title="RedSana API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(me.router)
app.include_router(devices.router)
app.include_router(network_metrics.router)
app.include_router(alerts.router)
app.include_router(admin_households.router)
app.include_router(admin_users.router)
app.include_router(security_assessments.router)
app.include_router(admin_metrics.router, prefix=admin_metrics.PLATFORM_METRICS_PREFIX)
app.include_router(admin_metrics.router, prefix=admin_metrics.LEGACY_PLATFORM_METRICS_PREFIX, include_in_schema=False)
app.include_router(chat_conversations.router, prefix=chat_conversations.CHAT_CONVERSATIONS_PREFIX)
app.include_router(
    chat_conversations.router, prefix=chat_conversations.LEGACY_CHAT_CONVERSATIONS_PREFIX, include_in_schema=False
)
app.include_router(ai.router)
app.include_router(realtime.router)
