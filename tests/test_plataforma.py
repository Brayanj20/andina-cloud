import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from andina.common.bus import Evento, InMemoryBus
from andina.common.config import Settings
from andina.common.resilience import CircuitBreaker, CircuitOpenError
from andina.facturacion.domain import FacturaInvalida
from andina.facturacion.parsers import ParserFactory, UblXmlParser
from andina.gateway.api import create_app as crear_gateway
from andina.monolito import create_app as crear_monolito

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
COMPRA = (SAMPLES / "factura_compra_attached.xml").read_bytes()
VENTA = (SAMPLES / "factura_venta.xml").read_bytes()
XML = {"content-type": "application/xml"}


@pytest.fixture
def client():
    return TestClient(crear_monolito())


def test_parser_lee_attached_document():
    f = UblXmlParser().parse(COMPRA)
    assert f.numero == "FV-8841" and f.nit_receptor == "900123456"
    assert len(f.lineas) == 2 and f.lineas[0].sku == "MOR-001"


def test_factory_rechaza_formato_desconocido():
    with pytest.raises(FacturaInvalida):
        ParserFactory.para("text/plain")


def test_flujo_completo_compra_venta_actualiza_inventario(client):
    r = client.post("/facturacion/facturas", content=COMPRA, headers=XML)
    assert r.status_code == 201 and r.json()["tipo"] == "compra"
    r = client.post("/facturacion/facturas", content=VENTA, headers=XML)
    assert r.status_code == 201 and r.json()["tipo"] == "venta"

    stock = {p["sku"]: p["stock"] for p in client.get("/inventario/productos").json()}
    assert stock == {"CAN-002": "3", "MOR-001": "18"}
    alertas = client.get("/inventario/alertas").json()
    assert [a["sku"] for a in alertas] == ["CAN-002"]

    resumen = client.get("/facturacion/reportes/resumen").json()
    assert resumen["ventas"]["cantidad"] == 1 and resumen["compras"]["cantidad"] == 1


def test_factura_duplicada_devuelve_409(client):
    assert client.post("/facturacion/facturas", content=VENTA, headers=XML).status_code == 201
    assert client.post("/facturacion/facturas", content=VENTA, headers=XML).status_code == 409


def test_factura_de_otra_empresa_es_rechazada(client):
    ajena = VENTA.replace(b"900123456", b"999999999")
    assert client.post("/facturacion/facturas", content=ajena, headers=XML).status_code == 422


def test_registro_por_json(client):
    body = {"numero": "AND-2000", "fecha": "2026-10-05", "nit_emisor": "900123456", "nit_receptor": "123",
            "total": 119000, "iva": 19000, "lineas": [{"sku": "MOR-001", "cantidad": 1, "precio_unitario": 100000}]}
    r = client.post("/facturacion/facturas", json=body)
    assert r.status_code == 201 and r.json()["tipo"] == "venta"


def test_consumidor_idempotente():
    from andina.inventario.service import InventarioRepository, InventarioService
    bus = InMemoryBus()
    svc = InventarioService(InventarioRepository(), bus)
    datos = {"tipo": "compra", "numero": "X1", "fecha": "2026-10-01", "lineas": [{"sku": "A", "descripcion": "a", "cantidad": "10"}]}
    ev = Evento("FacturaRegistrada", datos)
    svc.on_factura_registrada(ev)
    svc.on_factura_registrada(ev)  # reentrega del mismo evento
    assert svc.repo.producto("A")["stock"] == "10"


def test_circuit_breaker_abre_y_se_recupera():
    t = [0.0]
    cb = CircuitBreaker(umbral_fallos=2, tiempo_reset=10, reloj=lambda: t[0])

    async def falla():
        raise RuntimeError("caido")

    async def ok():
        return "ok"

    async def escenario():
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.llamar(falla)
        assert cb.estado == "ABIERTO"
        with pytest.raises(CircuitOpenError):
            await cb.llamar(ok)
        t[0] = 11
        assert cb.estado == "SEMIABIERTO"
        assert await cb.llamar(ok) == "ok"
        assert cb.estado == "CERRADO"

    asyncio.run(escenario())


def test_gateway_autentica_y_enruta():
    def handler(request: httpx.Request):
        if request.url.host == "facturacion":
            return httpx.Response(200, json={"servicio": "facturacion", "path": request.url.path})
        return httpx.Response(500)

    s = Settings(api_keys=("clave",), facturacion_url="http://facturacion", inventario_url="http://inventario")
    gw = TestClient(crear_gateway(s, transport=httpx.MockTransport(handler)))
    assert gw.get("/api/facturacion/facturas").status_code == 401
    r = gw.get("/api/facturacion/facturas", headers={"x-api-key": "clave"})
    assert r.status_code == 200 and r.json()["path"] == "/facturas"
    # inventario responde 500: tras los reintentos el gateway devuelve 502 y luego abre el circuito
    for _ in range(3):
        assert gw.get("/api/inventario/productos", headers={"x-api-key": "clave"}).status_code == 502
    assert gw.get("/api/inventario/productos", headers={"x-api-key": "clave"}).status_code == 503


def test_bus_redis_streams_entre_servicios(monkeypatch):
    """Simula el despliegue distribuido: dos apps separadas comunicadas por Redis Streams."""
    import time
    fakeredis = pytest.importorskip("fakeredis")
    import redis
    from andina.common.bus import RedisStreamBus
    from andina.facturacion.api import create_app as crear_facturacion
    from andina.inventario.api import create_app as crear_inventario

    server = fakeredis.FakeServer()
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url, **kw: fakeredis.FakeRedis(server=server, **kw)))
    s = Settings(redis_url="redis://fake")
    fact = TestClient(crear_facturacion(s, RedisStreamBus(s.redis_url)))
    inv = TestClient(crear_inventario(s, RedisStreamBus(s.redis_url)))

    assert fact.post("/facturas", content=COMPRA, headers=XML).status_code == 201
    for _ in range(50):
        if inv.get("/productos").json():
            break
        time.sleep(0.1)
    assert {p["sku"]: p["stock"] for p in inv.get("/productos").json()} == {"CAN-002": "20", "MOR-001": "30"}
