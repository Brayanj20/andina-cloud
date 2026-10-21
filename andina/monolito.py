"""Modo demo "todo en uno": ambos servicios en un solo proceso con bus en memoria.

Útil para desplegar la demo en un plan gratuito con un único servicio web.
Rutas: /facturacion/... y /inventario/...
"""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from .common.bus import InMemoryBus
from .common.config import get_settings
from .facturacion.api import create_app as crear_facturacion
from .inventario.api import create_app as crear_inventario


def create_app() -> FastAPI:
    settings = get_settings()
    bus = InMemoryBus()
    app = FastAPI(title="Distribuciones Andina · Plataforma de facturación e inventario (demo)", version="1.0.0")
    app.mount("/facturacion", crear_facturacion(settings, bus))
    app.mount("/inventario", crear_inventario(settings, bus))

    @app.get("/", include_in_schema=False)
    def inicio():
        return RedirectResponse("/facturacion/docs")

    @app.get("/salud")
    def salud():
        return {"modo": "monolito-demo", "facturacion": "ok", "inventario": "ok"}

    return app
