# Andina Cloud: plataforma de facturación e inventario

Prototipo funcional de la actividad **"Orquestando códigos: la sinfonía de los sistemas"** (Arquitectura de Software, Tecnológica del Oriente).

Lleva la facturación electrónica y el inventario de **Distribuciones Andina S.A.S.** (empresa ficticia del caso de estudio) a una arquitectura de **microservicios en la nube**. El sistema registra facturas electrónicas UBL 2.1 (el estándar DIAN), las clasifica como venta o compra y actualiza el inventario de forma **asíncrona** mediante eventos.

```
Cliente ──HTTPS──▶ API Gateway ──▶ Servicio de Facturación ──XADD──▶ Redis Streams ──▶ Servicio de Inventario
                   (API key,          (parsers Strategy,                (Pub/Sub,          (consumidor idempotente,
                    retry, circuit     repositorio, reportes)            competing          stock, kardex, alertas)
                    breaker, salud)                                      consumers)
```

## Patrones de diseño aplicados

| Patrón | Dónde | Para qué |
|---|---|---|
| Microservicios + **API Gateway** | `andina/gateway/api.py` | Punto único de entrada, autenticación y enrutamiento |
| **Publicador/Suscriptor** + Competing Consumers | `andina/common/bus.py` | Desacoplar facturación de inventario y escalar consumidores |
| **Consumidor idempotente** | `andina/inventario/service.py` | Entrega "al menos una vez" sin duplicar movimientos |
| **Retry** con backoff exponencial + **Circuit Breaker** | `andina/common/resilience.py` | Tolerar fallos transitorios y evitar fallas en cascada |
| **Health Endpoint Monitoring** | `GET /salud` en cada servicio | Monitoreo y reinicio automático en la nube |
| **External Configuration Store** (12-Factor) | `andina/common/config.py` | Misma imagen en local, pruebas y nube |
| **Database per Service** + **Repository** | `*/repository.py`, `service.py` | Autonomía de datos y cambio de motor sin tocar la lógica |
| **Strategy** + **Factory** | `andina/facturacion/parsers.py` | Agregar formatos de factura sin modificar el servicio |

## Estructura

```
andina/
  common/       config.py · bus.py · resilience.py
  facturacion/  domain.py · parsers.py · repository.py · api.py
  inventario/   service.py · api.py
  gateway/      api.py
  monolito.py   modo demo "todo en uno" (bus en memoria)
samples/        facturas UBL de ejemplo (venta y compra en AttachedDocument)
tests/          10 pruebas automatizadas (pytest)
docs/diagramas  UML en PlantUML (.puml) y PNG/SVG
Dockerfile · docker-compose.yml · render.yaml
```

## Ejecutar

### 1. Pruebas

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q
```

### 2. Demo rápida (un solo proceso)

```bash
uvicorn andina.monolito:create_app --factory --reload
# Swagger: http://localhost:8000/facturacion/docs  y  http://localhost:8000/inventario/docs
curl -X POST localhost:8000/facturacion/facturas -H "content-type: application/xml" --data-binary @samples/factura_compra_attached.xml
curl -X POST localhost:8000/facturacion/facturas -H "content-type: application/xml" --data-binary @samples/factura_venta.xml
curl localhost:8000/inventario/productos
curl localhost:8000/inventario/alertas
curl localhost:8000/facturacion/reportes/resumen
```

### 3. Arquitectura completa con Docker (gateway + 2 servicios + Redis)

```bash
docker compose up --build
curl -H "X-API-Key: demo-key" -X POST localhost:8000/api/facturacion/facturas \
     -H "content-type: application/xml" --data-binary @samples/factura_compra_attached.xml
curl -H "X-API-Key: demo-key" localhost:8000/api/inventario/productos
curl localhost:8000/salud
# Escalar consumidores de inventario:
docker compose up --scale inventario=3
```

## Despliegue en la nube (Render)

- **Opción A, demo gratuita:** crear un *Web Service* desde este repositorio con runtime Docker y la variable `APP=monolito`. Render asigna una URL pública `https://<nombre>.onrender.com`.
- **Opción B, arquitectura completa:** *New → Blueprint* y seleccionar este repositorio. `render.yaml` crea el gateway (web), los dos servicios privados y el Redis administrado. Los servicios privados requieren un plan de pago.

La misma imagen funciona en Google Cloud Run, Azure Container Apps o AWS App Runner, porque toda la configuración va por variables de entorno (`.env.example`).

## Variables de entorno

| Variable | Uso | Valor por defecto |
|---|---|---|
| `APP` | Componente a ejecutar: `gateway`, `facturacion`, `inventario` o `monolito` | `monolito` |
| `NIT_EMPRESA` | NIT que define venta o compra | `900123456` |
| `REDIS_URL` | Bus de eventos; vacío usa el bus en memoria | vacío |
| `DB_PATH` | Ruta de SQLite (en producción: PostgreSQL) | `:memory:` |
| `STOCK_MINIMO` | Umbral de alerta de stock | `5` |
| `API_KEYS` | Claves aceptadas por el gateway, separadas por comas | `demo-key` |
| `FACTURACION_URL`, `INVENTARIO_URL` | URL internas de los servicios | `localhost` |

## Autor

Brayan Julián Herrera Rodríguez · Ingeniería de Software · 2026
