"""Servicio de Inventario: consume eventos de facturas y mantiene el stock.

- Consumidor idempotente: registra los id de eventos procesados para que una
  reentrega del bus no duplique movimientos.
- Publica StockBajo cuando un producto queda por debajo del mínimo.
"""
from __future__ import annotations

import sqlite3
import threading
from decimal import Decimal
from typing import List, Optional

from ..common.bus import EventBus, Evento


class InventarioRepository:
    def __init__(self, path: str = ":memory:") -> None:
        self._cx = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._cx.executescript(
            """CREATE TABLE IF NOT EXISTS productos (sku TEXT PRIMARY KEY, descripcion TEXT, stock TEXT NOT NULL);
               CREATE TABLE IF NOT EXISTS movimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT, tipo TEXT,
                   cantidad TEXT, factura TEXT, fecha TEXT);
               CREATE TABLE IF NOT EXISTS eventos_procesados (evento_id TEXT PRIMARY KEY);"""
        )

    def aplicar_factura(self, evento_id: str, datos: dict) -> List[dict]:
        """Aplica todas las líneas en una sola transacción. Devuelve productos afectados."""
        signo = Decimal(1) if datos["tipo"] == "compra" else Decimal(-1)
        afectados = []
        with self._lock, self._cx:
            try:
                self._cx.execute("INSERT INTO eventos_procesados VALUES (?)", (evento_id,))
            except sqlite3.IntegrityError:
                return []  # ya procesado: idempotencia
            for l in datos["lineas"]:
                cant = Decimal(l["cantidad"]) * signo
                row = self._cx.execute("SELECT stock FROM productos WHERE sku = ?", (l["sku"],)).fetchone()
                nuevo = (Decimal(row[0]) if row else Decimal(0)) + cant
                self._cx.execute(
                    "INSERT INTO productos (sku, descripcion, stock) VALUES (?,?,?) "
                    "ON CONFLICT(sku) DO UPDATE SET stock = excluded.stock, descripcion = COALESCE(NULLIF(excluded.descripcion,''), productos.descripcion)",
                    (l["sku"], l.get("descripcion", ""), str(nuevo)))
                self._cx.execute("INSERT INTO movimientos (sku, tipo, cantidad, factura, fecha) VALUES (?,?,?,?,?)",
                                 (l["sku"], "entrada" if signo > 0 else "salida", str(abs(cant)), datos["numero"], datos["fecha"]))
                afectados.append({"sku": l["sku"], "descripcion": l.get("descripcion", ""), "stock": nuevo})
        return afectados

    def productos(self) -> List[dict]:
        with self._lock:
            rows = self._cx.execute("SELECT sku, descripcion, stock FROM productos ORDER BY sku").fetchall()
        return [{"sku": r[0], "descripcion": r[1], "stock": format(Decimal(r[2]).normalize(), "f")} for r in rows]

    def producto(self, sku: str) -> Optional[dict]:
        return next((p for p in self.productos() if p["sku"] == sku), None)

    def movimientos(self, sku: str) -> List[dict]:
        with self._lock:
            rows = self._cx.execute("SELECT tipo, cantidad, factura, fecha FROM movimientos WHERE sku = ? ORDER BY id", (sku,)).fetchall()
        return [{"tipo": r[0], "cantidad": r[1], "factura": r[2], "fecha": r[3]} for r in rows]


class InventarioService:
    def __init__(self, repo: InventarioRepository, bus: EventBus, stock_minimo: int = 5):
        self.repo, self.bus, self.stock_minimo = repo, bus, stock_minimo
        self.alertas: List[dict] = []

    def suscribir(self) -> None:
        self.bus.subscribe("FacturaRegistrada", self.on_factura_registrada, grupo="inventario")

    def on_factura_registrada(self, evento: Evento) -> None:
        for p in self.repo.aplicar_factura(evento.id, evento.datos):
            if p["stock"] < self.stock_minimo:
                alerta = {"sku": p["sku"], "descripcion": p["descripcion"], "stock": str(p["stock"]), "minimo": self.stock_minimo}
                self.alertas.append(alerta)
                self.bus.publish(Evento("StockBajo", alerta))
