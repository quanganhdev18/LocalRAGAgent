import json
import time

import pytest

from conftest import make_docx
from localrag.models import ModelError, load_manifest, save_manifest, verify_models
from localrag.search import Filters


@pytest.fixture()
def indexed(core, corpus):
    core.db.add_folder(str(corpus))
    core.indexer.start()
    core.indexer.wait()
    return core


def test_indexing_status_and_scan_not_indexed(indexed):
    rows = {r["file_name"]: r for r in indexed.db.conn().execute("SELECT * FROM documents")}
    assert rows["hợp đồng mua bán.docx"]["status"] == "indexed"
    assert rows["report.pdf"]["status"] == "indexed"
    assert rows["scan.pdf"]["status"] == "needs_ocr"  # scanned PDF must not count as success
    assert rows["scan.pdf"]["ocr_todo"] == "[1, 2]"
    st = indexed.db.index_status()
    assert st["chunks"] == st["embedded"] > 0


def test_exact_code_found_by_bm25(indexed):
    hits = indexed.search.search("HD-2024-0173")
    assert hits and hits[0].file_name == "hợp đồng mua bán.docx"
    hits = indexed.search.search("ZX-9981-ALPHA")
    assert hits[0].file_name == "report.pdf" and hits[0].page_number == 1


def test_semantic_paraphrase_vietnamese(indexed):
    # no literal overlap with "nghỉ phép năm 12 ngày"
    hits = indexed.search.search("mỗi năm người lao động được nghỉ bao nhiêu ngày có lương", mode="semantic")
    assert hits[0].file_name == "nghi quyet nhan su.docx"
    hits = indexed.search.search("quy định về thời hạn thanh toán")
    assert hits[0].file_name == "hợp đồng mua bán.docx"
    assert hits[0].section_heading and "Thanh toán" in hits[0].section_heading


def test_accent_insensitive_keyword(indexed):
    hits = indexed.search.search("thoi han thanh toan", mode="bm25")
    assert hits and hits[0].file_name == "hợp đồng mua bán.docx"


def test_table_content_searchable(indexed):
    hits = indexed.search.search("250.000.000 đồng máy chủ", mode="bm25")
    assert hits and "Máy chủ" in hits[0].text


def test_filters(indexed):
    only_pdf = indexed.search.search("quarter", Filters(extensions=["pdf"]))
    assert only_pdf and all(h.extension == ".pdf" for h in only_pdf)
    assert indexed.search.search("quarter", Filters(extensions=["docx"]), mode="bm25") == []
    future = time.time() + 86400
    assert indexed.search.search("thanh toán", Filters(modified_after=future), mode="bm25") == []
    fid = indexed.db.list_folders()[0]["id"]
    assert indexed.search.search("thanh toán", Filters(folder_ids=[fid + 99]), mode="bm25") == []


def test_unchanged_files_not_reindexed_and_changes_detected(indexed, corpus):
    before = {r["file_name"]: r["updated_at"] for r in indexed.db.conn().execute("SELECT * FROM documents")}
    indexed.indexer.start()
    indexed.indexer.wait()
    after = {r["file_name"]: r["updated_at"] for r in indexed.db.conn().execute("SELECT * FROM documents")}
    assert before == after
    assert indexed.indexer.progress.total == 0
    # modify one file -> only that one is reprocessed
    make_docx(corpus / "nghi quyet nhan su.docx", [("p", "Chính sách làm việc từ xa hai ngày mỗi tuần.")])
    indexed.indexer.start()
    indexed.indexer.wait()
    assert indexed.indexer.progress.total == 1
    hits = indexed.search.search("làm việc từ xa", mode="bm25")
    assert hits and hits[0].file_name == "nghi quyet nhan su.docx"
    stale = indexed.search.search("nghỉ ốm giấy xác nhận bệnh viện", mode="bm25")
    assert all("nghỉ ốm" not in h.text for h in stale)  # old chunks of the modified file are gone


def test_bad_file_does_not_stop_indexing(core, corpus):
    (corpus / "hỏng.docx").write_bytes(b"garbage")
    core.db.add_folder(str(corpus))
    core.indexer.start()
    core.indexer.wait()
    bad = core.db.conn().execute("SELECT * FROM documents WHERE file_name='hỏng.docx'").fetchone()
    assert bad["status"] == "corrupt" and bad["error_message"]
    assert core.db.index_status()["by_status"]["indexed"] >= 3


def test_rebuild_and_cancel(indexed):
    n = indexed.db.index_status()["chunks"]
    indexed.indexer.start(rebuild=True)
    indexed.indexer.wait()
    assert indexed.db.index_status()["chunks"] == n


# ------------------------------------------------------------------ models
def test_verify_models_ok_and_detects_problems(cfg, tmp_path, monkeypatch):
    res = verify_models(cfg, ["embedding-multilingual-e5-small"], full=True)
    assert res[0].ok, res[0].problem

    # sandbox the manifest + a fake model root so we never touch the real assets
    root = tmp_path / "models"
    (root / "embeddings" / "m").mkdir(parents=True)
    (root / "embeddings" / "m" / "model.onnx").write_bytes(b"abc")
    monkeypatch.setenv("MODEL_ROOT", str(root))
    from localrag.models import REGISTRY, hash_asset
    spec = REGISTRY["embedding-multilingual-e5-small"]
    digest, size, files = hash_asset(root / "embeddings" / "m")
    entry = {"id": spec.id, "revision": spec.revision, "path": "embeddings/m", "format": "onnx",
             "quantization": "int8", "sha256": digest, "size_bytes": size, "source": "x", "license": "MIT"}
    save_manifest(cfg, {"schema_version": 1, "models": [entry]})
    assert verify_models(cfg, [spec.id], full=True)[0].ok
    # wrong checksum
    (root / "embeddings" / "m" / "model.onnx").write_bytes(b"tampered")
    r = verify_models(cfg, [spec.id], full=True)[0]
    assert not r.ok and "checksum" in r.problem and "prepare-models" in r.fix
    # wrong revision
    entry["revision"] = "deadbeef"
    save_manifest(cfg, {"schema_version": 1, "models": [entry]})
    assert "revision" in verify_models(cfg, [spec.id], full=True)[0].problem
    # missing file
    (root / "embeddings" / "m" / "model.onnx").unlink()
    (root / "embeddings" / "m").rmdir()
    entry["revision"] = spec.revision
    save_manifest(cfg, {"schema_version": 1, "models": [entry]})
    assert "Thiếu" in verify_models(cfg, [spec.id], full=True)[0].problem
    # model missing from manifest entirely
    save_manifest(cfg, {"schema_version": 1, "models": []})
    assert "MANIFEST" in verify_models(cfg, [spec.id])[0].problem


def test_model_root_env_override(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_ROOT", str(tmp_path / "elsewhere"))
    assert cfg.model_root == (tmp_path / "elsewhere").resolve()
    assert cfg.model_path("embedding_path").is_relative_to((tmp_path / "elsewhere").resolve())


def test_indexing_without_model_reports_fix(core, corpus, monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_ROOT", str(tmp_path / "empty"))
    core.db.add_folder(str(corpus))
    core.indexer.start()
    core.indexer.wait()
    assert "prepare-models" in core.indexer.progress.message
    assert core.indexer.progress.running is False
