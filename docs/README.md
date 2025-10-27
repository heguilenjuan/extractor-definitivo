# Factura Extractor API v6

Servicio REST con FastAPI para extraer datos estructurados desde facturas PDF
utilizando plantillas por proveedor. El objetivo es entregar un **payload
estandarizado**, útil tanto para sistemas modernos como para sistemas legados (ej. VB6).

- **Framework:** FastAPI
- **Versión API:** 1.2.0
- **Entrada:** Archivo PDF + proveedor
- **Salida:** JSON normalizado / formato `key=value` compatible con VB6 / formato `INI`

---

## Características

- Detección y normalización de campos clave:
  - `numero` (número de factura)
  - `fecha`
  - `cuit`
  - `subtotal`, `iva`, `total`
  - `percepciones` y `retenciones` por tipo
- Formateo opcional según necesidad de integración:
  - `json`
  - `kv` (key=value por línea)
  - `ini`
- Limpieza automática de CUIT (solo dígitos).
- Borra los PDFs temporales luego del procesamiento.
- Soporta múltiples proveedores mediante `vendors.yaml`.

---

## Endpoints

### `GET /health`
Verifica estado del servicio.
```json
{ "status": "ok" }

### `POST /extract` 
Endpoint principal