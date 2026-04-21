"""
Biker Fall Detection Monitor  v2
Requires : pip install pyserial matplotlib
Optional  : pip install twilio      (for real SMS alerts)
"""

import tkinter as tk
from tkinter import ttk
import serial
import serial.tools.list_ports
import threading
import time
import math
import json
import urllib.request
import datetime
from collections import deque

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ── Optional Twilio SMS ────────────────────────────────────────────
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

# ── Twilio credentials  (leave blank to use demo-only mode) ───────
TWILIO_SID   = ""   # "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_TOKEN = ""   # your auth token
TWILIO_FROM  = ""   # "+1XXXXXXXXXX"

# ── Config ────────────────────────────────────────────────────────
BAUD_RATE        = 115200
HISTORY_LEN      = 300
PLOT_LEN         = 150       # ~7.5 s at 20 Hz
UPDATE_MS        = 60
GAS_THRESHOLD    = 400       # must match Arduino define
FALL_ALERT_DELAY = 10        # seconds before auto-alert fires

# ── Colour tokens ─────────────────────────────────────────────────
BG_ROOT  = '#0f1117'
BG_PANEL = '#1a1f2e'
BG_CARD  = '#212840'
BG_PLOT  = '#0d1018'
FG_DIM   = '#4a5568'
FG_MID   = '#7a8aaa'
FG_MAIN  = '#c8d6f0'
FG_WHITE = '#eef3ff'
GREEN    = '#3dffa0'
ORANGE   = '#ffaa33'
RED      = '#ff4455'
BLUE     = '#4da6ff'
YELLOW   = '#ffee55'

STATE_CLR = {'NORMAL': GREEN, 'FREEFALL': ORANGE, 'IMPACT': '#ff7700', 'FALLEN': RED}

FONT_LABEL = ('Menlo', 11)
FONT_VAL   = ('Menlo', 15, 'bold')
FONT_HEAD  = ('Menlo', 10, 'bold')
FONT_TITLE = ('Menlo', 12, 'bold')
FONT_MEGA  = ('Menlo', 17, 'bold')
FONT_BTN   = ('Menlo', 12, 'bold')

