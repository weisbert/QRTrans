import base64
import numpy as np
from PIL import Image

from core.utils import gzip_decompress, crc32
from core.protocol import unpack_chunk, MissingPacketError, CRCError, ProtocolError


def _b64_decode_qr(data: bytes) -> bytes:
    """Decode base64-encoded QR content back to binary packet."""
    return base64.b64decode(data)


def preprocess_image(img: Image.Image, enhance: bool = False) -> np.ndarray:
    gray = img.convert("L")
    arr = np.array(gray)
    if not enhance:
        return arr
    import cv2
    arr = cv2.adaptiveThreshold(
        arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    return arr


# Module-level probe: remember whether pyzbar is actually usable. On Windows
# the Python package imports fine but libzbar.dll may fail to load, which only
# surfaces when decode() is first called. Cache the outcome so we can surface
# a clear diagnostic in the UI instead of silently returning "no QR detected".
_pyzbar_ok: bool | None = None
_pyzbar_error: str | None = None


def pyzbar_status() -> tuple[bool, str | None]:
    """Return (usable, error_message). Lazily probes on first call."""
    global _pyzbar_ok, _pyzbar_error
    if _pyzbar_ok is not None:
        return _pyzbar_ok, _pyzbar_error
    try:
        from pyzbar import pyzbar  # noqa: F401
        # Call decode on a tiny image to force libzbar DLL load
        pyzbar.decode(Image.new("L", (8, 8), 255))
        _pyzbar_ok = True
    except Exception as e:
        _pyzbar_ok = False
        _pyzbar_error = f"{type(e).__name__}: {e}"
    return _pyzbar_ok, _pyzbar_error


def _pyzbar_decode(arr: np.ndarray) -> list[tuple[bytes, int, int]]:
    ok, _ = pyzbar_status()
    if not ok:
        return []
    try:
        from pyzbar import pyzbar
        pil_img = Image.fromarray(arr)
        return [(bytes(o.data), o.rect.left, o.rect.top) for o in pyzbar.decode(pil_img)]
    except Exception:
        return []


def _opencv_multi_decode(arr: np.ndarray) -> list[tuple[bytes, int, int]]:
    try:
        import cv2
        detector = cv2.QRCodeDetector()
        retval, decoded_list, points_list, _ = detector.detectAndDecodeMulti(arr)
        if not retval or not decoded_list:
            return []
        out = []
        for text, pts in zip(decoded_list, points_list):
            if text:
                x = int(pts[:, 0].min())
                y = int(pts[:, 1].min())
                out.append((text.encode("ascii"), x, y))
        return out
    except Exception:
        return []


def _opencv_detect_then_crop_decode(arr: np.ndarray) -> list[tuple[bytes, int, int]]:
    """OpenCV's `detectMulti` locates more QRs than `detectAndDecodeMulti`
    actually manages to decode. For each located region, crop and retry with
    the single-code decoder, which is often strong enough to read v40 codes
    that the multi decoder gives up on.
    """
    try:
        import cv2
        detector = cv2.QRCodeDetector()
        ok, pts_multi = detector.detectMulti(arr)
        if not ok or pts_multi is None:
            return []
        out = []
        h, w = arr.shape[:2]
        for p in pts_multi:
            xs, ys = p[:, 0], p[:, 1]
            x0 = max(0, int(xs.min()) - 10)
            x1 = min(w, int(xs.max()) + 10)
            y0 = max(0, int(ys.min()) - 10)
            y1 = min(h, int(ys.max()) + 10)
            if x1 <= x0 or y1 <= y0:
                continue
            crop = arr[y0:y1, x0:x1]
            text, _, _ = detector.detectAndDecode(crop)
            if text:
                out.append((text.encode("ascii"), x0, y0))
        return out
    except Exception:
        return []


def _expected_total(seen: dict) -> int | None:
    """Peek at any successfully-parsed packet to learn the expected total."""
    for data in seen:
        try:
            return unpack_chunk(_b64_decode_qr(data))["total"]
        except Exception:
            continue
    return None


def detect_and_decode_qrs(img_array: np.ndarray) -> list[dict]:
    """Detect QR codes via multiple passes and merge by content.

    Chains: pyzbar → OpenCV multi → OpenCV detect+crop+single on the original
    image, then the same cascade on a NEAREST 2x upscale if we still look
    short of the packet count advertised by a parsed chunk. Each detector
    only needs to recognise a given code in one pass for us to keep it.
    """
    seen: dict[bytes, tuple[int, int]] = {}

    def add(items):
        for data, x, y in items:
            if data and data not in seen:
                seen[data] = (x, y)

    def need_more() -> bool:
        total = _expected_total(seen)
        return total is None or len(seen) < total

    add(_pyzbar_decode(img_array))
    if need_more():
        add(_opencv_multi_decode(img_array))
    if need_more():
        add(_opencv_detect_then_crop_decode(img_array))

    if need_more():
        try:
            import cv2
            h, w = img_array.shape[:2]
            up = cv2.resize(img_array, (w * 2, h * 2), interpolation=cv2.INTER_NEAREST)
            add(_pyzbar_decode(up))
            if need_more():
                add(_opencv_multi_decode(up))
            if need_more():
                add(_opencv_detect_then_crop_decode(up))
        except Exception:
            pass

    results = [{"raw_bytes": _b64_decode_qr(data), "x": x, "y": y}
               for data, (x, y) in seen.items()]
    results.sort(key=lambda r: (r["y"] // 50, r["x"]))
    return results


def reassemble(packets: list[dict]) -> str:
    if not packets:
        raise MissingPacketError([0])

    parsed = []
    for pkt in packets:
        parsed.append(unpack_chunk(pkt["raw_bytes"]))

    parsed.sort(key=lambda p: p["index"])
    total = parsed[0]["total"]

    # Check for missing packets
    present = {p["index"] for p in parsed}
    expected = set(range(total))
    missing = sorted(expected - present)
    if missing:
        raise MissingPacketError(missing)

    data_crc_expected = parsed[0]["data_crc32"]
    compressed = b"".join(p["payload"] for p in parsed)

    actual_crc = crc32(compressed)
    if actual_crc != data_crc_expected:
        raise CRCError(
            f"Data CRC32 mismatch (expected {data_crc_expected:#010x}, got {actual_crc:#010x})"
        )

    raw = gzip_decompress(compressed)
    return raw.decode("utf-8")
