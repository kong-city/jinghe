from __future__ import annotations

"""v1.8.4 守护：左侧思源式文档目录。

约束来源（用户裁决 2026-11-27）：
- 历史版本先封存；新版本左侧栏做成书籍目录样。
- 提纯目录本次不处理。
- 超长标题右端淡化消失，hover / 聚焦才显示全部。
- 点开折叠区才加载，左侧默认显示文档标题。
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class V184SidebarTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        cls.js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        cls.i18n = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")

    def test_01_independent_ids_no_new_data_page(self):
        for marker in ('id="sideKbTree"', 'id="sideKbToggle"', 'id="sideKbList"'):
            self.assertIn(marker, self.html)
        # 7 个功能入口被测试契约锁定，文档目录不得占用 data-page
        self.assertEqual(self.html.count('data-page="'), 7)
        self.assertNotIn('data-page="sideKb', self.html)

    def test_02_default_collapsed(self):
        self.assertIn('aria-expanded="false"', self.html)
        self.assertIn('<div class="side-kb-list" id="sideKbList" hidden>', self.html)

    def test_03_refine_tree_not_touched(self):
        self.assertNotIn("side-refine-tree", self.html)
        self.assertNotIn("sideRefine", self.js)

    def test_04_mask_gradient_fade(self):
        self.assertIn("-webkit-mask-image: linear-gradient", self.css)
        self.assertIn("mask-image: linear-gradient", self.css)
        self.assertIn("white-space: nowrap; overflow: hidden", self.css)

    def test_05_hover_unmasks(self):
        self.assertIn(".side-kb-item:hover .side-kb-title", self.css)
        self.assertIn(".side-kb-item:focus-visible .side-kb-title", self.css)
        self.assertIn("-webkit-mask-image: none; mask-image: none;", self.css)

    def test_06_hover_full_title_popup(self):
        self.assertIn(".side-kb-item:hover::after", self.css)
        self.assertIn("content: attr(data-full)", self.css)
        self.assertIn("word-break: break-all", self.css)

    def test_07_collapsed_sidebar_hides_tree(self):
        self.assertIn(".app.nav-collapsed .side-kb-tree { display: none; }", self.css)

    def test_08_lazy_load_guard(self):
        self.assertIn("var sideKbLoading = false, sideKbLoaded = false;", self.js)
        self.assertIn("if (!list || sideKbLoading || sideKbLoaded) return;", self.js)
        self.assertIn("if (opening) loadSideKbTree();", self.js)
        self.assertIn("sideKbLoaded = true;", self.js)

    def test_09_reuses_browse_endpoint_and_shows_doc_title(self):
        self.assertIn('/api/kb/browse?limit=200', self.js)
        self.assertIn('data-full", name', self.js)
        self.assertIn('\\.refine\\.md$/i', self.js)
        self.assertIn("kbView.activeDoc = doc.doc_id", self.js)
        self.assertIn('activatePage("kb")', self.js)

    def test_10_i18n_both_languages(self):
        self.assertEqual(self.i18n.count('"sideKb.title"'), 2)
        self.assertIn('"sideKb.title": "文档目录"', self.i18n)
        self.assertIn('"sideKb.title": "Documents"', self.i18n)

    def test_11_shared_active_state(self):
        self.assertIn('document.querySelectorAll(".side-kb-item")', self.js)
        self.assertIn('getAttribute("data-doc-id") === kbView.activeDoc', self.js)


if __name__ == "__main__":
    unittest.main()
