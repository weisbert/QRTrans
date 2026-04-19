# QRTrans v1.0

将任意文本编码为二维码网格图，或从截图中还原文本。支持大文本自动分片、多图合并解码。

---

## 功能特性

- **编码**：输入文本 → 自动分片 → 生成 QR 码网格图（支持全屏展示）
- **解码**：粘贴/加载截图 → 自动识别所有 QR 码 → 还原原始文本
- **多图解码**：可依次加载多张截图，一次性合并解码
- **容量指示**：实时显示字符数、压缩后大小、所需 QR 数量
- **双引擎识别**：pyzbar 优先，自动 fallback 到 OpenCV
- **高对比度重试**：针对截图质量较差的场景

---

## 安装

### 在线安装

```bash
pip install -r requirements.txt
```

### 离线安装（无网络环境）

在有网络的机器上运行 `prepare_wheels.bat`，下载 Windows 和 Linux 的离线包：

```bat
prepare_wheels.bat
```

将整个项目目录（含 `wheels\`）拷贝到目标机器后：

- **Windows**：运行 `install_offline.bat`
- **Linux**：运行 `bash install_offline.sh`

> Linux 还需提前安装系统库：
> - CentOS/RHEL：`sudo yum install zbar`
> - Debian/Ubuntu：`sudo apt install libzbar0`

---

## 启动

```bash
python main.py
```

---

## 使用方法

### 编码

1. 在「编码 Encode」Tab 中粘贴文本，或点击「加载文件」（支持 .txt / .csv / .log 等，自动识别 UTF-8 / GBK）
2. 选择纠错等级（推荐 **H**，抗干扰能力最强）
3. 点击「生成 QR 码」，布局自动推荐
4. 全屏展示供截图

### 解码

1. 在「解码 Decode」Tab 中粘贴截图（`Ctrl+V`）或点击「加载图片」
2. 如有多张截图，可多次粘贴/加载，程序会合并所有图片一起解码
3. 点击「解码」
4. 识别失败时点击「高对比度预处理后重试」
5. 解码成功后「复制全部」或「保存为文件」

---

## 数据协议

每个 QR 码承载一个数据包，整包经 Base64 编码写入 QR 码：

```
偏移  长度  字段
 0     4    MAGIC       固定值 b'QRDB'
 4     1    VERSION     当前 0x01
 5     2    PKT_INDEX   包序号（0-based，big-endian）
 7     2    PKT_TOTAL   总包数（big-endian）
 9     4    DATA_CRC32  全部压缩数据的 CRC32
13     2    CHUNK_CRC16 本包 payload 的 CRC16
15     1    FLAGS       bit0=gzip, bit1=文本
16     N    PAYLOAD     gzip 压缩后的数据片段
```

### 每码容量

| 纠错等级 | QR v40 原始容量 | 可用 payload |
|---------|----------------|-------------|
| H       | 1273 B         | **938 B**   |
| Q       | 1663 B         | **1231 B**  |
| M       | 2331 B         | **1732 B**  |
| L       | 2953 B         | **2198 B**  |

---

## 文件结构

```
QRTrans/
├── main.py
├── requirements.txt
├── requirements-linux.txt
├── install_offline.bat
├── install_offline.sh
├── prepare_wheels.bat
├── test_roundtrip.py
├── app/
│   ├── gui.py
│   ├── encode_tab.py
│   ├── decode_tab.py
│   └── widgets.py
└── core/
    ├── protocol.py
    ├── encoder.py
    ├── decoder.py
    └── utils.py
```

---

## 运行测试

```bash
python test_roundtrip.py
```

---

## 依赖

| 包 | 用途 |
|----|------|
| qrcode[pil] | QR 码生成 |
| Pillow | 图像处理 |
| numpy | 图像矩阵操作 |
| opencv-python | QR 识别 + 图像预处理 |
| pyzbar | QR 识别（主引擎） |
