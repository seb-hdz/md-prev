import os
import sys
import logging
from pathlib import Path

# Mock paths_util
class MockPathsUtil:
    def get_base_path(self):
        return os.path.abspath('.')

import paths_util
paths_util.get_base_path = MockPathsUtil().get_base_path

from renderer import MarkdownRenderer

logging.getLogger('renderer').setLevel(logging.ERROR)

renderer = MarkdownRenderer()
html = renderer.render('latex_test.md')

print(html)
