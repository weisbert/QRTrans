import base64
import math
from PIL import Image, ImageDraw, ImageFont
import qrcode
import qrcode.constants

from core.utils import gzip_compress, crc32
from core.protocol import pack_chunk

# QR v40 byte-mode capacities per EC level, minus 16-byte header, with base64 overhead (×3/4).
# Source: ISO 18004 Table 1.
_EC_CAPACITY = {
    "H": (1273 * 3 // 4) - 16,   # 938 B
    "Q": (1663 * 3 // 4) - 16,   # 1231 B
    "M": (2331 * 3 // 4) - 16,   # 1732 B
    "L": (2953 * 3 // 4) - 16,   # 2197 B
}
MAX_PAYLOAD = _EC_CAPACITY["H"]  # conservative default; use get_max_payload() for exact value


def get_max_payload(ec_level: str = "H") -> int:
    return _EC_CAPACITY.get(ec_level, _EC_CAPACITY["H"])


def encode_text(text: str, ec_level: str = "H") -> list[bytes]:
    max_payload = get_max_payload(ec_level)
    raw = text.encode("utf-8")
    compressed = gzip_compress(raw)
    data_crc = crc32(compressed)
    total = math.ceil(len(compressed) / max_payload)

    packets = []
    for i in range(total):
        chunk = compressed[i * max_payload:(i + 1) * max_payload]
        pkt = pack_chunk(i, total, data_crc, chunk, is_text=True)
        packets.append(pkt)
    return packets


_EC_MAP = {
    "H": qrcode.constants.ERROR_CORRECT_H,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "L": qrcode.constants.ERROR_CORRECT_L,
}


def make_qr_image(payload: bytes, module_size: int = 4, ec_level: str = "H") -> Image.Image:
    # Base64-encode to keep QR content in printable ASCII, avoiding qrcode library's
    # Latin-1→UTF-8 expansion of high bytes which corrupts binary data.
    b64 = base64.b64encode(payload).decode("ascii")
    qr = qrcode.QRCode(
        version=40,
        error_correction=_EC_MAP.get(ec_level, qrcode.constants.ERROR_CORRECT_H),
        box_size=module_size,
        border=2,
    )
    qr.add_data(b64)
    qr.make(fit=False)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def make_grid_image(
    qr_images: list[Image.Image],
    cols: int,
    rows: int,
    padding: int = 20,
    label: bool = True,
) -> Image.Image:
    if not qr_images:
        raise ValueError("No QR images provided")

    qw, qh = qr_images[0].size
    label_height = 22 if label else 0

    cell_w = qw + padding
    cell_h = qh + padding + label_height
    canvas_w = cols * cell_w + padding
    canvas_h = rows * cell_h + padding

    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)

    for idx, img in enumerate(qr_images):
        row = idx // cols
        col = idx % cols
        x = padding + col * cell_w
        y = padding + row * cell_h
        canvas.paste(img, (x, y))
        if label:
            total = len(qr_images)
            text = f"{idx + 1}/{total}"
            draw.text((x + qw // 2, y + qh + 4), text, fill="black", anchor="mt")

    return canvas


def paginate(qr_images: list[Image.Image], cols: int, rows: int) -> list[Image.Image]:
    per_page = cols * rows
    pages = []
    for start in range(0, len(qr_images), per_page):
        chunk = qr_images[start:start + per_page]
        pages.append(make_grid_image(chunk, cols, rows))
    return pages


def recommend_layout(num_packets: int) -> tuple[int, int]:
    """Return (cols, rows) that fits all packets in one page, smallest area first."""
    layouts = [(1, 1), (2, 1), (3, 1), (2, 2), (3, 2), (4, 2)]
    for cols, rows in layouts:
        if cols * rows >= num_packets:
            return cols, rows
    return 4, 2
