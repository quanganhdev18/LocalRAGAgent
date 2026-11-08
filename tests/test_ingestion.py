import pytest

from conftest import make_docx, make_pdf
from localrag.chunker import chunk_segments
from localrag.extract import ExtractionError, Segment, extract
from localrag.textutil import count_tokens, fold, fts_query


def test_fold_vietnamese():
    assert fold("Thanh toán Đồng") == "thanh toan dong"
    assert fts_query("thời hạn") == '"thoi" OR "han" OR "thoi han"'
    assert '"hd 2024 0173"' in fts_query("số HD-2024-0173")


def test_docx_headings_tables(tmp_path):
    p = tmp_path / "a b.docx"
    make_docx(p, [("h1", "Tiêu đề"), ("p", "Nội dung đoạn một.")], table=[["A", "B"], ["1", "2"]])
    ex = extract(p)
    assert ex.segments[0].is_heading and ex.segments[0].text == "Tiêu đề"
    assert ex.segments[1].heading == "Tiêu đề"
    assert any("A | B" in s.text and "1 | 2" in s.text for s in ex.segments)  # table content kept


def test_pdf_pages(tmp_path):
    p = tmp_path / "x.pdf"
    make_pdf(p, [["Page one has enough text to count as real content here."],
                 ["Second page also carries real extractable text for the test."]])
    ex = extract(p)
    assert {s.page for s in ex.segments} == {1, 2}


def test_pdf_scan_pages_flagged_for_ocr(tmp_path):
    p = tmp_path / "scan.pdf"
    make_pdf(p, [[""], [""]])
    ex = extract(p)
    assert ex.ocr_pages == [1, 2] and not ex.segments


def test_pdf_repeated_header_footer_removed(tmp_path):
    p = tmp_path / "h.pdf"
    bodies = ["Alpha paragraph discusses budgets and forecasts in detail for the board.",
              "Beta paragraph covers hiring plans and the training programme this year.",
              "Gamma paragraph explains the security audit findings and remediation steps.",
              "Delta paragraph lists the supplier contracts that are up for renewal soon."]
    pages = [["CONFIDENTIAL HEADER", bodies[i], f"Page {i + 1}"] for i in range(4)]
    make_pdf(p, pages)
    text = " ".join(s.text for s in extract(p).segments)
    assert "CONFIDENTIAL HEADER" not in text
    assert "Gamma paragraph" in text


def test_corrupt_file_friendly_error(tmp_path):
    p = tmp_path / "bad.docx"
    p.write_bytes(b"not a zip")
    with pytest.raises(ExtractionError) as e:
        extract(p)
    assert "DOCX" in str(e.value)


def test_chunk_sizes_overlap_and_headings():
    para = " ".join(f"từ{i}" for i in range(200)) + "."
    segs = [Segment("Điều 1", None, "Điều 1", True)] + [Segment(para, None, "Điều 1") for _ in range(6)]
    chunks = chunk_segments(segs, target=350, overlap=60)
    assert len(chunks) >= 3
    assert chunks[0].text.startswith("Điều 1")  # heading glued to its paragraph
    assert all(c.section_heading == "Điều 1" for c in chunks)
    for c in chunks[:-1]:
        assert 250 <= count_tokens(c.text) <= 520
    # overlap: the second chunk starts with words from the end of the first
    tail = chunks[0].text.split()[-10:]
    assert " ".join(tail[-5:]) in chunks[1].text


def test_chunk_never_spans_pages():
    segs = [Segment("a " * 100, 1), Segment("b " * 100, 2)]
    chunks = chunk_segments(segs, target=350, overlap=60)
    assert [c.page_number for c in chunks] == [1, 2]
    assert "b" not in chunks[0].text and "a" not in chunks[1].text


def test_long_paragraph_split():
    segs = [Segment("Câu một có nhiều từ. " * 300, None)]
    chunks = chunk_segments(segs, target=350, overlap=60)
    assert len(chunks) > 2
    assert max(count_tokens(c.text) for c in chunks) < 600
