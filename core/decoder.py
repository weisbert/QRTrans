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


def detect_and_decode_qrs(img_array: np.ndarray) -> list[dict]:
    results = []

    # Try pyzbar first
    try:
        from pyzbar import pyzbar
        from PIL import Image as PILImage
        pil_img = PILImage.fromarray(img_array)
        decoded = pyzbar.decode(pil_img)
        if decoded:
            for obj in decoded:
                x, y = obj.rect.left, obj.rect.top
                results.append({"raw_bytes": _b64_decode_qr(obj.data), "x": x, "y": y})
            results.sort(key=lambda r: (r["y"] // 50, r["x"]))
            return results
    except Exception:
        pass

    # Fallback: OpenCV QR detector
    import cv2
    detector = cv2.QRCodeDetector()
    retval, decoded_list, points_list, _ = detector.detectAndDecodeMulti(img_array)
    if retval and decoded_list:
        for text, pts in zip(decoded_list, points_list):
            if text:
                x = int(pts[:, 0].min())
                y = int(pts[:, 1].min())
                results.append({"raw_bytes": _b64_decode_qr(text.encode("ascii")), "x": x, "y": y})
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
