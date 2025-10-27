# FAQ - Preguntas Frecuentes

### ¿Qué pasa si el PDF es una imagen escaneada?
El sistema activa automáticamente **OCR**, sin intervención del usuario.

### El proveedor no aparece detectado, ¿es un error?
No.  
Simplemente se debe **seleccionar manualmente** o agregar reglas en `vendors.yaml`.

### El total no coincide con la factura
El pipeline incluye un validador que:
- Si falta total → lo calcula
- Si hay diferencia → agrega `warnings`

### ¿Se puede usar en batch (muchos PDFs)?
Sí.  
El endpoint `/extract` es idempotente y sin estado.  
Se puede llamar en bucle.

### ¿El formato JSON cambia?
No.  
`numero`, `fecha`, `cuit`, `subtotal`, `total`, `iva`, `percepciones`, `retenciones` son **estables**.

### ¿El formato KV está pensado para VB6?
Sí.  
Ese formato evita problemas con JSON y caracteres especiales.

---

## Atención en Producción
| Problema | Causa | Solución |
|--------|--------|----------|
| Facturas sin texto | Escaneadas | Se usa OCR automáticamente |
| Percepciones sin identificar | Texto muy variable | Agregar patrón → `NORMALIZATION_RULES` |
| IVA sin tasa diferenciada | Falta detalle | El sistema lo agrupa en `iva["otros"]` |