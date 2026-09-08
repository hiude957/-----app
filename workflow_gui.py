# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
CORE_DIR = APP_DIR / "core"
START_MARK = "# ===== Change these values each time ====="
END_MARK = "# ========================================"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str = "text"


@dataclass(frozen=True)
class StepSpec:
    tab: str
    title: str
    description: str
    script: str
    fields: tuple[FieldSpec, ...]


STEPS = (
    StepSpec(
        "第1步",
        "合并 E/CTE 参数和 Mechanical constants",
        "读取多个 fiber-rve 分组文件夹中的 Mechanical_constants.txt，按 E、CTE、nu 顺序合并输出。",
        "01_merge_E_CTE_and_mechanical_constants.py",
        (
            FieldSpec("ROOT_DIR", "总文件夹", "folder"),
            FieldSpec("GROUP_PREFIX", "分组文件夹名前缀"),
            FieldSpec("OUTPUT_FULL_PARAMS", "完整参数输出文件名"),
            FieldSpec("OUTPUT_MECH_ONLY", "仅力学常数输出文件名"),
            FieldSpec("OUTPUT_WITH_PARAMS", "参数+力学常数输出文件名"),
            FieldSpec("OUTPUT_FIBER_BUNDLE_CSV", "同格式 CSV 输出路径", "file"),
        ),
    ),
    StepSpec(
        "第2步",
        "绘制 E/CTE 敏感性图",
        "读取第1步输出表或 CSV，分别绘制固定 E 改变 CTE、固定 CTE 改变 E 的性能曲线。",
        "02_plot_E_CTE_sensitivity.py",
        (
            FieldSpec("CSV_PATH", "输入表格 CSV/TXT", "file"),
            FieldSpec("OUT_DIR", "图片输出文件夹", "folder"),
            FieldSpec("E_COL", "E 列名"),
            FieldSpec("CTE_COL", "CTE 列名"),
        ),
    ),
    StepSpec(
        "第3步",
        "绘制玻纤布 E/resin 分组图",
        "读取玻纤布转换 CSV，分别绘制固定 E 改变 resin、固定 resin 改变 E 的性能曲线。",
        "03_plot_fabric_E_resin_sensitivity.py",
        (
            FieldSpec("CSV_PATH", "玻纤布转换 CSV", "file"),
            FieldSpec("OUT_DIR", "图片输出文件夹", "folder"),
            FieldSpec("E_COL", "E 列名"),
            FieldSpec("RESIN_COL", "resin 列名"),
        ),
    ),
)


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def config_block(path: Path) -> str:
    text = read_text(path)
    start = text.find(START_MARK)
    end = text.find(END_MARK, start + len(START_MARK))
    if start < 0 or end < 0:
        raise ValueError(f"脚本中未找到配置区域：{path.name}")
    return text[start + len(START_MARK) : end].strip()


def parse_config(path: Path) -> dict[str, object]:
    tree = ast.parse("from pathlib import Path\n" + config_block(path))
    result: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "Path":
            result[target.id] = ast.literal_eval(value.args[0])
        else:
            result[target.id] = ast.literal_eval(value)
    return result


