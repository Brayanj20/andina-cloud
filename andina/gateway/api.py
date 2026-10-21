"""API Gateway: punto único de entrada.

Responsabilidades: autenticación por API key, enrutamiento a los
microservicios, reintentos con backoff y Circuit Breaker por servicio, y un
endpoint de salud agregado (patrón Health Endpoint Monitoring).
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

from ..common.config import Settings, get_settings
from ..common.resilience import CircuitBreaker, CircuitOpenError, reintentar


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()
    rutas = {"facturacion": settings.facturacion_url, "inventario": settings.inventario_url}
    breakers = {k: CircuitBreaker(umbral_fallos=3, tiempo_reset=30) for k in rutas}
    client = httpx.AsyncClient(timeout=5.0, transport=transport)
    app = FastAPI(title="Andina · API Gateway", version="1.0.0")
    app.state.breakers = breakers

    async def llamar(servicio: str, metodo: str, path: str, **kw) -> httpx.Response:
        url = rutas[servicio].rstrip("/") + "/" + path.lstrip("/")

        async def una_vez():
            resp = await client.request(metodo, url, **kw)
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError("error del servicio", request=resp.request, response=resp)
            return resp

        return await breakers[servicio].llamar(lambda: reintentar(una_vez, intentos=3, base=0.1,
                                                                   reintentables=(httpx.TransportError, httpx.HTTPStatusError)))

    @app.get("/salud")
    async def salud():
        estado = {}
        for s in rutas:
            try:
                r = await llamar(s, "GET", "/salud")
                estado[s] = "ok" if r.status_code == 200 else f"http {r.status_code}"
            except Exception:
                estado[s] = "caido"
            estado[s + "_circuito"] = breakers[s].estado
        return {"gateway": "ok", **estado}

    @app.api_route("/api/{servicio}/{path:path}", methods=["GET", "POST"])
    async def proxy(servicio: str, path: str, request: Request):
        if request.headers.get("x-api-key") not in settings.api_keys:
            raise HTTPException(401, "API key inválida o ausente")
        if servicio not in rutas:
            raise HTTPException(404, "Servicio desconocido")
        try:
            r = await llamar(servicio, request.method, path, params=dict(request.query_params),
                             content=await request.body(),
                             headers={"content-type": request.headers.get("content-type", "application/json")})
        except CircuitOpenError as e:
            raise HTTPException(503, str(e))
        except (httpx.TransportError, httpx.HTTPStatusError):
            raise HTTPException(502, f"El servicio {servicio} no respondió")
        return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))

    return app
