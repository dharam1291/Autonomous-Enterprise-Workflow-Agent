from __future__ import annotations

from pathlib import Path


class DocumentLoaderError(RuntimeError):
    """Raised when document text cannot be loaded."""


class DocumentLoader:
    def load_text(self, file_name: str, content: bytes) -> str:
        suffix = Path(file_name).suffix.lower()
        if suffix in {"", ".txt"}:
            return content.decode("utf-8", errors="replace")
        if suffix == ".pdf":
            return self._load_pdf(content)
        raise DocumentLoaderError(f"Unsupported document type: {suffix}")

    @staticmethod
    def _load_pdf(content: bytes) -> str:
        try:
            from io import BytesIO

            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentLoaderError(
                "PDF ingestion requires the optional dependency: pip install -e '.[pdf]'"
            ) from exc

        reader = PdfReader(BytesIO(content))
        text_parts = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(part.strip() for part in text_parts if part.strip())
        if not text:
            raise DocumentLoaderError("No readable text found in PDF.")
        return text