def clean_path_input(value: str) -> str:
    text = str(value).strip()
    quote_pairs = (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"))
    changed = True
    while changed and len(text) >= 2:
        changed = False
        for left, right in quote_pairs:
            if text.startswith(left) and text.endswith(right):
                text = text[1:-1].strip()
                changed = True
                break
    return text


def serialize_value(spec: FieldSpec, raw: str) -> str:
    raw = clean_path_input(raw) if spec.kind in {"folder", "file"} else raw.strip()
    if spec.kind in {"folder", "file"}:
        if not raw:
            raise ValueError(f"“{spec.label}”不能为空")
        return f'Path(r"{raw}")'
    try:
        value = ast.literal_eval(raw)
        if isinstance(value, (int, float)):
            return repr(value)
    except (ValueError, SyntaxError):
        pass
    return repr(raw)


def replace_config(path: Path, specs: tuple[FieldSpec, ...], values: dict[str, str]) -> None:
    text = read_text(path)
    start = text.find(START_MARK)
    end = text.find(END_MARK, start + len(START_MARK))
    if start < 0 or end < 0:
        raise ValueError(f"脚本中未找到配置区域：{path.name}")
    lines = [f"{spec.name} = {serialize_value(spec, values[spec.name])}" for spec in specs]
    new_block = "\n\n".join(lines)
    updated = text[: start + len(START_MARK)] + "\n" + new_block + "\n" + text[end:]
    path.write_text(updated, encoding="utf-8", newline="\n")


class StepPage(ttk.Frame):
    def __init__(self, master: ttk.Notebook, spec: StepSpec, app: "PreprocessApp"):
        super().__init__(master, padding=(18, 14))
        self.spec = spec
        self.app = app
        self.script_path = CORE_DIR / spec.script
        self.widgets: dict[str, tk.Widget] = {}
        self.process: subprocess.Popen[str] | None = None
        self.stop_requested = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        heading = ttk.Frame(self)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(heading, text=spec.title, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(heading, text=spec.description, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))

        form = ttk.Frame(self, padding=(16, 14), style="Panel.TFrame")
        form.grid(row=1, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        for row, field in enumerate(spec.fields):
            ttk.Label(form, text=field.label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=8)
            widget = ttk.Entry(form)
            widget.grid(row=row, column=1, sticky="ew", pady=8)
            if field.kind in {"folder", "file"}:
                ttk.Button(form, text="选择", width=9, command=lambda f=field: self.choose_path(f)).grid(
                    row=row, column=2, padx=(10, 0), pady=8
                )
            self.widgets[field.name] = widget

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.run_button = ttk.Button(actions, text="保存并开始运行", style="Primary.TButton", command=self.save_and_run)
        self.run_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="终止运行", style="Danger.TButton", command=self.stop_running, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="仅保存设置", command=self.save).pack(side="left", padx=8)
        ttk.Button(actions, text="重新读取", command=self.load).pack(side="left")
        ttk.Button(actions, text="打开输出位置", command=self.open_output).pack(side="left", padx=8)

        self.load()

    def choose_path(self, spec: FieldSpec) -> None:
        widget = self.widgets[spec.name]
        current = clean_path_input(widget.get())
        initial = current if current and Path(current).exists() else str(APP_DIR)
        if spec.kind == "folder":
            selected = filedialog.askdirectory(title=f"选择{spec.label}", initialdir=initial)
        else:
            selected = filedialog.askopenfilename(title=f"选择{spec.label}", initialdir=str(Path(initial).parent))
        if selected:
            widget.delete(0, "end")
            widget.insert(0, selected)

    def load(self) -> None:
        try:
            config = parse_config(self.script_path)
            for field in self.spec.fields:
                widget = self.widgets[field.name]
                widget.delete(0, "end")
                widget.insert(0, str(config.get(field.name, "")))
            self.app.set_status(f"已读取 {self.spec.tab} 设置")
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))

    def values(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for field in self.spec.fields:
            value = self.widgets[field.name].get()
            result[field.name] = clean_path_input(value) if field.kind in {"folder", "file"} else value
        return result

    def save(self, notify: bool = True) -> bool:
        try:
            replace_config(self.script_path, self.spec.fields, self.values())
            self.app.log(f"[{self.spec.tab}] 设置已保存。\n")
            self.app.set_status("设置已保存")
            if notify:
                messagebox.showinfo("保存完成", f"{self.spec.title} 的设置已保存。")
            return True
        except Exception as exc:
            messagebox.showerror("设置有误", str(exc))
            return False

    def save_and_run(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showwarning("正在运行", "当前步骤尚未运行结束。")
            return
        if not self.save(notify=False):
            return
        self.stop_requested = False
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.app.set_status(f"正在运行：{self.spec.title}")
        threading.Thread(target=self.run_script, daemon=True).start()

    def stop_running(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            self.stop_button.configure(state="disabled")
            self.app.set_status("当前没有正在运行的步骤")
            return
        self.stop_requested = True
        self.stop_button.configure(state="disabled")
        process.terminate()
        self.app.set_status("已请求终止")

    def run_script(self) -> None:
        self.app.log("\n" + "=" * 72 + "\n")
        self.app.log(f"启动：{self.spec.title}\n")
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(self.script_path)],
                cwd=str(CORE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.app.log(line)
            code = self.process.wait()
            self.app.log(f"\n处理结束，返回码：{code}\n")
            self.app.after(0, lambda: self.app.set_status("处理完成" if code == 0 else "处理失败，请查看日志"))
        except Exception as exc:
            self.app.log(f"运行失败：{exc}\n")
            self.app.after(0, lambda: self.app.set_status("运行失败"))
        finally:
            self.process = None
            self.app.after(0, lambda: self.run_button.configure(state="normal"))
            self.app.after(0, lambda: self.stop_button.configure(state="disabled"))

    def open_output(self) -> None:
        values = self.values()
        if "OUT_DIR" in values:
            target = Path(values["OUT_DIR"])
        else:
            target = Path(values.get("ROOT_DIR", APP_DIR))
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(target)


class PreprocessApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("纤维-玻纤布-前处理")
        self.geometry("1120x760")
        self.minsize(900, 620)
        self.configure(background="#eef1f4")
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.status_var = tk.StringVar(value="就绪")

        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#eef1f4")
        style.configure("Panel.TFrame", background="#f4f6f8")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 13, "bold"), background="#eef1f4")
        style.configure("Muted.TLabel", foreground="#52606d", background="#eef1f4")
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=(14, 7))
        style.configure("Danger.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=(14, 7))

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(2, weight=2)

        header = ttk.Frame(self, padding=(20, 14, 20, 8))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="纤维-玻纤布-前处理", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        ttk.Label(header, text="合并 Fiber RVE 力学常数，并绘制 E/CTE 敏感性图", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=18)
        for step in STEPS:
            notebook.add(StepPage(notebook, step, self), text=step.tab)

        log_frame = ttk.LabelFrame(self, text="运行日志", padding=8)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=18, pady=(12, 8))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=9, wrap="word", font=("Consolas", 10), state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_bar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_bar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_bar.set)

        ttk.Label(self, textvariable=self.status_var, padding=(20, 4, 20, 10)).grid(row=3, column=0, sticky="ew")
        self.after(100, self.pump_logs)

    def log(self, message: str) -> None:
        self.log_queue.put(message)

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def pump_logs(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", message)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self.pump_logs)


if __name__ == "__main__":
    PreprocessApp().mainloop()
