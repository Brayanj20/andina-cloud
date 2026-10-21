"""Patrones de resiliencia para llamadas remotas: Retry con backoff exponencial y Circuit Breaker."""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class CircuitOpenError(Exception):
    """El circuito está abierto: se falla rápido sin llamar al servicio."""


class CircuitBreaker:
    """Estados: CERRADO -> ABIERTO (tras N fallos) -> SEMIABIERTO (tras el tiempo de espera)."""

    CERRADO, ABIERTO, SEMIABIERTO = "CERRADO", "ABIERTO", "SEMIABIERTO"

    def __init__(self, umbral_fallos: int = 3, tiempo_reset: float = 30.0, reloj: Callable[[], float] = time.monotonic):
        self.umbral_fallos = umbral_fallos
        self.tiempo_reset = tiempo_reset
        self._reloj = reloj
        self.fallos = 0
        self._abierto_desde = 0.0
        self._estado = self.CERRADO

    @property
    def estado(self) -> str:
        if self._estado == self.ABIERTO and self._reloj() - self._abierto_desde >= self.tiempo_reset:
            self._estado = self.SEMIABIERTO
        return self._estado

    def registrar_exito(self) -> None:
        self.fallos = 0
        self._estado = self.CERRADO

    def registrar_fallo(self) -> None:
        self.fallos += 1
        if self._estado == self.SEMIABIERTO or self.fallos >= self.umbral_fallos:
            self._estado = self.ABIERTO
            self._abierto_desde = self._reloj()

    async def llamar(self, fn: Callable[[], Awaitable[T]]) -> T:
        if self.estado == self.ABIERTO:
            raise CircuitOpenError("Servicio no disponible temporalmente (circuito abierto)")
        try:
            res = await fn()
        except Exception:
            self.registrar_fallo()
            raise
        self.registrar_exito()
        return res


async def reintentar(fn: Callable[[], Awaitable[T]], intentos: int = 3, base: float = 0.2,
                     reintentables: tuple = (Exception,)) -> T:
    """Reintenta con backoff exponencial: base, base*2, base*4..."""
    for i in range(intentos):
        try:
            return await fn()
        except reintentables:
            if i == intentos - 1:
                raise
            await asyncio.sleep(base * (2 ** i))
    raise RuntimeError("inalcanzable")  # pragma: no cover
