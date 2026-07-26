import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import server


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "frontend" / "app.js"
INDEX_HTML = ROOT / "frontend" / "index.html"


class FrontendStartupTests(unittest.TestCase):
    def test_terminal_body_is_not_referenced_before_initialization(self):
        source = APP_JS.read_text(encoding="utf-8")
        declaration = "const terminalBody = document.getElementById('terminal-body');"
        declaration_offset = source.index(declaration)

        self.assertNotIn("terminalBody", source[:declaration_offset])

    def test_root_uses_versioned_frontend_assets_and_disables_html_cache(self):
        response = TestClient(server.app).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertRegex(response.text, r'/static/app\.js\?v=\d+')
        self.assertRegex(response.text, r'/static/styles\.css\?v=\d+')

    def test_terminal_has_copy_log_control(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        script = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="copy-log-btn"', html)
        self.assertIn("copyLogBtn.addEventListener('click', copyTerminalLog)", script)
        self.assertIn("navigator.clipboard.writeText(logText)", script)


if __name__ == "__main__":
    unittest.main()
