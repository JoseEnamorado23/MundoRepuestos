//! Secretos (token del dispositivo) en el almacén seguro del sistema operativo.
use keyring::Entry;

const SERVICIO: &str = "co.mundorepuestos.pos";

fn entrada(clave: &str) -> Result<Entry, String> {
    Entry::new(SERVICIO, clave).map_err(|e| format!("almacén seguro no disponible: {e}"))
}

#[tauri::command]
pub fn secreto_leer(clave: String) -> Result<Option<String>, String> {
    match entrada(&clave)?.get_password() {
        Ok(v) => Ok(Some(v)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(format!("no se pudo leer el secreto: {e}")),
    }
}

#[tauri::command]
pub fn secreto_guardar(clave: String, valor: String) -> Result<(), String> {
    entrada(&clave)?
        .set_password(&valor)
        .map_err(|e| format!("no se pudo guardar el secreto: {e}"))
}

#[tauri::command]
pub fn secreto_borrar(clave: String) -> Result<(), String> {
    match entrada(&clave)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(format!("no se pudo borrar el secreto: {e}")),
    }
}
