# ONPE Segunda Vuelta Scraper

Scraper automático para capturar resultados electorales de la segunda vuelta presidencial del ONPE (Oficina Nacional de Procesos Electorales) del Perú.

## ¿Qué hace?

- Intercepta la URL de la API interna del ONPE a través de Playwright (paso de descubrimiento, una sola vez).
- Hace polling a esa API cada 5, 10 o 15 minutos (configurable).
- Deduplica respuestas por hash SHA-256: solo guarda cuando hay cambio real.
- Almacena cada snapshot en dos formatos:
  - `data/snapshots/*.json` — archivos JSON crudos con timestamp.
  - `data/election.db` — base de datos SQLite con tablas `snapshots`, `regions` y `changes`.
- Calcula y registra deltas entre snapshots consecutivos (variación de actas y votos).

---

## Requisitos

- Python 3.12+
- Chromium (solo para el paso de descubrimiento):

```bash
playwright install chromium
```

---

## Instalación

```bash
pip install -e .
cp .env.example .env
```

Edita `.env` con tus valores. El archivo `.env.example` incluye todas las variables disponibles con sus valores por defecto.

---

## Paso 1: Descubrir el endpoint de la API (requerido una vez)

```bash
python main.py --discover
```

Esto abre un navegador Chromium con Playwright, intercepta las llamadas XHR/fetch que hace la página oficial del ONPE y escribe automáticamente `ONPE_API_URL` y `ONPE_SESSION_HEADERS` en tu archivo `.env`.

Solo necesitás hacer este paso una vez (o cuando el ONPE rote la URL o los headers de sesión).

---

## Paso 2: Probar una ejecución única

```bash
python main.py --once
```

Ejecuta un ciclo completo: fetch → deduplicación → parse → delta → almacenamiento. Imprime un resumen de una línea y termina.

---

## Paso 3: Ejecutar como daemon

```bash
python main.py --daemon
```

Inicia el scheduler APScheduler que ejecuta `--once` en el intervalo configurado por `SCRAPER_INTERVAL_MINUTES`. Corre indefinidamente hasta recibir `SIGTERM` o `SIGINT` (Ctrl+C).

---

## Despliegue en la nube con GitHub Actions

El workflow `.github/workflows/scraper.yml` ejecuta `python main.py --once` en un cron de GitHub Actions cada 10 minutos.

### Configurar los secretos del repositorio

Ve a **Settings → Secrets and variables → Actions → New repository secret** y agregá:

| Secret | Descripción |
|--------|-------------|
| `ONPE_API_URL` | La URL descubierta en el Paso 1 |
| `ONPE_SESSION_HEADERS` | JSON con los headers de sesión (ej: `{"Cookie": "...", "X-Token": "..."}`) |

Una vez configurados, el workflow corre automáticamente o podés dispararlo manualmente desde la pestaña **Actions → ONPE Scraper → Run workflow**.

Los snapshots generados en cada ejecución se suben como artefacto comprimido bajo el nombre `snapshots-{run_number}`.

---

## Salida de datos

```
data/
├── snapshots/          # JSON crudos, uno por ciclo con cambio real
│   └── 2025-06-08T12:00:00Z.json
└── election.db         # SQLite con tablas snapshots, regions, changes
```

---

## Ejemplos de consultas SQL para dashboard

```sql
-- Serie temporal de porcentajes de votos
SELECT scraped_at, candidato_1_pct, candidato_2_pct, actas_procesadas_pct
FROM snapshots ORDER BY scraped_at;

-- Último resultado disponible
SELECT * FROM snapshots ORDER BY scraped_at DESC LIMIT 1;

-- Variaciones detectadas a lo largo del tiempo
SELECT c.detected_at, c.delta_actas_pct, c.delta_c1_votos, c.delta_c2_votos
FROM changes c ORDER BY c.detected_at;

-- Resultados por región (snapshot más reciente)
SELECT r.region_nombre, r.candidato_1_pct, r.candidato_2_pct
FROM regions r
WHERE r.snapshot_id = (SELECT MAX(id) FROM snapshots)
ORDER BY r.region_nombre;
```

---

## Ajustar el intervalo de polling

Modificá `SCRAPER_INTERVAL_MINUTES` en tu `.env`. Valores válidos: `5`, `10` o `15`.

```env
SCRAPER_INTERVAL_MINUTES=5
```

---

## Variables de entorno disponibles

| Variable | Requerida | Default | Descripción |
|----------|-----------|---------|-------------|
| `ONPE_API_URL` | Sí (excepto `--discover`) | — | URL del endpoint de resultados |
| `ONPE_SESSION_HEADERS` | No | `{}` | JSON con headers HTTP de sesión |
| `SCRAPER_INTERVAL_MINUTES` | No | `10` | Intervalo en minutos (5, 10 o 15) |
| `DATA_DIR` | No | `./data` | Directorio de salida para snapshots y DB |
