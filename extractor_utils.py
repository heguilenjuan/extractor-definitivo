# extractor_utils.py
# Lee el texto del PDF con PyMuPDF o con OCR
# Normaliza texto: Limpia espacios, caracteres raros, etc
# Detecta y convierte numeros
# Detecta vendedor por nombre o CUIT
# Extrae datos comunes

import re
from typing import List, Tuple, Optional, Dict, Any
try:
    import fitz
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
    

def norm_line(s: str) -> str:
    s = s.replace('\xa0', ' ')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def strip_currency(s: str) -> str:
    return re.sub(r'[$]', '', s).strip()


def parse_number_smart(s: str) -> Optional[float]:
    if s is None: return None
    s = strip_currency(s).replace(' ', '')
    s = re.sub(r'[^0-9,.\-]', '', s)
    import re as _re
    if _re.search(r'[.,]\d{2}$', s):
        dec = s[-3:-2]
        t = s.replace('.', '').replace(',', '.') if dec == ',' else s.replace(',', '')
        try: return float(t)
        except: return None
    if ',' in s and '.' not in s:
        try: return float(s.replace(',', ''))
        except: return None
    if '.' in s and ',' not in s:
        try: return float(s)
        except:
            try: return float(s.replace('.', ''))
            except: return None
    m = list(_re.finditer(r'[.,]', s))
    if m:
        last = m[-1].group(0)
        t = s.replace('.', '').replace(',', '.') if last == ',' else s.replace(',', '')
        try: return float(t)
        except: return None
    try: return float(s)
    except: return None

RE_CUIT = re.compile(r'\b\d{2}[- ]?\d{7,8}[- ]?\d\b')
RE_FECHA = re.compile(r'\b(?:\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2,4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})(?:\s+\d{1,2}:\d{1,2}:\d{1,2})?\b')
RE_NUM_FACT = re.compile(r'\b\d{4}-\d{8}\b')
RE_CAE = re.compile(r'\b\d{14}\b', re.ASCII)
NUM_PURE = re.compile(r'^\s*-?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*$')
NUM_ANY = re.compile(r'[-]?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|[-]?\d+(?:[.,]\d{2})')

def read_pdf_text(pdf_path: str) -> List[str]:
    lines = []
    if fitz is None: return lines
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                txt = page.get_text("text")
                if txt: lines.extend(txt.splitlines())
    except Exception:
        return []
    return [norm_line(l) for l in lines if norm_line(l)]

def ocr_pdf_to_lines(pdf_path: str, dpi: int = 300) -> List[str]:
    if convert_from_path is None or pytesseract is None or Image is None: return []
    text_lines: List[str] = []
    try: images = convert_from_path(pdf_path, dpi=dpi)
    except Exception: return []
    for img in images:
        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang='spa+eng')
            n = len(data['text']); current_line_no = None; buf = []
            for i in range(n):
                if int(data['conf'][i]) < 0: continue
                t = data['text'][i].strip()
                if not t: continue
                ln = data.get('line_num', [1]*n)[i]
                if current_line_no is None: current_line_no = ln
                if ln != current_line_no:
                    line = norm_line(' '.join(buf))
                    if line: text_lines.append(line)
                    buf = [t]; current_line_no = ln
                else:
                    buf.append(t)
            if buf:
                line = norm_line(' '.join(buf))
                if line: text_lines.append(line)
        except Exception:
            txt = pytesseract.image_to_string(img, lang='spa+eng')
            for line in txt.splitlines():
                line = norm_line(line)
                if line: text_lines.append(line)
    return text_lines

def first_amount_forward(lines: List[str], start_idx: int, max_ahead: int = 12) -> Optional[float]:
    for j in range(start_idx, min(len(lines), start_idx + max_ahead + 1)):
        line = lines[j].strip()
        if not line: continue
        import re as _re
        solo = _re.fullmatch(r'[-]?\s*[\d.,]+\s*', line)
        m = NUM_PURE.search(line) or NUM_ANY.search(line) if solo else NUM_PURE.search(line) or NUM_ANY.search(line)
        if m:
            v = parse_number_smart(m.group(0))
            if v is not None: return v
    return None

def detect_vendor_basic(lines: List[str], name_keywords: Dict[str, list]) -> Optional[str]:
    header = ' '.join(lines[:120]).upper()
    for vid, keys in name_keywords.items():
        for k in keys:
            if k.upper() in header: return vid
    return None

def detect_vendor_by_cuit(cuit: Optional[str], cuit_map: Dict[str, str]) -> Optional[str]:
    if not cuit: return None
    return cuit_map.get(cuit)

def extract_header_common(lines: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"tipo": None, "numero": None, "fecha": None, "cae": None, "cae_vto": None}
    for i, line in enumerate(lines[:200]):
        m = re.search(r'\bFactura\s*([ABC])\b', line, re.I)
        if m: out["tipo"] = m.group(1).upper(); break
        if re.fullmatch(r'[ABC]', line.strip(), re.I): out["tipo"] = line.strip().upper()
    for line in lines:
        m = RE_NUM_FACT.search(line)
        if m: out["numero"] = m.group(0)
    for line in lines:
        m = RE_FECHA.search(line)
        if m: out["fecha"] = m.group(0); break
    for i, line in enumerate(lines):
        up = line.upper()
        if 'CAE' in up:
            m = RE_CAE.search(line) or RE_CAE.search(line.replace('CAE', ''))
            if m: out["cae"] = m.group(0)
            if any(k in up for k in ['VTO', 'VENC']):
                mf = RE_FECHA.search(line)
                if not mf and i+1 < len(lines):
                    for k in range(i+1, min(i+3, len(lines))):
                        mf = RE_FECHA.search(lines[k])
                        if mf: break
                if mf: out["cae_vto"] = mf.group(0)
    return out

def extract_names_and_cuits(lines: List[str], vendor: Optional[str]):
    proveedor = None; cuit_prov = None; cliente = None; cuit_cli = None
    cuit_positions: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        for m in RE_CUIT.finditer(line):
            cuit_positions.append((i, m.group(0)))
    cuit_positions.sort(key=lambda x: x[0])
    if cuit_positions:
        cuit_prov = cuit_positions[0][1]
        rest = [c for c in cuit_positions if c[1] != cuit_prov]
        if rest:
            cuit_cli = rest[-1][1]
            idx = rest[-1][0]
            for j in range(max(0, idx-5), idx+1):
                cand = lines[j].strip()
                if re.search(r'(ALVAREZ|NEUM[AÁ]TIC|S\.A\.|SRL|RESPONSABLE|CLIENTE)', cand, re.I) or cand.isupper():
                    cliente = cand; break
    head = [l.strip() for l in lines[:80]]
    if vendor == 'GUERRINI':
        for l in head:
            if re.search(r'GUERRINI\s+NEUM[AÁ]TICOS?\s*S\.?A\.?', l, re.I): proveedor = l; break
    elif vendor == 'PIRELLI':
        for l in head:
            if re.search(r'PIRELLI\s+NEUM[AÁ]TICOS?\s*S\.?A\.?I\.?C\.?', l, re.I): proveedor = l; break
    return proveedor, cuit_prov, cliente, cuit_cli