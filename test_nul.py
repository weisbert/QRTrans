"""NUL bytes in the input must not truncate the text.

Tk's Text widget drops everything from the first NUL on, so a log with a
zero-filled hole used to lose its whole tail on both the load-file and paste
paths, and again on the decode side's copy/save.
"""
import os
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, os.path.dirname(__file__))

from core.utils import mark_nuls
from core.encoder import encode_text
from core.decoder import reassemble
from app import encode_tab as enc_mod
from app import decode_tab as dec_mod

SAMPLE = "head line\ncomplex refactor fail.\n" + "\x00" * 4096 + "tail\x00line\nSimulation completes.\n"


def check(label, ok):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    return ok


def main():
    results = []

    marked, nuls, runs = mark_nuls(SAMPLE)
    results.append(check("mark_nuls counts", (nuls, runs) == (4097, 2)))
    results.append(check("mark_nuls keeps tail", marked.endswith("tail␀line\nSimulation completes.\n")
                         and "[␀×4096]" in marked))

    root = tk.Tk()
    root.withdraw()

    # Encode: load file path keeps the original, NULs included.
    fd, path = tempfile.mkstemp(suffix=".log")
    with os.fdopen(fd, "wb") as f:
        f.write(SAMPLE.encode("utf-8"))
    enc_mod.filedialog.askopenfilename = lambda **kw: path
    tab = enc_mod.EncodeTab(root)
    tab._load_file()
    results.append(check("encode load-file source is verbatim", tab._source_text() == SAMPLE))

    # Encode: paste path keeps everything after the NUL (as markers).
    tab._clear()
    tab.clipboard_get = lambda: SAMPLE  # Tk's own clipboard can't carry NUL either
    tab._on_paste()
    results.append(check("encode paste keeps tail", tab._source_text() == marked.rstrip("\n")))

    # Decode: output/copy/save don't lose the tail.
    packets = encode_text(SAMPLE)
    text = reassemble([{"raw_bytes": p} for p in packets])
    dtab = dec_mod.DecodeTab(root)
    dtab._decode_start_time = 0.0
    dtab._on_decode_success(text, len(packets))
    shown = dtab._output.get("1.0", "end-1c")
    results.append(check("decode display keeps tail", shown == marked))
    copied = {}
    dtab.clipboard_clear = lambda: None
    dtab.clipboard_append = lambda t: copied.setdefault("t", t)
    dtab._copy_all()
    results.append(check("decode copy keeps tail", copied.get("t") == marked))
    fd, out = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    dec_mod.filedialog.asksaveasfilename = lambda **kw: out
    dtab._save_file()
    with open(out, encoding="utf-8") as f:
        results.append(check("decode save is verbatim", f.read() == SAMPLE))

    root.destroy()
    os.remove(path)
    os.remove(out)
    print(f"\n{sum(results)}/{len(results)} passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
