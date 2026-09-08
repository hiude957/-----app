# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


# ===== Change these values each time =====
CSV_PATH = Path(r"D:\1_sdu\fiber\pp106\20260907-fiber-rve-5-fiber-106-test2-2\Mechanical_constants.txt")

OUT_DIR = Path(r"D:\1_sdu\fiber\pp106\绘图结果")

E_COL = 'E1MPa'

CTE_COL = 'CTE/e-5'
# ========================================


PERFORMANCE_COLS = [
    "E1",
    "E2",
    "E3",
    "V12",
    "V13",
    "V23",
    "G12",
    "G13",
    "G23",
    "CTE_X",
    "CTE_Y",
    "CTE_Z",
]

def read_table(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError("Input table does not exist: {}".format(path))
    if path.suffix.lower() in {".txt", ".tsv"}:
        return pd.read_csv(path, sep="\t")
    return pd.read_csv(path)


def fmt_value(value):
    text = f"{float(value):g}"
    return text.replace(".", "p").replace("-", "m")


def plot_group(df, fixed_col, fixed_value, x_col, out_path):
    group = df[df[fixed_col] == fixed_value].sort_values(x_col)
    if group.empty:
        return

    fig, axes = plt.subplots(3, 4, figsize=(18, 11), constrained_layout=True)
    fig.suptitle(f"Fixed {fixed_col} = {fixed_value:g}", fontsize=16)

    for ax, y_col in zip(axes.ravel(), PERFORMANCE_COLS):
        ax.plot(group[x_col], group[y_col], marker="o", linewidth=1.6, markersize=3.5)
        ax.set_title(y_col)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.grid(True, alpha=0.3)

    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def main():
    df = read_table(CSV_PATH)
    df.columns = [col.strip() for col in df.columns]

    missing = [col for col in [E_COL, CTE_COL] + PERFORMANCE_COLS if col not in df.columns]
    if missing:
        raise ValueError("Input table is missing columns: " + ", ".join(missing))

    for col in [E_COL, CTE_COL] + PERFORMANCE_COLS:
        df[col] = pd.to_numeric(df[col], errors="raise")

    fixed_e_dir = OUT_DIR / "fixed_E_x_CTE"
    fixed_cte_dir = OUT_DIR / "fixed_CTE_x_E"
    fixed_e_dir.mkdir(parents=True, exist_ok=True)
    fixed_cte_dir.mkdir(parents=True, exist_ok=True)

    for e_value in sorted(df[E_COL].unique()):
        out_path = fixed_e_dir / f"E_{fmt_value(e_value)}_vs_CTE.png"
        plot_group(df, E_COL, e_value, CTE_COL, out_path)

    for cte_value in sorted(df[CTE_COL].unique()):
        out_path = fixed_cte_dir / f"CTE_{fmt_value(cte_value)}e-5_vs_E.png"
        plot_group(df, CTE_COL, cte_value, E_COL, out_path)

    print("Input table: {}".format(CSV_PATH))
    print("Rows: {}".format(len(df)))
    print("Saved fixed-E plots to: {}".format(fixed_e_dir))
    print("Saved fixed-CTE plots to: {}".format(fixed_cte_dir))


if __name__ == "__main__":
    main()
