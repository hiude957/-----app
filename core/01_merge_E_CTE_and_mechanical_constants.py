# -*- coding: utf-8 -*-
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path


# ===== Change these values each time =====
ROOT_DIR = Path(r"D:\1_sdu\fiber\pp106")

GROUP_PREFIX = '20260907-fiber-rve-5-fiber-106-test2-'

OUTPUT_FULL_PARAMS = 'E_CTE_full_params.txt'

OUTPUT_MECH_ONLY = 'merged_Mechanical_constants_only.txt'

OUTPUT_WITH_PARAMS = 'merged_E_CTE_Mechanical_constants.txt'

OUTPUT_FIBER_BUNDLE_CSV = Path(r"D:\1_sdu\fiber\pp106\fiber_bundle_E_CTE_Mechanical_constants.csv")
# ========================================

MECH_COLUMNS = [
    "E1", "E2", "E3",
    "V12", "V13", "V23",
    "G12", "G13", "G23",
    "CTE_X", "CTE_Y", "CTE_Z",
]

CSV_COLUMNS = ["E1MPa", "CTE/e-5"] + MECH_COLUMNS


def natural_sort_key(s):
    parts = re.split(r"(\d+)", str(s))
    key = []
    for part in parts:
        if part == "":
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.lower()))
    return key


def build_full_params():
    e_values_gpa = [0.1, 0.25] + [x * 0.5 for x in range(1, 33)]
    cte_values = [1.0 + x * 0.5 for x in range(39)]

    params = []
    for e_gpa in e_values_gpa:
        e_mpa = int(round(e_gpa * 1000))
        for cte in cte_values:
            params.append((e_mpa, cte, 0.38))

    return params


def format_num(x):
    return str(x)


def format_plain_decimal(value):
    text = str(value).strip()
    if text == "":
        return text
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    plain = format(number, "f")
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    return plain


def write_params(path, params):
    with open(path, "w", encoding="utf-8") as f:
        for e_mpa, cte, nu in params:
            f.write("    ({}, {}, {}),\n".format(
                format_num(e_mpa),
                format_num(cte),
                format_num(nu),
            ))


def output_path(root_dir, value):
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return os.path.join(root_dir, str(value))


def read_mechanical_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("e1") or line.lower().startswith("e11"):
                continue

            parts = re.split(r"[\t, ]+", line)
            nums = []

            for part in parts:
                if part == "":
                    continue
                try:
                    float(part)
                    nums.append(part)
                except Exception:
                    pass

            if len(nums) >= 12:
                rows.append(nums[:12])

    return rows


def expected_count_for_group(group_index):
    if group_index in [1, 2, 3, 4]:
        return 273
    if group_index == 5:
        return 234
    return 0


def main():
    root_dir = os.path.abspath(ROOT_DIR)
    if not os.path.isdir(root_dir):
        print("[ERROR] ROOT_DIR does not exist:", root_dir)
        return

    full_params = build_full_params()
    full_params_path = output_path(root_dir, OUTPUT_FULL_PARAMS)
    write_params(full_params_path, full_params)

    all_mech_rows = []
    all_param_rows = []
    report_lines = []
    param_start = 0

    for group_index in range(1, 6):
        expected_count = expected_count_for_group(group_index)
        group_name = GROUP_PREFIX + str(group_index)
        group_dir = os.path.join(root_dir, group_name)
        mech_path = os.path.join(group_dir, "Mechanical_constants.txt")

        group_params = full_params[param_start:param_start + expected_count]
        param_start += expected_count

        if not os.path.isfile(mech_path):
            report_lines.append(
                "Group {} missing Mechanical_constants.txt: {}".format(group_index, mech_path)
            )
            continue

        mech_rows = read_mechanical_rows(mech_path)

        if len(mech_rows) != expected_count:
            report_lines.append(
                "Group {} row count mismatch: actual {}, expected {}".format(
                    group_index, len(mech_rows), expected_count
                )
            )
        else:
            report_lines.append(
                "Group {} OK: {} rows".format(group_index, len(mech_rows))
            )

        use_count = min(len(mech_rows), len(group_params))
        all_mech_rows.extend(mech_rows[:use_count])
        all_param_rows.extend(group_params[:use_count])

    mech_only_path = output_path(root_dir, OUTPUT_MECH_ONLY)
    with open(mech_only_path, "w", encoding="utf-8") as f:
        for row in all_mech_rows:
            f.write("\t".join(row) + "\n")

    with_params_path = output_path(root_dir, OUTPUT_WITH_PARAMS)
    with open(with_params_path, "w", encoding="utf-8") as f:
        f.write("\t".join(["E_MPa", "CTE/e-5", "nu"] + MECH_COLUMNS) + "\n")
        for param, mech in zip(all_param_rows, all_mech_rows):
            e_mpa, cte, nu = param
            f.write("\t".join([format_num(e_mpa), format_num(cte), format_num(nu)] + mech) + "\n")

    fiber_bundle_csv_path = output_path(root_dir, OUTPUT_FIBER_BUNDLE_CSV)
    Path(fiber_bundle_csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(fiber_bundle_csv_path, "w", encoding="utf-8-sig") as f:
        f.write(",".join(CSV_COLUMNS) + "\n")
        for param, mech in zip(all_param_rows, all_mech_rows):
            e_mpa, cte, _nu = param
            csv_row = [format_plain_decimal(e_mpa), format_plain_decimal(cte)]
            csv_row.extend(format_plain_decimal(value) for value in mech)
            f.write(",".join(csv_row) + "\n")

    report_lines.append("")
    report_lines.append("Full param rows: {}".format(len(full_params)))
    report_lines.append("Available merged rows: {}".format(len(all_mech_rows)))
    report_lines.append("Output: {}".format(full_params_path))
    report_lines.append("Output: {}".format(mech_only_path))
    report_lines.append("Output: {}".format(with_params_path))
    report_lines.append("Output: {}".format(fiber_bundle_csv_path))

    print("\n".join(report_lines))


if __name__ == "__main__":
    main()
