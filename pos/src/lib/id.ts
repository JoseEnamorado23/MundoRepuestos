import { uuidv7 } from 'uuidv7'

/** UUIDv7 generado en el cliente: clave de idempotencia de la venta (el servidor la usa como PK). */
export const nuevoId = (): string => uuidv7()
