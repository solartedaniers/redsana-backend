from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import admin_households, admin_users, alerts, devices, me, network_metrics

settings = get_settings()

app = FastAPI(title="RedSana API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)
app.include_router(devices.router)
app.include_router(network_metrics.router)
app.include_router(alerts.router)
app.include_router(admin_households.router)
app.include_router(admin_users.router)