# ── Shared state ──────────────────────────────────────────────────
_lock = threading.Lock()
_data = {
    'ax': deque([0.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'ay': deque([0.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'az': deque([1.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'gx': deque([0.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'gy': deque([0.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'gz': deque([0.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'pitch':    deque([0.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'roll':     deque([0.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'accelMag': deque([1.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'gyroMag':  deque([0.0]*HISTORY_LEN, maxlen=HISTORY_LEN),
    'fall':     deque([0]*HISTORY_LEN,   maxlen=HISTORY_LEN),
    'gas':      deque([0]*HISTORY_LEN,   maxlen=HISTORY_LEN),
    'helmet':   deque([0]*HISTORY_LEN,   maxlen=HISTORY_LEN),
    'tilt':  'Level',
    'dist':  0,
    'state': 'NORMAL',
}

_ser     = None
_running = False


def _parse_line(line: str):
    parts = line.split(',')
    if len(parts) < 16:
        return
    try:
        ax, ay, az        = float(parts[0]),  float(parts[1]),  float(parts[2])
        gx, gy, gz        = float(parts[3]),  float(parts[4]),  float(parts[5])
        pitch, roll       = float(parts[6]),  float(parts[7])
        accelMag, gyroMag = float(parts[8]),  float(parts[9])
        fall   = int(parts[10])
        tilt   = parts[11].strip()
        dist   = int(parts[12])
        state  = parts[13].strip()
        gas    = int(parts[14])
        helmet = int(parts[15])
    except (ValueError, IndexError):
        return

    with _lock:
        _data['ax'].append(ax);   _data['ay'].append(ay);   _data['az'].append(az)
        _data['gx'].append(gx);   _data['gy'].append(gy);   _data['gz'].append(gz)
        _data['pitch'].append(pitch);    _data['roll'].append(roll)
        _data['accelMag'].append(accelMag); _data['gyroMag'].append(gyroMag)
        _data['fall'].append(fall);  _data['gas'].append(gas)
        _data['helmet'].append(helmet)
        _data['tilt']  = tilt
        _data['dist']  = dist
        _data['state'] = state


def _reader_thread():
    global _ser, _running
    while _running:
        try:
            if _ser and _ser.is_open:
                line = _ser.readline().decode('utf-8', errors='ignore').strip()
                if line and line != 'READY':
                    _parse_line(line)
        except Exception:
            pass
        time.sleep(0.001)


def get_location() -> str:
    try:
        with urllib.request.urlopen('https://ipapi.co/json/', timeout=5) as r:
            d = json.loads(r.read())
            return (f"{d.get('city','?')}, {d.get('region','?')}  "
                    f"({d.get('latitude','?')}, {d.get('longitude','?')})")
    except Exception:
        return 'Location unavailable'


def send_twilio_sms(phone: str, message: str) -> bool:
    if not (TWILIO_AVAILABLE and TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        return False
    try:
        c = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        c.messages.create(body=message, from_=TWILIO_FROM, to=phone)
        return True
    except Exception:
        return False


# ── Countdown dialog ──────────────────────────────────────────────
class CountdownDialog(tk.Toplevel):
    def __init__(self, parent, seconds: int, on_send, on_cancel):
        super().__init__(parent)
        self.title('EMERGENCY ALERT')
        self.configure(bg='#180000')
        self.resizable(False, False)
        self.grab_set()
        self.lift()

        self._remaining  = seconds
        self._on_send    = on_send
        self._on_cancel  = on_cancel
        self._cancelled  = False

        tk.Label(self, text='FALL DETECTED', font=('Menlo', 18, 'bold'),
                 bg='#180000', fg=RED).pack(pady=(22, 4))
        tk.Label(self, text='Sending emergency alert in:', font=FONT_LABEL,
                 bg='#180000', fg=FG_MAIN).pack()

        self._cnt = tk.Label(self, text=str(seconds),
                              font=('Menlo', 60, 'bold'),
                              bg='#180000', fg=RED)
        self._cnt.pack(pady=8)

        tk.Label(self, text='Press cancel if you are OK.',
                 font=('Menlo', 10), bg='#180000', fg=FG_DIM).pack()

        _btn(self, text='CANCEL  —  I AM OK', command=self._cancel,
             bg='#223344', font=FONT_BTN, pady=12)

        self._tick()

    def _tick(self):
        if self._cancelled:
            return
        if self._remaining <= 0:
            self.destroy()
            self._on_send()
            return
        self._cnt.config(text=str(self._remaining))
        self._remaining -= 1
        self.after(1000, self._tick)

    def _cancel(self):
        self._cancelled = True
        self.destroy()
        self._on_cancel()


# ── Label-based button (macOS tk.Button ignores bg/fg) ────────────
def _btn(parent, text, command, bg, fg=FG_WHITE, font=FONT_BTN,
         pady=8, padx=0, fill_pack=True, side=None):
    """Returns a styled Frame+Label that acts as a button.
    Works reliably on macOS where tk.Button overrides colours."""
    hover = _lighten(bg)
    f = tk.Frame(parent, bg=bg, cursor='hand2')
    lbl = tk.Label(f, text=text, bg=bg, fg=fg, font=font,
                   pady=pady, padx=padx + 10)
    lbl.pack(fill='x', padx=1, pady=1)

    def _on_click(e):
        command()
    def _on_enter(e):
        lbl.config(bg=hover); f.config(bg=hover)
    def _on_leave(e):
        lbl.config(bg=bg); f.config(bg=bg)

    for w in (f, lbl):
        w.bind('<Button-1>', _on_click)
        w.bind('<Enter>',    _on_enter)
        w.bind('<Leave>',    _on_leave)

    if fill_pack:
        f.pack(fill='x', pady=3)
    elif side:
        f.pack(side=side, padx=padx)
    return f, lbl


def _lighten(hex_color: str) -> str:
    """Returns a slightly lighter version of a hex colour for hover."""
    hex_color = hex_color.lstrip('#')
    r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    r = min(r + 30, 255); g = min(g + 30, 255); b = min(b + 30, 255)
    return f'#{r:02x}{g:02x}{b:02x}'


# ── Main GUI ──────────────────────────────────────────────────────
class FallDetectionGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Biker Fall Detection Monitor')
        self.root.configure(bg=BG_ROOT)
        self.root.geometry('1280x860')
        self.root.minsize(1100, 720)

        self._fall_first_seen = None
        self._alert_sent      = False
        self._countdown_open  = False
        self._blink_on        = False

        # Fire / gas tracking (independent of fall)
        self._fire_active      = False   # gas currently above threshold
        self._fire_alert_sent  = False   # fire alert already dispatched
        self._fall_then_fire   = False   # fire detected after a fall

        self._build_ui()
        self._refresh_ports()
        self._update_gui()

    # ── Top bar ───────────────────────────────────────────────────
    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=BG_CARD, pady=7)
        bar.pack(fill='x', padx=6, pady=(6, 0))

        tk.Label(bar, text='PORT:', bg=BG_CARD, fg=FG_MID,
                 font=FONT_HEAD).pack(side='left', padx=(12, 4))

        self._port_var = tk.StringVar()
        self._port_cb  = ttk.Combobox(bar, textvariable=self._port_var,
                                       width=18, state='readonly')
        self._port_cb.pack(side='left', padx=4)

        _btn(bar, text='Refresh', command=self._refresh_ports,
             bg='#1e2a44', fg=FG_MAIN, font=('Menlo', 9),
             pady=4, padx=2, fill_pack=False, side='left')

        self._conn_frame, self._conn_lbl_btn = _btn(
            bar, text='Connect', command=self._toggle_connection,
            bg='#0a5530', font=FONT_BTN, pady=5, padx=4,
            fill_pack=False, side='left')

        self._conn_status = tk.Label(bar, text='Disconnected',
                                      bg=BG_CARD, fg=RED, font=FONT_HEAD)
        self._conn_status.pack(side='left', padx=8)

        self._state_lbl = tk.Label(bar, text='NORMAL',
                                    bg=BG_CARD, fg=GREEN, font=FONT_MEGA)
        self._state_lbl.pack(side='right', padx=14)
        tk.Label(bar, text='STATE:', bg=BG_CARD, fg=FG_MID,
                 font=FONT_HEAD).pack(side='right')

    # ── Full UI ───────────────────────────────────────────────────
    def _build_ui(self):
        self._build_topbar()

        self._helmet_banner = tk.Label(
            self.root,
            text='PUT ON YOUR HELMET  —  Protection features disabled',
            font=FONT_TITLE, bg='#2a1200', fg=ORANGE, pady=8)
        self._helmet_banner.pack(fill='x', padx=6, pady=(3, 0))

        body = tk.Frame(self.root, bg=BG_ROOT)
        body.pack(fill='both', expand=True, padx=6, pady=4)
        body.columnconfigure(0, weight=0, minsize=305)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left  = tk.Frame(body, bg=BG_PANEL)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        right = tk.Frame(body, bg=BG_ROOT)
        right.grid(row=0, column=1, sticky='nsew')

        self._build_bubble(left)
        self._build_stats(left)
        self._build_gas_bar(left)
        self._build_controls(left)
        self._build_emergency(left)
        self._build_graphs(right)

        self._fall_banner = tk.Label(self.root, text='', font=FONT_MEGA,
                                      bg=BG_ROOT, fg=BG_ROOT, pady=7)
        self._fall_banner.pack(fill='x', padx=6, pady=(2, 0))

        self._fire_banner = tk.Label(self.root, text='', font=FONT_TITLE,
                                      bg=BG_ROOT, fg=BG_ROOT, pady=6)
        self._fire_banner.pack(fill='x', padx=6, pady=(0, 6))

    # ── Bubble indicator ──────────────────────────────────────────
    def _build_bubble(self, parent):
        tk.Label(parent, text='TILT INDICATOR', bg=BG_PANEL,
                 fg=FG_MID, font=FONT_HEAD).pack(pady=(10, 2))
        self._bubble_cv = tk.Canvas(parent, width=260, height=260,
                                     bg=BG_PLOT, highlightthickness=1,
                                     highlightbackground='#2a3a5a')
        self._bubble_cv.pack(padx=10, pady=2)
        self._draw_bubble_static()
        self._tilt_lbl = tk.Label(parent, text='Level', bg=BG_PANEL,
                                   fg=GREEN, font=FONT_MEGA)
        self._tilt_lbl.pack(pady=(2, 6))

    def _draw_bubble_static(self):
        cx, cy, R = 130, 130, 110
        c = self._bubble_cv
        c.create_oval(cx-R, cy-R, cx+R, cy+R, outline='#2a4060', width=2)
        for r, col, lbl in [(int(R*.52), '#664400', '30'), (int(R*.88), '#660000', '55')]:
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=col, width=1, dash=(5, 4))
            c.create_text(cx+r+6, cy-8, text=f'{lbl}', fill=col, font=('Menlo', 7))
        c.create_line(cx-R+4, cy, cx+R-4, cy, fill='#1c2e40', width=1)
        c.create_line(cx, cy-R+4, cx, cy+R-4, fill='#1c2e40', width=1)
        for txt, x, y in [('FWD', cx, cy-R-13), ('BCK', cx, cy+R+14),
                           ('L',  cx-R-14, cy), ('R',  cx+R+14, cy)]:
            c.create_text(x, y, text=txt, fill=FG_DIM, font=('Menlo', 8, 'bold'))

    def _update_bubble(self, pitch, roll, active):
        cx, cy, R = 130, 130, 110
        c = self._bubble_cv
        c.delete('dyn')
        if not active:
            c.create_text(cx, cy, text='NO HELMET', fill='#886633',
                          font=('Menlo', 14, 'bold'), tags='dyn')
            return
        limit = R - 16
        px =  roll  / 90.0 * R
        py = -pitch / 90.0 * R
        d  = math.sqrt(px*px + py*py)
        if d > limit:
            px *= limit / d;  py *= limit / d
        bx, by = cx + px, cy + py
        mag = math.sqrt(pitch**2 + roll**2)
        col = GREEN if mag < 30 else ORANGE if mag < 55 else RED
        c.create_line(cx, cy, bx, by, fill=col, width=1, tags='dyn')
        c.create_oval(cx-4, cy-4, cx+4, cy+4, fill=FG_DIM, outline='', tags='dyn')
        c.create_oval(bx-14, by-14, bx+14, by+14,
                      fill=col, outline=FG_WHITE, width=1, tags='dyn')

    # ── Stats ─────────────────────────────────────────────────────
    def _build_stats(self, parent):
        tk.Frame(parent, bg='#2a3a5a', height=1).pack(fill='x', padx=10, pady=4)
        frame = tk.Frame(parent, bg=BG_PANEL)
        frame.pack(fill='x', padx=14)

        for label, attr, default in [
            ('Pitch',    'v_pitch', '+0.0°'),
            ('Roll',     'v_roll',  '+0.0°'),
            ('Accel',    'v_accel', '0.000 g'),
            ('Gyro',     'v_gyro',  '0.0 dps'),
            ('Distance', 'v_dist',  '0 mm'),
        ]:
            row = tk.Frame(frame, bg=BG_PANEL)
            row.pack(fill='x', pady=3)
            tk.Label(row, text=label, bg=BG_PANEL, fg=FG_MID,
                     font=FONT_LABEL, width=9, anchor='w').pack(side='left')
            v = tk.Label(row, text=default, bg=BG_PANEL, fg=FG_WHITE,
                         font=FONT_VAL, anchor='w')
            v.pack(side='left')
            setattr(self, attr, v)

    # ── Gas bar ───────────────────────────────────────────────────
    def _build_gas_bar(self, parent):
        tk.Frame(parent, bg='#2a3a5a', height=1).pack(fill='x', padx=10, pady=4)
        frame = tk.Frame(parent, bg=BG_PANEL)
        frame.pack(fill='x', padx=14, pady=(0, 2))

        hdr = tk.Frame(frame, bg=BG_PANEL)
        hdr.pack(fill='x')
        tk.Label(hdr, text='Gas / Smoke', bg=BG_PANEL, fg=FG_MID,
                 font=FONT_LABEL).pack(side='left')
        self._gas_val_lbl = tk.Label(hdr, text='0', bg=BG_PANEL,
                                      fg=FG_WHITE, font=FONT_VAL)
        self._gas_val_lbl.pack(side='right')

        self._gas_cv = tk.Canvas(frame, height=20, bg='#111820',
                                  highlightthickness=1,
                                  highlightbackground='#2a3a5a')
        self._gas_cv.pack(fill='x', pady=3)
        self._gas_alert_lbl = tk.Label(frame, text='', bg=BG_PANEL,
                                        fg=RED, font=FONT_HEAD)
        self._gas_alert_lbl.pack()

    def _update_gas_bar(self, value: int):
        self._gas_val_lbl.config(text=str(value))
        self._gas_cv.delete('all')
        w     = self._gas_cv.winfo_width() or 270
        frac  = min(value / 1023.0, 1.0)
        fw    = int(frac * w)
        col   = GREEN if value < GAS_THRESHOLD else (ORANGE if value < 700 else RED)
        if fw > 0:
            self._gas_cv.create_rectangle(0, 0, fw, 20, fill=col, outline='')
        tx = int(GAS_THRESHOLD / 1023.0 * w)
        self._gas_cv.create_line(tx, 0, tx, 20, fill=FG_WHITE, width=1, dash=(3, 3))
        self._gas_alert_lbl.config(
            text='SMOKE / GAS DETECTED' if value > GAS_THRESHOLD else '')

    # ── Controls ──────────────────────────────────────────────────
    def _build_controls(self, parent):
        tk.Frame(parent, bg='#2a3a5a', height=1).pack(fill='x', padx=10, pady=4)
        frame = tk.Frame(parent, bg=BG_PANEL)
        frame.pack(fill='x', padx=10, pady=(0, 2))
        self._trig_frame, self._trig_lbl = _btn(
            frame, text='TRIGGER FALL', command=self._cmd_trigger,
            bg='#7a1200', font=FONT_BTN, pady=8)
        _btn(frame, text='RESET', command=self._cmd_reset,
             bg='#003a66', font=FONT_BTN, pady=8)

    # ── Emergency contacts ────────────────────────────────────────
    def _build_emergency(self, parent):
        tk.Frame(parent, bg='#2a3a5a', height=1).pack(fill='x', padx=10, pady=4)
        frame = tk.Frame(parent, bg=BG_PANEL)
        frame.pack(fill='x', padx=10, pady=(0, 8))

        tk.Label(frame, text='EMERGENCY CONTACTS', bg=BG_PANEL,
                 fg=FG_MID, font=FONT_HEAD).pack(anchor='w', pady=(0, 4))

        self._contacts = []
        for i in range(2):
            row = tk.Frame(frame, bg=BG_PANEL)
            row.pack(fill='x', pady=2)
            tk.Label(row, text=f'#{i+1}', bg=BG_PANEL, fg=FG_DIM,
                     font=FONT_LABEL, width=3).pack(side='left')
            n_var = tk.StringVar(value=f'Contact {i+1}')
            p_var = tk.StringVar(value='+91XXXXXXXXXX')
            tk.Entry(row, textvariable=n_var, bg='#0d1320', fg=FG_WHITE,
                     font=('Menlo', 10), width=11,
                     insertbackground=FG_WHITE,
                     relief='flat').pack(side='left', padx=2)
            tk.Entry(row, textvariable=p_var, bg='#0d1320', fg=FG_MAIN,
                     font=('Menlo', 10), width=14,
                     insertbackground=FG_WHITE,
                     relief='flat').pack(side='left', padx=2)
            self._contacts.append((n_var, p_var))

        _btn(frame, text='Send Alert Now (Manual)',
             command=self._manual_alert,
             bg='#441100', font=('Menlo', 10, 'bold'), pady=6)

        self._notified_lbl = tk.Label(frame, text='', bg=BG_PANEL,
                                       fg=GREEN, font=('Menlo', 9),
                                       wraplength=275, justify='left')
        self._notified_lbl.pack(fill='x')

    # ── Graphs ────────────────────────────────────────────────────
    def _build_graphs(self, parent):
        self._fig = Figure(facecolor=BG_PLOT, figsize=(7, 5))
        self._fig.subplots_adjust(hspace=0.52, left=0.09,
                                   right=0.97, top=0.94, bottom=0.06)
        self._ax_a = self._fig.add_subplot(211)
        self._ax_g = self._fig.add_subplot(212)

        x = list(range(PLOT_LEN)); z = [0.0] * PLOT_LEN

        for ax, title, ylim in [
            (self._ax_a, 'Accelerometer (g)',  (-5, 5)),
            (self._ax_g, 'Gyroscope (deg/s)', (-400, 400)),
        ]:
            ax.set_facecolor(BG_PLOT)
            ax.set_title(title, color=FG_MID, fontsize=10, pad=3, loc='left')
            ax.set_ylim(*ylim); ax.set_xlim(0, PLOT_LEN-1)
            ax.tick_params(colors=FG_DIM, labelsize=8)
            for sp in ax.spines.values(): sp.set_color('#1e2e40')
            ax.grid(True, color='#141f2e', linewidth=0.5, linestyle='--')
            ax.axhline(0, color='#202e3e', lw=0.7)

        self._la_x, = self._ax_a.plot(x, z, color='#ff5533', lw=1.0, label='X')
        self._la_y, = self._ax_a.plot(x, z, color='#33ff66', lw=1.0, label='Y')
        self._la_z, = self._ax_a.plot(x, z, color=BLUE,      lw=1.0, label='Z')
        self._ax_a.legend(loc='upper right', fontsize=8, facecolor=BG_CARD,
                           labelcolor=FG_WHITE, framealpha=0.7, edgecolor='#334466')

        self._lg_x, = self._ax_g.plot(x, z, color='#ff44cc', lw=1.0, label='X')
        self._lg_y, = self._ax_g.plot(x, z, color='#44ffee', lw=1.0, label='Y')
        self._lg_z, = self._ax_g.plot(x, z, color=YELLOW,    lw=1.0, label='Z')
        self._ax_g.legend(loc='upper right', fontsize=8, facecolor=BG_CARD,
                           labelcolor=FG_WHITE, framealpha=0.7, edgecolor='#334466')

        canvas = FigureCanvasTkAgg(self._fig, master=parent)
        canvas.get_tk_widget().pack(fill='both', expand=True)
        self._fig_canvas = canvas

    # ── Periodic update ───────────────────────────────────────────
    def _update_gui(self):
        with _lock:
            pitch    = list(_data['pitch'])[-1]
            roll     = list(_data['roll'])[-1]
            accel    = list(_data['accelMag'])[-1]
            gyro     = list(_data['gyroMag'])[-1]
            fall     = list(_data['fall'])[-1]
            gas      = list(_data['gas'])[-1]
            helmet   = list(_data['helmet'])[-1]
            dist     = _data['dist']
            tilt     = _data['tilt']
            state    = _data['state']
            ax_h = list(_data['ax'])[-PLOT_LEN:]
            ay_h = list(_data['ay'])[-PLOT_LEN:]
            az_h = list(_data['az'])[-PLOT_LEN:]
            gx_h = list(_data['gx'])[-PLOT_LEN:]
            gy_h = list(_data['gy'])[-PLOT_LEN:]
            gz_h = list(_data['gz'])[-PLOT_LEN:]

        helmeted = bool(helmet)

        # Helmet banner
        if helmeted:
            self._helmet_banner.config(text='', bg=BG_ROOT, fg=BG_ROOT)
        else:
            self._helmet_banner.config(
                text='PUT ON YOUR HELMET  —  Protection features disabled',
                bg='#2a1200', fg=ORANGE)

        # Bubble
        self._update_bubble(pitch, roll, helmeted)
        mag = math.sqrt(pitch**2 + roll**2)
        tc  = GREEN if mag < 30 else ORANGE if mag < 55 else RED
        self._tilt_lbl.config(
            text=tilt if helmeted else '—',
            fg=tc if helmeted else FG_DIM)

        # Stats
        def col(v, w, c): return GREEN if abs(v) < w else ORANGE if abs(v) < c else RED
        if helmeted:
            self.v_pitch.config(text=f'{pitch:+.1f}°',  fg=col(pitch, 30, 55))
            self.v_roll.config( text=f'{roll:+.1f}°',   fg=col(roll,  30, 55))
            self.v_accel.config(text=f'{accel:.3f} g',  fg=FG_WHITE)
            self.v_gyro.config( text=f'{gyro:.1f} dps', fg=FG_WHITE)
        else:
            for lbl in (self.v_pitch, self.v_roll, self.v_accel, self.v_gyro):
                lbl.config(text='—', fg=FG_DIM)
        self.v_dist.config(text=f'{dist} mm',
                            fg=GREEN if helmeted else ORANGE)

        # Gas
        self._update_gas_bar(gas)

        # State badge
        disp  = state if helmeted else 'NO HELMET'
        sc    = STATE_CLR.get(state, FG_MID) if helmeted else ORANGE
        self._state_lbl.config(text=disp, fg=sc)

        # Trigger button — enable/disable by swapping colour and click binding
        trig_bg = '#7a1200' if helmeted else '#2a2a2a'
        trig_fg = FG_WHITE  if helmeted else FG_DIM
        self._trig_frame.config(bg=trig_bg)
        self._trig_lbl.config(bg=trig_bg, fg=trig_fg)
        for w in (self._trig_frame, self._trig_lbl):
            w.unbind('<Button-1>')
            if helmeted:
                w.bind('<Button-1>', lambda e: self._cmd_trigger())

        # ── Fire / gas banner (independent of fall) ─────────────────
        gas_active = (gas > GAS_THRESHOLD)
        self._fire_active = gas_active

        if gas_active:
            # If a fall was already detected, flag the combined scenario
            if fall:
                self._fall_then_fire = True

            if not self._fire_alert_sent:
                self._fire_alert_sent = True
                threading.Thread(target=self._send_fire_alert,
                                 args=(bool(fall),), daemon=True).start()

            if self._fall_then_fire or fall:
                fire_text = ('FIRE + CRASH DETECTED  —  Emergency services & fire dept notified')
                fire_bg, fire_fg = '#660033', '#ff88cc'
            else:
                fire_text = ('FIRE / GAS DETECTED  —  Informing emergency services  |  Contacting fire dept')
                fire_bg, fire_fg = '#5a2a00', ORANGE

            self._fire_banner.config(text=fire_text, bg=fire_bg, fg=fire_fg)
        else:
            self._fire_banner.config(text='', bg=BG_ROOT, fg=BG_ROOT)
            if not gas_active:
                self._fire_alert_sent = False
                self._fall_then_fire  = False

        # ── Fall banner + auto-alert ──────────────────────────────
        # fall stays true even if helmet is off (Arduino now holds FALLEN state)
        if fall:
            self._blink_on = not self._blink_on
            bg_c = '#aa0000' if self._blink_on else '#660000'
            fg_c = FG_WHITE  if self._blink_on else '#ff8888'

            if self._fall_then_fire or gas_active:
                banner_text = '  FALL + FIRE  —  RIDER DOWN  |  FIRE DETECTED  '
            else:
                banner_text = '  FALL DETECTED  —  RIDER DOWN  '

            self._fall_banner.config(text=banner_text, bg=bg_c, fg=fg_c)

            if not self._alert_sent and not self._countdown_open:
                if self._fall_first_seen is None:
                    self._fall_first_seen = time.time()
                elif time.time() - self._fall_first_seen >= 2.0:
                    self._launch_countdown()
        else:
            self._blink_on = False
            self._fall_banner.config(text='', bg=BG_ROOT, fg=BG_ROOT)
            if not fall:
                self._fall_first_seen = None
                self._alert_sent      = False

        # Graphs
        x = list(range(PLOT_LEN))
        self._la_x.set_data(x, ax_h); self._la_y.set_data(x, ay_h); self._la_z.set_data(x, az_h)
        self._lg_x.set_data(x, gx_h); self._lg_y.set_data(x, gy_h); self._lg_z.set_data(x, gz_h)
        self._fig_canvas.draw_idle()

        self.root.after(UPDATE_MS, self._update_gui)

    # ── Alert system ──────────────────────────────────────────────
    def _launch_countdown(self):
        self._countdown_open = True
        CountdownDialog(self.root, FALL_ALERT_DELAY,
                        on_send=self._fire_alert,
                        on_cancel=self._cancel_alert)

    def _fire_alert(self):
        self._countdown_open = False
        self._alert_sent     = True
        threading.Thread(target=self._send_worker, daemon=True).start()

    def _cancel_alert(self):
        self._countdown_open  = False
        self._fall_first_seen = None
        self._alert_sent      = False

    def _send_worker(self):
        with _lock:
            pitch   = list(_data['pitch'])[-1]
            roll    = list(_data['roll'])[-1]
            accel   = list(_data['accelMag'])[-1]
            gas_val = list(_data['gas'])[-1]

        location   = get_location()
        ts         = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        fire_note  = (f"\nFIRE/GAS ALSO DETECTED — gas reading {gas_val}/1023"
                      if self._fire_active else '')
        msg = (f"EMERGENCY: Rider may have fallen!\n"
               f"Time    : {ts}\n"
               f"Location: {location}\n"
               f"Impact  : {accel:.2f}g\n"
               f"Tilt    : Pitch {pitch:.1f}  Roll {roll:.1f} deg{fire_note}\n"
               f"Please check on them immediately.")

        sent = []
        for name_v, phone_v in self._contacts:
            name  = name_v.get().strip()
            phone = phone_v.get().strip()
            if phone and phone != '+91XXXXXXXXXX':
                ok = send_twilio_sms(phone, msg)
                sent.append(f"{name}  ({'SMS sent' if ok else 'demo — no Twilio'})")
            else:
                sent.append(f"{name}  (demo — fill phone to send SMS)")

        self.root.after(0, lambda: self._show_notified(sent, ts, location))

    def _send_fire_alert(self, also_fallen: bool):
        """Dispatch fire/gas alert to contacts and update the notified label."""
        with _lock:
            gas_val = list(_data['gas'])[-1]

        location = get_location()
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if also_fallen:
            subject = "EMERGENCY: Rider has fallen AND fire/smoke detected!"
            detail  = (f"A crash has been detected and smoke/gas levels are critical.\n"
                       f"Gas reading: {gas_val}/1023\n"
                       f"Both emergency services and fire department have been notified.")
        else:
            subject = "FIRE/GAS ALERT: Smoke or fire detected on rider's helmet!"
            detail  = (f"Smoke or gas detected by helmet sensor.\n"
                       f"Gas reading: {gas_val}/1023\n"
                       f"Emergency services and fire department have been notified.")

        msg = f"{subject}\nTime    : {ts}\nLocation: {location}\n{detail}"

        sent = []
        for name_v, phone_v in self._contacts:
            name  = name_v.get().strip()
            phone = phone_v.get().strip()
            if phone and phone != '+91XXXXXXXXXX':
                ok = send_twilio_sms(phone, msg)
                sent.append(f"{name}  ({'SMS sent' if ok else 'demo — no Twilio'})")
            else:
                sent.append(f"{name}  (demo)")

        self.root.after(0, lambda: self._show_fire_notified(sent, ts, location, also_fallen))

    def _show_fire_notified(self, sent: list, ts: str, location: str, also_fallen: bool):
        prefix = 'FIRE + CRASH ALERT SENT' if also_fallen else 'FIRE ALERT SENT'
        lines  = [prefix, ts, f'Location : {location}',
                  'Contacting : Emergency services + Fire dept', '']
        lines += [f'  {s}' for s in sent]
        self._notified_lbl.config(text='\n'.join(lines), fg=ORANGE)

    def _show_notified(self, sent: list, ts: str, location: str):
        lines = ['EMERGENCY ALERT SENT', ts, f'Location: {location}', '']
        lines += [f'  {s}' for s in sent]
        self._notified_lbl.config(text='\n'.join(lines), fg=GREEN)

    def _manual_alert(self):
        self._alert_sent = False
        threading.Thread(target=self._send_worker, daemon=True).start()

    # ── Serial ────────────────────────────────────────────────────
    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._port_cb['values'] = ports
        if ports and not self._port_var.get():
            self._port_cb.current(0)

    def _toggle_connection(self):
        global _ser, _running
        if _ser and _ser.is_open:
            _running = False
            time.sleep(0.15)
            _ser.close(); _ser = None
            self._conn_lbl_btn.config(text='Connect', bg='#0a5530')
            self._conn_frame.config(bg='#0a5530')
            self._conn_status.config(text='Disconnected', fg=RED)
        else:
            port = self._port_var.get()
            if not port:
                return
            try:
                _ser = serial.Serial(port, BAUD_RATE, timeout=1)
                _running = True
                threading.Thread(target=_reader_thread, daemon=True).start()
                self._conn_lbl_btn.config(text='Disconnect', bg='#770000')
                self._conn_frame.config(bg='#770000')
                self._conn_status.config(text=f'Connected: {port}', fg=GREEN)
            except Exception as e:
                self._conn_status.config(text=f'Error: {e}', fg=ORANGE)

    def _cmd_trigger(self):
        if _ser and _ser.is_open:
            _ser.write(b'F')

    def _cmd_reset(self):
        global _ser
        if _ser and _ser.is_open:
            _ser.write(b'R')
        self._alert_sent      = False
        self._fall_first_seen = None
        self._notified_lbl.config(text='')


# ── Entry point ───────────────────────────────────────────────────
def main():
    root = tk.Tk()
    FallDetectionGUI(root)

    def _on_close():
        global _running, _ser
        _running = False
        if _ser and _ser.is_open:
            _ser.close()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', _on_close)
    root.mainloop()


if __name__ == '__main__':
    main()
