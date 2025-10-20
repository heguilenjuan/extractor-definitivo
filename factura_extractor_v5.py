#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extractor de facturas AR v5
- Mantiene Pirelli estable.
- Corrige GUERRINI con parsing por bloque (SUBTOTAL / IVA / PERCEP / TOTAL): toma los
cuatro importes "numéricos puros" que aparecen después de esas etiquetas, en orden.
- Evita falsos positivos (ej. "Ingresos Brutos: C.M. 913-502151-6") en percepciones.
- Nombre de proveedor/cliente más robusto (busca GUERRINI/PIRELLI explícitamente).
"""

import re
import os
from typing import List, Dict, Any, Tuple, Optional

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None

try:
    import pytesseract
    from pytesseract import image_to_data
except Exception:
    pytesseract = None
    image_to_data = None

try:
    from PIL import Image
except Exception:
    Image = None

def _norm_line(s: str) -> str:
    s = s.replace('\xa0', ' ')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def _strip_currency(s: str) -> str:
    return re.sub(r'[$]', '', s).strip()

def _parse_number_smart(s: str) -> Optional[float]:
    if s is None:
        return None
    s = _strip_currency(s)
    s = s.replace(' ', '')
    s = re.sub(r'[^0-9,.\-]', '', s)
    if re.search(r'[.,]\d{2}$', s):
        dec = s[-3:-2]
        if dec == ',':
            t = s.replace('.', '').replace(',', '.')
        else:
            t = s.replace(',', '')
        try:
            return float(t)
        except Exception:
            return None
    if ',' in s and '.' not in s:
        t = s.replace(',', '')
        try:
            return float(t)
        except Exception:
            return None
    if '.' in s and ',' not in s:
        try:
            return float(s)
        except Exception:
            t = s.replace('.', '')
            try:
                return float(t)
            except Exception:
                return None
    m = list(re.finditer(r'[.,]', s))
    if m:
        last = m[-1].group(0)
        if last == ',':
            t = s.replace('.', '').replace(',', '.')
        else:
            t = s.replace(',', '')
        try:
            return float(t)
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None


RE_CUIT = re.compile(r'\b\d{2}[- ]?\d{7,8}[- ]?\d\b')
RE_FECHA = re.compile(
    r'\b(?:\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})(?:\s+\d{1,2}:\d{1,2}:\d{1,2})?\b'
)
RE_NUM_FACT = re.compile(r'\b\d{4}-\d{8}\b')
RE_CAE = re.compile(r'\b\d{14}\b', re.ASCII)
NUM_PURE = re.compile(r'^\s*-?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*$')  # línea “sólo número con 2 decimales”
NUM_ANY = re.compile(r'[-]?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|[-]?\d+(?:[.,]\d{2})')


def read_pdf_text(pdf_path: str) -> List[str]:
    lines = []
    if fitz is None:
        return lines
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                txt = page.get_text("text")
                if txt:
                    lines.extend(txt.splitlines())
    except Exception:
        return []
    return [_norm_line(l) for l in lines if _norm_line(l)]


def ocr_pdf_to_lines(pdf_path: str, dpi: int = 300) -> List[str]:
    if convert_from_path is None or pytesseract is None or Image is None:
        return []
    text_lines: List[str] = []
    try:
        images = convert_from_path(pdf_path, dpi=dpi)
    except Exception:
        return []
    for img in images:
        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang='spa+eng')
            n = len(data['text'])
            current_line_no = None
            buf = []
            for i in range(n):
                if int(data['conf'][i]) < 0:
                    continue
                t = data['text'][i].strip()
                if not t:
                    continue
                ln = data.get('line_num', [1]*n)[i]
                if current_line_no is None:
                    current_line_no = ln
                if ln != current_line_no:
                    line = _norm_line(' '.join(buf))
                    if line:
                        text_lines.append(line)
                    buf = [t]
                    current_line_no = ln
                else:
                    buf.append(t)
            if buf:
                line = _norm_line(' '.join(buf))
                if line:
                    text_lines.append(line)
        except Exception:
            txt = pytesseract.image_to_string(img, lang='spa+eng')
            for line in txt.splitlines():
                line = _norm_line(line)
                if line:
                    text_lines.append(line)
    return text_lines


def _detect_vendor(lines: List[str]) -> Optional[str]:
    s = ' '.join(lines[:120]).upper()  # sólo cabecera
    if 'PIRELLI' in s:
        return 'PIRELLI'
    if 'GUERRINI NEUMATICOS' in s or 'GUERRINI NEUMÁTICOS' in s:
        return 'GUERRINI'
    return None


def _extract_names_and_cuits(lines: List[str], vendor: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    proveedor = None
    cuit_prov = None
    cliente = None
    cuit_cli = None

    # Proveedor: buscar explícito por vendor en cabecera
    head = [l.strip() for l in lines[:60]]
    if vendor == 'GUERRINI':
        for l in head:
            if re.search(r'GUERRINI\s+NEUM[AÁ]TICOS?\s*S\.?A\.?', l, re.I):
                proveedor = l
                break
    elif vendor == 'PIRELLI':
        for l in head:
            if re.search(r'PIRELLI\s+NEUM[AÁ]TICOS?\s*S\.?A\.?I\.?C\.?', l, re.I):
                proveedor = l
                break

    # CUITs
    cuit_positions: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        for m in RE_CUIT.finditer(line):
            cuit_positions.append((i, m.group(0)))
    cuit_positions.sort(key=lambda x: x[0])
    if cuit_positions:
        cuit_prov = cuit_positions[0][1]
        # cliente = último CUIT distinto
        rest = [c for c in cuit_positions if c[1] != cuit_prov]
        if rest:
            cuit_cli = rest[-1][1]
            # nombre de cliente: buscar líneas anteriores a ese CUIT que parezcan nombre
            idx = rest[-1][0]
            for j in range(max(0, idx-5), idx+1):
                cand = lines[j].strip()
                if re.search(r'(ALVAREZ|NEUM[AÁ]TIC|S\.A\.|SRL|RESPONSABLE|CLIENTE)', cand, re.I) or cand.isupper():
                    cliente = cand
                    break

    return proveedor, cuit_prov, cliente, cuit_cli


def _extract_header_common(lines: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "proveedor": None, "cuit_proveedor": None,
        "cliente": None, "cuit_cliente": None,
        "tipo": None, "numero": None, "fecha": None,
        "cae": None, "cae_vto": None,
    }

    # Tipo y número
    for i, line in enumerate(lines[:200]):
        m = re.search(r'\bFactura\s*([ABC])\b', line, re.I)
        if m:
            out["tipo"] = m.group(1).upper()
            break
        if re.fullmatch(r'[ABC]', line.strip(), re.I):
            out["tipo"] = line.strip().upper()

    for line in lines:
        m = RE_NUM_FACT.search(line)
        if m:
            out["numero"] = m.group(0)

    # Fecha (primera razonable)
    for line in lines:
        m = RE_FECHA.search(line)
        if m:
            out["fecha"] = m.group(0)
            break

    # CAE + Vto
    for i, line in enumerate(lines):
        up = line.upper()
        if 'CAE' in up:
            m = RE_CAE.search(line)
            if not m:
                m = RE_CAE.search(line.replace('CAE', ''))
            if m:
                out["cae"] = m.group(0)
            # Vto en misma o próximas 2 líneas
            if any(k in up for k in ['VTO', 'VENC']):
                mf = RE_FECHA.search(line)
                if not mf and i+1 < len(lines):
                    for k in range(i+1, min(i+3, len(lines))):
                        mf = RE_FECHA.search(lines[k])
                        if mf:
                            break
                if mf:
                    out["cae_vto"] = mf.group(0)
    return out


def _extract_totals_block_guerrini(lines: List[str], out: Dict[str, Any]) -> None:
    """Busca el bloque 'SUBTOTAL: ... TOTAL:' y mapea los 4 números 'puros' siguientes en orden."""
    # Encontrar índice de 'SUBTOTAL:' que esté más cerca del pie
    idx_sub = None
    for i in range(len(lines)-1, -1, -1):
        if re.search(r'\bSUBTOTAL\b', lines[i].upper()):
            idx_sub = i
            break
    if idx_sub is None:
        return

    # Buscar ventana hasta 60 líneas después o hasta fin
    win = lines[idx_sub: min(len(lines), idx_sub + 60)]
    numeric_lines: List[Tuple[int, float]] = []
    for j, l in enumerate(win):
        if NUM_PURE.match(l):
            v = _parse_number_smart(l)
            if v is not None:
                numeric_lines.append((j, v))

    # Filtrar números aislados que pertenezcan a items (heurística):
    # mantendremos sólo los que aparecen DESPUÉS de "SUBTOTAL" y cerca de "TOTAL"
    # (ya estamos en una ventana desde SUBTOTAL, así que tomamos los 4 primeros)
    values = [v for _, v in numeric_lines[:4]]
    if len(values) >= 2:
        out["subtotal"] = values[0]
        out["iva"] = values[1]
        out["iva_detalle"] = [{"alicuota": "21.00", "monto": values[1]}]  # Guerrini imprime "IVA 21.00"
        out["percepciones_total"] = values[2] if len(values) >= 3 else 0.0
        out["percepciones_detalle"] = [] if len(values) < 3 else [{"desc": "PERCEP. IIBB", "monto": values[2]}]
        out["total"] = values[3] if len(values) >= 4 else round(values[0] + values[1] + (values[2] if len(values)>=3 else 0.0), 2)


def _extract_totals_pirelli(lines: List[str], out: Dict[str, Any]) -> None:
    # Escaneo de cola y etiquetas (como v3/v4) con números próximos
    start = max(0, len(lines) - 120)
    tail = lines[start:]
    subtotal = iva_total = percep_total = total = None
    iva_items = []
    percep_items = []

    def first_num_near(i: int, span: int = 6) -> Optional[float]:
        for j in range(i, min(len(tail), i + span + 1)):
            # Sólo números con 2 decimales o línea-numérica
            m = NUM_ANY.search(tail[j])
            if m and NUM_PURE.match(tail[j]) or m:
                v = _parse_number_smart(m.group(0))
                if v is not None:
                    return v
        return None

    for i, line in enumerate(tail):
        up = line.upper()
        if 'SUBTOTAL' in up and subtotal is None:
            v = first_num_near(i)
            if v is not None:
                subtotal = v
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
            if v is not None:
                total = v

    out["subtotal"] = subtotal
    out["iva"] = round(iva_total, 2) if iva_total is not None else None
    out["iva_detalle"] = iva_items
    out["percepciones_total"] = round(percep_total, 2) if percep_total is not None else None
    out["percepciones_detalle"] = percep_items
    out["total"] = total
    if out["total"] is None and (subtotal is not None):
        out["total"] = round(subtotal + (out["iva"] or 0.0) + (out["percepciones_total"] or 0.0), 2)


def extract_fields_from_lines(lines: List[str]) -> Dict[str, Any]:
    vendor = _detect_vendor(lines)
    header = _extract_header_common(lines)
    proveedor, cuit_prov, cliente, cuit_cli = _extract_names_and_cuits(lines, vendor)

    out: Dict[str, Any] = {
        "proveedor": proveedor or header["proveedor"] or ("GUERRINI NEUMATICOS S.A." if vendor=="GUERRINI" else ("PIRELLI NEUMÁTICOS S.A.I.C" if vendor=="PIRELLI" else None)),
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

    if vendor == 'GUERRINI':
        _extract_totals_block_guerrini(lines, out)
    elif vendor == 'PIRELLI':
        _extract_totals_pirelli(lines, out)
    else:
        # fallback parecido al de Guerrini (etiquetas claras)
        _extract_totals_block_guerrini(lines, out)

    return out


def extract_from_pdf(pdf_path: str) -> Dict[str, Any]:
    lines = read_pdf_text(pdf_path)
    used_ocr = False
    if not lines or sum(len(l) for l in lines) < 30:
        lines = ocr_pdf_to_lines(pdf_path)
        used_ocr = True
    result = extract_fields_from_lines(lines)
    result["source"] = "ocr" if used_ocr else "text"
    result["file"] = os.path.basename(pdf_path)
    return result
