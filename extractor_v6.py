# extractor_v6.py
import os, yaml
from typing import List, Dict, Any, Optional
from vendors_registry import REGISTRY
from extractor_utils import (
    read_pdf_text, ocr_pdf_to_lines, extract_header_common, extract_names_and_cuits,
    detect_vendor_basic, detect_vendor_by_cuit
)
import handlers_pirelli  # noqa: F401
import handlers_guerrini  # noqa: F401
def _load_vendor_config(cfg_path: str) -> Dict[str, Any]:
    if not os.path.exists(cfg_path):
        return {"detect": {"names": {}, "cuits": {}}}
    with open(cfg_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    names = {}; cuits = {}
    for vid, cfg in (data or {}).items():
        for name in cfg.get('detect', {}).get('names', []):
            names.setdefault(vid.upper(), []).append(name)
        for cuit in cfg.get('detect', {}).get('cuits', []):
            cuits[cuit] = vid.upper()
    return {"detect": {"names": names, "cuits": cuits}}
def _fallback_labels(lines: List[str], out: Dict[str, Any]) -> None:
    from extractor_utils import NUM_PURE, NUM_ANY, parse_number_smart
    start = max(0, len(lines) - 150)
    tail = lines[start:]
    def find_first_amount(i: int):
        for j in range(i, min(len(tail), i+10)):
            m = NUM_PURE.search(tail[j]) or NUM_ANY.search(tail[j])
            if m:
                v = parse_number_smart(m.group(0))
                if v is not None: return v
        return None
    sub = iva = perc = tot = None
    iva_items = []; perc_items = []
    for i, line in enumerate(tail):
        up = line.upper()
        if sub is None and 'SUBTOTAL' in up:
            sub = find_first_amount(i)
        if 'IVA' in up:
            v = find_first_amount(i)
            if v is not None:
                iva = (iva or 0.0) + v
                iva_items.append({"alicuota": None, "monto": v})
        if any(k in up for k in ['PERC', 'PERCEP', 'IIBB', 'INGRESOS BRUTOS', 'ARBA', 'AGIP']):
            v = find_first_amount(i)
            if v is not None:
                perc = (perc or 0.0) + v
                perc_items.append({"desc": line, "monto": v})
        if 'TOTAL' in up:
            tot = find_first_amount(i)
    out["subtotal"] = sub
    out["iva"] = iva
    out["iva_detalle"] = iva_items
    out["percepciones_total"] = perc
    out["percepciones_detalle"] = perc_items
    out["total"] = tot
    if out["total"] is None and (sub is not None):
        out["total"] = round((sub or 0.0) + (iva or 0.0) + (perc or 0.0), 2)
def _validate_and_repair(out: Dict[str, Any], tol: float = 0.05) -> None:
    sub = out.get("subtotal") or 0.0
    iva = out.get("iva") or 0.0
    perc = out.get("percepciones_total") or 0.0
    tot = out.get("total")
    comp = round(sub + iva + perc, 2)
    out.setdefault("warnings", [])
    if tot is None:
        out["total"] = comp
        out["warnings"].append("TOTAL estimado = SUBTOTAL + IVA + PERCEPCIONES")
    elif abs((tot or 0.0) - comp) > tol:
        out["warnings"].append(f"Diferencia contable: total({tot}) != subtotal+iva+percepciones({comp})")
def extract_from_pdf(pdf_path: str, vendor_hint: Optional[str] = None, cfg_path: str = "vendors.yaml") -> Dict[str, Any]:
    lines = read_pdf_text(pdf_path)
    used_ocr = False
    if not lines or sum(len(l) for l in lines) < 30:
        lines = ocr_pdf_to_lines(pdf_path); used_ocr = True
    header = extract_header_common(lines)
    cfg = _load_vendor_config(cfg_path)
    name_keywords = cfg["detect"]["names"]; cuit_map = cfg["detect"]["cuits"]
    vendor = (vendor_hint or "").upper() or detect_vendor_basic(lines, name_keywords) or None
    proveedor, cuit_prov, cliente, cuit_cli = (None, None, None, None)
    from extractor_utils import extract_names_and_cuits
    proveedor, cuit_prov, cliente, cuit_cli = extract_names_and_cuits(lines, vendor)
    if not vendor and cuit_prov:
        vendor = detect_vendor_by_cuit(cuit_prov, cuit_map)
    out: Dict[str, Any] = {
        "proveedor": proveedor, "cuit_proveedor": cuit_prov,
        "cliente": cliente, "cuit_cliente": cuit_cli,
        "tipo": header["tipo"], "numero": header["numero"],
        "fecha": header["fecha"], "cae": header["cae"], "cae_vto": header["cae_vto"],
        "subtotal": None, "iva": None, "iva_detalle": [],
        "percepciones_total": None, "percepciones_detalle": [],
        "total": None,
        "debug": {"vendor": vendor or "UNKNOWN", "lines_count": len(lines)}
    }
    handler = REGISTRY.get((vendor or "").upper())
    if handler: handler(lines, out)
    else: _fallback_labels(lines, out)
    _validate_and_repair(out)
    out["source"] = "ocr" if used_ocr else "text"
    out["file"] = os.path.basename(pdf_path)
    return out
