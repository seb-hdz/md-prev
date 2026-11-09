"""
test_notes_manager.py
---------------------
Unit tests for the notes persistence layer.
"""
import os
import sys
import tempfile
import unittest

# Ensure project root is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock paths_util before importing notes_manager
class MockPathsUtil:
    def get_base_path(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    def get_app_support_path(self):
        return tempfile.mkdtemp()

import paths_util
paths_util.get_base_path = MockPathsUtil().get_base_path
paths_util.get_app_support_path = MockPathsUtil().get_app_support_path

from notes_manager import NotesManager


class TestNotesManager(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, 'test_notes.sqlite3')
        self.mgr = NotesManager(db_path=self.db_path)
        self.test_file = '/tmp/test_doc.md'
        self.test_selector = {
            'exact': 'hello world',
            'prefix': 'say ',
            'suffix': ' today',
            'start': 4,
            'end': 15,
        }

    def test_create_and_list(self):
        note = self.mgr.create_note(self.test_file, 'My note', self.test_selector)
        self.assertIn('id', note)
        self.assertEqual(note['body'], 'My note')
        self.assertEqual(note['selector']['exact'], 'hello world')

        notes = self.mgr.list_notes(self.test_file)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['id'], note['id'])

    def test_idempotent_create(self):
        note = self.mgr.create_note(self.test_file, 'My note', self.test_selector, note_id='note_abc123')
        note2 = self.mgr.create_note(self.test_file, 'My note', self.test_selector, note_id='note_abc123')
        self.assertEqual(note['id'], note2['id'])

    def test_conflict_on_different_body(self):
        self.mgr.create_note(self.test_file, 'Body A', self.test_selector, note_id='note_conflict')
        with self.assertRaises(ValueError):
            self.mgr.create_note(self.test_file, 'Body B', self.test_selector, note_id='note_conflict')

    def test_update_body(self):
        note = self.mgr.create_note(self.test_file, 'Original', self.test_selector)
        updated = self.mgr.update_note(self.test_file, note['id'], body='Updated')
        self.assertEqual(updated['body'], 'Updated')
        self.assertEqual(updated['selector']['exact'], 'hello world')

    def test_update_nonexistent(self):
        with self.assertRaises(KeyError):
            self.mgr.update_note(self.test_file, 'note_missing', body='x')

    def test_delete(self):
        note = self.mgr.create_note(self.test_file, 'To delete', self.test_selector)
        self.assertTrue(self.mgr.delete_note(self.test_file, note['id']))
        self.assertEqual(len(self.mgr.list_notes(self.test_file)), 0)

    def test_delete_idempotent(self):
        self.assertFalse(self.mgr.delete_note(self.test_file, 'note_nonexist'))

    def test_isolation_between_files(self):
        sel_a = {**self.test_selector, 'exact': 'file A text'}
        sel_b = {**self.test_selector, 'exact': 'file B text'}
        self.mgr.create_note('/tmp/A.md', 'Note for A', sel_a)
        self.mgr.create_note('/tmp/B.md', 'Note for B', sel_b)

        notes_a = self.mgr.list_notes('/tmp/A.md')
        notes_b = self.mgr.list_notes('/tmp/B.md')
        self.assertEqual(len(notes_a), 1)
        self.assertEqual(len(notes_b), 1)
        self.assertEqual(notes_a[0]['body'], 'Note for A')
        self.assertEqual(notes_b[0]['body'], 'Note for B')

    def test_blank_body_rejected(self):
        with self.assertRaises(ValueError):
            self.mgr.create_note(self.test_file, '', self.test_selector)
        with self.assertRaises(ValueError):
            self.mgr.create_note(self.test_file, '   ', self.test_selector)

    def test_bad_selector_rejected(self):
        with self.assertRaises(ValueError):
            self.mgr.create_note(self.test_file, 'Note', {'prefix': 'no exact'})
        with self.assertRaises(ValueError):
            self.mgr.create_note(self.test_file, 'Note', 'not a dict')


if __name__ == '__main__':
    unittest.main()

