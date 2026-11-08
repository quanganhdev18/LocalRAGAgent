import pytest
from PIL import Image, ImageDraw

from conftest import make_docx, make_pdf
from localrag.extract import ExtractionError, extract


def make_pptx(path, slides, hidden=(), notes=None):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    for i, (title, body) in enumerate(slides, start=1):
        s = prs.slides.add_slide(prs.slide_layouts[5])
        s.shapes.title.text = title
        tb = s.shapes.add_textbox(Inches(1), Inches(2), Inches(5), Inches(1))
        tb.text_frame.text = body
        if notes and i in notes:
            s.notes_slide.notes_text_frame.text = notes[i]
        if i in hidden:
            s._element.set("show", "0")
    s = prs.slides[0]  # table + group shape on slide 1
    tbl = s.shapes.add_table(2, 2, Inches(1), Inches(4), Inches(4), Inches(1)).table
    tbl.cell(0, 0).text, tbl.cell(1, 1).text = "Cột A", "giá trị bảng độc nhất"
    grp = s.shapes.add_group_shape()
    g = grp.shapes.add_textbox(Inches(1), Inches(6), Inches(3), Inches(1))
    g.text_frame.text = "chữ trong nhóm hình"
    prs.save(str(path))


def make_scan_pdf(path, pages_text):
    imgs = []
    for t in pages_text:
        im = Image.new("RGB", (800, 1000), "white")
        ImageDraw.Draw(im).text((50, 50), t, fill="black")
        imgs.append(im)
    imgs[0].save(path, save_all=True, append_images=imgs[1:])


class FakeEngine:
    def __init__(self, conf=90.0):
        self.conf, self.calls = conf, 0

    def recognize(self, png):
        assert png.exists()
        self.calls += 1
        return f"văn bản nhận dạng số {self.calls} về bảo hành thiết bị", self.conf


def index(core):
    core.indexer.start()
    core.indexer.wait()


def status(core, name):
    return core.db.conn().execute("SELECT * FROM documents WHERE file_name=?", (name,)).fetchone()


def test_pptx_extract(tmp_path):
    p = tmp_path / "bài giảng.pptx"
    make_pptx(p, [("Chương 1", "nội dung slide một"), ("Chương 2", "nội dung hai")], hidden={2},
              notes={1: "ghi chú người nói riêng"})
    ex = extract(p)
    allt = " ".join(s.text for s in ex.segments)
    assert "giá trị bảng độc nhất" in allt and "chữ trong nhóm hình" in allt
    assert any(s.source == "notes" and s.page == 1 for s in ex.segments)
    assert any(s.hidden and s.page == 2 for s in ex.segments)
    assert all(s.heading for s in ex.segments)


def test_pptx_search_slide_label_and_notes(core, tmp_path):
    d = tmp_path / "ppt"
    d.mkdir()
    make_pptx(d / "a.pptx", [("Tiêu đề A", "thuật toán sắp xếp nổi bọt")], notes={1: "bí mật ghi chú"})
    core.db.add_folder(str(d))
    index(core)
    h = core.search.search("thuật toán nổi bọt", mode="bm25")[0]
    assert h.location_label == "Slide 1" and h.citation() == "a.pptx, slide 1"
    assert h.text.startswith("Tiêu đề A")  # slide title prefixed for context
    n = core.search.search("bí mật ghi chú", mode="bm25")[0]
    assert n.source == "notes"


def test_pptx_encrypted_and_corrupt(tmp_path):
    p = tmp_path / "x.pptx"
    p.write_bytes(b"\xd0\xcf\x11\xe0" + b"0" * 100)
    with pytest.raises(ExtractionError) as e:
        extract(p)
    assert e.value.status == "encrypted"
    p.write_bytes(b"junk")
    with pytest.raises(ExtractionError) as e:
        extract(p)
    assert e.value.status == "corrupt"


def test_mixed_pdf_flags_only_scan_pages(tmp_path):
    p = tmp_path / "m.pdf"
    make_pdf(p, [["This page has plenty of real text content for extraction purposes."], [""],
                 ["Another text page that is long enough to count as real text."]])
    ex = extract(p)
    assert ex.ocr_pages == [2] and {s.page for s in ex.segments} == {1, 3}


