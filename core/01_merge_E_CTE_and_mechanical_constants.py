# -*- coding: utf-8 -*-
import csv
import math
import os
import re
import sys
import tempfile
from contextlib import contextmanager
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
    """Read exactly 12 finite values per row; never drop or shift bad data."""
    rows = []
    first_record = True
    with open(path, "r", encoding="utf-8-sig") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            # CSV splitting preserves empty fields instead of shifting columns.
            parts = next(csv.reader([line])) if "," in line else line.split()
            parts = [part.strip() for part in parts]
            header = [part.upper() for part in parts]
            aliases = {"E11": "E1", "E22": "E2", "E33": "E3"}
            header = [aliases.get(name, name) for name in header]
            if first_record and header == MECH_COLUMNS:
                first_record = False
                continue
            first_record = False

            if len(parts) != len(MECH_COLUMNS):
                raise ValueError(
                    "{}: line {} has {} columns; expected exactly 12 in order: {}".format(
                        path, line_number, len(parts), ", ".join(MECH_COLUMNS)
                    )
                )
            for column, value in zip(MECH_COLUMNS, parts):
                try:
                    valid = math.isfinite(float(value))
                except ValueError:
                    valid = False
                if not valid:
                    raise ValueError(
                        "{}: line {}, column {}: expected a finite number, got {!r}".format(
                            path, line_number, column, value
                        )
                    )
            rows.append(parts)

    if not rows:
        raise ValueError("Input table contains no data rows: {}".format(path))
    return rows


def expected_count_for_group(group_index):
    if group_index in [1, 2, 3, 4]:
        return 273
    if group_index == 5:
        return 234
    raise ValueError("Unsupported legacy group number: {}".format(group_index))


def load_mechanical_inputs(root_dir, full_params):
    """Accept one full table, or all five original batches in their fixed order.

    ROOT_DIR can be the folder containing the complete Mechanical_constants.txt,
    or the parent of GROUP_PREFIX + number folders. A complete table found in
    any one numbered folder starts at the FIRST parameter, regardless of suffix.
    Row order must still match build_full_params(): E outer loop, CTE inner loop.
    """
    root_dir = Path(root_dir)
    direct_path = root_dir / "Mechanical_constants.txt"
    candidates = [(None, direct_path)] if direct_path.is_file() else []
    prefix = str(GROUP_PREFIX).strip()
    if prefix:
        for folder in sorted(root_dir.iterdir(), key=lambda p: natural_sort_key(p.name)):
            suffix = folder.name[len(prefix):] if folder.name.startswith(prefix) else ""
            if folder.is_dir() and suffix.isdigit():
                path = folder / "Mechanical_constants.txt"
                if path.is_file():
                    candidates.append((int(suffix), path))
    if not candidates:
        raise FileNotFoundError(
            "No Mechanical_constants.txt found in {} or its {}<number> folders. "
            "Set ROOT_DIR to the folder containing your input TXT or the batch folders.".format(
                root_dir, prefix
            )
        )

    tables = [(index, path, read_mechanical_rows(path)) for index, path in candidates]
    total = len(full_params)
    if len(tables) == 1 and len(tables[0][2]) == total:
        _index, path, rows = tables[0]
        return rows, [path], ["Mode: single complete table", "Input: {} ({} rows)".format(path, total)]

    # Do not guess which run to use if a full table coexists with other results.
    if any(index is None or len(rows) == total for index, _path, rows in tables):
        raise ValueError(
            "Ambiguous or incomplete input: {}. A single complete table must have {} rows "
            "and be the only input. Set ROOT_DIR to the specific folder containing it.".format(
                "; ".join("{}: {} rows".format(path, len(rows)) for _i, path, rows in tables), total
            )
        )

    indices = [index for index, _path, _rows in tables]
    if sorted(indices) != [1, 2, 3, 4, 5]:
        raise ValueError(
            "Incomplete or ambiguous batch set: found groups {}. Expected one complete "
            "{}-row TXT, or groups 1-5 with row counts 273, 273, 273, 273, 234. "
            "No rows were truncated or matched to guessed parameters.".format(indices, total)
        )

    all_rows = []
    sources = []
    report = ["Mode: five legacy batches"]
    for index, path, rows in sorted(tables, key=lambda item: item[0]):
        expected = expected_count_for_group(index)
        if len(rows) != expected:
            raise ValueError(
                "{}: group {} has {} rows; expected {}. No output was written.".format(
                    path, index, len(rows), expected
                )
            )
        all_rows.extend(rows)
        sources.append(path)
        report.append("Group {} OK: {} rows ({})".format(index, len(rows), path))
    if len(all_rows) != total:
        raise ValueError("Parameter count {} does not match data count {}".format(total, len(all_rows)))
    return all_rows, sources, report


