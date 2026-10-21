"""Microservicio de Inventario (API de consulta)."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException

from ..common.bus import EventBus, get_bus
from ..common.config import Settings, get_settings
from .service import InventarioRepository, InventarioService


def build_router(svc: InventarioService) -> APIRouter:
    r = APIRouter(tags=["inventario"])

    @r.get("/salud")
    def salud():
        return {"servicio": "inventario", "estado": "ok"}

    @r.get("/productos")
    def productos():
        return svc.repo.productos()

    @r.get("/productos/{sku}")
    def producto(sku: str):
        p = svc.repo.producto(sku)
        if not p:
            raise HTTPException(404, "Producto no encontrado")
        return p

    @r.get("/productos/{sku}/movimientos")
    def movimientos(sku: str):
        return svc.repo.movimientos(sku)

    @r.get("/alertas")
    def alertas():
        return svc.alertas

    return r


def create_app(settings: Settings | None = None, bus: EventBus | None = None) -> FastAPI:
    settings = settings or get_settings()
    svc = InventarioService(InventarioRepository(settings.db_path), bus or get_bus(settings.redis_url), settings.stock_minimo)
    svc.suscribir()
    app = FastAPI(title="Andina · Servicio de Inventario", version="1.0.0")
    app.include_router(build_router(svc))
    app.state.service = svc
    return app
