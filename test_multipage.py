"""
Test: multi-page decode scenario.

Simulates the real workflow where a large payload fills multiple pages of QR
codes. Each page is decoded as a separate "screenshot" (separate PIL Image),
then all packets are merged and reassembled — exactly what DecodeTab does.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from core.encoder import encode_text, make_qr_image, paginate
from core.decoder import preprocess_image, detect_and_decode_qrs, reassemble


def multipage_roundtrip(text: str, label: str, cols: int = 4, rows: int = 2) -> bool:
    packets = encode_text(text)
    qr_images = [make_qr_image(p) for p in packets]
    pages = paginate(qr_images, cols=cols, rows=rows)

    per_page = cols * rows
    print(f"  → {len(packets)} QR码，{per_page} 码/页，共 {len(pages)} 页截图")

    # Simulate DecodeTab._do_decode: each page image is a separate screenshot
    all_packets = []
    for i, page_img in enumerate(pages):
        arr = preprocess_image(page_img, enhance=False)
        pkts = detect_and_decode_qrs(arr)
        all_packets.extend(pkts)
        print(f"    第 {i+1}/{len(pages)} 页：检测到 {len(pkts)} 个QR码")

    result = reassemble(all_packets)
    ok = result == text
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}: {len(text)} 字符 → 解码 {len(result)} 字符")
    if not ok:
        # Show where first difference is
        for idx, (a, b) in enumerate(zip(text, result)):
            if a != b:
                print(f"  首个差异位置 {idx}: expected {a!r} got {b!r}")
                break
        if len(text) != len(result):
            print(f"  长度不一致: expected {len(text)}, got {len(result)}")
    return ok


def make_log_text(lines: int) -> str:
    """Generate varied log lines that resist gzip compression."""
    rows = []
    for i in range(lines):
        hh = i // 3600 % 24
        mm = (i // 60) % 60
        ss = i % 60
        level = "WARN" if i % 7 == 0 else "INFO"
        worker = i % 16
        rows.append(
            f"2026-04-20T{hh:02d}:{mm:02d}:{ss:02d} [{level}] "
            f"worker-{worker:02d}: batch_{i:05d} latency={i*3.14159:.4f}ms "
            f"status={'ok' if i % 11 else 'retry'} seq={i*997}"
        )
    return "\n".join(rows)


def make_csv_text(rows: int) -> str:
    header = "timestamp,job_id,status,duration_ms,node,retries"
    lines = [header]
    for i in range(rows):
        lines.append(
            f"2026-04-20T{i%86400:05d}Z,job_{i:06d},"
            f"{'PASS' if i % 5 else 'FAIL'},{i*0.987654:.4f},"
            f"node-{i%32:02d},{i%4}"
        )
    return "\n".join(lines)


def main():
    test_cases = [
        # (text, label, cols, rows)
        # 2-page test at 2×1 layout (2 QR/page): needs >2 QR codes
        ("A" * 5000 + "B" * 5000, "10K 混合字符 2×1布局", 2, 1),
        # Realistic log, 2×2 layout: needs >4 QR codes
        (make_log_text(200), "200行日志 2×2布局", 2, 2),
        # Large CSV, 4×2 layout: needs >8 QR codes (2+ pages)
        (make_csv_text(600), "600行CSV 4×2布局", 4, 2),
        # Large log, 4×2 layout: needs >8 QR codes
        (make_log_text(500), "500行日志 4×2布局", 4, 2),
    ]

    results = []
    for text, label, cols, rows in test_cases:
        print(f"\n=== {label} ===")
        ok = multipage_roundtrip(text, label, cols=cols, rows=rows)
        results.append(ok)

    passed = sum(results)
    total = len(results)
    print(f"\n{'='*50}")
    print(f"结果: {passed}/{total} 通过")
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
