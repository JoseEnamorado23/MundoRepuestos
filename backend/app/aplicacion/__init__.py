"""Capa de aplicación: casos de uso que coordinan varios módulos en UNA transacción.

Regla de dependencias (la verifica `tests/test_arquitectura.py`): api -> aplicacion -> modules (servicios) -> core.
Los routers solo validan la entrada, llaman a un caso de uso y responden; los servicios de un módulo no conocen
ni a `aplicacion` ni a `api`. Los casos de uso NO hacen commit (lo hace la sesión por petición, ver `app/api/deps.py`).
Ver docs/arquitectura.md.
"""
