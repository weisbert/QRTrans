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


def _pyzbar_decode(arr: np.ndarray) -> list[tuple[bytes, int, int]]:
    try:
        from pyzbar import pyzbar
        pil_img = Image.fromarray(arr)
        return [(bytes(o.data), o.rect.left, o.rect.top) for o in pyzbar.decode(pil_img)]
    except Exception:
        return []


def _opencv_decode(arr: np.ndarray) -> list[tuple[bytes, int, int]]:
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

    Real-world screenshots (display-scaled, compressed, partially clipped) often
    defeat a single detector. Run pyzbar and OpenCV on the original, and on a
    NEAREST 2x upscale if we still look short. A code only needs to survive
    one pass to make it through. Dedup by QR content so overlaps don't matter.
    """
    seen: dict[bytes, tuple[int, int]] = {}

    def add(items):
        for data, x, y in items:
            if data and data not in seen:
                seen[data] = (x, y)

    add(_pyzbar_decode(img_array))
    add(_opencv_decode(img_array))

    expected = _expected_total(seen)
    if expected is None or len(seen) < expected:
        try:
            import cv2
            h, w = img_array.shape[:2]
            up = cv2.resize(img_array, (w * 2, h * 2), interpolation=cv2.INTER_NEAREST)
            add(_pyzbar_decode(up))
            if _expected_total(seen) is None or len(seen) < (_expected_total(seen) or 0):
                add(_opencv_decode(up))
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
