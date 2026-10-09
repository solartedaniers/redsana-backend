from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


# Sin auth ni base de datos a propósito: lo usa la medición web y cualquier trabajo extra inflaría la latencia.
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
