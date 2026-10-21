"""Bus de eventos (patrón Publicador/Suscriptor).

- InMemoryBus: entrega síncrona dentro del mismo proceso (pruebas y modo monolito).
- RedisStreamBus: Redis Streams con grupos de consumidores (patrón Competing
  Consumers). El mensaje solo se confirma (XACK) cuando el manejador termina bien,
  lo que da entrega "al menos una vez"; por eso los consumidores son idempotentes.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List

log = logging.getLogger("andina.bus")
STREAM = "andina.eventos"


@dataclass
class Evento:
    tipo: str
    datos: dict
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ocurrido_en: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(raw: str) -> "Evento":
        return Evento(**json.loads(raw))


Handler = Callable[[Evento], None]


class EventBus:
    def publish(self, evento: Evento) -> None:  # pragma: no cover - interfaz
        raise NotImplementedError

    def subscribe(self, tipo: str, handler: Handler, grupo: str = "default") -> None:  # pragma: no cover
        raise NotImplementedError


class InMemoryBus(EventBus):
    def __init__(self) -> None:
        self._subs: Dict[str, List[Handler]] = {}
        self.publicados: List[Evento] = []

    def publish(self, evento: Evento) -> None:
        self.publicados.append(evento)
        for h in self._subs.get(evento.tipo, []):
            h(evento)

    def subscribe(self, tipo: str, handler: Handler, grupo: str = "default") -> None:
        self._subs.setdefault(tipo, []).append(handler)


class RedisStreamBus(EventBus):  # pragma: no cover - requiere Redis
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, decode_responses=True)
        self._stop = threading.Event()

    def publish(self, evento: Evento) -> None:
        self._r.xadd(STREAM, {"tipo": evento.tipo, "data": evento.to_json()}, maxlen=10000)

    def subscribe(self, tipo: str, handler: Handler, grupo: str = "default") -> None:
        try:
            self._r.xgroup_create(STREAM, grupo, id="0", mkstream=True)
        except Exception:  # el grupo ya existe
            pass
        consumidor = f"{grupo}-{uuid.uuid4().hex[:6]}"

        def loop() -> None:
            while not self._stop.is_set():
                resp = self._r.xreadgroup(grupo, consumidor, {STREAM: ">"}, count=10, block=2000)
                for _stream, mensajes in resp or []:
                    for msg_id, campos in mensajes:
                        if campos.get("tipo") != tipo:
                            self._r.xack(STREAM, grupo, msg_id)
                            continue
                        try:
                            handler(Evento.from_json(campos["data"]))
                            self._r.xack(STREAM, grupo, msg_id)
                        except Exception:
                            log.exception("Error procesando %s; quedará pendiente para reintento", msg_id)

        threading.Thread(target=loop, daemon=True, name=f"consumer-{grupo}").start()

    def close(self) -> None:
        self._stop.set()


_bus: EventBus | None = None


def get_bus(redis_url: str = "") -> EventBus:
    global _bus
    if _bus is None:
        _bus = RedisStreamBus(redis_url) if redis_url else InMemoryBus()
    return _bus


def reset_bus() -> None:
    global _bus
    _bus = None
