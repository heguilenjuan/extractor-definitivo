import os, yaml, re
from typing import List, Dict, Any, Optional, Tuple
from vendors_registry import REGISTRY
from extractor_utils import (
    read_pdf_text, ocr_pdf_to_lines, extract_header_common, extract_names_and_cuits,
    detect_vendor_basic, detect_vendor_by_cuit, parse_number_smart
)

import handlers_pirelli  # noqa: F401
import handlers_guerrini  # noqa: F401

# =========================
#  NORMALIZACIÓN DE TRIBUTOS
# =========================

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
    # --- RETENCIONES (primero) ---
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
    # --- PERCEPCIONES IIBB
    (r'\b(?:IB|IIBB)\s*BA\b.*\bLOC(?:AL)?\.?\b.*\bDN\b\s*B\s*70\s*[/\-]?\s*0?7\b', "percepcion_iibb_bs_as"),
    (r'\bDN\b\s*B\s*70\s*[/\-]?\s*0?7\b',                                          "percepcion_iibb_bs_as"),
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

# Alícuotas de IVA que solemos ver; agregamos 27 por las dudas
IVA_RATES_CANON = (27.0, 21.0, 10.5, 5.0, 2.5)


# =========================
#  HELPERS
# =========================

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
    from extractor_utils import NUM_PURE, NUM_ANY, first_amount_forward
    start = max(0, len(lines) - 150)
    tail = lines[start:]
    sub = iva = perc = tot = None
    iva_items = []; perc_items = []
    for i, line in enumerate(tail):
        up = line.upper()
        if sub is None and 'SUBTOTAL' in up:
            v = first_amount_forward(tail, i)
            if v is not None: sub = v
        if 'IVA' in up:
            v = first_amount_forward(tail, i)
            if v is not None:
                iva = (iva or 0.0) + v
                iva_items.append({"alicuota": None, "monto": v})
        if any(k in up for k in ['PERC', 'PERCEP', 'IIBB', 'INGRESOS BRUTOS', 'ARBA', 'AGIP']):
            v = first_amount_forward(tail, i)
            if v is not None:
                perc = (perc or 0.0) + v
                perc_items.append({"desc": line, "monto": v})
        if 'TOTAL' in up:
            v = first_amount_forward(tail, i)
            if v is not None: tot = v
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

