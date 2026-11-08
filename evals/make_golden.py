"""Generate the synthetic golden corpus from evals/golden_spec/corpus.yaml (reproducible, seeded).

Output goes to evals/_generated/ (git-ignored): one file per doc id plus expected.json.
Scan PDFs are rendered from the known text, then blurred / skewed / noised, so the exact
ground truth is available for CER. Usage: python evals/make_golden.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import textwrap
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SPEC = HERE / "golden_spec" / "corpus.yaml"
FONT_CANDIDATES = [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def load_spec() -> dict:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ writers
def write_docx(path: Path, d: dict) -> None:
    import docx
    doc = docx.Document()
    doc.add_heading(d["title"], level=1)
    doc.add_paragraph(d["text"])
    doc.save(str(path))


def _pdf_bytes(pages: list[list[str]]) -> bytes:
    """Minimal ASCII text PDF writer (Helvetica) - English documents only."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    font_id = 3 + 2 * n
    for i, lines in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode())
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 740 Td"]
        for ln in lines:
            ops.append("(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1", "replace")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


def write_pdf(path: Path, d: dict) -> None:
    lines = [d["title"], ""] + textwrap.wrap(d["text"], 90)
    path.write_bytes(_pdf_bytes([lines]))


def write_pptx(path: Path, d: dict) -> None:
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = d["title"]
    tb = s.shapes.add_textbox(Inches(1), Inches(2), Inches(7), Inches(1))
    tb.text_frame.text = d["text"]
    if d.get("table"):
        rows = d["table"]
        t = s.shapes.add_table(len(rows), len(rows[0]), Inches(1), Inches(3.5), Inches(6), Inches(1)).table
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                t.cell(r, c).text = v
    if d.get("group"):
        g = s.shapes.add_group_shape().shapes.add_textbox(Inches(1), Inches(5.5), Inches(5), Inches(1))
        g.text_frame.text = d["group"]
    if d.get("notes"):
        s.notes_slide.notes_text_frame.text = d["notes"]
    if d.get("hidden"):
        s._element.set("show", "0")
    prs.save(str(path))


def _font(size: int):
    from PIL import ImageFont
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    sys.exit("Không tìm thấy font hỗ trợ tiếng Việt (arial.ttf / DejaVuSans.ttf) để sinh bản scan.")


def render_scan_image(title: str, text: str, quality: str, seed: int):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    rng = random.Random(seed)
    img = Image.new("L", (1654, 2339), 255)  # A4 @ 200 dpi
    draw = ImageDraw.Draw(img)
    draw.text((120, 150), title, font=_font(44), fill=0)
    y = 260
    font = _font(34)
    for line in textwrap.wrap(text, 62):
        draw.text((120, y), line, font=font, fill=0)
        y += 52
    if quality == "skewed":
        img = img.rotate(rng.choice([-2.5, 2.5]), resample=Image.BICUBIC, fillcolor=255)
    if quality == "blurry":
        img = img.filter(ImageFilter.GaussianBlur(1.4))
    arr = np.asarray(img, dtype=np.float32)
    noise = np.random.default_rng(seed).normal(0, 6 if quality == "clean" else 18, arr.shape)
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype("uint8")).convert("RGB")


def write_scan(path: Path, d: dict, seed: int) -> None:
    render_scan_image(d["title"], d["text"], d.get("quality", "clean"), seed).save(path, resolution=200)


def write_mixed(path: Path, d: dict, seed: int, tmp: Path) -> None:
    import pypdfium2 as pdfium
    body, appendix = d["text"].split(". ", 1)
    txt = tmp / f"{d['id']}_t.pdf"
    scn = tmp / f"{d['id']}_s.pdf"
    txt.write_bytes(_pdf_bytes([[d["title"], ""] + textwrap.wrap(body + ".", 90)]))
    render_scan_image("Appendix", appendix, "clean", seed).save(scn, resolution=200)
    merged = pdfium.PdfDocument(str(txt))
    merged.import_pages(pdfium.PdfDocument(str(scn)))
    merged.save(str(path))
    merged.close()


def generate(out: Path) -> dict:
    spec = load_spec()
    out.mkdir(parents=True, exist_ok=True)
    expected = {"docs": [], "queries": []}
    for i, d in enumerate(spec["docs"]):
        fmt = d["fmt"]
        ext = {"docx": "docx", "pdf": "pdf", "pptx": "pptx", "scan": "pdf", "mixed": "pdf", "encrypted": "docx"}[fmt]
        path = out / f"{d['id']}.{ext}"
        if fmt == "docx":
            write_docx(path, d)
        elif fmt == "pdf":
            write_pdf(path, d)
        elif fmt == "pptx":
            write_pptx(path, d)
        elif fmt == "scan":
            write_scan(path, d, seed=1000 + i)
        elif fmt == "mixed":
            write_mixed(path, d, 1000 + i, out)
            for t in out.glob(f"{d['id']}_*.pdf"):
                t.unlink()
        else:
            path.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 256)  # password-protected OOXML stub
        expected["docs"].append({"id": d["id"], "file": path.name, "fmt": fmt, "lang": d["lang"],
                                 "title": d["title"], "text": d["text"]})
        for q in d.get("q", []):
            group_doc = "ocr" if fmt in ("scan", "mixed") else ("pptx" if fmt == "pptx" else "text")
            expected["queries"].append({"doc": d["id"], "type": q["t"], "query": q["q"], "doc_group": group_doc})
    for q in spec.get("none_queries", []):
        expected["queries"].append({"doc": None, "type": "none", "query": q, "doc_group": "none"})
    (out / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1), encoding="utf-8")
    return expected


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "_generated"))
    a = ap.parse_args()
    e = generate(Path(a.out))
    print(f"Đã sinh {len(e['docs'])} file và {len(e['queries'])} truy vấn vào {a.out}")
