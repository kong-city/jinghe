# -*- coding: utf-8 -*-
"""v1.6.4：左上角导航按钮 + 页头的中英切换契约测试。

范围严格限定：
* 第一步只覆盖左上角导航（7 按钮 + 4 分组标题）与页头 title/sub；
* 页面正文仍是中文，不应被整体翻译；
* 语言持久化走 /api/settings 的 lang 字段，白名单 zh/en，默认 zh。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")


def strip_js_comments(src: str) -> str:
    """去掉 // 与 /* */ 注释，避免注释里的文案命中断言（v1.4.0 踩过的坑）。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"//[^\n]*", "", src)
    return src


JS_CODE = strip_js_comments(JS)


class TestV164I18n(unittest.TestCase):

    # ---- 一、HTML 标记 ----
    def test_01_nav_labels_have_i18n_markers(self):
        for page in ("home", "process", "refine", "revise", "kb", "settings", "about"):
            self.assertIn(
                'data-i18n="nav.%s"' % page, HTML,
                "导航 %s 缺 data-i18n 标记" % page)
            self.assertIn(
                'data-i18n-title="nav.%s"' % page, HTML,
                "导航 %s 缺 title 标记" % page)

    def test_02_group_titles_have_i18n_markers(self):
        for key in ("source", "refine-flow", "knowledge", "system"):
            self.assertIn('data-i18n="group.%s"' % key, HTML,
                          "分组标题 %s 缺标记" % key)

    def test_03_nav_labels_still_chinese_by_default(self):
        """默认必须是中文——用户要求的第一步就是「翻译中文」。"""
        for label in ("首页", "加工", "精读", "修订", "知识库", "设置", "关于"):
            self.assertIn('data-i18n="nav.', HTML)
            self.assertIn(">%s</span>" % label, HTML,
                          "默认文案缺中文 %s" % label)

    def test_04_language_switch_present(self):
        for sid in ("setLangZh", "setLangEn"):
            self.assertIn('id="%s"' % sid, HTML, "语言单选缺 %s" % sid)
        self.assertIn('value="zh"', HTML)
        self.assertIn('value="en"', HTML)
        self.assertIn('role="radiogroup"', HTML)

    # ---- 二、JS 字典与应用 ----
    def test_05_i18n_dict_has_all_keys(self):
        self.assertIn("var I18N = {", JS_CODE)
        for lang in ("zh:", "en:"):
            self.assertIn(lang, JS_CODE)
        for page in ("home", "process", "refine", "revise", "kb", "settings", "about"):
            self.assertIn('"nav.%s"' % page, JS_CODE,
                          "字典缺 nav.%s" % page)
            self.assertIn('"page.%s.title"' % page, JS_CODE)
            self.assertIn('"page.%s.sub"' % page, JS_CODE)

    def test_06_english_labels_present(self):
        for word in ("Home", "Process", "Refine", "Revise", "Knowledge", "Settings", "About"):
            self.assertIn('"%s"' % word, JS_CODE, "英文字典缺 %s" % word)

    def test_07_apply_lang_updates_dom(self):
        self.assertIn("function applyLang(lang)", JS_CODE)
        self.assertIn('querySelectorAll("[data-i18n]")', JS_CODE)
        self.assertIn('querySelectorAll("[data-i18n-title]")', JS_CODE)
        self.assertIn('getAttribute("data-i18n")', JS_CODE)

    def test_08_header_follows_current_page_and_lang(self):
        self.assertIn('tr("page." + name + ".title")', JS_CODE)
        self.assertIn('tr("page." + name + ".sub")', JS_CODE)

    def test_09_lang_change_preview_bound(self):
        self.assertIn('el.setLangZh.addEventListener("change"', JS_CODE)
        self.assertIn('el.setLangEn.addEventListener("change"', JS_CODE)
        self.assertIn('applyLang("zh")', JS_CODE)
        self.assertIn('applyLang("en")', JS_CODE)

    def test_10_default_chinese_on_init(self):
        # 注意：JS_CODE 已剥离行尾注释，故只断言可执行语句本身
        self.assertIn('applyLang("zh");', JS_CODE)

    # ---- 三、设置持久化 ----
    def test_11_settings_read_write_lang(self):
        self.assertIn('lang: (el.setLangEn && el.setLangEn.checked) ? "en" : "zh"', JS_CODE)

    def test_12_backend_default_and_whitelist(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"lang": "zh",', app, "后端默认语言应是 zh")
        self.assertIn('if "lang" in data:', app)
        self.assertIn('out["lang"] = "en" if', app, "后端缺 lang 白名单校验")

    # ---- 四、CSS ----
    def test_13_lang_switch_styled(self):
        self.assertIn(".lang-switch", CSS)
        self.assertIn(".lang-opt input:checked + span", CSS)

    # ---- 五、回归护栏 ----
    def test_14_function_attrs_untouched(self):
        """翻译不能动 data-page / data-extract-tab 等功能属性。"""
        self.assertEqual(HTML.count('data-page="'), 7, "导航入口数被改动")
        for tab in ("file", "audio", "video", "sub"):
            self.assertIn('data-extract-tab="%s"' % tab, HTML)
            self.assertNotIn('data-i18n="%s"' % tab, HTML)

    def test_15_no_full_page_translation(self):
        """第一步只翻导航+页头，正文文案的 data-i18n 标记不应出现。"""
        ids = re.findall(r'data-i18n="([^"]+)"', HTML)
        for key in ids:
            self.assertTrue(key.startswith("nav.") or key.startswith("group."),
                            "超出第一步范围: %s" % key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
