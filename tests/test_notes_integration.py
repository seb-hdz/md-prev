"""
test_notes_integration.py
-------------------------
Integration tests verifying template assembly, placeholders, and bridge helpers.
"""
import os
import sys
import re
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockPathsUtil:
    def get_base_path(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    def get_app_support_path(self):
        tmp = os.path.join(tempfile.gettempdir(), 'md_prev_test_support')
        os.makedirs(os.path.join(tmp, 'assets'), exist_ok=True)
        return tmp

import paths_util
paths_util.get_base_path = MockPathsUtil().get_base_path
paths_util.get_app_support_path = MockPathsUtil().get_app_support_path

from renderer import MarkdownRenderer
from notes_manager import NotesManager


class TestNotesIntegration(unittest.TestCase):

    def setUp(self):
        self.renderer = MarkdownRenderer()

    def test_template_contains_no_unfilled_placeholders(self):
        html = self.renderer.wrap_in_template('<h1>Test</h1>', 'body { color: red; }')
        unfilled = re.findall(r'{%[a-zA-Z0-9_]+%}', html)
        self.assertEqual(unfilled, [], f'Found unfilled placeholders: {unfilled}')

    def test_template_contains_notes_elements(self):
        html = self.renderer.wrap_in_template('<p>Content</p>', 'body{}')
        self.assertIn('id="note-fab"', html)
        self.assertIn('id="note-dialog"', html)
        self.assertIn('id="note-inspector"', html)
        self.assertIn('note-dialog-input', html)
        self.assertIn('note-dialog-save', html)
        self.assertIn('md-note-highlight', html)

    def test_notes_manager_json_roundtrip(self):
        tmp_db = os.path.join(tempfile.mkdtemp(), 'test.sqlite3')
        mgr = NotesManager(db_path=tmp_db)
        filepath = '/Users/test/test.md'
        selector = {
            'exact': 'Texto de prueba con acentos y ñ',
            'prefix': 'Inicio: ',
            'suffix': ' :Fin',
            'start': 8,
            'end': 40
        }
        created = mgr.create_note(filepath, 'Nota con emojis 🚀 y saltos\nde línea', selector)
        listed = mgr.list_notes(filepath)

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['id'], created['id'])
        self.assertEqual(listed[0]['body'], 'Nota con emojis 🚀 y saltos\nde línea')
        self.assertEqual(listed[0]['selector']['exact'], 'Texto de prueba con acentos y ñ')


if __name__ == '__main__':
    unittest.main()

