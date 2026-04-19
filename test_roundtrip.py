import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from PIL import Image
from core.encoder import encode_text, make_qr_image, make_grid_image
from core.decoder import preprocess_image, detect_and_decode_qrs, reassemble


def roundtrip(text: str, label: str) -> bool:
    packets = encode_text(text)
    qr_images = [make_qr_image(p) for p in packets]
    cols = min(len(qr_images), 4)
    rows = (len(qr_images) + cols - 1) // cols
    grid = make_grid_image(qr_images, cols=cols, rows=rows)
    arr = preprocess_image(grid, enhance=False)
    decoded_packets = detect_and_decode_qrs(arr)
    result = reassemble(decoded_packets)
    ok = result == text
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}: {len(text)} chars → {len(packets)} QRs → decoded {len(result)} chars")
    if not ok:
        print(f"  expected[:80]: {text[:80]!r}")
        print(f"  got[:80]:      {result[:80]!r}")
    return ok


def main():
    test_cases = [
        ("Hello World", "最小用例"),
        ("A" * 1000, "单包边界"),
        ("A" * 2000, "双包"),
        ("特殊字符: αβγδ ±∞∫∂ ←→↑↓\n汉字测试：你好世界", "Unicode"),
        ("\n".join(f"2026-04-19,job_{i},PASS,{i*0.1:.2f}ms" for i in range(100)), "CSV仿真"),
    ]

    results = [roundtrip(text, label) for text, label in test_cases]
    passed = sum(results)
    total = len(results)
    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} 通过")
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
