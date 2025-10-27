# Arquitectura del Sistema de Extracción de Facturas

## Objetivo
Unificar la extracción de datos de facturas PDF con estructura variable (distintos proveedores) y producir un **payload normalizado** apto para integraciones modernas y sistemas heredados (VB6 / ERP).

---

## Visión General

```mermaid
flowchart LR
  User --> API[FastAPI /extract]
  API --> Uploads[save_temp_pdf]
  Uploads --> PDF[(archivo temporal)]
  PDF --> Extractor[extract_from_pdf]
  Extractor --> Detect[Detección del proveedor]
  Detect --> Handler[Vendedor específico]
  Handler --> RawOut[(Datos Brutos)]
  RawOut --> Normalizacion[Normalización de IVA/Percepciones/Retenciones]
  Normalizacion --> Payload[(Payload MINIMAL)]
  Payload --> Formato[JSON / KV / INI]
  Formato --> Respuesta[(Salida API)]



| Archivo                   | Rol                    | Resumen                                           |
| ------------------------- | ---------------------- | ------------------------------------------------- |
| `server.py`               | API HTTP               | Recibe PDF + vendor + formato. Convierte salida.  |
| `uploads.py`              | Manejo de archivos     | Guarda temporalmente el PDF y limpia luego.       |
| `extractor_v6.py`         | **Pipeline principal** | Lógica de extracción + normalización del payload. |
| `vendors_registry.py`     | Registro dinámico      | Permite agregar proveedores sin tocar el core.    |
| `handlers_*.py`           | Handlers por proveedor | Reglas específicas para leer totales y tributos.  |
| `vendors.yaml` (opcional) | Configuración          | Detecta proveedor según nombres o CUIT.           |
