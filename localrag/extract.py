"""DOCX / PDF / PPTX text extraction with page / section tracking (per-page PDF analysis)."""
from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .textutil import normalize_text


class ExtractionError(Exception):
    """Friendly extraction failure. `status` is the document status to record."""

    status = "error"

    def __init__(self, message: str, status: str | None = None):
        super().__init__(message)
        if status:
            self.status = status


class NoTextError(ExtractionError):
    """No extractable text and nothing OCR can be attempted on."""

    status = "no_text"


@dataclass
class Segment:
    text: str
    page: int | None = None
    heading: str | None = None
    is_heading: bool = False
    source: str = "text"  # 'text' | 'ocr' | 'notes'
    confidence: float | None = None
    hidden: bool = False


@dataclass
class Extracted:
    segments: list[Segment] = field(default_factory=list)
    page_count: int | None = None
    ocr_pages: list[int] = field(default_factory=list)  # PDF pages (1-based) with no usable text layer
    suspect_pages: list[int] = field(default_factory=list)  # subset of ocr_pages: garbage text (broken fonts)
    status: str = "indexed"  # indexed | partial_content | text_suspect
    warning: str | None = None
    prefix_heading: bool = False


def extract(path: Path, min_pdf_chars_per_page: int = 40, cfg=None) -> Extracted:
    ext = path.suffix.lower()
    try:
        if ext == ".docx":
            return extract_docx(path)
        if ext == ".pdf":
            ratio = float(cfg.get("index", "suspect_char_ratio", default=0.30)) if cfg else 0.30
            return extract_pdf(path, min_pdf_chars_per_page, ratio)
        if ext == ".pptx":
            notes = bool(cfg.get("pptx", "include_notes", default=True)) if cfg else True
            return extract_pptx(path, include_notes=notes)
    except ExtractionError:
        raise
    except PermissionError as e:
        raise ExtractionError(f"File bị khóa hoặc không có quyền đọc: {path.name}", "locked") from e
    except Exception as e:  # corrupt files raise many different exception types
        kind = {".docx": "DOCX không đọc được", ".pptx": "PPTX không đọc được"}.get(ext, "PDF hỏng hoặc không đọc được")
        raise ExtractionError(f"{kind}: {path.name} ({type(e).__name__}: {e})", "corrupt") from e
    raise ExtractionError(f"Định dạng không được hỗ trợ: {ext}")


_OLE_MAGIC = b"\xd0\xcf\x11\xe0"  # password-protected OOXML files are wrapped in an OLE container


def _check_ole_encrypted(path: Path, label: str) -> None:
    with open(path, "rb") as f:
        if f.read(4) == _OLE_MAGIC:
            raise ExtractionError(f"{label} có mật khẩu (hoặc định dạng cũ), không đọc được: {path.name}", "encrypted")


# --------------------------------------------------------------------- DOCX
def extract_docx(path: Path) -> Extracted:
    _check_ole_encrypted(path, "DOCX")
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    out = Extracted()
    current_heading: str | None = None

    def para_segment(p: Paragraph) -> None:
        nonlocal current_heading
        text = normalize_text(p.text)
        if not text:
            return
        style = (p.style.name if p.style is not None else "") or ""
        if style.lower().startswith("heading") or style.lower() == "title":
            current_heading = text
            out.segments.append(Segment(text, None, current_heading, True))
        else:
            out.segments.append(Segment(text, None, current_heading))

    def table_segment(t: Table) -> None:
        rows = []
        for row in t.rows:
            seen, cells = set(), []
            for cell in row.cells:
                if id(cell._tc) in seen:  # merged cells repeat
                    continue
                seen.add(id(cell._tc))
                cells.append(normalize_text(cell.text).replace("\n", " "))
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            out.segments.append(Segment("\n".join(rows), None, current_heading))

    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para_segment(Paragraph(child, document))
        elif tag == "tbl":
            table_segment(Table(child, document))
    return out


# ---------------------------------------------------------------------- PDF
def _suspect_ratio(text: str) -> float:
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    bad = sum(1 for ch in chars if ch == "�" or unicodedata.category(ch) in ("Co", "Cn", "Cs"))
    bad += text.count("(cid:") * 6
    return min(1.0, bad / len(chars))


