"""Regression checks for complete-table and original five-batch inputs."""
import contextlib
import csv
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("01_merge_E_CTE_and_mechanical_constants.py")


class MergeTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("merge_under_test", SCRIPT)
        self.merge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.merge)
        self.temporary = tempfile.TemporaryDirectory(prefix=".test_merge_", dir=SCRIPT.parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.merge.ROOT_DIR = self.root
        self.merge.GROUP_PREFIX = "batch-"
        self.merge.OUTPUT_FIBER_BUNDLE_CSV = "result.csv"
        # Unique E1 values detect truncation, reordering and wrong parameter offsets.
        self.rows = [[str(i)] + ["1.25e-05"] * 11 for i in range(1, 1327)]

    def write_input(self, rows=None, group=None):
        folder = self.root if group is None else self.root / ("batch-" + str(group))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "Mechanical_constants.txt"
        path.write_text("\n".join("\t".join(row) for row in (self.rows if rows is None else rows)) + "\n", encoding="utf-8")
        return path

    def run_merge(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.merge.main()
        with (self.root / "result.csv").open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def assert_complete_output(self, result):
        self.assertEqual(len(result), 1326)
        self.assertEqual([int(row["E1"]) for row in result], list(range(1, 1327)))
        self.assertEqual((result[0]["E1MPa"], result[0]["CTE/e-5"]), ("100", "1"))
        self.assertEqual((result[38]["E1MPa"], result[38]["CTE/e-5"]), ("100", "20"))
        self.assertEqual((result[39]["E1MPa"], result[39]["CTE/e-5"]), ("250", "1"))
        self.assertEqual((result[-1]["E1MPa"], result[-1]["CTE/e-5"]), ("16000", "20"))

    def test_complete_file_in_second_folder_starts_with_first_parameter(self):
        self.write_input(group=2)
        self.assert_complete_output(self.run_merge())
        self.assertEqual(len((self.root / self.merge.OUTPUT_MECH_ONLY).read_text().splitlines()), 1326)
        self.assertEqual(len((self.root / self.merge.OUTPUT_WITH_PARAMS).read_text().splitlines()), 1327)

    def test_complete_file_directly_in_root(self):
        self.write_input()
        self.assert_complete_output(self.run_merge())

    def test_original_batches_keep_their_order(self):
        start = 0
        for index, count in enumerate([273, 273, 273, 273, 234], 1):
            self.write_input(self.rows[start:start + count], group=index)
            start += count
        self.assert_complete_output(self.run_merge())

    def test_missing_batches_do_not_overwrite_existing_outputs(self):
        self.write_input(self.rows[:273], group=2)
        outputs = [self.merge.OUTPUT_FULL_PARAMS, self.merge.OUTPUT_MECH_ONLY,
                   self.merge.OUTPUT_WITH_PARAMS, self.merge.OUTPUT_FIBER_BUNDLE_CSV]
        for name in outputs:
            (self.root / name).write_bytes(b"previous valid result")
        with self.assertRaisesRegex(ValueError, "Incomplete.*batch"):
            self.run_merge()
        for name in outputs:
            self.assertEqual((self.root / name).read_bytes(), b"previous valid result")

    def test_wrong_batch_length_is_not_truncated(self):
        for index, count in enumerate([274, 273, 273, 273, 234], 1):
            self.write_input(self.rows[:count], group=index)
        with self.assertRaisesRegex(ValueError, "group 1 has 274 rows; expected 273"):
            self.run_merge()
        self.assertFalse((self.root / "result.csv").exists())

    def test_short_or_long_complete_table_is_rejected(self):
        for rows in (self.rows[:-1], self.rows + [self.rows[0]]):
            with self.subTest(count=len(rows)):
                self.write_input(rows)
                with self.assertRaisesRegex(ValueError, "1326 rows"):
                    self.run_merge()

    def test_complete_table_mixed_with_another_run_is_rejected(self):
        self.write_input(group=2)
        self.write_input(self.rows[:273], group=1)
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            self.run_merge()

    def test_two_complete_tables_are_rejected(self):
        self.write_input(group=1)
        self.write_input(group=2)
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            self.run_merge()

    def test_bom_header_and_supported_delimiters_preserve_first_row(self):
        for sep in ("\t", " ", ","):
            with self.subTest(separator=sep):
                path = self.root / "Mechanical_constants.txt"
                path.write_text("\n" + sep.join(self.merge.MECH_COLUMNS) + "\n\n" + sep.join(self.rows[0]) + "\n", encoding="utf-8-sig")
                self.assertEqual(self.merge.read_mechanical_rows(path), [self.rows[0]])

    def test_bad_rows_are_reported_instead_of_skipped(self):
        cases = [self.rows[0][:-1], self.rows[0] + ["2"],
                 ["bad"] + self.rows[0][1:], ["nan"] + self.rows[0][1:],
                 ["inf"] + self.rows[0][1:], ["1e999"] + self.rows[0][1:],
                 [""] + self.rows[0][1:]]
        for row in cases:
            with self.subTest(row=row):
                path = self.root / "bad.txt"
                path.write_text(",".join(self.rows[0]) + "\n" + ",".join(row) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "line 2"):
                    self.merge.read_mechanical_rows(path)

    def test_wrong_header_order_is_rejected(self):
        path = self.root / "bad.txt"
        path.write_text("\t".join(reversed(self.merge.MECH_COLUMNS)) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "line 1"):
            self.merge.read_mechanical_rows(path)

    def test_empty_file_or_missing_input_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            self.run_merge()
        path = self.root / "Mechanical_constants.txt"
        path.write_text("\n\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no data rows"):
            self.run_merge()

    def test_output_cannot_overwrite_input(self):
        source = self.write_input()
        original = source.read_bytes()
        self.merge.OUTPUT_MECH_ONLY = source
        with self.assertRaisesRegex(ValueError, "overwrite an input"):
            self.run_merge()
        self.assertEqual(source.read_bytes(), original)

    def test_duplicate_output_paths_are_rejected(self):
        self.write_input()
        self.merge.OUTPUT_MECH_ONLY = self.merge.OUTPUT_WITH_PARAMS
        with self.assertRaisesRegex(ValueError, "different from each other"):
            self.run_merge()

    def test_failed_write_preserves_all_previous_outputs_and_cleans_temporary_files(self):
        self.write_input()
        outputs = [self.root / name for name in [self.merge.OUTPUT_FULL_PARAMS,
                   self.merge.OUTPUT_MECH_ONLY, self.merge.OUTPUT_WITH_PARAMS,
                   self.merge.OUTPUT_FIBER_BUNDLE_CSV]]
        for path in outputs:
            path.write_bytes(b"previous valid result")
        with patch.object(self.merge, "format_plain_decimal", side_effect=OSError("simulated disk error")):
            with self.assertRaisesRegex(OSError, "simulated disk error"):
                self.run_merge()
        for path in outputs:
            self.assertEqual(path.read_bytes(), b"previous valid result")
        self.assertEqual(list(self.root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
