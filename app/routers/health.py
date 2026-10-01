from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


# Sin auth ni base de datos a proposito: lo usa la medicion web de latencia
# (cualquier trabajo extra aqui inflaria la latencia medida) y el health check del hosting.
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
