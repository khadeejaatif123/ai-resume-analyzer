import os
import io

def extract_text(file_path: str, file_type: str) -> tuple[str, str | None]:
    """
    Extract plain text from a resume file.
    Returns (text, error_message). If extraction fails, text="" and error is set.
    """
    try:
        if file_type == "pdf":
            return _extract_pdf(file_path)
        elif file_type == "docx":
            return _extract_docx(file_path)
        elif file_type == "txt":
            return _extract_txt(file_path)
        else:
            return "", f"Unsupported file type: {file_type}"
    except Exception as e:
        return "", f"Extraction error: {str(e)}"


def _extract_pdf(file_path: str) -> tuple[str, str | None]:
    try:
        import PyPDF2
        text_parts = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        text = "\n".join(text_parts).strip()
        if not text:
            return "", "PDF appears to be empty or image-only (no extractable text)."
        return text, None
    except Exception as e:
        return "", f"PDF parse error: {str(e)}"


def _extract_docx(file_path: str) -> tuple[str, str | None]:
    try:
        from docx import Document
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs).strip()
        if not text:
            return "", "DOCX appears to contain no text paragraphs."
        return text, None
    except Exception as e:
        return "", f"DOCX parse error: {str(e)}"


def _extract_txt(file_path: str) -> tuple[str, str | None]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
        if not text:
            return "", "TXT file is empty."
        return text, None
    except Exception as e:
        return "", f"TXT read error: {str(e)}"
