import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# -------- Parsers --------
HEADER_RE = re.compile(r"\{\s*(\d+)\s*;\s*(\d+)\s*\}")
POINT_RE = re.compile(
    r"^\s*\d+\.\s*\{\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*\}\s*$"
)

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def fmt_float(v, ndp=3):
    s = f"{v:.{ndp}f}"
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"

def fmt_feed(v):
    """Feedrate: DO NOT scale. Output as integer mm/min."""
    try:
        return str(int(round(float(v))))
    except Exception:
        return "0"

def parse_curves(text: str):
    """
    Returns list[(curve_id, [(x,y,z), ...])]
    curve_id like "0;0"
    """
    curves = []
    current_id = None
    current_pts = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = HEADER_RE.search(line)
        if m:
            if current_id is not None and current_pts:
                curves.append((current_id, current_pts))
            current_id = f"{m.group(1)};{m.group(2)}"
            current_pts = []
            continue

        pm = POINT_RE.match(line)
        if pm:
            x = float(pm.group(1))
            y = float(pm.group(2))
            z = float(pm.group(3))
            if current_id is None:
                current_id = "0;0"
            current_pts.append((x, y, z))

    if current_id is not None and current_pts:
        curves.append((current_id, current_pts))

    return curves

# -------- Bounds / Transform --------
def analyze_bounds(curves, cfg):
    """
    raw: before transform
    pre: after xy_scale + user offset, before auto_origin shift
    post: after auto_origin shift
    shift: (shiftx, shifty)
    """
    xs, ys = [], []
    for _, pts in curves:
        for x, y, _ in pts:
            xs.append(x); ys.append(y)
    raw = (min(xs), max(xs), min(ys), max(ys))

    xs2, ys2 = [], []
    for _, pts in curves:
        for x, y, _ in pts:
            X = x * cfg["xy_scale"] + cfg["x_off"]
            Y = y * cfg["xy_scale"] + cfg["y_off"]
            xs2.append(X); ys2.append(Y)
    pre = (min(xs2), max(xs2), min(ys2), max(ys2))

    shiftx = -pre[0] if cfg["auto_origin_min"] else 0.0
    shifty = -pre[2] if cfg["auto_origin_min"] else 0.0

    xs3 = [v + shiftx for v in xs2]
    ys3 = [v + shifty for v in ys2]
    post = (min(xs3), max(xs3), min(ys3), max(ys3))

    return {"raw": raw, "pre": pre, "post": post, "shift": (shiftx, shifty)}

# -------- G-code generation --------
def generate_gcode(curves, cfg, bounds_info=None):
    ndp = cfg["ndp"]
    shiftx = 0.0
    shifty = 0.0
    if bounds_info is not None:
        shiftx, shifty = bounds_info["shift"]

    def tx(x): return x * cfg["xy_scale"] + cfg["x_off"] + shiftx
    def ty(y): return y * cfg["xy_scale"] + cfg["y_off"] + shifty
    def tz(z):
        Z = z * cfg["z_scale"] + cfg["z_off"]
        return clamp(Z, cfg["z_min"], cfg["z_max"])

    lines = []
    lines.append("G21")  # mm
    lines.append("G90")  # absolute
    lines.append("; NOTE: Feedrate F is mm/min. No scaling is applied.")
    lines.append(f"F{fmt_feed(cfg['f_write'])}")
    lines.append(f"G0 Z{fmt_float(cfg['z_up'], ndp)}")

    for cid, pts in curves:
        if not pts:
            continue

        x0, y0, z0 = tx(pts[0][0]), ty(pts[0][1]), tz(pts[0][2])

        lines.append(f"; --- curve {{{cid}}} ---")
        # Pen up then rapid to start
        lines.append(f"G0 Z{fmt_float(cfg['z_up'], ndp)}")
        lines.append(f"G0 X{fmt_float(x0, ndp)} Y{fmt_float(y0, ndp)} F{fmt_feed(cfg['f_rapid_xy'])}")
        if cfg["dwell_s"] > 0:
            lines.append(f"G4 P{fmt_float(cfg['dwell_s'], 3)}")

        # Pen down to first Z
        lines.append(f"G1 Z{fmt_float(z0, ndp)} F{fmt_feed(cfg['f_z'])}")
        if cfg["dwell_s"] > 0:
            lines.append(f"G4 P{fmt_float(cfg['dwell_s'], 3)}")

        lastX, lastY, lastZ = x0, y0, z0

        for (x, y, z) in pts[1:]:
            X, Y, Z = tx(x), ty(y), tz(z)

            if cfg["skip_repeated_points"]:
                same_xy = (abs(X - lastX) < 1e-9 and abs(Y - lastY) < 1e-9)
                same_z = (abs(Z - lastZ) < 1e-9)
                if same_xy and (not cfg["emit_z_each_point"] or same_z):
                    continue

            if cfg["emit_z_each_point"]:
                lines.append(
                    f"G1 X{fmt_float(X, ndp)} Y{fmt_float(Y, ndp)} Z{fmt_float(Z, ndp)} F{fmt_feed(cfg['f_write'])}"
                )
            else:
                lines.append(
                    f"G1 X{fmt_float(X, ndp)} Y{fmt_float(Y, ndp)} F{fmt_feed(cfg['f_write'])}"
                )

            lastX, lastY, lastZ = X, Y, Z

        # Pen up after curve
        lines.append(f"G0 Z{fmt_float(cfg['z_up'], ndp)}")

    if cfg["go_home"]:
        lines.append("G0 X0 Y0")

    return "\n".join(lines) + "\n"

