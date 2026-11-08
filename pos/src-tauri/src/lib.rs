//! Comandos nativos del POS: almacén seguro de secretos e impresión ESC/POS cruda.
//! Los bytes ESC/POS los construye el frontend (TypeScript); aquí solo se entregan a la impresora.
mod impresion;
mod secretos;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            secretos::secreto_leer,
            secretos::secreto_guardar,
            secretos::secreto_borrar,
            impresion::imprimir_raw,
            impresion::abrir_cajon,
        ])
        .run(tauri::generate_context!())
        .expect("error al iniciar MundoRepuestos POS");
}