def _normalize_fixed_schema(out: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Devuelve un dict con claves fijas y montos sumados por cada clave normalizada.
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
    return fixed

def _to_iso_date(maybe_date: Optional[str]) -> Optional[str]:
    if not maybe_date:
        return None
    s = maybe_date.strip()
    # Formatos típicos: dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd
    m = re.fullmatch(r'(\d{2})[\/\-.](\d{2})[\/\-.](\d{4})', s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}"
    m = re.fullmatch(r'(\d{4})[\/\-](\d{2})[\/\-](\d{2})', s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Si no puedo parsear, devuelvo lo original
    return s

def _parse_aliquota_to_float(a) -> Optional[float]:
    if a is None:
        return None
    s = str(a).strip().replace('%','').replace(',','.')
    try:
        v = float(s)
        # normalizo a 1 decimal cuando aplica (10.5)
        if abs(v - 10.5) < 1e-6: return 10.5
        if abs(v - 2.5) < 1e-6:  return 2.5
        if abs(v - 5.0) < 1e-6:  return 5.0
        if abs(v - 21.0) < 1e-6: return 21.0
        if abs(v - 27.0) < 1e-6: return 27.0
        return v
    except:
        return None

def _sum_iva_by_rate(iva_detalle: List[Dict[str, Any]], iva_total: Optional[float]) -> Dict[str, float]:
    """
    Devuelve {'21': 123.45, '10.5': 0.0, ...} solo con tasas presentes.
    Si no hay detalle pero hay total, deja {'otros': total}.
    """
    buckets: Dict[float, float] = {}
    for item in iva_detalle or []:
        rate = _parse_aliquota_to_float(item.get("alicuota"))
        amt = float(item.get("monto") or 0.0)
        if rate is None:
            # Lo mando a 'otros' si no hay tasa
            buckets[999.0] = round((buckets.get(999.0, 0.0) + amt), 2)
        else:
            buckets[rate] = round((buckets.get(rate, 0.0) + amt), 2)
    if not buckets and iva_total:
        buckets[999.0] = round(float(iva_total or 0.0), 2)
    out: Dict[str, float] = {}
    for k, v in buckets.items():
        key = "otros" if k == 999.0 else (str(int(k)) if float(k).is_integer() else str(k))
        out[key] = v
    # Orden sugerido por canon conocido
    ordered: Dict[str, float] = {}
    for r in IVA_RATES_CANON:
        rk = str(int(r)) if float(r).is_integer() else str(r)
        if rk in out and out[rk] > 0:
            ordered[rk] = out[rk]
    # agrego cualquiera extra (p.ej., 12 o 24)
    for rk, v in out.items():
        if rk not in ordered and v > 0:
            ordered[rk] = v
    return ordered

def _split_perc_ret(tributos: Dict[str, Optional[float]]) -> Tuple[Dict[str, float], Dict[str, float]]:
    percepciones: Dict[str, float] = {}
    retenciones: Dict[str, float] = {}
    for k, v in (tributos or {}).items():
        if v is None or float(v) == 0.0:
            continue
        if k.startswith("percepcion_") or k in ("impuesto_combustible","impuestos_y_sellados"):
            percepciones[k] = float(v)
        elif k.startswith("retencion_"):
            retenciones[k] = float(v)
    return percepciones, retenciones


def _build_minimal_payload(full: Dict[str, Any], prefer_cuit: str = "proveedor") -> Dict[str, Any]:
    """
    Devuelve: numero, fecha, cuit, subtotal, total, iva{...}, percepciones{...}, retenciones{...}.
    Si falta subtotal en 'full', lo estima como: total - sum(iva) - sum(percepciones).
    """
    numero = full.get("numero")
    fecha = _to_iso_date(full.get("fecha"))
    cuit = (full.get("cuit_proveedor") if prefer_cuit == "proveedor" else full.get("cuit_cliente")) or ""
    total = float(full.get("total") or 0.0)

    # IVA por alícuota + suma
    iva_por_tasa = _sum_iva_by_rate(full.get("iva_detalle"), full.get("iva"))
    iva_total = round(sum(iva_por_tasa.values()), 2) if iva_por_tasa else float(full.get("iva") or 0.0)

    # Percepciones / retenciones normalizadas
    trib_norm = _normalize_fixed_schema(full)
    percepciones, retenciones = _split_perc_ret(trib_norm)
    perc_total = round(sum(percepciones.values()), 2) if percepciones else 0.0

    # Subtotal directo o estimado
    subtotal = full.get("subtotal")
    if subtotal is None:
        subtotal = round(total - iva_total - perc_total, 2) if total else 0.0
        if abs(subtotal) < 1e-6:
            subtotal = 0.0

    out: Dict[str, Any] = {
        "numero": numero or "",
        "fecha": fecha or "",
        "cuit": cuit or "",
        "subtotal": round(float(subtotal or 0.0), 2),
        "total": round(total, 2),
        "iva": iva_por_tasa,
        "percepciones": percepciones,
        "retenciones": retenciones
    }
    return out

# =========================
#  PIPELINE PRINCIPAL
# =========================

def extract_from_pdf(pdf_path: str, vendor_hint: Optional[str] = None, cfg_path: str = "vendors.yaml") -> Dict[str, Any]:
    """Mantengo tu pipeline, pero ahora retornamos el payload MINIMAL normalizado."""
    lines = read_pdf_text(pdf_path)
    used_ocr = False

    if not lines or sum(len(l) for l in lines) < 30:
        lines = ocr_pdf_to_lines(pdf_path); used_ocr = True

    header = extract_header_common(lines)
    cfg = _load_vendor_config(cfg_path)
    name_keywords = cfg["detect"]["names"]; cuit_map = cfg["detect"]["cuits"]
    vendor = (vendor_hint or "").upper() or detect_vendor_basic(lines, name_keywords) or None

    proveedor, cuit_prov, cliente, cuit_cli = extract_names_and_cuits(lines, vendor)

    if not vendor and cuit_prov:
        vendor = detect_vendor_by_cuit(cuit_prov, cuit_map)

    # OUT COMPLETO (se usa como base interna, no es la respuesta final)
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

    _validate_and_repair(out)

    # === AQUÍ construimos la RESPUESTA MINIMAL ===
    minimal = _build_minimal_payload(out, prefer_cuit="proveedor")  # <-- cambia a "cliente" si querés

    # Si te interesa saber si usamos OCR para log/debug, podés anexarlo:
    # minimal["_meta"] = {"source": "ocr" if used_ocr else "text", "file": os.path.basename(pdf_path)}

    return minimal
