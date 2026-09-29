import gzip
import zlib
import struct


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly=0x1021, init=0xFFFF, no reflect"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def gzip_compress(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=9)


def gzip_decompress(data: bytes) -> bytes:
    return gzip.decompress(data)


def detect_encoding(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


NUL_MARK = "␀"  # ␀


def mark_nuls(text: str) -> tuple[str, int, int]:
    """Replace NUL runs with a visible marker. Returns (marked, nul_count, run_count).

    Tk's Text widget silently drops everything from the first NUL on, and
    Windows clipboard text is NUL-terminated, so a raw NUL in a log cuts the
    rest of it off with no error. Logs pick NULs up when two writers share one
    file (holes get zero-filled). A lone NUL becomes ␀, a run becomes [␀×N].
    """
    if "\x00" not in text:
        return text, 0, 0
    out, count, runs, i, n = [], 0, 0, 0, len(text)
    while i < n:
        j = text.find("\x00", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        k = j
        while k < n and text[k] == "\x00":
            k += 1
        run = k - j
        out.append(NUL_MARK if run == 1 else f"[{NUL_MARK}×{run}]")
        count += run
        runs += 1
        i = k
    return "".join(out), count, runs
