# -*- coding: utf-8 -*-
"""中英切换契约测试（v1.6.4 第一步导航+页头；v1.6.6 扩展到页面正文全量）。

范围：
* 导航（7 按钮 + 4 分组标题）、页头 title/sub、页面正文文案（250 条中文原文 key）；
* placeholder / title / aria-label 三类属性同样接入；
* 语义 key（nav.* / group.* / page.*）与中文原文 key 共存于 I18N.en 字典；
* 语言持久化走 /api/settings 的 lang 字段，白名单 zh/en，默认 zh。
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
I18NJS = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")
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
        self.assertIn("window.JINGHE_I18N = {", I18NJS)
        self.assertIn("var I18N = window.JINGHE_I18N", JS_CODE)
        for lang in ("zh:", "en:"):
            self.assertIn(lang, I18NJS)
        for page in ("home", "process", "refine", "revise", "kb", "settings", "about"):
            self.assertIn('"nav.%s"' % page, I18NJS,
                          "字典缺 nav.%s" % page)
            self.assertIn('"page.%s.title"' % page, I18NJS)
            self.assertIn('"page.%s.sub"' % page, I18NJS)

    def test_06_english_labels_present(self):
        for word in ("Home", "Process", "Refine", "Revise", "Knowledge", "Settings", "About"):
            self.assertIn('"%s"' % word, I18NJS, "英文字典缺 %s" % word)

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

    def test_15_full_page_translation_coverage(self):
        """v1.6.6：正文已全量接入 i18n；中文文本节点必须带标记。"""
        # 1) 导航语义 key 仍在（页头由 JS 动态注入，不落在 HTML 上）
        for key in ("nav.home", "group.source", "nav.about"):
            self.assertIn('data-i18n="%s"' % key, HTML)
        # 2) 正文标记数量应远超第一步的导航+分组（>=150）
        ids = re.findall(r'data-i18n="([^"]+)"', HTML)
        self.assertGreaterEqual(len(ids), 150,
                                "正文 i18n 标记过少，疑似未全量接入: %d" % len(ids))
        # 3) 属性类标记齐备
        self.assertGreaterEqual(HTML.count("data-i18n-ph="), 10, "placeholder 未接入")
        self.assertGreaterEqual(HTML.count("data-i18n-aria="), 20, "aria-label 未接入")
        self.assertGreaterEqual(HTML.count("data-i18n-title="), 20, "title 未接入")

    def test_16_all_chinese_keys_have_english(self):
        """每个中文原文 key 都有对应英文翻译（映射表覆盖）。"""
        sys.path.insert(0, str(ROOT / "tools"))
        from i18n_en_map import EN  # noqa: WPS433
        keys = json.loads((ROOT / "tools" / "i18n_pending_en.json").read_text(encoding="utf-8"))
        missing = [k for k in keys if not EN.get(k)]
        self.assertEqual(missing, [], "缺英文翻译: %s" % missing[:5])
        self.assertGreaterEqual(len(EN), 240, "翻译条数不足")

    def test_17_en_auto_block_in_js(self):
        """生成的英文映射已注入 I18N.en 字典。"""
        self.assertIn("/* I18N_AUTO_BEGIN */", I18NJS)
        self.assertIn("/* I18N_AUTO_END */", I18NJS)
        # 抽查几条翻译确实在独立字典文件里
        self.assertIn('"精核 · 文件提取": "Jinghe · File extraction"', I18NJS)
        self.assertIn('"保存设置": "Save settings"', I18NJS)

    def test_18_apply_lang_handles_attrs(self):
        """applyLang 同时更新 placeholder / aria-label / title。"""
        self.assertIn('querySelectorAll("[data-i18n-ph]")', JS_CODE)
        self.assertIn('querySelectorAll("[data-i18n-aria]")', JS_CODE)
        self.assertIn('setAttribute("placeholder"', JS_CODE)
        self.assertIn('setAttribute("aria-label"', JS_CODE)


class NativeMenuI18nTest(unittest.TestCase):
    """v1.6.6：原生菜单保留但跟随界面语言（菜单可不用、不能没有）。"""

    @classmethod
    def setUpClass(cls):
        cls.main = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        cls.preload = (ROOT / "electron" / "preload.js").read_text(encoding="utf-8")

    def test_01_menu_always_present(self):
        """菜单常驻：启动时构建，绝不再出现 setApplicationMenu(null)。"""
        self.assertNotIn("setApplicationMenu(null)", self.main)
        self.assertIn("buildAppMenu('zh')", self.main)
        self.assertIn("Menu.setApplicationMenu(Menu.buildFromTemplate(template))", self.main)

    def test_02_menu_has_bilingual_labels(self):
        """中英两套菜单标签齐全，覆盖文件/编辑/视图/窗口/帮助。"""
        for lang in ("zh:", "en:"):
            self.assertIn(lang, self.main)
        self.assertIn("file: '文件'", self.main)
        self.assertIn("file: 'File'", self.main)
        self.assertIn("help: '帮助'", self.main)
        self.assertIn("help: 'Help'", self.main)
        self.assertIn("quit: '退出精核'", self.main)
        self.assertIn("quit: 'Quit Jinghe'", self.main)

    def test_03_lang_sync_channel_end_to_end(self):
        """语言同步链路：applyLang → 白名单 setLang → IPC → 重建菜单。"""
        self.assertIn("window.desktopMenu.setLang(currentLang)", JS)
        self.assertIn("menu:set-lang", self.preload)
        self.assertIn("ipcMain.handle('menu:set-lang'", self.main)
        self.assertIn("buildAppMenu(lang)", self.main)

    def test_04_menu_navigate_to_about(self):
        """菜单关于走应用内页面，不用 Electron 原生关于面板。"""
        self.assertIn("menu:navigate", self.main)
        self.assertIn("menu:navigate", self.preload)
        self.assertIn('activatePageInRenderer(\'about\')', self.main)
        self.assertIn('window.desktopMenu.onNavigate', JS)

    def test_05_shell_bridge_is_whitelisted(self):
        """页面拿不到 ipcRenderer，菜单只暴露具名方法且语言值归一化。"""
        self.assertIn("contextBridge.exposeInMainWorld('desktopMenu'", self.preload)
        self.assertNotIn("exposeInMainWorld('desktopMenu', ipcRenderer", self.preload)
        self.assertIn("(lang === 'en') ? 'en' : 'zh'", self.preload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
