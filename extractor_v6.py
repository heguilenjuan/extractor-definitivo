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
import re


# --- ESQUEMA DE SALIDA FIJO ---
FIXED_TAX_FIELDS = [
    # Percepciones
    "percepcion_iva",
    "percepcion_iibb_bs_as",
    "percepcion_ganancias",
    "percepcion_iibb_la_pampa",
    "percepcion_iibb_rio_negro",
    "percepcion_iibb_neuquen",
    "percepcion_iibb_caba",
    "percepcion_iibb_cordoba",
    "percepcion_iibb_chubut",
    "percepcion_iibb_mendoza",
    "percepcion_iibb_santa_cruz",
    "percepcion_iibb_santa_fe",
    "percepcion_iibb_tucuman",
    "percepcion_iibb_entre_rios",
    "percepcion_iibb_la_rioja",
    "impuesto_combustible",
    "impuestos_y_sellados",
    # Retenciones
    "retencion_iva",
    "retencion_iibb_pcia_bs_as",
    "retencion_ganancias",
    "retencion_iibb_pcia_rio_negro",
    "retencion_iibb_pcia_neuquen",
    "retencion_iibb_sirtac",
]

# Orden importa: la primera que matchea gana
NORMALIZATION_RULES = [
    # --- RETENCIONES (detectamos primero para que no caigan en percepciones) ---
    (r'\bRET(ENCI[ÓO]N|\.?)\b.*\bIVA\b',                       "retencion_iva"),
    (r'\bRET(ENCI[ÓO]N|\.?)\b.*\bGANANCIAS?\b',                "retencion_ganancias"),
    (r'\bRET(ENCI[ÓO]N|\.?)\b.*\bIIBB\b.*\b(BUENOS\s*AIRES|ARBA|P\.?B\.?A)\b', "retencion_iibb_pcia_bs_as"),
    (r'\bRET(ENCI[ÓO]N|\.?)\b.*\bIIBB\b.*\bR[ÍI]O\s*NEGRO\b',  "retencion_iibb_pcia_rio_negro"),
    (r'\bRET(ENCI[ÓO]N|\.?)\b.*\bIIBB\b.*\bNEUQU[ÉE]N\b',      "retencion_iibb_pcia_neuquen"),
    (r'\bRET(ENCI[ÓO]N|\.?)\b.*\bSIRTAC\b',                    "retencion_iibb_sirtac"),

    # --- PERCEPCIONES IVA / AFIP ---
    (r'\bPERCEP(CCI[ÓO]N|\.?)\b.*\bIVA\b',                     "percepcion_iva"),
    (r'\bRG\s*3337\b|\bR\.?G\.?\s*3337\b|\bDGI\s*3337\b',      "percepcion_iva"),   
    (r'\bRG\s*2126\b|\bR\.?G\.?\s*2126\b',                     "percepcion_iva"),

    # --- PERCEPCIONES IIBB (provincias) ---
    (r'\bIIBB\b.*\b(BUENOS\s*AIRES|ARBA|P\.?B\.?A)\b',         "percepcion_iibb_bs_as"),
    (r'\bIIBB\b.*\bCABA\b|\bAGIP\b',                           "percepcion_iibb_caba"),
    (r'\bIIBB\b.*\bNEUQU[ÉE]N\b|\bIB\s*(CONV\.?|CONVENIO)\s*NEUQ', "percepcion_iibb_neuquen"), 
    (r'\bIIBB\b.*\bR[ÍI]O\s*NEGRO\b|\bRIO\s*NEG\b|\bIB\s*(CONV\.?|CONVENIO)\s*R[ÍI]O\s*NEG', "percepcion_iibb_rio_negro"), 
    (r'\bIIBB\b.*\bLA\s*PAMPA\b',                              "percepcion_iibb_la_pampa"),
    (r'\bIIBB\b.*\bC[ÓO]RDOBA\b',                              "percepcion_iibb_cordoba"),
    (r'\bIIBB\b.*\bCHUBUT\b',                                  "percepcion_iibb_chubut"),
    (r'\bIIBB\b.*\bMENDOZA\b',                                 "percepcion_iibb_mendoza"),
    (r'\bIIBB\b.*\bSANTA\s*CRUZ\b',                            "percepcion_iibb_santa_cruz"),
    (r'\bIIBB\b.*\bSANTA\s*FE\b',                              "percepcion_iibb_santa_fe"),
    (r'\bIIBB\b.*\bTUCUM[ÁA]N\b',                              "percepcion_iibb_tucuman"),
    (r'\bIIBB\b.*\bENTRE\s*R[IÍ]OS\b',                         "percepcion_iibb_entre_rios"),
    (r'\bIIBB\b.*\bLA\s*RIOJA\b',                              "percepcion_iibb_la_rioja"),

    # --- BA: DN B70/07 también es Bs.As. ---
    (r'\bDN\s*B70(?:\/0?7)?\b|\bIB\s*BA\b',                    "percepcion_iibb_bs_as"),
    
    # --- GANANCIAS (percepciones) ---
    (r'\bPERCEP(CCI[ÓO]N|\.?)\b.*\bGANANCIAS?\b',              "percepcion_ganancias"),

    # --- OTROS ---
    (r'IMPUESTO\s+AL\s+COMBUSTIBLE|ITC\b',                     "impuesto_combustible"),
    (r'\bSELLOS\b|\bIMPUESTOS?\s+VARIOS\b|\bIMPUESTOS?\b',     "impuestos_y_sellados"),
 
]

def _normalize_fixed_schema(out: Dict[str, Any]) -> None:
    """
    Rellena SIEMPRE las claves fijas (FIXED_TAX_FIELDS) con None o con el total
    sumado por cada clave normalizada, usando percepciones_detalle/percepciones_total.
    """
    fixed = {k: None for k in FIXED_TAX_FIELDS}

    items = list(out.get("percepciones_detalle") or [])
    total_perc = out.get("percepciones_total")
    if (not items) and (total_perc is not None):
        items = [{"desc": "PERCEP. IIBB", "monto": total_perc}]

    for it in items:
        desc_raw = (it.get("desc") or "").upper()
        monto = float(it.get("monto") or 0.0)
        matched_key = None
        for pattern, key in NORMALIZATION_RULES:
            if re.search(pattern, desc_raw, flags=re.I):
                matched_key = key
                break
        if matched_key:
            fixed[matched_key] = round((fixed[matched_key] or 0.0) + monto, 2)

    # lo agregamos como bloque aparte; no toca tus campos existentes
    out["tributos_normalizados"] = fixed

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
        "proveedor": proveedor, 
        "cuit_proveedor": cuit_prov,
        "cliente": cliente,
        "cuit_cliente": cuit_cli,
        "tipo": header["tipo"], 
        "numero": header["numero"],
        "fecha": header["fecha"], 
        "cae": header["cae"], 
        "cae_vto": header["cae_vto"],
        "subtotal": None, 
        "iva": None, 
        "iva_detalle": [],
        "percepciones_total": None, 
        "percepciones_detalle": [],
        "total": None,
        "debug": {"vendor": vendor or "UNKNOWN", "lines_count": len(lines)}
    }
    
    handler = REGISTRY.get((vendor or "").upper())
    
    if handler: 
        handler(lines, out)
    else: 
        _fallback_labels(lines, out)
        
    _normalize_fixed_schema(out)
    _validate_and_repair(out)
        
    out["source"] = "ocr" if used_ocr else "text"
    out["file"] = os.path.basename(pdf_path)
    
    return out
