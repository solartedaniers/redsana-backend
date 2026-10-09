# 🐍 RedSana API (backend)

API REST de RedSana con FastAPI. Autentica con los JWT de Supabase, guarda mediciones, dispositivos, evaluaciones, alertas y conversaciones en Postgres (SQLAlchemy + Alembic) y orquesta la IA del paquete `redsana-ai`: el asistente de seguridad y la detección de anomalías y cortes.

> Repositorios del proyecto: frontend · backend · IA (enlaces pendientes de publicar).

## Estructura

```
app/
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

La IA se construye solo en `app/core/ai_composition.py`; el resto del backend la usa a través de las interfaces de `redsana_ai` (`ChatEngine`, `SecurityChat`, `SecurityBriefing`, `AnomalyDetector`, `OutageDetector`).

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

## Despliegue

`render.yaml` describe el servicio de Render: build `pip install -r requirements.txt`, inicio con `uvicorn` y las variables secretas (`sync: false`) se cargan en el panel de Render.
