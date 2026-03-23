"""
QR Code Builder — local desktop app
Requires: qrcode[pil]>=7.4, Pillow>=10.0, cairosvg>=2.7, zxing-cpp>=2.0
Run:  python main.py
"""

import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import urllib.parse

import cairosvg
import qrcode
import qrcode.constants
import zxingcpp
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageTk
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import (
    HorizontalGradiantColorMask,
    RadialGradiantColorMask,
    SolidFillColorMask,
    SquareGradiantColorMask,
    VerticalGradiantColorMask,
)
from qrcode.image.styles.moduledrawers.pil import (
    CircleModuleDrawer,
    GappedSquareModuleDrawer,
    HorizontalBarsDrawer,
    RoundedModuleDrawer,
    SquareModuleDrawer,
    VerticalBarsDrawer,
)

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHAPE_DRAWERS = {
    "Square": SquareModuleDrawer,
    "Rounded": RoundedModuleDrawer,
    "Circle / Dots": CircleModuleDrawer,
    "Gapped Square": GappedSquareModuleDrawer,
    "Vertical Bars": VerticalBarsDrawer,
    "Horizontal Bars": HorizontalBarsDrawer,
}

EC_LEVELS = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}

GRADIENT_TYPES = ["None", "Radial", "Horizontal", "Vertical", "Square"]

EYE_SHAPES = ["Square", "Rounded", "Circle"]

QR_TYPES = ["URL / Text", "WiFi", "Contact", "Email", "SMS", "Phone"]

PRESETS_DIR = os.path.expanduser("~/.qrbuilder/presets")

DEFAULT_SETTINGS = {
    "qr_type": "URL / Text", "url": "",
    "wifi_ssid": "", "wifi_pass": "", "wifi_sec": "WPA",
    "contact_name": "", "contact_phone": "", "contact_email": "",
    "email_to": "", "email_subject": "", "email_body": "",
    "sms_number": "", "sms_body": "", "phone": "",
    "ec": "Q", "shape": "Square",
    "bg": "#FFFFFF", "fg": "#000000", "fg2": "#0055FF",
    "gradient": "None", "eye_shape": "Square", "eye_color": "#000000",
    "border": 4, "logo_size": 25, "logo_pad": 8,
    "logo_path": "", "bg_image_path": "", "bg_opacity": 30,
}