def checked_output_paths(root_dir, sources):
    paths = [Path(output_path(root_dir, name)).resolve() for name in (
        OUTPUT_FULL_PARAMS, OUTPUT_MECH_ONLY, OUTPUT_WITH_PARAMS, OUTPUT_FIBER_BUNDLE_CSV
    )]
    if len(set(paths)) != len(paths):
        raise ValueError("Output paths must be different from each other.")
    inputs = {Path(path).resolve() for path in sources}
    for path in paths:
        if path in inputs or (path.exists() and any(path.samefile(source) for source in inputs)):
            raise ValueError("Output would overwrite an input table: {}".format(path))
        if path.is_dir():
            raise ValueError("Output path is a directory, not a file: {}".format(path))
    for i, path in enumerate(paths):
        if path.exists() and any(other.exists() and path.samefile(other) for other in paths[:i]):
            raise ValueError("Output paths refer to the same file: {}".format(path))
    return paths


@contextmanager
def staged_outputs(paths):
    """Finish writing all temporary tables before replacing existing outputs."""
    temporary_paths = []
    try:
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name + ".", suffix=".tmp", delete=False) as f:
                temporary_paths.append(Path(f.name))
        yield temporary_paths
        for temporary, path in zip(temporary_paths, paths):
            os.replace(temporary, path)
    finally:
        for temporary in temporary_paths:
            if temporary.exists():
                temporary.unlink()


def main():
    root_dir = os.path.abspath(ROOT_DIR)
    if not os.path.isdir(root_dir):
        raise NotADirectoryError("ROOT_DIR is not an existing folder: {}".format(root_dir))

    full_params = build_full_params()
    all_mech_rows, sources, report_lines = load_mechanical_inputs(root_dir, full_params)
    paths = checked_output_paths(root_dir, sources)
    full_params_path, mech_only_path, with_params_path, fiber_bundle_csv_path = paths

    # Validation above completes before any existing output file is changed.
    with staged_outputs(paths) as temporary_paths:
        params_temp, mech_temp, with_params_temp, csv_temp = temporary_paths
        write_params(params_temp, full_params)

        with open(mech_temp, "w", encoding="utf-8") as f:
            for row in all_mech_rows:
                f.write("\t".join(row) + "\n")

        with open(with_params_temp, "w", encoding="utf-8") as f:
            f.write("\t".join(["E_MPa", "CTE/e-5", "nu"] + MECH_COLUMNS) + "\n")
            for param, mech in zip(full_params, all_mech_rows):
                e_mpa, cte, nu = param
                f.write("\t".join([format_num(e_mpa), format_num(cte), format_num(nu)] + mech) + "\n")

        with open(csv_temp, "w", encoding="utf-8-sig") as f:
            f.write(",".join(CSV_COLUMNS) + "\n")
            for param, mech in zip(full_params, all_mech_rows):
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
    # workflow_gui.py reads subprocess logs as UTF-8, including Chinese paths.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        main()
    except (OSError, ValueError) as exc:
        print("[ERROR] {}".format(exc), file=sys.stderr)
        sys.exit(1)
