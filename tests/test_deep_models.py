"""Migrated from ``docconvert`` ``tests/test_models.py`` -> ``omnidoc.engines.deep._models``."""

import unittest

from omnidoc.engines.deep._models import MergeInfo, ProgressEvent


class TestMergeInfo(unittest.TestCase):

    def test_defaults(self):
        m = MergeInfo()
        self.assertEqual(m.rowspan, 1)
        self.assertEqual(m.colspan, 1)
        self.assertFalse(m.is_master)
        self.assertFalse(m.is_merged)
        self.assertEqual(m.min_row, 0)

    def test_can_set_all_fields(self):
        m = MergeInfo(
            rowspan=2, colspan=3, is_master=True, is_merged=True,
            min_row=1, min_col=1, max_row=2, max_col=3,
        )
        self.assertEqual(m.rowspan, 2)
        self.assertEqual(m.colspan, 3)
        self.assertTrue(m.is_master)
        self.assertEqual(m.max_row, 2)
        self.assertEqual(m.max_col, 3)


class TestProgressEvent(unittest.TestCase):

    def test_defaults(self):
        e = ProgressEvent()
        self.assertEqual(e.message, "")
        self.assertEqual(e.progress, 0.0)
        self.assertFalse(e.done)
        self.assertIsNone(e.error)

    def test_error_field_optional(self):
        e = ProgressEvent(message="failed", error="boom")
        self.assertEqual(e.message, "failed")
        self.assertEqual(e.error, "boom")


if __name__ == "__main__":
    unittest.main()
