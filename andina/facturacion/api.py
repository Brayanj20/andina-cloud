"""Microservicio de Facturación: registra facturas electrónicas y publica eventos."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request

from ..common.bus import EventBus, Evento, get_bus
from ..common.config import Settings, get_settings
from .domain import FacturaInvalida
from .parsers import ParserFactory
from .repository import FacturaDuplicada, FacturaRepository, SqliteFacturaRepository


class FacturacionService:
    """Capa de aplicación: orquesta parser, dominio, repositorio y bus."""

    def __init__(self, repo: FacturaRepository, bus: EventBus, settings: Settings):
        self.repo, self.bus, self.settings = repo, bus, settings

    def registrar(self, contenido: bytes, content_type: str):
        factura = ParserFactory.para(content_type).parse(contenido)
        factura.validar()
        factura.clasificar(self.settings.nit_empresa)
        self.repo.guardar(factura)
        self.bus.publish(Evento("FacturaRegistrada", factura.to_dict()))
        return factura

    def resumen(self, desde: Optional[date], hasta: Optional[date]) -> dict:
        fs = self.repo.listar(desde=desde, hasta=hasta)
        tot = lambda tipo, campo: sum((getattr(f, campo) for f in fs if f.tipo == tipo), Decimal("0"))
        return {
            "desde": desde.isoformat() if desde else None, "hasta": hasta.isoformat() if hasta else None,
            "facturas": len(fs),
            "ventas": {"cantidad": sum(f.tipo == "venta" for f in fs), "total": str(tot("venta", "total")), "iva": str(tot("venta", "iva"))},
            "compras": {"cantidad": sum(f.tipo == "compra" for f in fs), "total": str(tot("compra", "total")), "iva": str(tot("compra", "iva"))},
        }


def build_router(svc: FacturacionService) -> APIRouter:
    r = APIRouter(tags=["facturacion"])

    @r.get("/salud")
    def salud():
        return {"servicio": "facturacion", "estado": "ok"}

    @r.post("/facturas", status_code=201)
    async def registrar(request: Request):
        try:
            f = svc.registrar(await request.body(), request.headers.get("content-type", ""))
        except FacturaDuplicada as e:
            raise HTTPException(409, str(e))
        except FacturaInvalida as e:
            raise HTTPException(422, str(e))
        return f.to_dict()

    @r.get("/facturas")
    def listar(tipo: Optional[str] = None, desde: Optional[date] = None, hasta: Optional[date] = None):
        return [f.to_dict() for f in svc.repo.listar(tipo, desde, hasta)]

    @r.get("/facturas/{id_}")
    def obtener(id_: int):
        f = svc.repo.obtener(id_)
        if not f:
            raise HTTPException(404, "Factura no encontrada")
        return f.to_dict()

    @r.get("/reportes/resumen")
    def resumen(desde: Optional[date] = None, hasta: Optional[date] = None):
        return svc.resumen(desde, hasta)

    return r


def create_app(settings: Settings | None = None, bus: EventBus | None = None) -> FastAPI:
    settings = settings or get_settings()
    svc = FacturacionService(SqliteFacturaRepository(settings.db_path), bus or get_bus(settings.redis_url), settings)
    app = FastAPI(title="Andina · Servicio de Facturación", version="1.0.0")
    app.include_router(build_router(svc))
    app.state.service = svc
    return app
