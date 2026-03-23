# QR Builder

A local desktop app for generating styled QR codes with full visual customisation. No internet connection required — everything runs on your machine.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **QR types:** URL/Text, WiFi, Contact (vCard), Email, SMS, Phone
- **Module shapes:** Square, Rounded, Circle/Dots, Gapped Square, Vertical Bars, Horizontal Bars
- **Eye shapes:** Square, Rounded, Circle
- **Colour gradients:** Solid, Radial, Horizontal, Vertical, Square
- **Logo overlay:** PNG, JPG, or SVG — with optional shaped border that follows the logo contour
- **Background image:** composited behind the QR pattern
- **Error correction:** L / M / Q / H
- **Scan validation:** auto-validates every generated code to confirm it is readable
- **Presets:** save and load named style configurations
- **Export:** PNG (standard), PNG (hi-res 4×), copy to clipboard
- **Session restore:** reopens with your last-used settings

## Requirements

- Python 3.10+
- On macOS with Homebrew Python, Tkinter requires a separate install:
  ```bash
  brew install python-tk@3.14
  ```

## Installation

```bash
git clone https://github.com/your-username/qr-builder.git
cd qr-builder
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Dependencies

| Package | License | Purpose |
|---|---|---|
| [qrcode[pil]](https://github.com/lincolnloop/python-qrcode) | MIT | QR generation and styled drawers |
| [Pillow](https://python-pillow.org) | HPND | Image compositing and export |
| [cairosvg](https://cairosvg.org) | LGPL-3.0 | SVG logo rasterisation |
| [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp) | Apache-2.0 | Scan validation |
| [numpy](https://numpy.org) | BSD-3-Clause | Alpha channel processing |

## License

MIT — see [LICENSE](LICENSE).
