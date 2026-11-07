"""POS: dispositivos, login por PIN/carné, bloqueo por fuerza bruta y autorización de supervisor de un solo uso."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errores import Conflicto, ReglaNegocio
from app.core.seguridad import sha256_hex
from app.modules.cajas import servicios as svc_cajas
from app.modules.identidad.autorizaciones import consumir_autorizacion
from tests import api_helpers as h

API = "/api/v1"


@pytest.fixture
def mundo(conn, db):
    return h.construir_mundo(conn, db)


# ------------------------------------------------------------------------------ dispositivos
def test_el_token_del_dispositivo_se_muestra_una_sola_vez(client, mundo, conn):
    admin = h.bearer(h.token_de(client, "admin"))
    caja2 = h.f.caja(conn, mundo.sede, mundo.ent["bodega"])
    r = client.post(f"{API}/cajas/dispositivos", json={"caja_id": caja2, "nombre": "POS 2"}, headers=admin)
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert len(token) >= 43  # 32 bytes aleatorios en base64url
    # en la BD solo existe el SHA-256
    guardado = conn.execute(
        text("SELECT token_hash FROM cajas.dispositivos WHERE id = :i"), {"i": r.json()["id"]}
    ).scalar()
    assert guardado == sha256_hex(token) and token not in guardado
    # ni el listado ni ningún otro endpoint lo vuelve a mostrar
    listado = client.get(f"{API}/cajas/dispositivos", headers=admin)
    assert listado.status_code == 200 and token not in listado.text and "token" not in listado.text
    # el token sirve para iniciar sesión (aunque el empleado no tenga PIN en esa sede, el dispositivo es válido)
    r2 = client.post(f"{API}/pos/auth/pin", json={"pin": "111111"}, headers={"X-Dispositivo-Token": token})
    assert r2.status_code == 200


def test_solo_un_dispositivo_activo_por_caja_y_requiere_permiso(client, mundo):
    admin = h.bearer(h.token_de(client, "admin"))
    r = client.post(f"{API}/cajas/dispositivos", json={"caja_id": mundo.caja, "nombre": "Otro"}, headers=admin)
    assert r.status_code == 409
    assert r.json()["detail"].startswith("La caja ya tiene un dispositivo POS activo")
    cajero = h.bearer(h.token_de(client, mundo.cajero.usuario))
    assert (
        client.post(
            f"{API}/cajas/dispositivos", json={"caja_id": mundo.caja, "nombre": "x"}, headers=cajero
        ).status_code
        == 403
    )
    inexistente = client.post(
        f"{API}/cajas/dispositivos", json={"caja_id": str(uuid.uuid4()), "nombre": "x"}, headers=admin
    )
    assert inexistente.status_code == 404


def test_dispositivo_invalido_ausente_o_revocado_da_401(client, mundo):
    sin = client.post(f"{API}/pos/auth/pin", json={"pin": "111111"})
    assert sin.status_code == 401 and sin.json()["code"] == "dispositivo_invalido"
    malo = client.post(f"{API}/pos/auth/pin", json={"pin": "111111"}, headers=mundo.cabecera_disp("token-falso"))
    assert malo.status_code == 401 and malo.json()["code"] == "dispositivo_invalido"
    # revocar: el mismo token deja de servir, y las sesiones POS ya emitidas también
    sesion = h.sesion_pos(client, mundo, "111111")
    admin = h.bearer(h.token_de(client, "admin"))
    assert client.post(f"{API}/cajas/dispositivos/{mundo.dispositivo_id}/revocar", headers=admin).status_code == 200
    revocado = client.post(f"{API}/pos/auth/pin", json={"pin": "111111"}, headers=mundo.cabecera_disp())
    assert revocado.status_code == 401 and revocado.json()["code"] == "dispositivo_invalido"
    r = client.post(
        f"{API}/pos/autorizaciones", headers=h.bearer(sesion), json={"pin": "999999", "accion": "pos.descuento_mayor"}
    )
    assert r.status_code == 401 and r.json()["code"] == "dispositivo_invalido"


# ------------------------------------------------------------------------------ PIN
def test_pin_correcto_y_claims_de_la_sesion(client, mundo):
    r = client.post(f"{API}/pos/auth/pin", json={"pin": "111111"}, headers=mundo.cabecera_disp())
    assert r.status_code == 200
    d = r.json()
    assert d["empleado_id"] == str(mundo.cajero.id) and d["caja_id"] == mundo.caja and d["sede_id"] == mundo.sede
    assert d["dispositivo_id"] == str(mundo.dispositivo_id) and d["expira_en"] == 600 * 60
    import jwt as pyjwt

    claims = pyjwt.decode(d["token"], options={"verify_signature": False})
    assert {claims["sub"], claims["dsp"], claims["caja"], claims["sede"]} == {
        str(mundo.cajero.id),
        str(mundo.dispositivo_id),
        mundo.caja,
        mundo.sede,
    }
    assert claims["typ"] == "pos" and claims["exp"] > claims["iat"]
    # también por código de carné
    c = client.post(f"{API}/pos/auth/pin", json={"codigo_carne": "CARNE-CAJERO"}, headers=mundo.cabecera_disp())
    assert c.status_code == 200
    # un token POS no abre recursos de backoffice
    assert client.get(f"{API}/auth/me", headers=h.bearer(d["token"])).status_code == 401
    assert client.get(f"{API}/empleados", headers=h.bearer(d["token"])).status_code == 403


def test_pin_exige_exactamente_un_dato(client, mundo):
    r = client.post(f"{API}/pos/auth/pin", json={}, headers=mundo.cabecera_disp())
    assert r.status_code == 422 and r.json()["code"] == "credencial_requerida"


def test_empleado_sin_pos_acceder_no_entra(client, mundo, db):
    bodeguero = h.crear_empleado(db, roles=["bodeguero"], sedes=[uuid.UUID(mundo.sede)], pin="222222")
    r = client.post(f"{API}/pos/auth/pin", json={"pin": "222222"}, headers=mundo.cabecera_disp())
    assert r.status_code == 403 and r.json()["permiso"] == "pos.acceder"
    assert bodeguero.activo


def test_empleado_de_otra_sede(client, mundo, db):
    otra = h.crear_empleado(db, roles=["cajero"], sedes=[uuid.UUID(mundo.sede2)], pin="333333", carne="CARNE-OTRA")
    assert otra.id
    # por PIN: el PIN no existe en esta sede -> credencial inválida (no se revela que existe en otra)
    por_pin = client.post(f"{API}/pos/auth/pin", json={"pin": "333333"}, headers=mundo.cabecera_disp())
    assert por_pin.status_code == 401 and por_pin.json()["code"] == "credenciales_invalidas"
    # por carné: se identifica pero no está asignado a esta sede
    por_carne = client.post(f"{API}/pos/auth/pin", json={"codigo_carne": "CARNE-OTRA"}, headers=mundo.cabecera_disp())
    assert por_carne.status_code == 403 and por_carne.json()["code"] == "sede_no_asignada"


def test_empleado_inactivo_no_entra(client, mundo):
    admin = h.bearer(h.token_de(client, "admin"))
    client.patch(f"{API}/empleados/{mundo.cajero.id}/activo", json={"activo": False}, headers=admin)
    r = client.post(f"{API}/pos/auth/pin", json={"pin": "111111"}, headers=mundo.cabecera_disp())
    assert r.status_code == 401


def test_bloqueo_por_dispositivo_tras_n_pines_incorrectos(client, mundo, conn):
    for _ in range(3):
        assert (
            client.post(f"{API}/pos/auth/pin", json={"pin": "000000"}, headers=mundo.cabecera_disp()).status_code == 401
        )
    r = client.post(f"{API}/pos/auth/pin", json={"pin": "111111"}, headers=mundo.cabecera_disp())  # PIN correcto
    assert r.status_code == 429 and r.json()["code"] == "bloqueo_temporal"
    assert int(r.headers["Retry-After"]) > 0
    # cada intento fallido quedó auditado con el dispositivo
    n = conn.execute(
        text(
            "SELECT count(*) FROM auditoria.log_acciones WHERE accion = 'pos.pin_fallido' "
            "AND dispositivo_id = :d AND resultado = 'denegado'"
        ),
        {"d": mundo.dispositivo_id},
    ).scalar()
    assert n == 3


def test_bloqueo_por_empleado_aunque_cambie_de_dispositivo(client, mundo, db, conn):
    """Con el carné se identifica al empleado: sus fallos (p. ej. sede equivocada) lo bloquean en cualquier dispositivo."""
    otro = h.crear_empleado(db, roles=["cajero"], sedes=[uuid.UUID(mundo.sede2)], carne="CARNE-X")
    caja2 = h.f.caja(conn, mundo.sede, mundo.ent["bodega"])
    _, token2 = svc_cajas.crear_dispositivo(db, uuid.UUID(caja2), "POS B", mundo.admin.id)
    db.commit()
    for _ in range(3):  # desde el dispositivo 1: asignado a otra sede -> 403 y cuenta como fallo del empleado
        assert (
            client.post(
                f"{API}/pos/auth/pin", json={"codigo_carne": "CARNE-X"}, headers=mundo.cabecera_disp()
            ).status_code
            == 403
        )
    r = client.post(f"{API}/pos/auth/pin", json={"codigo_carne": "CARNE-X"}, headers=mundo.cabecera_disp(token2))
    assert r.status_code == 429  # dispositivo 2 no tiene fallos propios, pero el empleado sí
    assert otro.id


def test_un_acierto_reinicia_el_conteo(client, mundo):
    for _ in range(2):
        client.post(f"{API}/pos/auth/pin", json={"pin": "000000"}, headers=mundo.cabecera_disp())
    assert client.post(f"{API}/pos/auth/pin", json={"pin": "111111"}, headers=mundo.cabecera_disp()).status_code == 200
    for _ in range(2):  # dos fallos más NO llegan al máximo, porque el éxito reinició la cuenta
        assert (
            client.post(f"{API}/pos/auth/pin", json={"pin": "000000"}, headers=mundo.cabecera_disp()).status_code == 401
        )


def test_el_pin_es_unico_por_sede(client, mundo, db):
    admin = h.bearer(h.token_de(client, "admin"))
    otro = h.crear_empleado(db, roles=["cajero"], sedes=[uuid.UUID(mundo.sede), uuid.UUID(mundo.sede2)])
    r = client.post(f"{API}/empleados/{otro.id}/pin", json={"pin": "111111"}, headers=admin)  # ya lo tiene el cajero
    assert r.status_code == 409 and r.json()["code"] == "pin_no_disponible"
    # en la otra sede sí está libre
    ok = client.post(f"{API}/empleados/{otro.id}/pin", json={"pin": "111111", "sede_id": mundo.sede2}, headers=admin)
    assert ok.status_code == 204
    # el mismo empleado puede repetir su propio PIN (no choca consigo mismo)
    assert (
        client.post(f"{API}/empleados/{mundo.cajero.id}/pin", json={"pin": "111111"}, headers=admin).status_code == 204
    )


# ------------------------------------------------------------------------------ autorizaciones
def _autorizar(client, mundo, sesion, pin="999999", accion="pos.descuento_mayor", **extra):
    return client.post(
        f"{API}/pos/autorizaciones",
        headers=h.bearer(sesion),
        json={"pin": pin, "accion": accion, "detalle": {"descuento_pct": 25}, **extra},
    )


class _Sesion:
    """SesionPos mínima para invocar el servicio de consumo igual que lo haría un endpoint protegido."""

    def __init__(self, mundo, empleado):
        self.empleado, self.dispositivo_id = empleado, mundo.dispositivo_id
        self.caja_id, self.sede_id = uuid.UUID(mundo.caja), uuid.UUID(mundo.sede)


def test_autorizacion_se_consume_una_sola_vez(client, mundo, db, conn):
    sesion = h.sesion_pos(client, mundo, "111111")
    r = _autorizar(client, mundo, sesion)
    assert r.status_code == 201, r.text
    aid = uuid.UUID(r.json()["autorizacion_id"])
    assert r.json()["supervisor_id"] == str(mundo.supervisor.id)
    fila = conn.execute(
        text("SELECT tipo, solicitado_por_id, autorizado_por_id, detalle FROM identidad.autorizaciones WHERE id = :i"),
        {"i": aid},
    ).one()
    assert fila.tipo == "descuento_mayor" and fila.solicitado_por_id == mundo.cajero.id
    assert fila.autorizado_por_id == mundo.supervisor.id and fila.detalle == {"descuento_pct": 25}

    yo = _Sesion(mundo, mundo.cajero)
    consumir_autorizacion(db, aid, accion="pos.descuento_mayor", sesion=yo)  # primera vez: ok
    with pytest.raises(Conflicto) as e:  # segunda: falla
        consumir_autorizacion(db, aid, accion="pos.descuento_mayor", sesion=yo)
    assert e.value.code == "autorizacion_consumida"


def test_autorizacion_de_otra_accion_o_de_otro_empleado_no_sirve(client, mundo, db):
    sesion = h.sesion_pos(client, mundo, "111111")
    aid = uuid.UUID(_autorizar(client, mundo, sesion).json()["autorizacion_id"])
    with pytest.raises(ReglaNegocio) as e:
        consumir_autorizacion(db, aid, accion="pos.anular", sesion=_Sesion(mundo, mundo.cajero))
    assert e.value.code == "autorizacion_otra_accion"
    from app.core.errores import PermisoDenegado

    with pytest.raises(PermisoDenegado):
        consumir_autorizacion(db, aid, accion="pos.descuento_mayor", sesion=_Sesion(mundo, mundo.supervisor))


def test_autorizacion_vencida_falla(client, mundo, db, monkeypatch):
    sesion = h.sesion_pos(client, mundo, "111111")
    monkeypatch.setattr(get_settings(), "autorizacion_ttl_seg", -1)  # nace ya vencida
    aid = uuid.UUID(_autorizar(client, mundo, sesion).json()["autorizacion_id"])
    with pytest.raises(ReglaNegocio) as e:
        consumir_autorizacion(db, aid, accion="pos.descuento_mayor", sesion=_Sesion(mundo, mundo.cajero))
    assert e.value.code == "autorizacion_vencida"


def test_autorizacion_valida_el_permiso_del_supervisor(client, mundo, db):
    sesion = h.sesion_pos(client, mundo, "111111")
    # PIN de otro cajero (no supervisor): existe en la sede pero no tiene el permiso
    h.crear_empleado(db, roles=["cajero"], sedes=[uuid.UUID(mundo.sede)], pin="444444")
    r = _autorizar(client, mundo, sesion, pin="444444")
    assert r.status_code == 403 and r.json()["permiso"] == "pos.descuento_mayor"
    # PIN inexistente
    assert _autorizar(client, mundo, sesion, pin="777777").status_code == 401
    # acción que no admite autorización
    assert _autorizar(client, mundo, sesion, accion="pos.vender").json()["code"] == "accion_no_autorizable"
    # el cajero no puede autorizarse a sí mismo aunque tuviera el permiso
    r = _autorizar(client, mundo, sesion, pin="111111")
    assert r.status_code in (403, 422)
    # sin sesión POS no hay autorización
    assert client.post(f"{API}/pos/autorizaciones", json={"pin": "999999", "accion": "pos.anular"}).status_code == 401


def test_autoautorizacion_se_rechaza(client, mundo, db):
    sup2 = h.crear_empleado(db, roles=["supervisor"], sedes=[uuid.UUID(mundo.sede)], pin="555555")
    sesion = h.sesion_pos(client, mundo, "555555")  # el supervisor opera la caja...
    r = _autorizar(client, mundo, sesion, pin="555555")  # ...e intenta autorizarse a sí mismo
    assert r.status_code == 422 and r.json()["code"] == "autoautorizacion"
    assert sup2.id


def test_autorizacion_queda_auditada(client, mundo, conn):
    sesion = h.sesion_pos(client, mundo, "111111")
    aid = _autorizar(client, mundo, sesion).json()["autorizacion_id"]
    fila = conn.execute(
        text(
            "SELECT autorizado_por_id, actor_id, sede_id FROM auditoria.log_acciones "
            "WHERE accion = 'pos.autorizacion_creada' AND autorizacion_id = :a"
        ),
        {"a": aid},
    ).one()
    assert fila.autorizado_por_id == mundo.supervisor.id and fila.actor_id == mundo.cajero.id
