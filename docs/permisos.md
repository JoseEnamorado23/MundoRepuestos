# Permisos y roles

> **Generado** por `uv run python -m scripts.permisos_doc` desde la base de datos migrada; no editar a mano
> (`backend/tests/test_permisos_doc.py` falla si queda desactualizado). Los permisos y roles se siembran en las
> migraciones (0004, 0006, 0008, 0009, 0010).

* **Req. aut.**: la acción puede exigir la autorización de OTRO empleado (PIN de supervisor o aprobación remota; ver
  `base-de-datos/modelo.md` §4.5 «Políticas de autorización»). Quien tiene el permiso no necesita pedirla.
* Un empleado tiene la unión de los permisos de sus roles activos.

## Roles

| Rol | Permisos |
|---|---|
| `administrador` | 35 |
| `bodeguero` | 7 |
| `cajero` | 11 |
| `propietario` | 35 |
| `supervisor` | 32 |
| `vendedor` | 5 |

## Permisos

| Código | Módulo | Descripción | Req. aut. | Roles que lo tienen |
|---|---|---|---|---|
| `admin.configuracion` | admin | Administrar configuración de sede, cajas y resoluciones | no | `administrador`, `propietario` |
| `admin.usuarios` | admin | Administrar empleados, roles y permisos | no | `administrador`, `propietario` |
| `autorizaciones.aprobar` | autorizaciones | Aprobar o rechazar solicitudes de autorización remotas | no | `administrador`, `propietario`, `supervisor` |
| `caja.abrir` | caja | Abrir turno de caja | no | `administrador`, `cajero`, `propietario`, `supervisor` |
| `caja.cerrar` | caja | Cerrar turno de caja | no | `administrador`, `cajero`, `propietario`, `supervisor` |
| `caja.cerrar_con_diferencia` | caja | Cerrar turno con faltante o sobrante | sí | `administrador`, `propietario`, `supervisor` |
| `cajas.cierre_forzado` | cajas | Cerrar a la fuerza el turno abandonado de otro cajero | no | `administrador`, `propietario`, `supervisor` |
| `cajas.dispositivos.gestionar` | cajas | Registrar, listar y revocar dispositivos POS | no | `administrador`, `propietario` |
| `cajas.movimientos` | cajas | Registrar ingresos y retiros de efectivo del turno | no | `administrador`, `cajero`, `propietario`, `supervisor` |
| `cajas.turno.abrir` | cajas | Abrir turno de caja | no | `administrador`, `cajero`, `propietario`, `supervisor` |
| `cajas.turno.cerrar` | cajas | Cerrar el propio turno de caja (conteo ciego) | no | `administrador`, `cajero`, `propietario`, `supervisor` |
| `catalogo.editar` | catalogo | Crear y editar productos | no | `administrador`, `bodeguero`, `propietario`, `supervisor` |
| `catalogo.editar_precios` | catalogo | Modificar precios y listas | no | `administrador`, `propietario`, `supervisor` |
| `catalogo.ver` | catalogo | Consultar y buscar productos, precios y compatibilidades | no | `administrador`, `bodeguero`, `cajero`, `propietario`, `supervisor`, `vendedor` |
| `precios.editar` | catalogo | Fijar precios de productos | no | `administrador`, `propietario`, `supervisor` |
| `compras.recibir` | compras | Recibir mercancía de proveedores | no | `administrador`, `bodeguero`, `propietario`, `supervisor` |
| `fiscal.reenviar` | fiscal | Reenviar documentos al proveedor tecnológico | no | `administrador`, `propietario`, `supervisor` |
| `fiscal.ver` | fiscal | Consultar documentos fiscales | no | `administrador`, `cajero`, `propietario`, `supervisor` |
| `inventario.ajustar` | inventario | Ajustar inventario manualmente | sí | `administrador`, `propietario`, `supervisor` |
| `inventario.aprobar` | inventario | Aprobar o rechazar entradas y ajustes sobre el umbral | no | `administrador`, `propietario`, `supervisor` |
| `inventario.conteo` | inventario | Realizar conteos físicos | no | `administrador`, `bodeguero`, `propietario`, `supervisor` |
| `inventario.entradas` | inventario | Registrar entradas de mercancía (compra simple) | no | `administrador`, `bodeguero`, `propietario`, `supervisor` |
| `inventario.importar` | inventario | Importar catálogo e inventario desde Excel | no | `administrador`, `bodeguero`, `propietario`, `supervisor` |
| `inventario.ver` | inventario | Consultar existencias y kardex | no | `administrador`, `bodeguero`, `cajero`, `propietario`, `supervisor`, `vendedor` |
| `pos.acceder` | pos | Iniciar sesión en el POS de una sede | no | `administrador`, `cajero`, `propietario`, `supervisor`, `vendedor` |
| `pos.anular` | pos | Anular o descartar una venta | sí | `administrador`, `propietario`, `supervisor` |
| `pos.cambiar_precio` | pos | Cambiar el precio de una línea (quien lo tiene no necesita autorización; también es la acción que autoriza un supervisor) | sí | `administrador`, `propietario`, `supervisor` |
| `pos.descuento_mayor` | pos | Aplicar descuentos por encima del tope del cajero | sí | `administrador`, `propietario`, `supervisor` |
| `pos.devolver` | pos | Registrar devoluciones de venta | sí | `administrador`, `propietario`, `supervisor` |
| `pos.retirar_efectivo` | pos | Retirar efectivo de la caja durante el turno | sí | `administrador`, `propietario`, `supervisor` |
| `pos.vender` | pos | Registrar y confirmar ventas | no | `administrador`, `cajero`, `propietario`, `supervisor`, `vendedor` |
| `pos.venta_sin_stock` | pos | Vender con existencias insuficientes | sí | `administrador`, `propietario`, `supervisor` |
| `reportes.ver` | reportes | Consultar reportes | no | `administrador`, `propietario`, `supervisor` |
| `revisiones.gestionar` | revisiones | Consultar y marcar como revisadas las acciones de revisión posterior | no | `administrador`, `propietario`, `supervisor` |
| `ventas.ver` | ventas | Consultar ventas, tirillas e informes de cierre | no | `administrador`, `cajero`, `propietario`, `supervisor`, `vendedor` |
