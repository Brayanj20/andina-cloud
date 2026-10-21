"""Persistencia de facturas (patrón Repository).

El servicio depende de la interfaz FacturaRepository, no de la base de datos.
SQLite sirve para el prototipo; en producción se cambia por PostgreSQL
administrado implementando la misma interfaz.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from typing import List, Optional

from .domain import Factura, LineaFactura


class FacturaDuplicada(Exception):
    pass


class FacturaRepository(ABC):
    @abstractmethod
    def guardar(self, f: Factura) -> Factura: ...

    @abstractmethod
    def obtener(self, id_: int) -> Optional[Factura]: ...

    @abstractmethod
    def listar(self, tipo: Optional[str] = None, desde: Optional[date] = None, hasta: Optional[date] = None) -> List[Factura]: ...


class SqliteFacturaRepository(FacturaRepository):
    def __init__(self, path: str = ":memory:") -> None:
        self._cx = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._cx.execute(
            """CREATE TABLE IF NOT EXISTS facturas (
                id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT NOT NULL, fecha TEXT NOT NULL,
                tipo TEXT NOT NULL, nit_emisor TEXT NOT NULL, nombre_emisor TEXT, nit_receptor TEXT NOT NULL,
                nombre_receptor TEXT, total TEXT NOT NULL, iva TEXT NOT NULL, lineas TEXT NOT NULL,
                UNIQUE (nit_emisor, numero))"""
        )
        self._cx.commit()

    def guardar(self, f: Factura) -> Factura:
        lineas = json.dumps([{"sku": l.sku, "descripcion": l.descripcion, "cantidad": str(l.cantidad),
                              "precio_unitario": str(l.precio_unitario)} for l in f.lineas], ensure_ascii=False)
        with self._lock:
            try:
                cur = self._cx.execute(
                    "INSERT INTO facturas (numero, fecha, tipo, nit_emisor, nombre_emisor, nit_receptor, nombre_receptor, total, iva, lineas)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f.numero, f.fecha.isoformat(), f.tipo, f.nit_emisor, f.nombre_emisor, f.nit_receptor,
                     f.nombre_receptor, str(f.total), str(f.iva), lineas))
                self._cx.commit()
            except sqlite3.IntegrityError as e:
                raise FacturaDuplicada(f"La factura {f.numero} del emisor {f.nit_emisor} ya existe") from e
        f.id = cur.lastrowid
        return f

    def _row(self, r) -> Factura:
        return Factura(id=r[0], numero=r[1], fecha=date.fromisoformat(r[2]), tipo=r[3], nit_emisor=r[4],
                       nombre_emisor=r[5], nit_receptor=r[6], nombre_receptor=r[7], total=Decimal(r[8]), iva=Decimal(r[9]),
                       lineas=[LineaFactura(l["sku"], l["descripcion"], Decimal(l["cantidad"]), Decimal(l["precio_unitario"]))
                               for l in json.loads(r[10])])

    def obtener(self, id_: int) -> Optional[Factura]:
        with self._lock:
            r = self._cx.execute("SELECT * FROM facturas WHERE id = ?", (id_,)).fetchone()
        return self._row(r) if r else None

    def listar(self, tipo=None, desde=None, hasta=None) -> List[Factura]:
        q, p = "SELECT * FROM facturas WHERE 1=1", []
        if tipo:
            q += " AND tipo = ?"; p.append(tipo)
        if desde:
            q += " AND fecha >= ?"; p.append(desde.isoformat())
        if hasta:
            q += " AND fecha <= ?"; p.append(hasta.isoformat())
        with self._lock:
            rows = self._cx.execute(q + " ORDER BY fecha, id", p).fetchall()
        return [self._row(r) for r in rows]
