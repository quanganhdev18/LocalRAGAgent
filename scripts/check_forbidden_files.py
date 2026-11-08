"""Pre-commit / CI guard: refuse models, binaries, databases, real data, and oversized files."""
import subprocess
import sys

BAD_SUFFIX = (".onnx", ".gguf", ".exe", ".traineddata", ".sqlite", ".db", ".sqlite-wal", ".sqlite-shm", ".log")
BAD_PREFIX = ("data/", "indexes/", "runtime/", "dist/", "evals/_generated/", "_downloads/")
MAX_BYTES = 5 * 1024 * 1024


def main() -> int:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    bad = []
    import os
    for f in filter(None, out):
        if f.endswith(BAD_SUFFIX) or f.startswith(BAD_PREFIX) or (f.startswith("models/") and not f.startswith(("models/MANIFEST.json", "models/LICENSES/"))):
            bad.append(f"{f}: loại file/thư mục không được commit")
        elif os.path.isfile(f) and os.path.getsize(f) > MAX_BYTES:
            bad.append(f"{f}: lớn hơn {MAX_BYTES // 1024 // 1024} MB")
    if bad:
        print("\n".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
