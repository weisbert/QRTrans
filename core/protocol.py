import struct
from core.utils import crc16, crc32

MAGIC = b'QRDB'
VERSION = 0x01
HEADER_SIZE = 16


class ProtocolError(Exception):
    pass


class MissingPacketError(Exception):
    def __init__(self, missing: list[int]):
        self.missing = missing
        super().__init__(f"Missing packets: {missing}")


class CRCError(Exception):
    pass


def pack_chunk(index: int, total: int, data_crc32: int, payload: bytes, is_text: bool) -> bytes:
    flags = 0x01 | (0x02 if is_text else 0x00)  # bit0=gzip, bit1=text
    chunk_crc = crc16(payload)
    header = struct.pack(
        ">4sBHHIHB",
        MAGIC,
        VERSION,
        index,
        total,
        data_crc32,
        chunk_crc,
        flags,
    )
    return header + payload


def unpack_chunk(raw: bytes) -> dict:
    if len(raw) < HEADER_SIZE:
        raise ProtocolError(f"Packet too short: {len(raw)} bytes")

    magic, version, pkt_index, pkt_total, data_crc32_val, chunk_crc16_val, flags = struct.unpack(
        ">4sBHHIHB", raw[:HEADER_SIZE]
    )

    if magic != MAGIC:
        raise ProtocolError(f"Bad magic: {magic!r}")

    payload = raw[HEADER_SIZE:]
    actual_crc = crc16(payload)
    if actual_crc != chunk_crc16_val:
        raise ProtocolError(
            f"Chunk CRC16 mismatch (expected {chunk_crc16_val:#06x}, got {actual_crc:#06x})"
        )

    return {
        "index": pkt_index,
        "total": pkt_total,
        "data_crc32": data_crc32_val,
        "chunk_crc16": chunk_crc16_val,
        "flags": flags,
        "is_gzip": bool(flags & 0x01),
        "is_text": bool(flags & 0x02),
        "payload": payload,
    }
