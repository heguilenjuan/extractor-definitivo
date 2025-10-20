# handlers_pirelli.py
# 
import re
from typing import List, Dict, Any, Optional
from vendors_registry import register
from extractor_utils import NUM_ANY, NUM_PURE, parse_number_smart

@register("PIRELLI")
def extract_totals_pirelli(lines: List[str], out: Dict[str, Any]) -> None:
    
    start = max(0, len(lines) - 120)
    tail = lines[start:]
    subtotal = iva_total = percep_total = total = None
    iva_items = []; percep_items = []

    def first_num_near(i: int, span: int = 6) -> Optional[float]:
        for j in range(i, min(len(tail), i + span + 1)):
            m = NUM_PURE.search(tail[j]) or NUM_ANY.search(tail[j])
            if m:
                v = parse_number_smart(m.group(0))
                if v is not None: return v
        return None

    for i, line in enumerate(tail):
        up = line.upper()
        if 'SUBTOTAL' in up and subtotal is None:
            v = first_num_near(i)
            if v is not None: subtotal = v
        if 'IVA' in up:
            mrate = re.search(r'IVA\s*([\d]{1,2}(?:[.,]\d{1,2})?)', line, re.I)
            alic = mrate.group(1).replace(',', '.') if mrate else None
            v = first_num_near(i)
            if v is not None:
                iva_total = (iva_total or 0.0) + v
                iva_items.append({"alicuota": alic, "monto": v})
        if any(k in up for k in ['IIBB', 'PERC', 'RG DGI', 'DN B70', 'NEUQUEN', 'RÍO NEG', 'RIO NEG']):
            v = first_num_near(i)
            if v is not None:
                percep_total = (percep_total or 0.0) + v
                percep_items.append({"desc": line, "monto": v})
        if 'IMPORTE TOTAL' in up or re.search(r'\bTOTAL\b', up):
            v = first_num_near(i)
            if v is not None: total = v

    out["subtotal"] = subtotal
    out["iva"] = round(iva_total, 2) if iva_total is not None else None
    out["iva_detalle"] = iva_items
    out["percepciones_total"] = round(percep_total, 2) if percep_total is not None else None
    out["percepciones_detalle"] = percep_items
    out["total"] = total
    
    if out["total"] is None and (subtotal is not None):
        out["total"] = round(subtotal + (out["iva"] or 0.0) + (out["percepciones_total"] or 0.0), 2)
