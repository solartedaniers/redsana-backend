import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.cache.owner_cache import CacheEntry, OwnerCache
from app.core.authorization import get_current_user
from app.core.cache_composition import get_owner_cache
from app.core.config import get_settings
from app.core.database import get_db
from app.core.realtime_composition import get_event_publisher
from app.core.security import get_current_claims, owner_id_from_claims
from app.domain.device_presence import is_device_online, latest_seen_among
from app.models.device import Device
from app.realtime.events import DEVICES_UPDATED, RealtimeEvent
from app.realtime.publisher import EventPublisher
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.publishing_alert_repository import PublishingAlertRepository
from app.schemas.device import DeviceCreate, DeviceRead, DeviceSyncRequest, DeviceUpdate
from app.services.device_service import DeviceNotFoundError, DeviceService
from app.services.untrusted_device_alert_service import UntrustedDeviceAlertService

# Cuenta suspendida: 403 en todo el router, no solo donde se usa el perfil (get_current_user lo comprueba).
router = APIRouter(prefix="/api/devices", tags=["devices"], dependencies=[Depends(get_current_user)])

DEVICES_CACHE = CacheEntry("devices", TypeAdapter(list[DeviceRead]))


def _to_device_read(device: Device, latest_seen: datetime | None) -> DeviceRead:
    return DeviceRead(
        id=device.id,
        name=device.name,
        mac_address=device.mac_address,
        ip_address=device.ip_address,
        trust=device.trust,
        first_seen=device.first_seen,
        last_seen=device.last_seen,
        is_online=is_device_online(device, latest_seen),
        network_role=device.network_role,
    )


def _get_service(db: Session = Depends(get_db)) -> DeviceService:
    return DeviceService(SqlAlchemyDeviceRepository(db))


def _get_untrusted_alert_service(
    db: Session = Depends(get_db), publisher: EventPublisher = Depends(get_event_publisher)
) -> UntrustedDeviceAlertService:
    return UntrustedDeviceAlertService(PublishingAlertRepository(db, publisher))


def _devices_changed(owner_id: uuid.UUID, cache: OwnerCache, publisher: EventPublisher) -> None:
    """Después del commit: la caché deja de servir lo viejo y los clientes abiertos vuelven a pedir la lista."""
    cache.invalidate(owner_id)
    publisher.publish(RealtimeEvent.now(DEVICES_UPDATED, owner_id))


@router.get("", response_model=list[DeviceRead])
def list_devices(
    claims: dict[str, Any] = Depends(get_current_claims),
    service: DeviceService = Depends(_get_service),
    cache: OwnerCache = Depends(get_owner_cache),
) -> list[DeviceRead]:
    owner_id = owner_id_from_claims(claims)

    def load() -> list[DeviceRead]:
        devices = service.list_devices(owner_id)
        latest_seen = latest_seen_among(devices)
        return [_to_device_read(device, latest_seen) for device in devices]

    return cache.get_or_load(owner_id, DEVICES_CACHE, get_settings().cache_devices_ttl_seconds, load)


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
def create_device(
    payload: DeviceCreate,
    claims: dict[str, Any] = Depends(get_current_claims),
    service: DeviceService = Depends(_get_service),
    cache: OwnerCache = Depends(get_owner_cache),
    publisher: EventPublisher = Depends(get_event_publisher),
) -> DeviceRead:
    device = service.create_device(owner_id_from_claims(claims), payload)
    _devices_changed(owner_id_from_claims(claims), cache, publisher)
    latest_seen = latest_seen_among(service.list_devices(owner_id_from_claims(claims)))
    return _to_device_read(device, latest_seen)


@router.patch("/{device_id}", response_model=DeviceRead)
def update_device(
    device_id: uuid.UUID,
    payload: DeviceUpdate,
    claims: dict[str, Any] = Depends(get_current_claims),
    service: DeviceService = Depends(_get_service),
    cache: OwnerCache = Depends(get_owner_cache),
    publisher: EventPublisher = Depends(get_event_publisher),
) -> DeviceRead:
    try:
        device = service.update_device(device_id, owner_id_from_claims(claims), payload)
    except DeviceNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found") from error
    _devices_changed(owner_id_from_claims(claims), cache, publisher)
    latest_seen = latest_seen_among(service.list_devices(owner_id_from_claims(claims)))
    return _to_device_read(device, latest_seen)


@router.post("/sync", response_model=list[DeviceRead])
def sync_devices(
    payload: DeviceSyncRequest,
    claims: dict[str, Any] = Depends(get_current_claims),
    service: DeviceService = Depends(_get_service),
    untrusted_alerts: UntrustedDeviceAlertService = Depends(_get_untrusted_alert_service),
    cache: OwnerCache = Depends(get_owner_cache),
    publisher: EventPublisher = Depends(get_event_publisher),
) -> list[DeviceRead]:
    owner_id = owner_id_from_claims(claims)
    devices = service.sync_discovered_devices(owner_id, payload.devices)
    # También cambia el diagnóstico de /latest, que cuenta los dispositivos conectados.
    _devices_changed(owner_id, cache, publisher)
    # El router orquesta: el servicio de dispositivos no sabe nada de alertas.
    untrusted_alerts.alert_for_scan(owner_id, devices)
    latest_seen = latest_seen_among(devices)
    return [_to_device_read(device, latest_seen) for device in devices]
