from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from enum import Enum
from typing import Annotated, Dict, Any, List
import tempfile, os, re

from extractor_v6 import extract_from_pdf  # <- devuelve el payload minimal normalizado

app = FastAPI(title="Factura Extractor API v6", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

class Vendor(str, Enum):
    GUERRINI = "GUERRINI"
    PIRELLI = "PIRELLI"

class OutFmt(str, Enum):
    json = "json"        # JSON minimal normalizado
    kv = "kv"            # VB6-friendly key=value (plano)
    ini = "ini"          # (opcional) INI por secciones

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

# ----------------------------
# Helpers VB6-friendly
# ----------------------------

def _to_kv(minimal: Dict[str, Any]) -> str:
    """
    Convierte el payload minimal:
      {
        "numero": "...",
        "fecha": "YYYY-MM-DD",
        "cuit": "nn-nnnnnnnn-n",
        "total": 123.45,
        "iva": {"21": 100.10, "10.5": 16.50, ...},
        "percepciones": {"percepcion_iva": 123.4, ...},
        "retenciones": {"retencion_iva": 55.0, ...}
      }
    a key=value por líneas, con contadores + claves indexadas.
    """
    lines: List[str] = []

    # Campos principales
    lines.append(f"status=ok")
    lines.append(f"version=1")
    lines.append(f"numero={minimal.get('numero','')}")
    lines.append(f"fecha={minimal.get('fecha','')}")
    lines.append(f"cuit={minimal.get('cuit','')}")
    lines.append(f"total={_num(minimal.get('total', 0))}")

    # IVA por alícuota
    iva = minimal.get("iva") or {}
    iva_items = [(str(k), float(v)) for k, v in iva.items() if v and float(v) != 0.0]
    lines.append(f"iva_count={len(iva_items)}")
    # orden clásico de tasas comunes
    order = ["27", "21", "10.5", "5", "2.5"]
    def rank(k: str) -> int:
        return order.index(k) if k in order else 999
    iva_items.sort(key=lambda x: (rank(x[0]), x[0]))
    for i, (rate, monto) in enumerate(iva_items, start=1):
        lines.append(f"iva_{i}_tasa={_clean(rate)}")
        lines.append(f"iva_{i}_monto={_num(monto)}")

    # Percepciones normalizadas
    percs = minimal.get("percepciones") or {}
    perc_items = [(k, float(v)) for k, v in percs.items() if v and float(v) != 0.0]
    perc_items.sort(key=lambda x: x[0])
    lines.append(f"percepciones_count={len(perc_items)}")
    for i, (name, monto) in enumerate(perc_items, start=1):
        lines.append(f"percepciones_{i}_clave={name}")
        lines.append(f"percepciones_{i}_monto={_num(monto)}")

    # Retenciones normalizadas
    rets = minimal.get("retenciones") or {}
    ret_items = [(k, float(v)) for k, v in rets.items() if v and float(v) != 0.0]
    ret_items.sort(key=lambda x: x[0])
    lines.append(f"retenciones_count={len(ret_items)}")
    for i, (name, monto) in enumerate(ret_items, start=1):
        lines.append(f"retenciones_{i}_clave={name}")
        lines.append(f"retenciones_{i}_monto={_num(monto)}")

    return "\n".join(lines)

def _to_ini(minimal: Dict[str, Any]) -> str:
    """
    Alternativa INI por secciones (si te gusta agrupar visualmente).
    """
    out: List[str] = []
    out += ["[meta]", "status=ok", "version=1", ""]
    out += ["[factura]"]
    out += [f"numero={minimal.get('numero','')}",
            f"fecha={minimal.get('fecha','')}",
            f"cuit={minimal.get('cuit','')}",
            f"total={_num(minimal.get('total', 0))}", ""]
    out += ["[iva]"]
    iva = minimal.get("iva") or {}
    order = ["27", "21", "10.5", "5", "2.5"]
    for r in order:
        if r in iva and float(iva[r]) != 0.0:
            out.append(f"{r}={_num(iva[r])}")
    # tasas “no estándar” que aparezcan
    for k, v in iva.items():
        if k not in order and float(v) != 0.0:
            out.append(f"{_clean(k)}={_num(v)}")
    out.append("")

    out += ["[percepciones]"]
    for k, v in sorted((minimal.get("percepciones") or {}).items(), key=lambda x: x[0]):
        if v and float(v) != 0.0:
            out.append(f"{k}={_num(v)}")
    out.append("")

    out += ["[retenciones]"]
    for k, v in sorted((minimal.get("retenciones") or {}).items(), key=lambda x: x[0]):
        if v and float(v) != 0.0:
            out.append(f"{k}={_num(v)}")
    out.append("")
    return "\n".join(out)

def _num(v) -> str:
    try:
        return str(float(v)).replace(",", ".")
    except Exception:
        return "0"

def _clean(s: str) -> str:
    return re.sub(r"[\r\n=]+", " ", str(s)).strip()


def _clean_cuit(cuit: str) -> str:
    """Deja solo los dígitos del CUIT."""
    if not cuit:
        return ""
    import re
    return re.sub(r"\D", "", cuit or "")

# ----------------------------
# Endpoints
# ----------------------------
@app.post("/extract", response_model=None)
async def extract_invoice(
    file: Annotated[UploadFile, File(...)],
    vendor: Annotated[Vendor, Form(...)],
    fmt: Annotated[OutFmt, Query(alias="format")] = OutFmt.json  # ?format=json|kv|ini
) -> Response:
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF por el momento.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Archivo vacío.")
        tmp.write(content)
        tmp.flush()
        tmp_path = tmp.name

    try:
        # El extractor ya devuelve el payload minimal normalizado
        minimal = extract_from_pdf(tmp_path, vendor_hint=vendor.value, cfg_path="vendors.yaml")

        # Limpieza del CUIT antes de devolver
        if "cuit" in minimal:
            minimal["cuit"] = _clean_cuit(minimal["cuit"])
        
        if fmt == OutFmt.json:
            return JSONResponse(minimal)

        if fmt == OutFmt.kv:
            body = _to_kv(minimal)
            return PlainTextResponse(content=body, media_type="text/plain; charset=utf-8")

        if fmt == OutFmt.ini:
            body = _to_ini(minimal)
            return PlainTextResponse(content=body, media_type="text/ini; charset=utf-8")

        # Fallback a JSON
        return JSONResponse(minimal)

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
