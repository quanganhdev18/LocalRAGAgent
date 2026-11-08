# PyInstaller onedir. CHƯA được build/kiểm thử. Model và runtime/tesseract không đóng vào Git; bản phát hành copy kèm.
# pyinstaller packaging/pyinstaller.spec
a = Analysis(['../localrag/__main__.py'], datas=[('../localrag/web/static', 'localrag/web/static'), ('../config.yaml', '.'),
             ('../models/MANIFEST.json', 'models')], hiddenimports=['uvicorn.logging', 'uvicorn.protocols.http.h11_impl'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LocalRAG', console=True)
coll = COLLECT(exe, a.binaries, a.datas, name='LocalRAG')