BOX_SIZE = 10
PREVIEW_SIZE = 420


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class QRBuilderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QR Code Builder — Private & Offline")
        self.minsize(700, 560)

        # Internal state
        self._debounce_id = None
        self._tk_img = None
        self._current_image: Image.Image | None = None
        self._logo_path: str | None = None
        self._bg_image_path: str | None = None
        self._generation_id = 0
        self._generation_lock = threading.Lock()
        self._wifi_warn_shown = False
        self._logo_cache: tuple | None = None    # (path, max_px, Image)
        self._bg_cache:   tuple | None = None    # (path, Image)

        d = DEFAULT_SETTINGS
        # ── Content vars ──────────────────────────────────────────────────
        self.qr_type_var = tk.StringVar(value=d["qr_type"])
        self.url_var = tk.StringVar(value=d["url"])
        # WiFi
        self.wifi_ssid_var = tk.StringVar(value=d["wifi_ssid"])
        self.wifi_pass_var = tk.StringVar(value=d["wifi_pass"])
        self.wifi_sec_var = tk.StringVar(value=d["wifi_sec"])
        # Contact (MECARD)
        self.contact_name_var = tk.StringVar(value=d["contact_name"])
        self.contact_phone_var = tk.StringVar(value=d["contact_phone"])
        self.contact_email_var = tk.StringVar(value=d["contact_email"])
        # Email
        self.email_to_var = tk.StringVar(value=d["email_to"])
        self.email_subject_var = tk.StringVar(value=d["email_subject"])
        self.email_body_var = tk.StringVar(value=d["email_body"])
        # SMS
        self.sms_number_var = tk.StringVar(value=d["sms_number"])
        self.sms_body_var = tk.StringVar(value=d["sms_body"])
        # Phone
        self.phone_var = tk.StringVar(value=d["phone"])

        # ── Style vars ────────────────────────────────────────────────────
        self.ec_var = tk.StringVar(value=d["ec"])
        self.shape_var = tk.StringVar(value=d["shape"])
        self.bg_var = tk.StringVar(value=d["bg"])
        self.fg_var = tk.StringVar(value=d["fg"])
        self.border_var = tk.IntVar(value=d["border"])
        # Gradient
        self.gradient_var = tk.StringVar(value=d["gradient"])
        self.fg2_var = tk.StringVar(value=d["fg2"])
        # Eyes
        self.eye_shape_var = tk.StringVar(value=d["eye_shape"])
        self.eye_color_var = tk.StringVar(value=d["eye_color"])
        # Background image
        self.bg_opacity_var = tk.IntVar(value=d["bg_opacity"])

        # ── Logo vars ─────────────────────────────────────────────────────
        self.logo_size_var = tk.IntVar(value=d["logo_size"])
        self.logo_pad_var = tk.IntVar(value=d["logo_pad"])

        self._build_ui()
        self._bind_events()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._restore_session()
        self.after(100, self.generate_qr)

    # ═══════════════════════════════════════════════════════════════════ UI ══

    def _build_ui(self):
        # ── Notebook (left) ───────────────────────────────────────────────
        self._notebook = ttk.Notebook(self)
        self._notebook.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        content_tab = ttk.Frame(self._notebook, padding=12)
        style_tab   = ttk.Frame(self._notebook, padding=12)
        logo_tab    = ttk.Frame(self._notebook, padding=12)
        output_tab  = ttk.Frame(self._notebook, padding=12)

        self._notebook.add(content_tab, text="  Content  ")
        self._notebook.add(style_tab,   text="  Style  ")
        self._notebook.add(logo_tab,    text="  Logo  ")
        self._notebook.add(output_tab,  text="  Output  ")

        self._build_content_tab(content_tab)
        self._build_style_tab(style_tab)
        self._build_logo_tab(logo_tab)
        self._build_output_tab(output_tab)
        self._build_menu()

        # ── Separator ─────────────────────────────────────────────────────
        ttk.Separator(self, orient="vertical").grid(
            row=0, column=1, sticky="ns", padx=2
        )

        # ── Right panel ───────────────────────────────────────────────────
        self._build_right_panel()

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save…", accelerator="Cmd+S", command=self.save_image)
        file_menu.add_command(label="Save Hi-Res…", command=self.save_image_hires)
        file_menu.add_command(label="Copy to Clipboard", accelerator="Cmd+C", command=self.copy_to_clipboard)
        menubar.add_cascade(label="File", menu=file_menu)
        self.configure(menu=menubar)
        mod = "Command" if sys.platform == "darwin" else "Control"
        self.bind_all(f"<{mod}-s>", lambda _: self.save_image())
        self.bind_all(f"<{mod}-c>", lambda _: self.copy_to_clipboard())

    # ── Content tab ───────────────────────────────────────────────────────

    def _build_content_tab(self, parent):
        pad = {"padx": 8, "pady": 3}

        ttk.Label(parent, text="QR Type", font=("", 9, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", **pad
        )
        type_combo = ttk.Combobox(
            parent, textvariable=self.qr_type_var,
            values=QR_TYPES, state="readonly", width=22
        )
        type_combo.grid(row=1, column=0, columnspan=3, sticky="w", **pad)
        type_combo.bind("<<ComboboxSelected>>", self._on_type_change)

        # Dynamic fields container
        self._content_fields_frame = ttk.Frame(parent)
        self._content_fields_frame.grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=4
        )

        # Error correction (always visible)
        ttk.Separator(parent, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=6
        )
        ttk.Label(parent, text="Damage Resistance", font=("", 9, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w", **pad
        )
        ec_frame = ttk.Frame(parent)
        ec_frame.grid(row=5, column=0, columnspan=3, sticky="w", padx=8)
        for i, (level, tip) in enumerate([("L","Low"),("M","Med"),("Q","High"),("H","Max")]):
            ttk.Radiobutton(
                ec_frame, text=f"{level} ({tip})", variable=self.ec_var, value=level,
                command=self._on_change
            ).grid(row=0, column=i, padx=4)
        ttk.Label(parent, text="Use High or Max when adding a logo.",
                  foreground="grey", font=("", 8)).grid(
            row=6, column=0, columnspan=3, sticky="w", padx=8
        )

        self._show_type_fields()

    def _show_type_fields(self):
        frame = self._content_fields_frame
        for w in frame.winfo_children():
            w.destroy()

        t = self.qr_type_var.get()
        pad = {"padx": 8, "pady": 2}

        if t == "URL / Text":
            ttk.Label(frame, text="URL / Text", font=("", 9, "bold")).grid(
                row=0, column=0, columnspan=2, sticky="w", **pad
            )
            self.url_entry = ttk.Entry(frame, textvariable=self.url_var, width=30)
            self.url_entry.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)
            self.url_entry.focus()

        elif t == "WiFi":
            for r, (lbl, var, show) in enumerate([
                ("SSID", self.wifi_ssid_var, False),
                ("Password", self.wifi_pass_var, True),
            ]):
                ttk.Label(frame, text=lbl).grid(row=r*2, column=0, sticky="w", **pad)
                e = ttk.Entry(frame, textvariable=var, width=28,
                              show="*" if show else "")
                e.grid(row=r*2+1, column=0, columnspan=2, sticky="ew", **pad)
            ttk.Label(frame, text="Security").grid(row=4, column=0, sticky="w", **pad)
            ttk.Combobox(
                frame, textvariable=self.wifi_sec_var,
                values=["WPA", "WEP", "nopass"], state="readonly", width=10
            ).grid(row=5, column=0, sticky="w", **pad)

        elif t == "Contact":
            for r, (lbl, var) in enumerate([
                ("Name", self.contact_name_var),
                ("Phone", self.contact_phone_var),
                ("Email", self.contact_email_var),
            ]):
                ttk.Label(frame, text=lbl).grid(row=r*2, column=0, sticky="w", **pad)
                ttk.Entry(frame, textvariable=var, width=28).grid(
                    row=r*2+1, column=0, columnspan=2, sticky="ew", **pad
                )

        elif t == "Email":
            for r, (lbl, var) in enumerate([
                ("To", self.email_to_var),
                ("Subject", self.email_subject_var),
                ("Body", self.email_body_var),
            ]):
                ttk.Label(frame, text=lbl).grid(row=r*2, column=0, sticky="w", **pad)
                ttk.Entry(frame, textvariable=var, width=28).grid(
                    row=r*2+1, column=0, columnspan=2, sticky="ew", **pad
                )

        elif t == "SMS":
            for r, (lbl, var) in enumerate([
                ("Number", self.sms_number_var),
                ("Message", self.sms_body_var),
            ]):
                ttk.Label(frame, text=lbl).grid(row=r*2, column=0, sticky="w", **pad)
                ttk.Entry(frame, textvariable=var, width=28).grid(
                    row=r*2+1, column=0, columnspan=2, sticky="ew", **pad
                )

        elif t == "Phone":
            ttk.Label(frame, text="Phone Number").grid(
                row=0, column=0, sticky="w", **pad
            )
            ttk.Entry(frame, textvariable=self.phone_var, width=28).grid(
                row=1, column=0, columnspan=2, sticky="ew", **pad
            )

    @staticmethod
    def _escape_wifi(value: str) -> str:
        """Escape special characters in WIFI QR format values (RFC 4180-style)."""
        return re.sub(r'([\\;,":{}])', r'\\\1', value)

    @staticmethod
    def _escape_mecard(value: str) -> str:
        """Escape special characters in MECARD format values."""
        return re.sub(r'([\\;:"])', r'\\\1', value)

    def _build_content_string(self) -> str:
        t = self.qr_type_var.get()
        if t == "URL / Text":
            return self.url_var.get().strip() or "https://example.com"
        elif t == "WiFi":
            ssid = self._escape_wifi(self.wifi_ssid_var.get())
            pw   = self._escape_wifi(self.wifi_pass_var.get())
            sec  = self.wifi_sec_var.get()
            return f"WIFI:T:{sec};S:{ssid};P:{pw};;"
        elif t == "Contact":
            n = self._escape_mecard(self.contact_name_var.get())
            p = self._escape_mecard(self.contact_phone_var.get())
            e = self._escape_mecard(self.contact_email_var.get())
            return f"MECARD:N:{n};TEL:{p};EMAIL:{e};;"
        elif t == "Email":
            to   = urllib.parse.quote(self.email_to_var.get(), safe="@.")
            subj = urllib.parse.quote(self.email_subject_var.get())
            body = urllib.parse.quote(self.email_body_var.get())
            return f"mailto:{to}?subject={subj}&body={body}"
        elif t == "SMS":
            number = re.sub(r"[^\d+\-() ]", "", self.sms_number_var.get())
            body   = urllib.parse.quote(self.sms_body_var.get())
            return f"smsto:{number}:{body}"
        elif t == "Phone":
            number = re.sub(r"[^\d+\-() ]", "", self.phone_var.get())
            return f"tel:{number}"
        return "https://example.com"

    # ── Style tab ─────────────────────────────────────────────────────────

    def _build_style_tab(self, parent):
        pad = {"padx": 8, "pady": 3}
        row = 0

        # Module shape
        ttk.Label(parent, text="Dot Shape", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        self.shape_combo = ttk.Combobox(
            parent, textvariable=self.shape_var,
            values=list(SHAPE_DRAWERS), state="readonly", width=20
        )
        self.shape_combo.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        self.shape_combo.bind("<<ComboboxSelected>>", lambda _: self._on_change())
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=5
        ); row += 1

        # Background color
        ttk.Label(parent, text="Background Color", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        self.bg_entry = ttk.Entry(parent, textvariable=self.bg_var, width=10)
        self.bg_entry.grid(row=row, column=0, sticky="w", padx=8)
        self.bg_swatch = tk.Label(parent, width=3, relief="sunken", bg="#FFFFFF")
        self.bg_swatch.grid(row=row, column=1, padx=2)
        ttk.Button(parent, text="Pick…", width=6,
                   command=lambda: self._pick_color(self.bg_var, self.bg_swatch)
                   ).grid(row=row, column=2, padx=4)
        row += 1

        # Foreground color
        ttk.Label(parent, text="QR Dot Color", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        self.fg_entry = ttk.Entry(parent, textvariable=self.fg_var, width=10)
        self.fg_entry.grid(row=row, column=0, sticky="w", padx=8)
        self.fg_swatch = tk.Label(parent, width=3, relief="sunken", bg="#000000")
        self.fg_swatch.grid(row=row, column=1, padx=2)
        ttk.Button(parent, text="Pick…", width=6,
                   command=lambda: self._pick_color(self.fg_var, self.fg_swatch)
                   ).grid(row=row, column=2, padx=4)
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=5
        ); row += 1

        # Gradient
        ttk.Label(parent, text="Gradient", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        ttk.Combobox(
            parent, textvariable=self.gradient_var,
            values=GRADIENT_TYPES, state="readonly", width=14
        ).grid(row=row, column=0, sticky="w", padx=8)
        self.gradient_var.trace_add("write", lambda *_: self._on_change())
        row += 1
        ttk.Label(parent, text="Gradient End Color", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        self.fg2_entry = ttk.Entry(parent, textvariable=self.fg2_var, width=10)
        self.fg2_entry.grid(row=row, column=0, sticky="w", padx=8)
        self.fg2_swatch = tk.Label(parent, width=3, relief="sunken", bg="#0055FF")
        self.fg2_swatch.grid(row=row, column=1, padx=2)
        ttk.Button(parent, text="Pick…", width=6,
                   command=lambda: self._pick_color(self.fg2_var, self.fg2_swatch)
                   ).grid(row=row, column=2, padx=4)
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=5
        ); row += 1

        # Eye shape
        ttk.Label(parent, text="Eye Shape", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        ttk.Combobox(
            parent, textvariable=self.eye_shape_var,
            values=EYE_SHAPES, state="readonly", width=14
        ).grid(row=row, column=0, sticky="w", padx=8)
        self.eye_shape_var.trace_add("write", lambda *_: self._on_change())
        row += 1
        ttk.Label(parent, text="Eye Color", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        self.eye_color_entry = ttk.Entry(parent, textvariable=self.eye_color_var, width=10)
        self.eye_color_entry.grid(row=row, column=0, sticky="w", padx=8)
        self.eye_color_swatch = tk.Label(parent, width=3, relief="sunken", bg="#000000")
        self.eye_color_swatch.grid(row=row, column=1, padx=2)
        ttk.Button(parent, text="Pick…", width=6,
                   command=lambda: self._pick_color(self.eye_color_var, self.eye_color_swatch)
                   ).grid(row=row, column=2, padx=4)
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=5
        ); row += 1

        # Quiet zone
        ttk.Label(parent, text="White Border Width", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        border_frame = ttk.Frame(parent)
        border_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        self.border_label = ttk.Label(border_frame, text="4", width=3)
        self.border_label.grid(row=0, column=1, padx=4)
        ttk.Scale(
            border_frame, from_=1, to=10, orient="horizontal",
            variable=self.border_var, length=160,
            command=self._on_border_change
        ).grid(row=0, column=0)
        row += 1

        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=5
        ); row += 1

        # Background image
        ttk.Label(parent, text="Background Image", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        self.bg_image_label = ttk.Label(parent, text="None", foreground="grey", width=22)
        self.bg_image_label.grid(row=row, column=0, columnspan=2, sticky="w", padx=8)
        ttk.Button(parent, text="Choose…", width=8,
                   command=self._pick_bg_image).grid(row=row, column=2, padx=4)
        row += 1
        ttk.Button(parent, text="Clear", width=8,
                   command=self._clear_bg_image).grid(row=row, column=0, sticky="w", padx=8, pady=2)
        row += 1
        ttk.Label(parent, text="Opacity", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        op_frame = ttk.Frame(parent)
        op_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        self.bg_opacity_label = ttk.Label(op_frame, text="30%", width=5)
        self.bg_opacity_label.grid(row=0, column=1, padx=4)
        ttk.Scale(
            op_frame, from_=0, to=100, orient="horizontal",
            variable=self.bg_opacity_var, length=150,
            command=self._on_opacity_change
        ).grid(row=0, column=0)

    # ── Logo tab ──────────────────────────────────────────────────────────

    def _build_logo_tab(self, parent):
        pad = {"padx": 8, "pady": 3}
        row = 0

        ttk.Label(parent, text="Logo File", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        self.logo_label = ttk.Label(parent, text="None", foreground="grey", width=26)
        self.logo_label.grid(row=row, column=0, columnspan=2, sticky="w", padx=8)
        ttk.Button(parent, text="Choose…", width=8,
                   command=self._pick_logo).grid(row=row, column=2, padx=4)
        row += 1
        ttk.Button(parent, text="Clear Logo", width=10,
                   command=self._clear_logo).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=2
        ); row += 1

        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=6
        ); row += 1

        ttk.Label(parent, text="Logo Size (% of QR)", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        logo_size_frame = ttk.Frame(parent)
        logo_size_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        self.logo_size_label = ttk.Label(logo_size_frame, text="25%", width=5)
        self.logo_size_label.grid(row=0, column=1, padx=4)
        ttk.Scale(
            logo_size_frame, from_=10, to=35, orient="horizontal",
            variable=self.logo_size_var, length=150,
            command=self._on_logo_size_change
        ).grid(row=0, column=0)
        row += 1

        ttk.Label(parent, text="Logo Border Width (px)", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1
        logo_pad_frame = ttk.Frame(parent)
        logo_pad_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=8)
        self.logo_pad_label = ttk.Label(logo_pad_frame, text="8 px", width=6)
        self.logo_pad_label.grid(row=0, column=1, padx=4)
        ttk.Scale(
            logo_pad_frame, from_=0, to=40, orient="horizontal",
            variable=self.logo_pad_var, length=150,
            command=self._on_logo_pad_change
        ).grid(row=0, column=0)

    # ── Output tab ────────────────────────────────────────────────────────

    def _build_output_tab(self, parent):
        pad = {"padx": 8, "pady": 3}
        row = 0

        ttk.Label(parent, text="Presets", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        ); row += 1

        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(
            parent, textvariable=self.preset_var, state="readonly", width=22
        )
        self.preset_combo.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Button(btn_frame, text="Save…", width=9,
                   command=self._save_preset).grid(row=0, column=0, padx=2)
        ttk.Button(btn_frame, text="Load", width=9,
                   command=self._load_preset).grid(row=0, column=1, padx=2)
        ttk.Button(btn_frame, text="Delete", width=9,
                   command=self._delete_preset).grid(row=0, column=2, padx=2)

        self._refresh_preset_list()

    # ── Right panel ───────────────────────────────────────────────────────

    def _build_right_panel(self):
        right = ttk.Frame(self, padding=12)
        right.grid(row=0, column=2, sticky="nsew")

        ttk.Label(right, text="Preview", font=("", 9, "bold")).grid(
            row=0, column=0, columnspan=3
        )

        self.preview_label = ttk.Label(
            right, relief="sunken", width=PREVIEW_SIZE, anchor="center"
        )
        self.preview_label.grid(
            row=1, column=0, columnspan=3, padx=8, pady=8, ipadx=4, ipady=4
        )
        placeholder = tk.PhotoImage(width=PREVIEW_SIZE, height=PREVIEW_SIZE)
        self.preview_label.configure(image=placeholder)
        self._placeholder = placeholder

        ttk.Button(right, text="Copy", command=self.copy_to_clipboard, width=10).grid(
            row=2, column=0, padx=4, pady=8
        )
        ttk.Button(right, text="Save…", command=self.save_image, width=10).grid(
            row=2, column=1, padx=4, pady=8
        )
        ttk.Button(right, text="Save Hi-Res…", command=self.save_image_hires, width=12).grid(
            row=2, column=2, padx=4, pady=8
        )

        self.status_label = ttk.Label(right, text="", foreground="grey")
        self.status_label.grid(row=3, column=0, columnspan=3)

        ttk.Button(right, text="Reset to Defaults", command=self._reset, width=16).grid(
            row=4, column=0, columnspan=3, pady=(8, 0)
        )

    # ═══════════════════════════════════════════════════════════════ Events ══

    def _bind_events(self):
        self.url_var.trace_add("write", lambda *_: self._on_change())
        self.wifi_ssid_var.trace_add("write", lambda *_: self._on_wifi_credential_change())
        self.wifi_pass_var.trace_add("write", lambda *_: self._on_wifi_credential_change())
        self.wifi_sec_var.trace_add("write", lambda *_: self._on_change())
        self.contact_name_var.trace_add("write", lambda *_: self._on_change())
        self.contact_phone_var.trace_add("write", lambda *_: self._on_change())
        self.contact_email_var.trace_add("write", lambda *_: self._on_change())
        self.email_to_var.trace_add("write", lambda *_: self._on_change())
        self.email_subject_var.trace_add("write", lambda *_: self._on_change())
        self.email_body_var.trace_add("write", lambda *_: self._on_change())
        self.sms_number_var.trace_add("write", lambda *_: self._on_change())
        self.sms_body_var.trace_add("write", lambda *_: self._on_change())
        self.phone_var.trace_add("write", lambda *_: self._on_change())
        self.bg_var.trace_add("write", lambda *_: self._on_color_typed(
            self.bg_var, self.bg_swatch))
        self.fg_var.trace_add("write", lambda *_: self._on_color_typed(
            self.fg_var, self.fg_swatch))
        self.fg2_var.trace_add("write", lambda *_: self._on_color_typed(
            self.fg2_var, self.fg2_swatch))
        self.eye_color_var.trace_add("write", lambda *_: self._on_color_typed(
            self.eye_color_var, self.eye_color_swatch))

    def _on_change(self):
        if self._debounce_id:
            self.after_cancel(self._debounce_id)
        self._debounce_id = self.after(300, self.generate_qr)

    def _on_wifi_credential_change(self):
        self._wifi_warn_shown = False
        self._on_change()

    def _on_type_change(self, _event=None):
        self._show_type_fields()
        self._on_change()

    def _on_border_change(self, val):
        self.border_label.configure(text=str(int(float(val))))
        self._on_change()

    def _on_logo_size_change(self, val):
        self.logo_size_label.configure(text=f"{int(float(val))}%")
        self._on_change()

    def _on_logo_pad_change(self, val):
        self.logo_pad_label.configure(text=f"{int(float(val))} px")
        self._on_change()

    def _on_opacity_change(self, val):
        self.bg_opacity_label.configure(text=f"{int(float(val))}%")
        self._on_change()

    def _on_color_typed(self, var: tk.StringVar, swatch: tk.Label):
        val = var.get().strip()
        try:
            color = ImageColor.getrgb(val)
            swatch.configure(bg=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}")
            self._on_change()
        except (ValueError, AttributeError):
            pass

    def _pick_color(self, var: tk.StringVar, swatch: tk.Label):
        try:
            init = ImageColor.getrgb(var.get().strip())
        except (ValueError, AttributeError):
            init = (0, 0, 0)
        result = colorchooser.askcolor(color=init, title="Choose color")
        if result and result[1]:
            var.set(result[1])
            swatch.configure(bg=result[1])
            self._on_change()

    def _pick_logo(self):
        path = filedialog.askopenfilename(
            title="Choose Logo",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg"),
                ("SVG files", "*.svg"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._logo_path = path
            self._logo_cache = None
            self.logo_label.configure(
                text=os.path.basename(path), foreground="black"
            )
            if self.ec_var.get() in ("L", "M"):
                self.ec_var.set("Q")
                messagebox.showinfo(
                    "Error Correction Adjusted",
                    "Error correction set to Q to ensure the QR code remains "
                    "scannable with a logo overlay."
                )
            self._on_change()

    def _clear_logo(self):
        self._logo_path = None
        self._logo_cache = None
        self.logo_label.configure(text="None", foreground="grey")
        self._on_change()

    def _pick_bg_image(self):
        path = filedialog.askopenfilename(
            title="Choose Background Image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._bg_image_path = path
            self._bg_cache = None
            self.bg_image_label.configure(
                text=os.path.basename(path), foreground="black"
            )
            self._on_change()

    def _clear_bg_image(self):
        self._bg_image_path = None
        self._bg_cache = None
        self.bg_image_label.configure(text="None", foreground="grey")
        self._on_change()

    # ═════════════════════════════════════════════════════ QR Generation ══

    def _validate_colors(self):
        results = {}
        for name, var in [
            ("bg",  self.bg_var),
            ("fg",  self.fg_var),
            ("fg2", self.fg2_var),
            ("eye", self.eye_color_var),
        ]:
            val = var.get().strip()
            try:
                results[name] = ImageColor.getrgb(val)
            except (ValueError, AttributeError):
                raise ValueError(f"Invalid color '{val}'")
        return results["bg"], results["fg"], results["fg2"], results["eye"]

    def _build_color_mask(self, bg_rgb, fg_rgb, fg2_rgb):
        g = self.gradient_var.get()
        if g == "None":
            return SolidFillColorMask(
                back_color=bg_rgb[:3], front_color=fg_rgb[:3]
            )
        elif g == "Radial":
            return RadialGradiantColorMask(
                back_color=bg_rgb[:3], center_color=fg_rgb[:3], edge_color=fg2_rgb[:3]
            )
        elif g == "Horizontal":
            return HorizontalGradiantColorMask(
                back_color=bg_rgb[:3], left_color=fg_rgb[:3], right_color=fg2_rgb[:3]
            )
        elif g == "Vertical":
            return VerticalGradiantColorMask(
                back_color=bg_rgb[:3], top_color=fg_rgb[:3], bottom_color=fg2_rgb[:3]
            )
        elif g == "Square":
            return SquareGradiantColorMask(
                back_color=bg_rgb[:3], center_color=fg_rgb[:3], edge_color=fg2_rgb[:3]
            )
        return SolidFillColorMask(back_color=bg_rgb[:3], front_color=fg_rgb[:3])

    def _build_qr_image(self, bg_rgb, fg_rgb, fg2_rgb) -> tuple[Image.Image, int]:
        """Returns (image, modules_count)."""
        text = self._build_content_string()
        ec = EC_LEVELS[self.ec_var.get()]
        border = int(self.border_var.get())
        drawer_cls = SHAPE_DRAWERS[self.shape_var.get()]

        qr = qrcode.QRCode(
            error_correction=ec,
            box_size=BOX_SIZE,
            border=border,
        )
        qr.add_data(text)
        qr.make(fit=True)

        mask = self._build_color_mask(bg_rgb, fg_rgb, fg2_rgb)
        img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=drawer_cls(),
            color_mask=mask,
        )
        return img.convert("RGBA"), qr.modules_count

    def _redraw_eyes(
        self, img: Image.Image, modules_count: int,
        eye_shape: str, eye_rgb, bg_rgb
    ) -> Image.Image:
        """Post-process: redraw the 3 finder patterns with custom shape/color."""
        border = int(self.border_var.get())
        bs = BOX_SIZE
        size = modules_count

        # Pixel offset to the top-left corner of each 7×7 eye
        eye_origins = [
            (border * bs, border * bs),                        # top-left
            ((border + size - 7) * bs, border * bs),           # top-right
            (border * bs, (border + size - 7) * bs),           # bottom-left
        ]

        draw = ImageDraw.Draw(img)
        eye_color_full = eye_rgb[:3] + (255,)
        bg_color_full  = bg_rgb[:3]  + (255,)

        def draw_shape(x0, y0, x1, y1, color):
            if eye_shape == "Square":
                draw.rectangle([x0, y0, x1, y1], fill=color)
            elif eye_shape == "Rounded":
                r = min((x1 - x0), (y1 - y0)) // 4
                draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=color)
            elif eye_shape == "Circle":
                draw.ellipse([x0, y0, x1, y1], fill=color)

        outer    = 7 * bs
        inner_off = 1 * bs
        dot_off   = 2 * bs
        dot_size  = 3 * bs

        for ox, oy in eye_origins:
            # 1. Erase the whole 7×7 region
            draw.rectangle([ox, oy, ox + outer - 1, oy + outer - 1],
                           fill=bg_color_full)

            # 2. Outer ring (filled 7×7)
            draw_shape(ox, oy, ox + outer - 1, oy + outer - 1, eye_color_full)
            # 3. Inner white area (5×5 inset by 1 module)
            draw_shape(
                ox + inner_off, oy + inner_off,
                ox + outer - inner_off - 1, oy + outer - inner_off - 1,
                bg_color_full
            )
            # 4. Center dot (3×3 inset by 2 modules)
            draw_shape(
                ox + dot_off, oy + dot_off,
                ox + dot_off + dot_size - 1, oy + dot_off + dot_size - 1,
                eye_color_full
            )

        return img

    def _load_logo(self, max_px: int) -> Image.Image:
        path = self._logo_path
        if self._logo_cache and self._logo_cache[:2] == (path, max_px):
            return self._logo_cache[2].copy()
        if path.lower().endswith(".svg"):
            # Security: cairosvg may follow xlink:href / CSS url() references inside
            # the SVG. path is always a file chosen by the user via the OS file picker,
            # so no remote-supply path exists. Users should avoid opening SVGs from
            # untrusted sources as logos.
            png_bytes = cairosvg.svg2png(
                url=path, output_width=max_px, output_height=max_px
            )
            logo = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        else:
            logo = Image.open(path).convert("RGBA")
            logo.thumbnail((max_px, max_px), Image.LANCZOS)
        self._logo_cache = (path, max_px, logo)
        return logo.copy()

    def _add_shaped_border(self, logo: Image.Image, pad: int, bg_rgb) -> Image.Image:
        new_w = logo.width + pad * 2
        new_h = logo.height + pad * 2
        expanded_alpha = Image.new("L", (new_w, new_h), 0)
        expanded_alpha.paste(logo.split()[3], (pad, pad))
        blurred = expanded_alpha.filter(ImageFilter.GaussianBlur(radius=pad * 0.9))
        dilated = blurred.point(lambda x: 255 if x > 8 else 0)
        border_layer = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
        bg_fill = Image.new("RGBA", (new_w, new_h), bg_rgb[:3] + (255,))
        border_layer.paste(bg_fill, mask=dilated)
        expanded_logo = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
        expanded_logo.paste(logo, (pad, pad))
        return Image.alpha_composite(border_layer, expanded_logo)

    def _composite_logo(self, qr_img: Image.Image, bg_rgb) -> Image.Image:
        if not self._logo_path:
            return qr_img
        qr_w, qr_h = qr_img.size
        max_px = int(min(qr_w, qr_h) * self.logo_size_var.get() / 100)
        try:
            logo = self._load_logo(max_px)
        except Exception as e:
            self.status_label.configure(text=f"Logo error: {e}", foreground="red")
            return qr_img
        pad = int(self.logo_pad_var.get())
        if pad > 0:
            logo = self._add_shaped_border(logo, pad, bg_rgb)
        logo_w, logo_h = logo.size
        paste_x = (qr_w - logo_w) // 2
        paste_y = (qr_h - logo_h) // 2
        qr_img.paste(logo, (paste_x, paste_y), mask=logo)
        return qr_img

    def _make_bg_transparent(self, img: Image.Image, bg_rgb) -> Image.Image:
        """Replace pixels close to bg_rgb with transparent, so a bg image shows through."""
        arr = np.array(img)
        is_bg = np.abs(arr[:, :, :3].astype(np.int16) - np.array(bg_rgb[:3], dtype=np.int16)).sum(axis=2) < 40
        arr[is_bg, 3] = 0
        return Image.fromarray(arr)

    def _composite_bg_image(self, qr_img: Image.Image) -> Image.Image:
        if not self._bg_image_path:
            return qr_img
        try:
            if self._bg_cache and self._bg_cache[0] == self._bg_image_path:
                bg = self._bg_cache[1].copy()
            else:
                bg = Image.open(self._bg_image_path).convert("RGBA")
                self._bg_cache = (self._bg_image_path, bg)
                bg = bg.copy()
        except Exception as e:
            self.status_label.configure(
                text=f"Background error: {e}", foreground="red"
            )
            return qr_img
        bg = bg.resize(qr_img.size, Image.LANCZOS)
        # Apply user opacity to the background image
        opacity = int(self.bg_opacity_var.get() / 100 * 255)
        r, g, b, a = bg.split()
        a = a.point(lambda x: min(x, opacity))
        bg.putalpha(a)
        # White base → background image → QR (transparent bg pixels let image show through)
        base = Image.new("RGBA", qr_img.size, (255, 255, 255, 255))
        base.alpha_composite(bg)
        base.alpha_composite(qr_img)
        return base

    def generate_qr(self):
        try:
            bg_rgb, fg_rgb, fg2_rgb, eye_rgb = self._validate_colors()
        except ValueError as e:
            self.status_label.configure(text=str(e), foreground="red")
            return

        try:
            qr_img, modules_count = self._build_qr_image(bg_rgb, fg_rgb, fg2_rgb)

            eye_shape = self.eye_shape_var.get()
            if eye_shape != "Square" or eye_rgb[:3] != fg_rgb[:3]:
                qr_img = self._redraw_eyes(
                    qr_img, modules_count, eye_shape, eye_rgb, bg_rgb
                )

            if self._bg_image_path:
                qr_img = self._make_bg_transparent(qr_img, bg_rgb)
            qr_img = self._composite_bg_image(qr_img)
            qr_img = self._composite_logo(qr_img, bg_rgb)
        except Exception as e:
            self.status_label.configure(text=f"Error: {e}", foreground="red")
            return

        self._current_image = qr_img
        self._update_preview(qr_img)
        self.status_label.configure(text="Validating…", foreground="grey")
        with self._generation_lock:
            self._generation_id += 1
            gen_id = self._generation_id
        has_logo = self._logo_path is not None
        has_bg   = self._bg_image_path is not None
        threading.Thread(
            target=self._validate_scan,
            args=(qr_img.copy(), gen_id, has_logo, has_bg),
            daemon=True
        ).start()

    def _update_preview(self, img: Image.Image):
        display = img.copy()
        display.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(display)
        self.preview_label.configure(image=self._tk_img)

    # ═══════════════════════════════════════════════ Scan validation ══

    def _validate_scan(self, img: Image.Image, gen_id: int, has_logo: bool, has_bg: bool):
        try:
            arr = np.array(img.convert("RGB"))
            results = zxingcpp.read_barcodes(arr)
            with self._generation_lock:
                current = self._generation_id
            if gen_id != current:
                return  # stale — a newer generation is in flight
            if results:
                self.after(0, lambda: self.status_label.configure(
                    text="✓ Scannable", foreground="green"
                ))
            else:
                if has_logo and has_bg:
                    hint = "reduce logo size, lower background opacity, or raise error correction"
                elif has_logo:
                    hint = "reduce logo size or raise error correction"
                elif has_bg:
                    hint = "lower background opacity or raise error correction"
                else:
                    hint = "raise error correction level"
                msg = f"⚠ Not scannable — {hint}"
                self.after(0, lambda m=msg: self.status_label.configure(
                    text=m, foreground="red"
                ))
        except Exception as e:
            self.after(0, lambda m=str(e): self.status_label.configure(
                text=f"Scan error: {m}", foreground="red"
            ))

    # ═══════════════════════════════════════════════════════════ Save ══

    def save_image(self):
        if self._current_image is None:
            messagebox.showwarning("Nothing to save", "Generate a QR code first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save QR Code",
            defaultextension=".png",
            filetypes=[
                ("PNG Image", "*.png"),
                ("High-Resolution PNG (4x)", "*.png"),
                ("JPEG Image", "*.jpg"),
                ("All Files", "*.*"),
            ],
        )
        if not path:
            return
        save_img = self._current_image
        if path.lower().endswith((".jpg", ".jpeg")):
            save_img = save_img.convert("RGB")
        save_img.save(path)
        self.status_label.configure(
            text=f"Saved: {os.path.basename(path)}", foreground="green"
        )

    def save_image_hires(self):
        """Save a 4x upscaled version for print production."""
        if self._current_image is None:
            messagebox.showwarning("Nothing to save", "Generate a QR code first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save High-Resolution QR Code",
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")],
        )
        if not path:
            return
        img = self._current_image
        w, h = img.size
        hires = img.resize((w * 4, h * 4), Image.LANCZOS)
        save_img = hires if path.lower().endswith(".png") else hires.convert("RGB")
        save_img.save(path, dpi=(300, 300))
        self.status_label.configure(
            text=f"Saved hi-res: {os.path.basename(path)}", foreground="green"
        )

    def copy_to_clipboard(self):
        if self._current_image is None:
            messagebox.showwarning("Nothing to copy", "Generate a QR code first.")
            return
        if sys.platform == "darwin":
            fd, tmp = tempfile.mkstemp(suffix=".png")
            try:
                # Write through the fd returned by mkstemp — avoids closing and
                # re-opening by path, which would create a TOCTOU window.
                # tmp is always a mkstemp-generated path; never pass user-supplied
                # paths here (shlex.quote inside AppleScript has POSIX-shell semantics
                # only, not AppleScript string semantics).
                with os.fdopen(fd, "wb") as fh:
                    self._current_image.convert("RGB").save(fh, format="PNG")
                fd = -1  # ownership transferred to fdopen; don't double-close
                subprocess.run(
                    ["osascript", "-e",
                     f"set the clipboard to (read (POSIX file {shlex.quote(tmp)}) as TIFF picture)"],
                    check=True
                )
                self.status_label.configure(text="Copied to clipboard.", foreground="green")
            finally:
                if fd != -1:
                    os.close(fd)
                if os.path.exists(tmp):
                    os.unlink(tmp)
        else:
            messagebox.showinfo(
                "Not supported",
                "Clipboard copy is currently only supported on macOS."
            )

    # ═══════════════════════════════════════════════════════ Presets ══

    def _preset_names(self) -> list[str]:
        if not os.path.isdir(PRESETS_DIR):
            return []
        return sorted(
            f[:-5] for f in os.listdir(PRESETS_DIR) if f.endswith(".json")
        )

    def _refresh_preset_list(self):
        names = self._preset_names()
        self.preset_combo.configure(values=names)
        if names and self.preset_var.get() not in names:
            self.preset_var.set(names[0])

    def _settings_dict(self) -> dict:
        return {
            "qr_type":       self.qr_type_var.get(),
            "url":           self.url_var.get(),
            "wifi_ssid":     self.wifi_ssid_var.get(),
            "wifi_pass":     self.wifi_pass_var.get(),
            "wifi_sec":      self.wifi_sec_var.get(),
            "contact_name":  self.contact_name_var.get(),
            "contact_phone": self.contact_phone_var.get(),
            "contact_email": self.contact_email_var.get(),
            "email_to":      self.email_to_var.get(),
            "email_subject": self.email_subject_var.get(),
            "email_body":    self.email_body_var.get(),
            "sms_number":    self.sms_number_var.get(),
            "sms_body":      self.sms_body_var.get(),
            "phone":         self.phone_var.get(),
            "ec":            self.ec_var.get(),
            "shape":         self.shape_var.get(),
            "bg":            self.bg_var.get(),
            "fg":            self.fg_var.get(),
            "fg2":           self.fg2_var.get(),
            "gradient":      self.gradient_var.get(),
            "eye_shape":     self.eye_shape_var.get(),
            "eye_color":     self.eye_color_var.get(),
            "border":        self.border_var.get(),
            "logo_size":     self.logo_size_var.get(),
            "logo_pad":      self.logo_pad_var.get(),
            "logo_path":     self._logo_path or "",
            "bg_image_path": self._bg_image_path or "",
            "bg_opacity":    self.bg_opacity_var.get(),
        }

    def _apply_settings_dict(self, d: dict):
        s = {**DEFAULT_SETTINGS, **d}  # d overrides defaults
        self.qr_type_var.set(s["qr_type"])
        self.url_var.set(s["url"])
        self.wifi_ssid_var.set(s["wifi_ssid"])
        self.wifi_pass_var.set(s["wifi_pass"])
        self.wifi_sec_var.set(s["wifi_sec"])
        self.contact_name_var.set(s["contact_name"])
        self.contact_phone_var.set(s["contact_phone"])
        self.contact_email_var.set(s["contact_email"])
        self.email_to_var.set(s["email_to"])
        self.email_subject_var.set(s["email_subject"])
        self.email_body_var.set(s["email_body"])
        self.sms_number_var.set(s["sms_number"])
        self.sms_body_var.set(s["sms_body"])
        self.phone_var.set(s["phone"])
        self.ec_var.set(s["ec"])
        self.shape_var.set(s["shape"])
        self.bg_var.set(s["bg"])
        self.fg_var.set(s["fg"])
        self.fg2_var.set(s["fg2"])
        self.gradient_var.set(s["gradient"])
        self.eye_shape_var.set(s["eye_shape"])
        self.eye_color_var.set(s["eye_color"])
        self.border_var.set(s["border"])
        self.border_label.configure(text=str(s["border"]))
        self.logo_size_var.set(s["logo_size"])
        self.logo_size_label.configure(text=f"{s['logo_size']}%")
        self.logo_pad_var.set(s["logo_pad"])
        self.logo_pad_label.configure(text=f"{s['logo_pad']} px")
        lp = s["logo_path"]
        if lp and not os.path.exists(lp):
            self.status_label.configure(
                text=f"Logo not found: {os.path.basename(lp)}", foreground="orange"
            )
            lp = ""
        self._logo_path = lp or None
        self.logo_label.configure(
            text=os.path.basename(lp) if lp else "None",
            foreground="black" if lp else "grey"
        )
        bp = s["bg_image_path"]
        if bp and not os.path.exists(bp):
            self.status_label.configure(
                text=f"Background image not found: {os.path.basename(bp)}", foreground="orange"
            )
            bp = ""
        self._bg_image_path = bp or None
        self.bg_image_label.configure(
            text=os.path.basename(bp) if bp else "None",
            foreground="black" if bp else "grey"
        )
        self.bg_opacity_var.set(s["bg_opacity"])
        self.bg_opacity_label.configure(text=f"{s['bg_opacity']}%")
        self._show_type_fields()

    @staticmethod
    def _sanitize_loaded_settings(d: dict) -> dict:
        """Validate enum fields from loaded JSON against allowed values.
        Unknown values are replaced with the DEFAULT_SETTINGS fallback so a
        tampered preset cannot crash the app via a bad dict-key lookup."""
        _ALLOWED = {
            "qr_type":    set(QR_TYPES),
            "ec":         set(EC_LEVELS),
            "shape":      set(SHAPE_DRAWERS),
            "gradient":   set(GRADIENT_TYPES),
            "eye_shape":  set(EYE_SHAPES),
            "wifi_sec":   {"WPA", "WEP", "nopass"},
        }
        out = dict(d)
        for key, allowed in _ALLOWED.items():
            if out.get(key) not in allowed:
                out[key] = DEFAULT_SETTINGS[key]
        # Ensure numeric fields are within sane bounds
        for key, lo, hi in [("border", 0, 20), ("logo_size", 5, 50),
                             ("logo_pad", 0, 40), ("bg_opacity", 0, 100)]:
            try:
                out[key] = max(lo, min(hi, int(out[key])))
            except (KeyError, TypeError, ValueError):
                out[key] = DEFAULT_SETTINGS[key]
        return out

    @staticmethod
    def _sanitize_preset_name(name: str) -> str:
        """Allow only alphanumeric, spaces, hyphens, underscores."""
        return re.sub(r"[^\w\s\-]", "", name).strip()

    def _save_preset(self):
        raw = simpledialog.askstring("Save Preset", "Preset name:")
        if not raw:
            return
        name = self._sanitize_preset_name(raw)
        if not name:
            messagebox.showerror(
                "Invalid name",
                "Preset name may only contain letters, numbers, spaces, hyphens, and underscores."
            )
            return
        if name != raw.strip():
            if not messagebox.askyesno(
                "Name adjusted",
                f"Some characters were removed. Save as '{name}'?"
            ):
                return
        os.makedirs(PRESETS_DIR, exist_ok=True)
        path = os.path.join(PRESETS_DIR, f"{name}.json")
        # Verify the resolved path stays within PRESETS_DIR (path traversal guard)
        if not os.path.realpath(path).startswith(os.path.realpath(PRESETS_DIR) + os.sep):
            messagebox.showerror("Error", "Invalid preset name.")
            return
        # P0-3: warn before storing plaintext WiFi password
        if (self.qr_type_var.get() == "WiFi"
                and self.wifi_pass_var.get()
                and not self._wifi_warn_shown):
            proceed = messagebox.askyesno(
                "WiFi Password Warning",
                f"This preset will save your WiFi password in plain text at:\n"
                f"{path}\n\n"
                "Only save if you are comfortable with this. Continue?"
            )
            if not proceed:
                return
            self._wifi_warn_shown = True
        with open(path, "w") as f:
            json.dump(self._settings_dict(), f, indent=2)
        self._refresh_preset_list()
        self.preset_var.set(name)
        self.status_label.configure(text=f"Preset '{name}' saved.", foreground="green")

    def _load_preset(self):
        name = self.preset_var.get()
        if not name:
            return
        path = os.path.join(PRESETS_DIR, f"{name}.json")
        if not os.path.realpath(path).startswith(os.path.realpath(PRESETS_DIR) + os.sep):
            messagebox.showerror("Error", "Invalid preset name.")
            return
        if not os.path.exists(path):
            messagebox.showerror("Not found", f"Preset '{name}' not found.")
            return
        with open(path) as f:
            d = json.load(f)
        self._apply_settings_dict(self._sanitize_loaded_settings(d))
        self.generate_qr()

    def _delete_preset(self):
        name = self.preset_var.get()
        if not name:
            return
        if not messagebox.askyesno("Delete", f"Delete preset '{name}'?"):
            return
        path = os.path.join(PRESETS_DIR, f"{name}.json")
        if not os.path.realpath(path).startswith(os.path.realpath(PRESETS_DIR) + os.sep):
            messagebox.showerror("Error", "Invalid preset name.")
            return
        if os.path.exists(path):
            os.unlink(path)
        self._refresh_preset_list()
        self.status_label.configure(text=f"Preset '{name}' deleted.", foreground="grey")

    # ══════════════════════════════════════════════════ Session restore ══

    _SESSION_FILE = os.path.join(os.path.expanduser("~/.qrbuilder"), "last_session.json")

    def _reset(self):
        if not messagebox.askyesno("Reset", "Clear all settings and start fresh?"):
            return
        self._wifi_warn_shown = False
        self._apply_settings_dict({})
        self._notebook.select(0)
        self._on_change()

    def _restore_session(self):
        if not os.path.exists(self._SESSION_FILE):
            return
        try:
            with open(self._SESSION_FILE) as f:
                d = json.load(f)
            self._apply_settings_dict(self._sanitize_loaded_settings(d))
        except (OSError, json.JSONDecodeError, ValueError):
            pass  # corrupt or missing session file — start fresh silently

    def _on_close(self):
        try:
            os.makedirs(os.path.dirname(self._SESSION_FILE), exist_ok=True)
            session = self._settings_dict()
            session["wifi_pass"] = ""  # never persist WiFi password without explicit consent
            with open(self._SESSION_FILE, "w") as f:
                json.dump(session, f, indent=2)
        except OSError:
            pass
        self.destroy()


if __name__ == "__main__":
    app = QRBuilderApp()
    app.mainloop()