def extract_pdf(path: Path, min_chars_per_page: int = 40, suspect_ratio: float = 0.30) -> Extracted:
    """Per-page analysis with pypdfium2: pages with too little text are queued for OCR (so mixed
    text/scan PDFs work); pages whose text layer is garbage (old fonts) are flagged as suspect."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise ExtractionError(f"PDF được mã hóa bằng mật khẩu: {path.name}", "encrypted") from e
        raise ExtractionError(f"PDF hỏng hoặc không đọc được: {path.name} ({e})", "corrupt") from e
    raw_pages: list[list[str]] = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                tp = page.get_textpage()
                try:
                    raw = tp.get_text_range() or ""
                finally:
                    tp.close()
            finally:
                page.close()
            raw = raw.replace("\r\n", "\n").replace("\r", "\n")
            raw_pages.append([ln.strip() for ln in normalize_text(raw).split("\n")])
    finally:
        pdf.close()

    pages = _strip_repeated_lines(raw_pages)
    out = Extracted(page_count=len(pages))
    for i, lines in enumerate(pages, start=1):
        text = _join_lines(lines)
        compact = len(text.replace(" ", "").replace("\n", ""))
        if compact < min_chars_per_page:
            out.ocr_pages.append(i)
            continue
        if _suspect_ratio(text) > suspect_ratio:
            out.ocr_pages.append(i)
            out.suspect_pages.append(i)
            continue
        for para in [p for p in text.split("\n\n") if p.strip()]:
            out.segments.append(Segment(para.strip(), i))
    if out.suspect_pages:
        out.status = "text_suspect"
        out.warning = (f"{len(out.suspect_pages)} trang có lỗi font (ký tự không đọc được); "
                       "các trang này chỉ tìm được sau khi OCR.")
    return out


def _digits_to_hash(line: str) -> str:
    """Normalise page numbers so 'Trang 1' and 'Trang 2' count as the same footer."""
    if len(line.split()) > 8:  # long lines are body text, not page-number footers
        return line
    return "".join("#" if ch.isdigit() else ch for ch in line)


def _strip_repeated_lines(pages: list[list[str]]) -> list[list[str]]:
    """Remove header/footer lines repeated on >= 50% of pages (needs >= 3 pages)."""
    if len(pages) < 3:
        return pages
    counter: Counter[str] = Counter()
    for lines in pages:
        edge = [ln for ln in lines[:2] + lines[-2:] if ln]
        for key in {_digits_to_hash(ln) for ln in edge}:
            counter[key] += 1
    threshold = max(2, len(pages) // 2)
    repeated = {k for k, v in counter.items() if v >= threshold}
    cleaned = []
    for lines in pages:
        n = len(lines)
        cleaned.append([
            ln for idx, ln in enumerate(lines)
            if not (_digits_to_hash(ln) in repeated and (idx < 2 or idx >= n - 2))
        ])
    return cleaned


def _join_lines(lines: list[str]) -> str:
    """Rebuild paragraphs from PDF lines: blank line = break; join wrapped lines."""
    paras: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if not ln:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(ln)
        if ln.endswith((".", ":", ";", "?", "!")) and len(ln) < 60:
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return "\n\n".join(paras)


# --------------------------------------------------------------------- PPTX
def _shape_texts(shape, out: list[str], flags: dict) -> None:
    """Collect text of a shape (recursing into groups); record content we cannot read."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for sub in shape.shapes:
            _shape_texts(sub, out, flags)
        return
    if getattr(shape, "has_table", False) and shape.has_table:
        rows = []
        for row in shape.table.rows:
            cells = [normalize_text(c.text).replace("\n", " ") for c in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            out.append("\n".join(rows))
        return
    if getattr(shape, "has_chart", False) and shape.has_chart:
        flags["chart"] = True
    elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        flags["picture"] = True
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = normalize_text(shape.text_frame.text)
        if text:
            out.append(text)


def extract_pptx(path: Path, include_notes: bool = True) -> Extracted:
    _check_ole_encrypted(path, "PPTX")
    from pptx import Presentation

    prs = Presentation(str(path))
    out = Extracted(prefix_heading=True)
    unread: list[str] = []
    for n, slide in enumerate(prs.slides, start=1):
        hidden = slide._element.get("show") == "0"
        title_shape = slide.shapes.title
        title = ""
        if title_shape is not None and title_shape.has_text_frame:
            title = normalize_text(title_shape.text_frame.text).replace("\n", " ")
        texts: list[str] = []
        flags: dict = {}
        for shape in slide.shapes:
            if shape is title_shape:
                continue
            _shape_texts(shape, texts, flags)
        for el in slide.shapes._spTree.iter():  # SmartArt appears as a graphicFrame with a diagram uri
            if el.tag.endswith("}graphicData") and "diagram" in (el.get("uri") or ""):
                flags["smartart"] = True
        if title and not texts:
            texts = [title]
        for t in texts:
            out.segments.append(Segment(t, n, title or None, hidden=hidden))
        if include_notes and slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            nt = normalize_text(slide.notes_slide.notes_text_frame.text)
            if nt:
                out.segments.append(Segment(nt, n, title or None, source="notes", hidden=hidden))
        if flags.get("chart") or flags.get("smartart") or (flags.get("picture") and not texts):
            unread.append(str(n))
    out.page_count = len(prs.slides)
    if unread:
        out.status = "partial_content"
        out.warning = ("Slide " + ", ".join(unread[:15]) + ("…" if len(unread) > 15 else "")
                       + " có SmartArt, biểu đồ hoặc ảnh mà chữ bên trong không đọc được.")
    return out
