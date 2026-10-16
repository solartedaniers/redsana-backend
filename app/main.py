import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
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
    security_assessments,
)

# uvicorn solo configura sus loggers: sin esto Python descartaba los INFO de la app (p. ej. el calentamiento de la IA).
logging.basicConfig(format="%(levelname)s:     %(name)s: %(message)s")
logging.getLogger("app").setLevel(logging.INFO)

settings = get_settings()

app = FastAPI(title="RedSana API")

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
app.include_router(admin_metrics.router)
app.include_router(chat_conversations.router)
app.include_router(ai.router)
