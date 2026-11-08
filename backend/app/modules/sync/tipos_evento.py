"""Registro central de tipos de evento del outbox y su ALCANCE.

* `sincronizable` (por defecto): el agente de sync lo replica a la otra punta (edge <-> nube).
* `local`: es estado operativo del nodo y NO se replica nunca. Hoy: todo `fiscal.*` (p. ej. `fiscal.emitir`, la cola
  del worker de facturación electrónica: el documento se emite desde la sede con su resolución, nunca desde la nube).

REGLA PARA EL AGENTE DE SYNC: solo lee eventos con `alcance = 'sincronizable'`. Un tipo nuevo es sincronizable salvo
que se registre aquí como local; la prueba `test_sync_alcance` impide que un `fiscal.*` salga como sincronizable.
"""

from __future__ import annotations

LOCAL = "local"
SINCRONIZABLE = "sincronizable"

# Prefijos de `evento_tipo` que son locales del nodo. Es la ÚNICA fuente: la migración 0012 usa el mismo criterio.
PREFIJOS_LOCALES: tuple[str, ...] = ("fiscal.",)


def alcance_de(evento_tipo: str) -> str:
    """Alcance por defecto de un tipo de evento según el registro."""
    return LOCAL if evento_tipo.startswith(PREFIJOS_LOCALES) else SINCRONIZABLE
