# QR DataBridge v1.0

在隔离网络环境（红区/黄区）之间，通过**截图 + 二维码**无损传输文本数据。

---

## 适用场景

| 角色 | 环境 | 操作 |
|------|------|------|
| 红区用户 | Linux，无网络 | 输入文本 → 生成二维码网格 → 全屏展示 |
| 黄区用户 | Windows，可联网 | Snipaste 截图 → 粘贴到解码 Tab → 还原文本 |

红区与黄区运行**同一份代码**，无需维护两套程序。

---

## 快速开始

### 安装依赖（黄区/联网机器）

```bash
pip install -r requirements.txt
```

### 红区离线安装

```bash
# 1. 在黄区下载 wheel 包
pip download -r requirements.txt -d wheels/ --python-version 3.11 --platform linux_x86_64

# 2. 将整个项目文件夹（含 wheels/）拷入红区

# 3. 红区执行
pip install --no-index --find-links=./wheels/ -r requirements.txt
```

Windows 红区使用 `install_offline.bat` 一键安装。

### 启动

```bash
python main.py
```

---

## 使用流程

### 编码端（红区）

1. 在「编码 Encode」Tab 中粘贴文本，或点击「加载文件」（支持 .txt / .csv / .log / .tsv，自动识别 UTF-8 / GBK）
2. 文本框下方的**容量指示条**实时显示：
   - 字符数、压缩后大小
   - 所需 QR 码数量
   - 每个 QR 码的填充率（绿色 < 75%，橙色 75-95%，红色 ≥ 95%）
3. 选择**纠错等级**（切换等级后容量指示条自动更新）：
   - **H（推荐）**：30% 冗余，抗水印/遮挡能力最强
   - Q：25% 冗余
   - M：15% 冗余
   - L：7% 冗余，单码容量最大（H 级的 2.3 倍）
4. 点击「生成 QR 码」，布局自动推荐
5. 全屏展示供黄区截图：
   - 「**当前屏全屏**」：最大化到当前显示器（多屏时在主窗口所在屏幕）
   - 「**跨屏全屏**」：铺满所有显示器的虚拟桌面，截图面积更大
   - 按 `Esc` 或点击图片关闭全屏

### 解码端（黄区）

1. 在「解码 Decode」Tab 中，用 Snipaste 截取红区屏幕后直接 `Ctrl+V` 粘贴，或点击「加载图片」
2. 点击「解码」
3. 如识别不完整，点击「**高对比度预处理后重试**」（针对 Snipaste 半透明水印场景）
4. 解码成功后点击「复制全部」或「保存为文件」

---

## 数据协议

每个 QR 码承载一个数据包，结构如下：

```
偏移  长度  字段
 0     4    MAGIC      固定值 b'QRDB'
 4     1    VERSION    当前 0x01
 5     2    PKT_INDEX  包序号（0-based，big-endian）
 7     2    PKT_TOTAL  总包数（big-endian）
 9     4    DATA_CRC32 全部压缩数据的 CRC32
13     2    CHUNK_CRC16 本包 payload 的 CRC16
15     1    FLAGS      bit0=gzip, bit1=文本
16     N    PAYLOAD    gzip 压缩后的数据片段
```

整包经 **Base64 编码**后写入 QR 码，避免 qrcode 库对高字节的 UTF-8 转义问题。

### 每码容量（Base64 折算后）

| 纠错等级 | QR v40 原始容量 | 可用 payload |
|---------|----------------|-------------|
| H       | 1273 B         | **938 B**   |
| Q       | 1663 B         | **1231 B**  |
| M       | 2331 B         | **1732 B**  |
| L       | 2953 B         | **2198 B**  |

---

## 文件结构

```
QR_DataBridge/
├── main.py                 # 入口
├── requirements.txt
├── install_offline.bat     # Windows 离线安装脚本
├── test_roundtrip.py       # 往返正确性测试（5 个用例）
├── app/
│   ├── gui.py              # 主窗口 + Tab 框架 + Ctrl+V 路由
│   ├── encode_tab.py       # 编码 Tab（容量指示条、全屏展示）
│   ├── decode_tab.py       # 解码 Tab（pyzbar + OpenCV 双引擎）
│   └── widgets.py          # QRCanvas（可滚动画布）、StatusBar
└── core/
    ├── protocol.py         # 二进制包头打包/拆包、CRC 校验
    ├── encoder.py          # 编码流程：gzip → 分片 → Base64 → QR
    ├── decoder.py          # 解码流程：图像预处理 → pyzbar/OpenCV → 重组
    └── utils.py            # CRC16/CRC32、gzip、编码检测
```

---

## 运行测试

```bash
python test_roundtrip.py
```

测试 5 个用例（最小字符串、1000 字符、2000 字符、Unicode、CSV 模拟数据），全部 PASS 即表示编解码链路正常。

---

## 已知注意事项

- **pyzbar（Windows）** 需要 `libzbar-64.dll`，通过 `pip install pyzbar` 通常会自动附带；若缺失请从 conda-forge 提取
- **跨屏全屏** 使用 `overrideredirect` 去除标题栏，只能通过 `Esc` 或点击图片关闭
- 纠错等级 H 抗干扰能力最强，**在 Snipaste 水印场景下推荐使用 H 级**
- 解码器优先使用 pyzbar，失败后自动 fallback 到 OpenCV

---

## 版本历史

| 版本 | 内容 |
|------|------|
| v1.0 | 编解码完整功能、容量可视化、双屏全屏、纠错等级说明 |
