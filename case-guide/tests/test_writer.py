"""Unit tests for lib/writer.py -- the output-filename sanitizer shared with
case_guide.py's own case-number sanitizer (see UNSAFE_CHARS, kept in sync on
purpose across the read side and the write side) and the small write/open
logic built on top of it. No network involved; VS Code invocation is mocked
out rather than actually shelling out to `code`.

Run with: python -m unittest discover -s tests   (from case-guide/)
      or: python -m pytest tests                 (if pytest is installed)
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import writer


class GuideFilenameTests(unittest.TestCase):
    def test_word_chars_dots_and_dashes_are_kept(self):
        self.assertEqual(writer.guide_filename("case-T26-11.845"), "case-T26-11.845.md")

    def test_a_run_of_unsafe_characters_collapses_to_a_single_underscore(self):
        self.assertEqual(writer.guide_filename("case T1/T2\\T3"), "case_T1_T2_T3.md")

    def test_leading_and_trailing_unsafe_characters_are_stripped_not_padded(self):
        self.assertEqual(writer.guide_filename("  case-T1  "), "case-T1.md")

    def test_an_all_unsafe_stem_falls_back_to_unlabeled(self):
        self.assertEqual(writer.guide_filename("///"), "unlabeled.md")

    def test_path_separators_cannot_escape_into_a_directory_traversal(self):
        # Write-side mirror of case_guide.py's _sanitize_case_number: a
        # malicious/mistyped stem must collapse to a plain filename
        # component, never something that walks back up the tree.
        result = writer.guide_filename("../../etc/passwd")
        self.assertEqual(result, ".._.._etc_passwd.md")
        self.assertNotIn("/", result)
        self.assertNotIn("\\", result)


class OpenEditorTests(unittest.TestCase):
    def test_does_nothing_when_code_is_not_on_path(self):
        with mock.patch.object(writer.shutil, "which", return_value=None), \
             mock.patch.object(writer.subprocess, "run") as run:
            writer.open_editor("some/path.md")
        run.assert_not_called()

    def test_launches_code_when_it_is_on_path(self):
        with mock.patch.object(writer.shutil, "which", return_value="C:\\code.cmd"), \
             mock.patch.object(writer.subprocess, "run") as run:
            writer.open_editor("some/path.md")
        run.assert_called_once_with(["C:\\code.cmd", "some/path.md"], check=False)


class WriteAndOpenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_the_output_directory_if_it_does_not_exist_yet(self):
        output_dir = os.path.join(self.tmp.name, "nested", "dir")
        with mock.patch.object(writer, "open_editor"):
            path = writer.write_and_open("hello", output_dir, "case-T1", open_in_vscode=False)
        self.assertTrue(os.path.isdir(output_dir))
        self.assertTrue(os.path.exists(path))

    def test_writes_text_with_exactly_one_trailing_newline_regardless_of_input(self):
        with mock.patch.object(writer, "open_editor"):
            path = writer.write_and_open("hello\n\n\n", self.tmp.name, "case-T1", open_in_vscode=False)
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "hello\n")

    def test_returned_path_matches_what_guide_filename_predicts(self):
        with mock.patch.object(writer, "open_editor"):
            path = writer.write_and_open("hello", self.tmp.name, "case-T1", open_in_vscode=False)
        self.assertEqual(os.path.basename(path), writer.guide_filename("case-T1"))

    def test_does_not_open_the_editor_when_disabled(self):
        with mock.patch.object(writer, "open_editor") as open_editor:
            writer.write_and_open("hello", self.tmp.name, "case-T1", open_in_vscode=False)
        open_editor.assert_not_called()

    def test_opens_the_editor_with_the_written_path_when_enabled(self):
        with mock.patch.object(writer, "open_editor") as open_editor:
            path = writer.write_and_open("hello", self.tmp.name, "case-T1", open_in_vscode=True)
        open_editor.assert_called_once_with(path)


if __name__ == "__main__":
    unittest.main()
