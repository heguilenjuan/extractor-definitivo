# handlers_guerrini.py
import re
from typing import List, Dict, Any, Tuple
from vendors_registry import register
from extractor_utils import NUM_PURE, parse_number_smart

@register("GUERRINI")
def extract_totals_guerrini(lines: List[str], out: Dict[str, Any]) -> None:
    idx_sub = None
    for i in range(len(lines)-1, -1, -1):
        if re.search(r'\bSUBTOTAL\b', lines[i].upper()):
            idx_sub = i; break
    if idx_sub is None: return
    win = lines[idx_sub: min(len(lines), idx_sub + 60)]
    numeric_lines: List[Tuple[int, float]] = []
    for j, l in enumerate(win):
        if NUM_PURE.match(l):
            v = parse_number_smart(l)
            if v is not None: numeric_lines.append((j, v))
    values = [v for _, v in numeric_lines[:4]]
    if len(values) >= 2:
        out["subtotal"] = values[0]
        out["iva"] = values[1]
        out["iva_detalle"] = [{"alicuota": "21.00", "monto": values[1]}]
        out["percepciones_total"] = values[2] if len(values) >= 3 else 0.0
        out["percepciones_detalle"] = [] if len(values) < 3 else [{"desc": "PERCEP. IIBB", "monto": values[2]}]
        out["total"] = values[3] if len(values) >= 4 else round(values[0] + values[1] + (values[2] if len(values)>=3 else 0.0), 2)
