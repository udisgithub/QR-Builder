# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup & Running

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

**macOS (Homebrew Python):** Tkinter requires a separate install: `brew install python-tk@3.14`

## Architecture

Single-file app: everything lives in `main.py` as one class `QRBuilderApp(tk.Tk)`.

**Rendering pipeline** (triggered on every control change, debounced 300ms):
1. `generate_qr()` → validates hex colors via `PIL.ImageColor.getrgb()`
2. `_build_qr_image()` → `qrcode.QRCode` + `StyledPilImage` factory + `SolidFillColorMask`
3. `_composite_logo()` → loads logo (SVG via `cairosvg`, raster via Pillow), optionally calls `_add_shaped_border()`, pastes centered
4. `_update_preview()` → `ImageTk.PhotoImage` bridge to Tkinter canvas

**SVG border shape** (`_add_shaped_border`): dilates the logo's alpha channel using Gaussian blur + threshold, fills the dilated region with the background color, then alpha-composites the original logo on top. This makes the border follow the vector shape rather than being a rectangle.

**Key Tkinter gotcha:** `self._tk_img` must be an instance variable. If assigned to a local variable, Python GC destroys the `PhotoImage` before Tkinter renders it, resulting in a blank preview.

**Debounce pattern:** `self._debounce_id` stores the `after()` return value; it is cancelled and rescheduled on every control change.

## Dependencies

| Package | Purpose |
|---------|---------|
| `qrcode[pil]>=7.4` | QR generation + `StyledPilImage` drawers |
| `Pillow>=10.0` | Image compositing, color parsing, export |
| `cairosvg>=2.7` | SVG → PNG rasterisation for logo loading |

Module shape drawers come from `qrcode.image.styles.moduledrawers.pil`. All six drawers share the same `BaseModuleDrawer` interface and are stored in the `SHAPE_DRAWERS` dict for direct lookup.
