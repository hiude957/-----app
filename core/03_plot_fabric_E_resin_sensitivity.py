# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


# ===== Change these values each time =====
CSV_PATH = Path(r"H:\fiber+bu+micro\2116\20260810-bu-2012-H\texgen\20260810-2116-texgen-7-fiber-2116-2012-quan\20260812-2116-玻纤布-7-fiber-2116-2012-quan-5-转换.csv")

OUT_DIR = Path(r"H:\fiber+bu+micro\2116\20260810-bu-2012-H\texgen\20260810-2116-texgen-7-fiber-2116-2012-quan\20260812-2116-玻纤布-E-resin-分组作图-5")

E_COL = 'E'

RESIN_COL = 'resin'
# ========================================


PREFERRED_PERFORMANCE_COLS = [
    "E1",
    "E2",
    "E3",
    "V12",
    "V13",
    "V23",
    "G12",
    "G13",
    "G23",
    "cte_x",
    "cte_y",
    "cte_z",
]


def read_table(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError("Input table does not exist: {}".format(path))
    if path.suffix.lower() in {".txt", ".tsv"}:
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def fmt_value(value) -> str:
    text = f"{float(value):g}"
    return text.replace(".", "p").replace("-", "m")


def usable_performance_cols(df: pd.DataFrame) -> list[str]:
    cols = []
    for col in PREFERRED_PERFORMANCE_COLS:
        if col in df.columns and col not in {E_COL, RESIN_COL}:
            cols.append(col)
    return cols


def plot_group(df: pd.DataFrame, y_cols: list[str], fixed_col: str, fixed_value, x_col: str, out_path: Path) -> None:
    group = df[df[fixed_col] == fixed_value].sort_values(x_col)
    if group.empty:
        return

    ncols = 4
    nrows = math.ceil(len(y_cols) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(18, 3.2 * nrows), constrained_layout=True)
    fig.suptitle(f"Fixed {fixed_col} = {fixed_value:g}", fontsize=16)

    axes_flat = list(axes.ravel()) if hasattr(axes, "ravel") else [axes]
    for ax, y_col in zip(axes_flat, y_cols):
        ax.plot(group[x_col], group[y_col], marker="o", linewidth=1.6, markersize=3.5)
        ax.set_title(y_col)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.grid(True, alpha=0.3)

    for ax in axes_flat[len(y_cols):]:
        ax.axis("off")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def main() -> None:
    df = read_table(CSV_PATH)
    df.columns = [col.strip() for col in df.columns]

    missing_keys = [col for col in [E_COL, RESIN_COL] if col not in df.columns]
    if missing_keys:
        raise ValueError("Input table is missing grouping columns: " + ", ".join(missing_keys))

    y_cols = usable_performance_cols(df)
    if not y_cols:
        raise ValueError("Input table does not contain any supported performance columns.")

    for col in [E_COL, RESIN_COL] + y_cols:
        df[col] = pd.to_numeric(df[col], errors="raise")

    fixed_e_dir = OUT_DIR / "fixed_E_x_resin"
    fixed_resin_dir = OUT_DIR / "fixed_resin_x_E"

    for e_value in sorted(df[E_COL].unique()):
        out_path = fixed_e_dir / f"E_{fmt_value(e_value)}_vs_resin.png"
        plot_group(df, y_cols, E_COL, e_value, RESIN_COL, out_path)

    for resin_value in sorted(df[RESIN_COL].unique()):
        out_path = fixed_resin_dir / f"resin_{fmt_value(resin_value)}_vs_E.png"
        plot_group(df, y_cols, RESIN_COL, resin_value, E_COL, out_path)

    print("Input table: {}".format(CSV_PATH))
    print("Rows: {}".format(len(df)))
    print("Performance columns: {}".format(", ".join(y_cols)))
    print("Saved fixed-E plots to: {}".format(fixed_e_dir))
    print("Saved fixed-resin plots to: {}".format(fixed_resin_dir))


if __name__ == "__main__":
    main()
