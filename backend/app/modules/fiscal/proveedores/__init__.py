"""Proveedores tecnológicos de facturación electrónica. `obtener_proveedor()` elige según `FISCAL_PROVEEDOR`."""

from __future__ import annotations

from app.core.config import ConfiguracionInvalida, Settings, get_settings
from app.modules.fiscal.proveedores.base import ProveedorFiscal


def crear_proveedor(cfg: Settings | None = None) -> ProveedorFiscal:
    cfg = cfg or get_settings()
    if cfg.fiscal_proveedor == "simulado":
        from app.modules.fiscal.proveedores.simulado import ProveedorFiscalSimulado

        return ProveedorFiscalSimulado(
            latencia_ms=cfg.fiscal_simulado_latencia_ms, rechazos=cfg.fiscal_simulado_rechazos
        )
    faltan = [
        n.upper()
        for n in ("factus_url", "factus_client_id", "factus_client_secret", "factus_username", "factus_password")
        if not getattr(cfg, n)
    ]
    if faltan:
        raise ConfiguracionInvalida(
            "FISCAL_PROVEEDOR=factus pero faltan variables en .env: " + ", ".join(faltan) + ". "
            "Use FISCAL_PROVEEDOR=simulado para trabajar sin Factus."
        )
    from app.modules.fiscal.proveedores.factus import ProveedorFiscalFactus

    return ProveedorFiscalFactus(
        url=cfg.factus_url,  # type: ignore[arg-type]
        client_id=cfg.factus_client_id,  # type: ignore[arg-type]
        client_secret=cfg.factus_client_secret,  # type: ignore[arg-type]
        username=cfg.factus_username,  # type: ignore[arg-type]
        password=cfg.factus_password,  # type: ignore[arg-type]
        timeout_conexion=cfg.fiscal_timeout_conexion_seg,
        timeout_lectura=cfg.fiscal_timeout_lectura_seg,
        certificados_sistema=cfg.fiscal_certificados_sistema,
    )
