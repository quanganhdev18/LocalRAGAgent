import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localrag.config import load_config  # noqa: E402
from localrag.core import Core  # noqa: E402


def make_pdf(path: Path, pages: list[list[str]]) -> None:
    """Minimal text PDF writer (Helvetica, ASCII) so tests need no extra libraries."""
    objs: list[bytes] = []
    n_pages = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    font_id = 3 + 2 * n_pages
    for i, lines in enumerate(pages):
        content_id = 4 + 2 * i
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode())
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 740 Td"]
        for ln in lines:
            ops.append("(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
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
    path.write_bytes(bytes(out))


def make_docx(path: Path, blocks: list[tuple[str, str]], table: list[list[str]] | None = None) -> None:
    import docx
    d = docx.Document()
    for kind, text in blocks:
        if kind.startswith("h"):
            d.add_heading(text, level=int(kind[1:]) or 1)
        else:
            d.add_paragraph(text)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, val in enumerate(row):
                t.cell(r, c).text = val
    d.save(str(path))


@pytest.fixture()
def cfg(tmp_path):
    c = load_config()
    c.data["paths"]["data_dir"] = str(tmp_path / "data")
    c.data["paths"]["index_dir"] = str(tmp_path / "indexes")
    return c


@pytest.fixture()
def core(cfg):
    return Core(cfg)


@pytest.fixture()
def corpus(tmp_path):
    """Corpus with a Unicode + space folder name, as required by the spec."""
    d = tmp_path / "Tài liệu mẫu"
    d.mkdir()
    make_docx(d / "hợp đồng mua bán.docx",
              [("h1", "Điều 5. Thanh toán"),
               ("p", "Bên mua phải hoàn tất nghĩa vụ thanh toán trong vòng 30 ngày kể từ ngày nhận hàng. "
                     "Số hợp đồng: HD-2024-0173. Nếu chậm thanh toán, bên mua chịu lãi suất 0,05% mỗi ngày."),
               ("h1", "Điều 6. Bảo hành"),
               ("p", "Thời gian bảo hành sản phẩm là 12 tháng kể từ ngày bàn giao.")],
              table=[["Hạng mục", "Số tiền"], ["Máy chủ", "250.000.000 đồng"]])
    make_docx(d / "nghi quyet nhan su.docx",
              [("h1", "Quy chế nghỉ phép"),
               ("p", "Nhân viên được nghỉ phép năm 12 ngày làm việc. Nghỉ ốm cần có giấy xác nhận của bệnh viện.")])
    make_pdf(d / "report.pdf", [
        ["Quarterly Report", "Revenue grew by 15 percent compared with the previous quarter.", "Contract code ZX-9981-ALPHA is pending review."],
        ["Risks", "Supply chain delays may impact delivery schedules in the next quarter."],
    ])
    make_pdf(d / "scan.pdf", [[""], [""]])  # no text -> must not count as indexed
    return d
