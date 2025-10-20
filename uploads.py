# uploads.py
import os
import tempfile
import time
from fastapi import UploadFile, HTTPException

class Uploads:
    """Servicio para manejar archivos temporales subidos."""

    @staticmethod
    def save_temp_pdf(file: UploadFile) -> str:
        """
        Valida que el archivo sea PDF y lo guarda como archivo temporal.
        Devuelve la ruta del archivo temporal.
        """
        # Validación doble: extensión + content_type (opcional)
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser un PDF")

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                # Copia por chunks para evitar cargar todo en memoria
                file.file.seek(0)
                while True:
                    chunk = file.file.read(1024 * 1024)  # 1 MB
                    if not chunk:
                        break
                    tmp.write(chunk)
                return tmp.name
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error guardando archivo temporal: {str(e)}"
            )

    @staticmethod
    def cleanup_temp_file(path: str) -> None:
        """
        Elimina un archivo temporal con hasta 3 reintentos.
        (No lanza excepción, sólo intenta limpiar.)
        """
        for attempt in range(3):
            try:
                if path and os.path.exists(path):
                    os.unlink(path)
                break
            except PermissionError:
                time.sleep(0.1 * (attempt + 1))
            except Exception:
                break
