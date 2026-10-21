"""Modelo de dominio del servicio de Facturación."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional


class FacturaInvalida(ValueError):
    pass


@dataclass
class LineaFactura:
    sku: str
    descripcion: str
    cantidad: Decimal
    precio_unitario: Decimal

    @property
    def subtotal(self) -> Decimal:
        return (self.cantidad * self.precio_unitario).quantize(Decimal("0.01"))


@dataclass
class Factura:
    numero: str
    fecha: date
    nit_emisor: str
    nombre_emisor: str
    nit_receptor: str
    nombre_receptor: str
    total: Decimal
    iva: Decimal
    lineas: List[LineaFactura] = field(default_factory=list)
    tipo: Optional[str] = None  # "venta" | "compra" (lo define el servicio según el NIT de la empresa)
    id: Optional[int] = None

    def validar(self) -> None:
        if not self.numero:
            raise FacturaInvalida("La factura no tiene número")
        if not self.lineas:
            raise FacturaInvalida("La factura no tiene líneas")
        if self.total < 0 or self.iva < 0:
            raise FacturaInvalida("Totales negativos")
        for l in self.lineas:
            if l.cantidad <= 0:
                raise FacturaInvalida(f"Cantidad inválida en {l.sku}")

    def clasificar(self, nit_empresa: str) -> None:
        if self.nit_emisor == nit_empresa:
            self.tipo = "venta"
        elif self.nit_receptor == nit_empresa:
            self.tipo = "compra"
        else:
            raise FacturaInvalida("La factura no pertenece a la empresa (NIT no coincide)")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fecha"] = self.fecha.isoformat()
        d["total"] = str(self.total)
        d["iva"] = str(self.iva)
        d["lineas"] = [
            {"sku": l.sku, "descripcion": l.descripcion, "cantidad": str(l.cantidad),
             "precio_unitario": str(l.precio_unitario), "subtotal": str(l.subtotal)}
            for l in self.lineas
        ]
        return d