def test_ocr_flow_consent_and_search(core, tmp_path):
    d = tmp_path / "scans"
    d.mkdir()
    make_scan_pdf(d / "scan.pdf", ["trang mot", "trang hai", "trang ba"])
    core.db.add_folder(str(d))
    core.ocr.engine = FakeEngine()
    index(core)
    assert status(core, "scan.pdf")["status"] == "needs_ocr"
    est = core.ocr.estimate()
    assert est["pages"] == 3 and est["awaiting_consent"] == 1
    assert core.ocr.engine.calls == 0  # nothing runs without consent
    assert core.ocr.approve() == 1
    assert core.ocr.start()
    core.ocr.wait()
    assert core.ocr.engine.calls == 3
    assert status(core, "scan.pdf")["status"] == "indexed"
    h = core.search.search("nhận dạng bảo hành thiết bị", mode="bm25")
    assert h and h[0].source == "ocr" and h[0].page_number in (1, 2, 3)
    index(core)  # rescan: nothing re-OCR'd
    assert core.ocr.engine.calls == 3


def test_ocr_cancel_keeps_finished_pages(core, tmp_path):
    d = tmp_path / "scans"
    d.mkdir()
    make_scan_pdf(d / "s.pdf", ["a", "b", "c"])
    core.db.add_folder(str(d))
    eng = FakeEngine()
    orig = eng.recognize

    def cancel_after_first(png):
        r = orig(png)
        core.ocr.cancel()
        return r
    eng.recognize = cancel_after_first
    core.ocr.engine = eng
    index(core)
    core.ocr.approve()
    core.ocr.start()
    core.ocr.wait()
    assert core.db.conn().execute("SELECT COUNT(*) FROM ocr_pages").fetchone()[0] == 1
    assert status(core, "s.pdf")["status"] == "needs_ocr"
    eng.recognize = orig  # resume: only the remaining pages are processed
    core.ocr.approve()
    core.ocr.start()
    core.ocr.wait()
    assert eng.calls == 3 and status(core, "s.pdf")["status"] == "indexed"


