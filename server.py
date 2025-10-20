from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from enum import Enum
from typing import Annotated  # 👈
import tempfile, os
from extractor_v6 import extract_from_pdf

app = FastAPI(title="Factura Extractor API v6", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

class Vendor(str, Enum):
    GUERRINI = "GUERRINI"
    PIRELLI = "PIRELLI"

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

@app.post("/extract", response_model=None)  # 👈 evita que Pydantic infiera un modelo
async def extract_invoice(
    file: Annotated[UploadFile, File(...)],   # 👈 Annotated
    vendor: Annotated[Vendor, Form(...)]      # 👈 Annotated + enum obligatorio
) -> dict:
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
        result = extract_from_pdf(tmp_path, vendor_hint=vendor.value, cfg_path="vendors.yaml")
        return result
    finally:
        try:
            os.remove(tmp_path)
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
