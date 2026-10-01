"""Turn uploaded data-room files into plain text for the model."""
import io


def to_text(name: str, data: bytes) -> str:
    n = name.lower()
    try:
        if n.endswith(".pdf"):
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(data))
            return "\n".join(f"[p{i+1}] " + (pg.extract_text() or "") for i, pg in enumerate(r.pages))
        if n.endswith(".docx"):
            import docx
            d = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in d.paragraphs)
        return data.decode("utf-8", errors="replace")
    except Exception as e:  # never silently drop a document
        return f"[COULD NOT READ {name}: {e}]"
