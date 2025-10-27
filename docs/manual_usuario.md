# Manual de Usuario - Sistema de Extracción de Facturas

## Objetivo
Permite cargar una factura en PDF y obtener sus valores calculados automáticamente:
- Subtotal
- IVA discriminado
- Percepciones provinciales
- Retenciones
- Total final

## Pasos de uso

1. Abrir el programa de carga (ERP / VB6).
2. Seleccionar la opción **"Cargar factura desde PDF"**.
3. Elegir el archivo PDF correspondiente.
4. Seleccionar el **proveedor** si lo solicita.
5. Confirmar.

El sistema muestra los valores completos y los inserta en la factura interna.

## Formatos de Salida
| Formato | Uso recomendado |
|--------|----------------|
| **JSON** | Integración con sistemas modernos |
| **KV (key=value)** | Sistemas antiguos (VB6) |
| **INI** | Depuración / importación por lote |
