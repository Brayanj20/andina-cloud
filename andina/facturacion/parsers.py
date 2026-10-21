"""Lectores de facturas (patrones Strategy + Factory).

Cada formato de entrada tiene su estrategia; la fábrica elige la adecuada según
el tipo de contenido. Agregar un formato nuevo no exige modificar el resto del
servicio (principio abierto/cerrado).
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal, InvalidOperation

from .domain import Factura, FacturaInvalida, LineaFactura

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "ad": "urn:oasis:names:specification:ubl:schema:xsd:AttachedDocument-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


def _dec(txt: str | None) -> Decimal:
    try:
        return Decimal((txt or "0").strip())
    except InvalidOperation as e:
        raise FacturaInvalida(f"Valor numérico inválido: {txt}") from e


class FacturaParser(ABC):
    @abstractmethod
    def parse(self, contenido: bytes) -> Factura: ...


class UblXmlParser(FacturaParser):
    """Lee facturas electrónicas UBL 2.1 (estándar DIAN).

    Acepta la factura directa (<Invoice>) o el contenedor <AttachedDocument> que
    llega por correo, cuyo XML de la factura viene embebido como texto.
    """

    def parse(self, contenido: bytes) -> Factura:
        try:
            root = ET.fromstring(contenido)
        except ET.ParseError as e:
            raise FacturaInvalida(f"XML mal formado: {e}") from e
        if root.tag == f"{{{NS['ad']}}}AttachedDocument":
            desc = root.find("cac:Attachment/cac:ExternalReference/cbc:Description", NS)
            if desc is None or not (desc.text or "").strip():
                raise FacturaInvalida("AttachedDocument sin factura embebida")
            root = ET.fromstring(desc.text.strip().encode("utf-8"))
        if root.tag != f"{{{NS['inv']}}}Invoice":
            raise FacturaInvalida("El XML no es una factura UBL (Invoice)")

        def t(path: str, base=root) -> str:
            el = base.find(path, NS)
            return (el.text or "").strip() if el is not None else ""

        lineas = []
        for ln in root.findall("cac:InvoiceLine", NS):
            sku = t("cac:Item/cac:StandardItemIdentification/cbc:ID", ln) or t("cac:Item/cac:SellersItemIdentification/cbc:ID", ln)
            lineas.append(LineaFactura(
                sku=sku or "SIN-SKU",
                descripcion=t("cac:Item/cbc:Description", ln),
                cantidad=_dec(t("cbc:InvoicedQuantity", ln)),
                precio_unitario=_dec(t("cac:Price/cbc:PriceAmount", ln)),
            ))
        sup = "cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/"
        cus = "cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/"
        try:
            fecha = date.fromisoformat(t("cbc:IssueDate"))
        except ValueError as e:
            raise FacturaInvalida("Fecha de emisión inválida") from e
        return Factura(
            numero=t("cbc:ID"), fecha=fecha,
            nit_emisor=t(sup + "cbc:CompanyID"), nombre_emisor=t(sup + "cbc:RegistrationName"),
            nit_receptor=t(cus + "cbc:CompanyID"), nombre_receptor=t(cus + "cbc:RegistrationName"),
            total=_dec(t("cac:LegalMonetaryTotal/cbc:PayableAmount")),
            iva=_dec(t("cac:TaxTotal/cbc:TaxAmount")), lineas=lineas,
        )


class JsonParser(FacturaParser):
    def parse(self, contenido: bytes) -> Factura:
        try:
            d = json.loads(contenido)
            return Factura(
                numero=d["numero"], fecha=date.fromisoformat(d["fecha"]),
                nit_emisor=d["nit_emisor"], nombre_emisor=d.get("nombre_emisor", ""),
                nit_receptor=d["nit_receptor"], nombre_receptor=d.get("nombre_receptor", ""),
                total=_dec(str(d["total"])), iva=_dec(str(d.get("iva", 0))),
                lineas=[LineaFactura(l["sku"], l.get("descripcion", ""), _dec(str(l["cantidad"])), _dec(str(l["precio_unitario"])))
                        for l in d.get("lineas", [])],
            )
        except (KeyError, ValueError, TypeError) as e:
            raise FacturaInvalida(f"JSON de factura inválido: {e}") from e


class ParserFactory:
    _estrategias = {"xml": UblXmlParser, "json": JsonParser}

    @classmethod
    def para(cls, content_type: str) -> FacturaParser:
        ct = (content_type or "").lower()
        clave = "json" if "json" in ct else "xml" if "xml" in ct else None
        if clave is None:
            raise FacturaInvalida(f"Formato no soportado: {content_type}")
        return cls._estrategias[clave]()
