# 🐍 RedSana API (backend)

API REST de RedSana con FastAPI. Autentica con los JWT de Supabase, guarda mediciones, dispositivos, evaluaciones, alertas y conversaciones en Postgres (SQLAlchemy + Alembic) y orquesta la IA del paquete `redsana-ai`: el asistente de seguridad y la detección de anomalías y cortes.

## 🔗 Repositorios del proyecto

| Repositorio | Qué contiene |
|---|---|
| [redsana-frontend](https://github.com/solartedaniers/redsana-frontend) | App Angular + Tauri (web en Vercel, instalador en Releases) |
| [redsana-backend](https://github.com/solartedaniers/redsana-backend) (este) | API FastAPI desplegada en Render; instala `redsana-ai` por tag |
| [redsana-ai](https://github.com/solartedaniers/redsana-ai) | Paquete Python con el asistente y los detectores |

## Estructura

```
app/
├── ai_gateway/    # Acceso a la IA: AiGateway con implementación local (paquete) y remota (servicio HTTP)
├── core/          # Configuración, seguridad, base de datos y ai_composition.py
├── domain/        # Reglas de negocio puras (sin I/O)
├── models/        # Modelos SQLAlchemy
├── repositories/  # Contratos e implementaciones de acceso a datos
├── schemas/       # Esquemas Pydantic de la API
├── services/      # Orquestación de casos de uso
└── routers/       # Endpoints HTTP
alembic/           # Migraciones
tests/
```

La IA se construye solo en `app/core/ai_composition.py`; el resto del backend la usa a través de `AiGateway` y de las interfaces de `redsana_ai` (`SecurityChat`, `SecurityBriefing`, `AnomalyDetector`, `OutageDetector`), sin saber si corre aquí o en el servicio de IA.

## Ejecución local

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS/Linux
pip install -r requirements-dev.txt   # dependencias + pytest (incluye redsana-ai)

cp .env.example .env           # completar las variables (documentadas en el archivo)
alembic upgrade head
uvicorn app.main:app --reload
```

## Pruebas

```bash
pytest
```

- Las pruebas necesitan un `.env` con las variables obligatorias (ver `.env.example`). `DATABASE_URL` debe tener formato válido de Postgres porque el engine se crea al importar, pero las pruebas no se conectan a ella: usan SQLite en memoria, también para las tareas en segundo plano.
- La prueba que verifica que cada clave de alerta tiene texto en el frontend lee los diccionarios i18n del repo del frontend. Sin `FRONTEND_I18N_DIR` se salta. Para correrla, clona los dos repos lado a lado y define la variable (en el entorno o en `.env`), relativa a esta carpeta:

  ```
  proyectos/
  ├── redsana-backend/    # este repo
  └── redsana-frontend/
  ```

  ```bash
  FRONTEND_I18N_DIR=../redsana-frontend/public/assets/i18n pytest
  ```

## Estado de la red (umbrales)

Cada medición se guarda con su estado (`good`, `warning` o `critical`), calculado por latencia **o** pérdida de paquetes con los umbrales `NETWORK_STATUS_*` (por defecto 80 / 150 ms y 1 / 5 %; ver `.env.example`). `GET /api/network-metrics/thresholds` los publica para que el gráfico del frontend clasifique igual que el dashboard. Cambiarlos solo afecta a las mediciones nuevas: el estado de las guardadas no se recalcula.

El puntaje de seguridad usa los rangos y pesos `SECURITY_SCORE_*` (por defecto: bueno desde 80, regular desde 50; cuestionario 30 % y análisis técnico 70 %). `GET /api/security-assessments/score-config` los publica para que el frontend coloree y divida el puntaje igual que el backend.

## Modo de la IA (`AI_MODE`)

| Modo | Qué hace |
|---|---|
| `remote` (**producción**) | Chat, resumen y detectores llaman al servicio de IA desplegado aparte en Render ([redsana-ai](https://github.com/solartedaniers/redsana-ai)). Exige `AI_SERVICE_URL` y `AI_SERVICE_API_KEY`; Groq vive en el servicio. |
| `local` (valor por defecto del código) | El paquete `redsana_ai` corre dentro de este proceso, sin el servicio de IA; útil en desarrollo. Exige `GROQ_API_KEY`. |

Producción usa `remote`. Cambiar de modo es solo la variable, sin tocar código.

En modo remoto:

- **Chat y resumen** siempre van al servicio. Si está dormido o arrancando (Render apaga el plan gratuito tras un rato sin uso), responden `503` con `{"detail": "ai_warming_up"}` y `Retry-After`, que el frontend muestra como "IA encendiendo" en vez de un error. La pregunta del chat se guarda solo cuando hay respuesta, así que reintentar no la duplica. Un fallo de Groq dentro del servicio sigue siendo `502`, igual que en modo local.
- **Detectores en segundo plano** (anomalías y cortes, que corren con cada medición): cualquier petición despierta un servicio de Render, así que solo usan el servicio dentro de una ventana de `AI_SERVICE_INTERACTIVE_WINDOW_SECONDS` tras el último uso interactivo (calentamiento, chat o resumen). Fuera de ella, o si el servicio falla, usan el paquete local, que da el mismo resultado (lo prueban las pruebas de paridad). Estas llamadas no renuevan la ventana.
- **Cliente HTTP** (`AiServiceClient`, urllib de la stdlib): timeout por llamada (`AI_SERVICE_TIMEOUT_SECONDS`), reintentos limitados (`AI_SERVICE_MAX_RETRIES`, con espera creciente desde `AI_SERVICE_RETRY_BACKOFF_SECONDS`) solo ante conexión rechazada o `502/503/504` del proxy, y errores tipados (`AiServiceUnavailableError`, `AiServiceChatEngineError`, `AiServiceRejectedError`, `AiServiceResponseError`).

| Endpoint | Qué hace |
|---|---|
| `GET /api/ai/status` | `{"status": "ready" \| "warming_up" \| "unavailable"}`. Liviano: con sesión pero sin base de datos; en modo local siempre `ready`. |
| `POST /api/ai/warm-up` | `202` con el estado actual; despierta el servicio en segundo plano (hasta `AI_SERVICE_WARM_UP_TIMEOUT_SECONDS`; cada consulta espera hasta `AI_SERVICE_WARM_UP_PROBE_TIMEOUT_SECONDS` y queda en el log como `AI warm-up probe N: ...`) y abre la ventana de uso interactivo. |

Todas las variables están documentadas en `.env.example`.

## Nombres de rutas

Las rutas usan sustantivos en inglés, en plural y con guiones. Estas cambiaron de nombre; el anterior sigue respondiendo igual (misma autenticación, mismo CORS) como alias oculto en `/docs`, porque lo usan el instalador 0.1.5 y la web ya desplegada:

| Nombre actual | Alias anterior |
|---|---|
| `GET, PATCH /api/users/me` | `/api/me` |
| `/api/chat-conversations/...` (lista, creación, mensajes, resumen `briefings`) | `/api/conversations/...` |
| `GET /api/alerts/recent?since=` | `/api/alerts/new` |
| `GET /api/admin/platform-metrics` | `/api/admin/metrics` |

`tests/test_route_aliases.py` comprueba que ambos nombres responden lo mismo. Los alias se pueden quitar cuando ya no quede ningún instalador 0.1.5 en uso.

## Versión de la IA

`redsana-ai` se instala desde su repositorio de GitHub, fijado a un tag en `requirements.txt`:

```
redsana-ai @ git+https://github.com/solartedaniers/redsana-ai.git@v0.1.0
```

Para actualizarla:

1. En el repo de la IA, sube `version` en `pyproject.toml`, haz commit, crea el tag anotado (`git tag -a v0.2.0 -m "..."`) y súbelo (`git push origin v0.2.0`).
2. Aquí, cambia `@v0.1.0` por el tag nuevo en `requirements.txt`, ejecuta `pip install -r requirements.txt` y corre `pytest`.
3. Haz commit y push: Render instala la versión nueva en el siguiente despliegue.

Para probar cambios de la IA sin publicar un tag, instala tu copia local encima: `pip install -e ../redsana-ai`.

## Despliegue

`render.yaml` describe el servicio de Render como corre en producción: build `pip install -r requirements.txt`, inicio con `uvicorn`, `AI_MODE=remote` con `AI_SERVICE_URL` del servicio de IA y un calentamiento de hasta 600 s. Los secretos (`DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `NETWORK_ID_SECRET`, `AI_SERVICE_API_KEY`, `GROQ_API_KEY`) van con `sync: false`: su valor solo vive en el panel de Render. Para volver al modo local basta poner `AI_MODE=local` en el panel (exige `GROQ_API_KEY`).
