//! Impresión RAW. `destino`: `tcp://host[:puerto]` (9100 por defecto) o `windows://Nombre de la impresora`
//! (cola de Windows, datatype RAW: los bytes ESC/POS pasan sin que el driver los reinterprete).
use std::io::Write;
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

/// Pulso ESC p m t1 t2 al pin 2 (≈50 ms encendido, ≈500 ms apagado). Lo construye Rust: el cajón no depende del frontend.
const PULSO_CAJON: [u8; 5] = [0x1B, 0x70, 0x00, 0x19, 0xFA];

enum Destino {
    Tcp(String),
    Windows(String),
}

fn analizar(destino: &str) -> Result<Destino, String> {
    if let Some(r) = destino.strip_prefix("tcp://") {
        let r = r.trim();
        if r.is_empty() {
            return Err("destino TCP vacío".into());
        }
        let con_puerto = if r.contains(':') { r.to_string() } else { format!("{r}:9100") };
        Ok(Destino::Tcp(con_puerto))
    } else if let Some(r) = destino.strip_prefix("windows://") {
        let r = r.trim();
        if r.is_empty() {
            return Err("nombre de impresora vacío".into());
        }
        Ok(Destino::Windows(r.to_string()))
    } else {
        Err(format!("destino no soportado: {destino} (use tcp://ip:9100 o windows://Nombre)"))
    }
}

fn enviar_tcp(direccion: &str, bytes: &[u8]) -> Result<(), String> {
    let dir = direccion
        .to_socket_addrs()
        .map_err(|e| format!("dirección inválida {direccion}: {e}"))?
        .next()
        .ok_or_else(|| format!("no se resolvió {direccion}"))?;
    let mut s = TcpStream::connect_timeout(&dir, Duration::from_secs(3))
        .map_err(|e| format!("no se pudo conectar con la impresora {direccion}: {e}"))?;
    s.set_write_timeout(Some(Duration::from_secs(5))).ok();
    s.write_all(bytes).map_err(|e| format!("error al enviar a la impresora: {e}"))?;
    s.flush().map_err(|e| format!("error al enviar a la impresora: {e}"))
}

#[cfg(windows)]
fn enviar_windows(nombre: &str, bytes: &[u8]) -> Result<(), String> {
    use windows::core::{PCWSTR, PWSTR};
    use windows::Win32::Graphics::Printing::{
        ClosePrinter, EndDocPrinter, EndPagePrinter, OpenPrinterW, StartDocPrinterW, StartPagePrinter, WritePrinter,
        DOC_INFO_1W, PRINTER_HANDLE,
    };

    fn ancho(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }
    let nombre_w = ancho(nombre);
    let mut doc_w = ancho("Tirilla POS");
    let mut tipo_w = ancho("RAW");

    unsafe {
        let mut h = PRINTER_HANDLE::default();
        OpenPrinterW(PCWSTR(nombre_w.as_ptr()), &mut h, None)
            .map_err(|e| format!("no se pudo abrir la impresora «{nombre}»: {e}"))?;
        let info = DOC_INFO_1W {
            pDocName: PWSTR(doc_w.as_mut_ptr()),
            pOutputFile: PWSTR::null(),
            pDatatype: PWSTR(tipo_w.as_mut_ptr()),
        };
        let resultado = (|| -> Result<(), String> {
            if StartDocPrinterW(h, 1, &info as *const _ as *const _) == 0 {
                return Err("StartDocPrinter falló".into());
            }
            if !StartPagePrinter(h).as_bool() {
                let _ = EndDocPrinter(h);
                return Err("StartPagePrinter falló".into());
            }
            let mut escritos = 0u32;
            let ok = WritePrinter(h, bytes.as_ptr() as *const _, bytes.len() as u32, &mut escritos).as_bool();
            let _ = EndPagePrinter(h);
            let _ = EndDocPrinter(h);
            if !ok || escritos as usize != bytes.len() {
                return Err(format!("WritePrinter escribió {escritos} de {} bytes", bytes.len()));
            }
            Ok(())
        })();
        let _ = ClosePrinter(h);
        resultado
    }
}

#[cfg(not(windows))]
fn enviar_windows(_nombre: &str, _bytes: &[u8]) -> Result<(), String> {
    Err("la impresión por nombre de impresora solo existe en Windows; use tcp://ip:9100".into())
}

fn enviar(destino: &str, bytes: &[u8]) -> Result<(), String> {
    match analizar(destino)? {
        Destino::Tcp(d) => enviar_tcp(&d, bytes),
        Destino::Windows(n) => enviar_windows(&n, bytes),
    }
}

#[tauri::command]
pub async fn imprimir_raw(destino: String, bytes: Vec<u8>) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || enviar(&destino, &bytes))
        .await
        .map_err(|e| format!("tarea de impresión interrumpida: {e}"))?
}

#[tauri::command]
pub async fn abrir_cajon(destino: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || enviar(&destino, &PULSO_CAJON))
        .await
        .map_err(|e| format!("tarea de cajón interrumpida: {e}"))?
}

#[cfg(test)]
mod pruebas {
    use super::*;
    use std::io::Read;
    use std::net::TcpListener;

    #[test]
    fn analiza_destinos() {
        assert!(matches!(analizar("tcp://10.0.0.5"), Ok(Destino::Tcp(d)) if d == "10.0.0.5:9100"));
        assert!(matches!(analizar("tcp://10.0.0.5:9101"), Ok(Destino::Tcp(d)) if d == "10.0.0.5:9101"));
        assert!(matches!(analizar("windows://POS-80"), Ok(Destino::Windows(n)) if n == "POS-80"));
        assert!(analizar("usb://x").is_err());
        assert!(analizar("tcp://").is_err());
    }

    #[test]
    fn tcp_entrega_los_bytes_intactos() {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let puerto = l.local_addr().unwrap().port();
        let h = std::thread::spawn(move || {
            let (mut s, _) = l.accept().unwrap();
            let mut b = Vec::new();
            s.read_to_end(&mut b).unwrap();
            b
        });
        let datos = vec![0x1B, 0x40, 0x00, 0xFF, 0x1D, 0x56, 0x42, 0x00];
        enviar(&format!("tcp://127.0.0.1:{puerto}"), &datos).unwrap();
        assert_eq!(h.join().unwrap(), datos);
    }

    #[test]
    fn el_pulso_del_cajon_es_esc_p() {
        assert_eq!(PULSO_CAJON[..2], [0x1B, 0x70]);
    }
}