def test_ocr_low_quality_label(core, tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    make_scan_pdf(d / "s.pdf", ["x"])
    core.db.add_folder(str(d))
    core.ocr.engine = FakeEngine(conf=30.0)
    index(core)
    core.ocr.approve()
    core.ocr.start()
    core.ocr.wait()
    assert status(core, "s.pdf")["status"] == "ocr_low_quality"
    assert core.search.search("bảo hành thiết bị", mode="bm25")


def test_ocr_always_policy_auto_runs(core, tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    make_scan_pdf(d / "s.pdf", ["x"])
    core.db.add_folder(str(d), "always")
    core.ocr.engine = FakeEngine()
    index(core)
    core.ocr.wait()
    assert status(core, "s.pdf")["status"] == "indexed"


def test_ocr_unavailable_gives_fix_hint(core, tmp_path, monkeypatch):
    d = tmp_path / "s"
    d.mkdir()
    make_scan_pdf(d / "s.pdf", ["x"])
    core.db.add_folder(str(d))
    monkeypatch.setattr("localrag.ocr.find_tesseract", lambda cfg: None)
    index(core)
    core.ocr.approve()
    assert core.ocr.start() is False
    assert "Tesseract" in core.ocr.progress.message


def test_reconcile_missing_rename_and_grace(core, corpus):
    core.db.add_folder(str(corpus))
    index(core)
    src = corpus / "nghi quyet nhan su.docx"
    before = status(core, src.name)
    src.rename(corpus / "đổi tên.docx")
    index(core)
    after = status(core, "đổi tên.docx")
    assert after and after["id"] == before["id"] and after["status"] == "indexed"  # index kept
    assert core.search.search("nghỉ phép năm", mode="bm25")
    (corpus / "đổi tên.docx").unlink()
    index(core)
    assert status(core, "đổi tên.docx")["status"] == "missing"
    assert not core.search.search("nghỉ phép năm", mode="bm25")  # hidden from search at once
    core.cfg.data["index"]["reconcile_grace_hours"] = 0
    index(core)
    assert status(core, "đổi tên.docx") is None


def test_unreachable_root_keeps_data(core, corpus, tmp_path):
    core.db.add_folder(str(corpus))
    index(core)
    n = core.db.index_status()["documents"]
    corpus.rename(tmp_path / "unplugged")
    core.cfg.data["index"]["reconcile_grace_hours"] = 0
    index(core)
    assert core.db.index_status()["documents"] == n
    assert not core.db.conn().execute("SELECT 1 FROM documents WHERE status='missing'").fetchone()


def test_encrypted_and_corrupt_do_not_stop_index(core, corpus):
    (corpus / "pw.docx").write_bytes(b"\xd0\xcf\x11\xe0" + b"0" * 64)
    (corpus / "hỏng.pptx").write_bytes(b"garbage")
    core.db.add_folder(str(corpus))
    index(core)
    assert status(core, "pw.docx")["status"] == "encrypted"
    assert status(core, "hỏng.pptx")["status"] == "corrupt"
    assert core.db.index_status()["by_status"]["indexed"] >= 3


def test_per_document_cap(core, tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    make_docx(d / "a.docx", [("p", f"báo cáo khoa học số {i} " * 60) for i in range(8)])
    core.db.add_folder(str(d))
    index(core)
    hits = core.search.search("báo cáo khoa học", mode="bm25", limit=10)
    assert 0 < len(hits) <= 3 and len({h.document_id for h in hits}) == 1


def test_feedback_stored_locally_and_telemetry_off(core):
    assert core.telemetry_enabled is False
    r = core.submit_feedback("Tôi muốn tìm theo tác giả", "a@b.vn", True)
    assert r["stored_locally"] and r["sent"] is False
    assert core.db.conn().execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 1
    with pytest.raises(ValueError):
        core.submit_feedback("  ")


def test_api_requires_session_token(core):
    from fastapi.testclient import TestClient
    from localrag.web.app import create_local_app
    app = create_local_app(core)
    c = TestClient(app, base_url="http://127.0.0.1")
    assert c.get("/local/api/status").status_code == 403
    tok = app.state.session_token
    assert c.get("/local/api/status", headers={"X-Session-Token": tok}).status_code == 200
    assert TestClient(app, base_url="http://evil.com").get("/").status_code == 403
    assert tok in c.get("/").text


def test_usage_counters_only_when_opted_in(core):
    core.record_usage("search", 0.1)
    assert core.db.get_setting("usage_counters") is None  # off by default: nothing recorded
    core.set_telemetry(True)
    core.record_usage("search", 0.2)
    import json
    assert json.loads(core.db.get_setting("usage_counters"))["search"] == 1


def test_setup_endpoints_and_job_runner(core):
    import time
    from fastapi.testclient import TestClient
    from localrag.web.app import create_local_app
    app = create_local_app(core)
    c = TestClient(app, base_url="http://127.0.0.1")
    h = {"X-Session-Token": app.state.session_token}
    s = c.get("/local/api/setup", headers=h).json()
    assert {"models", "ocr", "job"} <= set(s) and "languages" in s["ocr"]
    # job runner reports errors instead of swallowing them, and runs one job at a time
    def boom(progress):
        progress("working")
        raise RuntimeError("no network")
    assert core.jobs.start("test", boom)
    for _ in range(50):
        if not core.jobs.state.running:
            break
        time.sleep(0.05)
    assert "no network" in core.jobs.state.error


def test_real_tesseract_if_installed(core, tmp_path):
    from localrag.ocr import TesseractEngine, find_tesseract, render_page
    from localrag.setup_assets import ocr_status
    if not ocr_status(core.cfg)["ready"]:
        pytest.skip("Tesseract + vie/eng chưa được thiết lập")
    pdf = tmp_path / "s.pdf"
    make_scan_pdf(pdf, ["Hello world scanned page"])
    png = tmp_path / "p.png"
    render_page(pdf, 1, 250, png)
    text, conf = TesseractEngine(core.cfg).recognize(png)
    assert isinstance(text, str) and conf is not None
