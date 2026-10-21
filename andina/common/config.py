"""Configuración externa (patrón External Configuration Store / 12-Factor).

Toda la configuración se lee de variables de entorno para que la misma imagen
de contenedor funcione en local, en pruebas y en la nube.
"""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _url(name: str, default: str) -> str:
    """Acepta 'host:puerto' (como lo entregan algunas nubes) y le agrega el esquema."""
    v = _env(name, default)
    return v if "://" in v else f"http://{v}"


@dataclass(frozen=True)
class Settings:
    # NIT de la empresa: define si una factura es de venta (emisor = empresa) o de compra.
    nit_empresa: str = field(default_factory=lambda: _env("NIT_EMPRESA", "900123456"))
    # Si está vacío se usa el bus en memoria (modo monolito / pruebas).
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL"))
    db_path: str = field(default_factory=lambda: _env("DB_PATH", ":memory:"))
    stock_minimo: int = field(default_factory=lambda: int(_env("STOCK_MINIMO", "5")))
    api_keys: tuple = field(default_factory=lambda: tuple(k for k in _env("API_KEYS", "demo-key").split(",") if k))
    facturacion_url: str = field(default_factory=lambda: _url("FACTURACION_URL", "http://localhost:8001"))
    inventario_url: str = field(default_factory=lambda: _url("INVENTARIO_URL", "http://localhost:8002"))


def get_settings() -> Settings:
    return Settings()