# -------- GUI --------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("坐标文本 → G-code（Z=0抬笔，Z=10落笔）")
        self.geometry("1280x780")
        self._last_gcode = ""
        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self, padding=8)
        main.pack(fill="both", expand=True)

        ctrl = ttk.LabelFrame(main, text="参数 / 导出 / 范围分析")
        ctrl.pack(fill="x", pady=(0, 8))

        def add_entry(row, col, label, var, w=12):
            ttk.Label(ctrl, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=4)
            e = ttk.Entry(ctrl, textvariable=var, width=w)
            e.grid(row=row, column=col + 1, sticky="w", padx=6, pady=4)
            return e

        # Vars
        self.xy_scale = tk.DoubleVar(value=1.0)
        self.x_off = tk.DoubleVar(value=0.0)
        self.y_off = tk.DoubleVar(value=0.0)

        self.z_scale = tk.DoubleVar(value=1.0)
        self.z_off = tk.DoubleVar(value=0.0)
        self.z_up = tk.DoubleVar(value=0.0)  # 0 = pen up (you confirmed)
        self.z_min = tk.DoubleVar(value=0.0)
        self.z_max = tk.DoubleVar(value=10.0)

        self.f_rapid_xy = tk.DoubleVar(value=2500)
        self.f_write = tk.DoubleVar(value=1500)  # default 1500 mm/min
        self.f_z = tk.DoubleVar(value=8000)

        self.dwell_s = tk.DoubleVar(value=0.2)
        self.ndp = tk.IntVar(value=3)

        self.emit_z_each_point = tk.BooleanVar(value=True)
        self.skip_repeated = tk.BooleanVar(value=True)
        self.go_home = tk.BooleanVar(value=True)
        self.auto_origin_min = tk.BooleanVar(value=True)

        # Layout
        add_entry(0, 0, "XY缩放", self.xy_scale)
        add_entry(1, 0, "X偏移", self.x_off)
        add_entry(2, 0, "Y偏移", self.y_off)

        add_entry(0, 2, "Z缩放", self.z_scale)
        add_entry(1, 2, "Z偏移", self.z_off)
        add_entry(2, 2, "抬笔Z（上）", self.z_up)

        add_entry(0, 4, "F快速XY(mm/min)", self.f_rapid_xy)
        add_entry(1, 4, "F书写(mm/min)", self.f_write)
        add_entry(2, 4, "F上下笔Z(mm/min)", self.f_z)

        add_entry(0, 6, "停顿G4(s)", self.dwell_s)
        add_entry(1, 6, "Z最小", self.z_min)
        add_entry(2, 6, "Z最大", self.z_max)
        add_entry(3, 6, "小数位", self.ndp, w=6)

        ttk.Checkbutton(ctrl, text="每个点输出Z（笔压随z变化）", variable=self.emit_z_each_point)\
            .grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(ctrl, text="跳过重复点", variable=self.skip_repeated)\
            .grid(row=3, column=2, columnspan=2, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(ctrl, text="结束回到(0,0)", variable=self.go_home)\
            .grid(row=3, column=4, columnspan=2, sticky="w", padx=6, pady=4)

        ttk.Checkbutton(
            ctrl,
            text="自动将X/Y最小值作为原点（防止负坐标撞限位）",
            variable=self.auto_origin_min
        ).grid(row=4, column=0, columnspan=7, sticky="w", padx=6, pady=4)

        # Buttons
        btns = ttk.Frame(ctrl)
        btns.grid(row=0, column=8, rowspan=5, sticky="ns", padx=8)
        ttk.Button(btns, text="转换 →", command=self.on_convert).pack(fill="x", pady=4)
        ttk.Button(btns, text="导出G-code…", command=self.export_gcode).pack(fill="x", pady=4)
        ttk.Button(btns, text="清空输入", command=lambda: self.in_text.delete("1.0", "end")).pack(fill="x", pady=4)
        ttk.Button(btns, text="清空输出", command=lambda: self.out_text.delete("1.0", "end")).pack(fill="x", pady=4)
        ttk.Button(btns, text="复制输出", command=self.copy_output).pack(fill="x", pady=4)

        # Range info
        self.range_var = tk.StringVar(value="范围：—")
        ttk.Label(ctrl, textvariable=self.range_var).grid(row=5, column=0, columnspan=9, sticky="w", padx=6, pady=(2, 6))

        # Text areas
        pane = ttk.PanedWindow(main, orient="horizontal")
        pane.pack(fill="both", expand=True)

        left = ttk.Labelframe(pane, text="输入：坐标文本")
        right = ttk.Labelframe(pane, text="输出：G-code")

        pane.add(left, weight=1)
        pane.add(right, weight=1)

        self.in_text = tk.Text(left, wrap="none")
        self.out_text = tk.Text(right, wrap="none")

        in_scroll_y = ttk.Scrollbar(left, orient="vertical", command=self.in_text.yview)
        out_scroll_y = ttk.Scrollbar(right, orient="vertical", command=self.out_text.yview)

        self.in_text.configure(yscrollcommand=in_scroll_y.set)
        self.out_text.configure(yscrollcommand=out_scroll_y.set)

        self.in_text.pack(side="left", fill="both", expand=True)
        in_scroll_y.pack(side="right", fill="y")

        self.out_text.pack(side="left", fill="both", expand=True)
        out_scroll_y.pack(side="right", fill="y")

        # Insert minimal sample
        self.in_text.insert(
            "1.0",
            "{0;0}\n"
            "0. {295.555556, 0, 9.882353}\n"
            "1. {295.555556, 1.744186, 10}\n"
            "2. {295.555556, 3.488372, 4.627451}\n"
            "\n"
            "{0;1}\n"
            "0. {301.111111, 0, 9.921569}\n"
            "1. {301.111111, 1.744186, 9.803922}\n"
        )

    def cfg(self):
        return {
            "xy_scale": float(self.xy_scale.get()),
            "x_off": float(self.x_off.get()),
            "y_off": float(self.y_off.get()),
            "z_scale": float(self.z_scale.get()),
            "z_off": float(self.z_off.get()),
            "z_up": float(self.z_up.get()),
            "z_min": float(self.z_min.get()),
            "z_max": float(self.z_max.get()),
            "f_rapid_xy": float(self.f_rapid_xy.get()),
            "f_write": float(self.f_write.get()),
            "f_z": float(self.f_z.get()),
            "dwell_s": float(self.dwell_s.get()),
            "ndp": int(self.ndp.get()),
            "emit_z_each_point": bool(self.emit_z_each_point.get()),
            "skip_repeated_points": bool(self.skip_repeated.get()),
            "go_home": bool(self.go_home.get()),
            "auto_origin_min": bool(self.auto_origin_min.get()),
        }

    def on_convert(self):
        src = self.in_text.get("1.0", "end")
        try:
            curves = parse_curves(src)
            if not curves:
                messagebox.showwarning("未解析到曲线", "没有找到形如 {0;N} 的分组或点行：0. {x, y, z}")
                return

            cfg = self.cfg()
            bounds = analyze_bounds(curves, cfg)
            gcode = generate_gcode(curves, cfg, bounds_info=bounds)

            raw = bounds["raw"]
            pre = bounds["pre"]
            post = bounds["post"]
            shiftx, shifty = bounds["shift"]

            self.range_var.set(
                "范围(原始): X[{:.3f},{:.3f}] Y[{:.3f},{:.3f}]   | "
                "变换前(缩放+偏移): X[{:.3f},{:.3f}] Y[{:.3f},{:.3f}]   | "
                "自动原点平移: dX={:.3f}, dY={:.3f}   | "
                "最终: X[{:.3f},{:.3f}] Y[{:.3f},{:.3f}]"
                .format(raw[0], raw[1], raw[2], raw[3],
                        pre[0], pre[1], pre[2], pre[3],
                        shiftx, shifty,
                        post[0], post[1], post[2], post[3])
            )

        except Exception as e:
            messagebox.showerror("转换失败", str(e))
            return

        self.out_text.delete("1.0", "end")
        self.out_text.insert("1.0", gcode)
        self._last_gcode = gcode

    def export_gcode(self):
        if not self._last_gcode.strip():
            self.on_convert()
            if not self._last_gcode.strip():
                return

        path = filedialog.asksaveasfilename(
            title="保存 G-code",
            defaultextension=".gcode",
            filetypes=[("G-code", "*.gcode *.nc *.txt"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._last_gcode)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return

        messagebox.showinfo("已保存", f"已保存到：\n{path}")

    def copy_output(self):
        text = self.out_text.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        messagebox.showinfo("已复制", "输出G-code已复制到剪贴板。")

if __name__ == "__main__":
    App().mainloop()