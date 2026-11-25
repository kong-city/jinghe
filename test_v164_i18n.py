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
    """去掉 // 与 /* */ 注释，避免注释里的文案命中断言（v1.4.0 踩过的坑）。

    先剥行注释再剥块注释：源码里有 "/api/*，成功…" 这类注释，
    若先跑块注释正则会把 `/api/*` 当成块注释起点，一路吞掉后续所有代码
    （v1.7.0 补同源块测试时踩到）。先去掉 `//` 行注释即可规避。
    """
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
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


class UiDiagnosticsTest(unittest.TestCase):
    """v1.7.0：借鉴竞品的界面改造守护——逐文件诊断徽标 + 同源块反向引用。

    两项都必须是纯前端（不新增后端端点），动态文案经 tr() 走 i18n，
    保证切英文时诊断说明与同源块提示也跟着翻译。
    """

    def test_01_per_file_diag_badges(self):
        """预览后的每个文件带处理预期徽标，五档分流类别都有对应诊断。"""
        self.assertIn("KIND_DIAG", JS_CODE)
        for kind in ("文本类", "富文档", "阶段3预留", "需预处理", "不支持"):
            self.assertIn('"%s":' % kind, JS_CODE)
        self.assertIn("file-diag", JS_CODE)
        self.assertIn("badge.addEventListener", JS_CODE)

    def test_02_diag_badges_have_css(self):
        """五档语义色.css 存在，且用浅底深字（不靠渐变）。"""
        for cls in ("diag-ok", "diag-info", "diag-defer", "diag-warn", "diag-stop"):
            self.assertIn("." + cls, CSS)

    def test_03_backlink_in_source_pane(self):
        """来源栏列出同源块，点选在块视图聚焦——纯前端用 kbView.items。"""
        self.assertIn("kb-rel-head", JS_CODE)
        self.assertIn("kb-rel-item", JS_CODE)
        self.assertIn("it.doc_id === item.doc_id", JS_CODE)
        self.assertIn("kbView.activeId = sib.id", JS_CODE)

    def test_04_new_dynamic_text_is_translated(self):
        """新增动态文案全部经 tr()，并在 i18n 字典有英文映射。"""
        for literal in ("tr(diag.label)", "tr(diag.note)", "tr(\"同源块\")",
                        "tr(\"本文暂无其他块\")", "tr(\"诊断\")"):
            self.assertIn(literal, JS_CODE)
        for key in ("可直接提取", "同源块", "音视频·待工具", "注意", "诊断"):
            self.assertIn('"%s"' % key, I18NJS)

    def test_05_no_new_backend_endpoint(self):
        """本轮改造纯前端：不引入新的 API 路径。"""
        self.assertNotIn("/api/kb/backlinks", JS_CODE)
        self.assertNotIn("/api/file/diagnose", JS_CODE)


class UiExperienceV170Test(unittest.TestCase):
    """v1.7.0 视觉翻新 + 命令面板 + 结果前置的守护测试。"""

    def test_01_design_tokens(self):
        """字号/间距/圆角/语义色抽成 CSS 变量，基础字号提到 14px。"""
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        for token in ("--fs-base", "--fs-sm", "--sp-3", "--radius-md",
                      "--c-accent", "--c-surface", "--c-border", "--c-page"):
            self.assertIn(token, css, "缺设计 token：%s" % token)
        self.assertIn("font-size: var(--fs-base)", css, "body 字号未用 token")
        self.assertIn("--fs-base: 14px", css, "基础字号未提到 14px")

    def test_02_dark_theme_overlay(self):
        """深色主题走 html[data-theme] 集中覆写，不改浅色规则。"""
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        self.assertIn('html[data-theme="dark"]', css, "缺深色主题覆写层")
        self.assertIn("color-scheme: dark", css, "深色主题未声明 color-scheme")
        for sel in (".sidebar", ".card", ".text-input", ".btn-primary", ".tabs"):
            self.assertIn('html[data-theme="dark"] ' + sel, css,
                          "深色主题未覆盖：%s" % sel)
        self.assertIn("--c-page: #17191C", css, "深色背景色不符预期")

    def test_03_theme_persisted_whitelisted(self):
        """theme 字段落 settings.json，后端白名单归一化 dark/light，默认 light。"""
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"theme": "light"', app_src, "默认主题不是 light")
        self.assertIn('out["theme"] = "dark" if str(data["theme"])', app_src,
                      "theme 未做白名单归一化")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        # v1.7.1：不再无条件用后端值覆盖，而是先算 theme 变量、再叠加本地覆盖，
        # 最后应用——这样用户刚选的主题不会被后端旧值打回。
        self.assertIn("var theme = settings.theme === \"dark\" ? \"dark\" : \"light\";",
                      js, "设置加载未计算主题")
        self.assertIn("applyTheme(theme);", js, "设置加载未应用主题")
        self.assertIn('theme: (el.setThemeDark && el.setThemeDark.checked)', js,
                      "设置保存未写入 theme")
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="setThemeLight"', html, "缺浅色主题单选")
        self.assertIn('id="setThemeDark"', html, "缺深色主题单选")

    def test_04_command_palette(self):
        """Ctrl+K 命令面板：注册表 + 模糊搜索 + 键盘导航 + 页面跳转。"""
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="cmdOverlay"', html, "缺命令面板容器")
        self.assertIn('id="cmdInput"', html, "缺命令输入框")
        self.assertIn("toggleCmdPalette()", js, "未绑定命令面板开关")
        self.assertIn("e.key === \"k\"", js, "Ctrl+K 未接入")
        self.assertIn("var CMD_ITEMS", js, "缺命令注册表")
        self.assertIn("function cmdMatches", js, "缺模糊搜索")
        self.assertIn("function cmdMove", js, "缺键盘上下导航")
        self.assertIn("function cmdExecuteActive", js, "缺执行入口")
        self.assertIn(".cmd-overlay", css, "缺命令面板样式")
        # 命令面板不能加 data-page（否则破坏 7 个导航入口的测试契约）
        self.assertEqual(html.count('data-page="'), 7, "命令面板误加了 data-page")

    def test_05_result_front_loading(self):
        """提取成功后按钮下方直接给摘要，不必滚到结果 tab。"""
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="doneSummary"', html, "缺结果前置容器")
        self.assertIn("function showDoneSummary", js, "缺结果前置逻辑")
        self.assertIn("if (st === \"done\") showDoneSummary", js,
                      "完成回调未触发结果前置")

    def test_06_nav_active_marker(self):
        """导航当前位置用左侧竖条标识，深浅主题都有。"""
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".nav-item.active::before", css, "缺导航位置标识")
        self.assertIn('html[data-theme="dark"] .nav-item.active::before', css,
                      "深色主题缺导航位置标识")

    def test_07_new_texts_are_translated(self):
        """新增主题/命令面板文案全部有英译映射。"""
        i18n = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")
        for key in ("界面主题", "浅色主题", "深色主题", "知识库检索",
                    "没有匹配的命令", "本次完成", "耗时", "搜索命令"):
            self.assertIn('"%s"' % key, i18n, "新增文案缺英译：%s" % key)


class ThemePersistenceV171Test(unittest.TestCase):
    """v1.7.1：主题/语言点选即落盘，切页回来不再回退。

    缺陷复现：点「深色」只改前端 DOM，从不写 settings.json；
    切到别的功能页再回设置页时，loadSettingsIntoForm() 拉回后端旧值 light，
    applySettings() 覆盖回去 → 界面自己变回浅色。
    """

    def setUp(self):
        self.js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")

    def test_01_theme_change_is_persisted(self):
        """点主题 radio 必须调用 persistUiPref 落盘，不能只改 DOM。"""
        self.assertIn("function persistUiPref", self.js, "缺 persistUiPref")
        self.assertIn(
            'uiPrefOverride.theme = "dark"; persistUiPref("theme", "dark")',
            self.js, "深色主题未落盘")
        self.assertIn(
            'uiPrefOverride.theme = "light"; persistUiPref("theme", "light")',
            self.js, "浅色主题未落盘")

    def test_02_lang_change_is_persisted(self):
        """语言同样点选即落盘（原先也要靠「保存设置」按钮才写）。"""
        self.assertIn(
            'uiPrefOverride.lang = "en"; persistUiPref("lang", "en")',
            self.js, "英文未落盘")
        self.assertIn(
            'uiPrefOverride.lang = "zh"; persistUiPref("lang", "zh")',
            self.js, "中文未落盘")

    def test_03_apply_settings_respects_local_override(self):
        """applySettings 必须优先用本地覆盖值，不能无条件用后端值盖回。"""
        self.assertIn("if (uiPrefOverride.lang) lang = uiPrefOverride.lang;",
                      self.js, "applySettings 未尊重语言覆盖")
        self.assertIn("if (uiPrefOverride.theme) theme = uiPrefOverride.theme;",
                      self.js, "applySettings 未尊重主题覆盖")

    def test_04_persist_only_writes_single_field(self):
        """落盘只回写单个字段，避免冲掉用户未保存的其他表单改动。"""
        self.assertIn("settings[field] = r.settings[field];", self.js,
                      "persistUiPref 应只回写被改的字段")
        self.assertNotIn("settings = r.settings;", self.js,
                         "persistUiPref 不应整体覆盖 settings 对象")

    def test_05_backend_accepts_theme(self):
        """后端设置校验必须认 theme 字段（否则落盘被 _validate_settings 丢掉）。"""
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"theme": "light"', app_src, "默认主题不是 light")
        self.assertIn('if "theme" in data:', app_src, "后端未校验 theme 字段")
        self.assertIn('out["theme"] = "dark"', app_src, "后端未归一化 theme 值")


class LayoutRestructureV171Test(unittest.TestCase):
    """v1.7.1：功能布局借鉴竞品改造。

    借鉴对象与做法：
    - Trilium「加工流程指引」→ 首页流程指引条 + 加工页流水线看板
    - AnythingLLM「产物区常驻可见」→ 首页左右双栏，产物中心进右栏
    - NoteGen「先取后整理」→ 首页三段工作流（取内容 → 加工 → 沉淀）
    """

    def setUp(self):
        self.html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

    def test_01_home_pipeline_strip(self):
        """首页有三段工作流指引条：取内容 / 加工 / 沉淀。"""
        self.assertIn('class="pipeline-strip"', self.html, "缺首页流程指引条")
        for stage in ("取内容", "加工", "沉淀"):
            self.assertIn('data-i18n="%s"' % stage, self.html,
                          "流程指引条缺阶段：%s" % stage)

    def test_02_pipeline_strip_not_confused_with_removed_stepbar(self):
        """不能复活已被用户 2026-11-23 裁决移除的全局步骤条类名。"""
        for sym in (".flow-steps {", ".flow-step {", ".flow-num {"):
            self.assertNotIn(sym, self.css, "全局步骤条样式复活：%s" % sym)
        self.assertNotIn('id="flowSteps"', self.html, "全局步骤条容器复活")
        self.assertNotIn("stepOfPage", self.js, "stepOfPage 应已移除")

    def test_03_pipeline_highlight_follows_page(self):
        """切页时流程条高亮当前阶段。"""
        self.assertIn('querySelectorAll(".strip-step")', self.js,
                      "流程条未绑定高亮逻辑")
        self.assertIn('classList.toggle("is-current"', self.js,
                      "流程条未切换高亮")

    def test_04_artifact_center_moved_into_sidebar(self):
        """产物中心进右栏，不再沉在页面底部。"""
        home = self.html[self.html.index('id="page-home"'):
                         self.html.index('id="page-process"')]
        self.assertIn('id="artifactCenter"', home, "产物中心不在首页")
        # 必须位于 file 面板内（与结果区同列）
        panel = home[home.index('data-extract-panel="file"'):]
        self.assertIn('id="artifactCenter"', panel, "产物中心未进 file 面板")
        # 产物中心必须排在结果区之后（右栏第二格）
        self.assertLess(panel.index('class="card result"'),
                        panel.index('id="artifactCenter"'),
                        "产物中心应排在结果区之后")

    def test_05_home_two_column_grid(self):
        """首页左右双栏：左输入工作区，右产物栏；窄屏回落单列。"""
        self.assertIn('.extract-panel[data-extract-panel="file"]', self.css,
                      "缺首页双栏网格")
        self.assertIn('"work result"', self.css, "缺双栏网格区域定义")
        self.assertIn('"work artifacts"', self.css, "缺产物栏网格区域定义")
        self.assertIn("@media (max-width: 1180px)", self.css,
                      "缺窄屏单列回落")

    def test_06_process_page_pipeline_board(self):
        """加工页升级为流水线看板：三个步骤卡 + 跳转入口。"""
        proc = self.html[self.html.index('id="page-process"'):
                         self.html.index('id="page-kb"')]
        self.assertIn('class="pipeline"', proc, "缺流水线看板")
        self.assertEqual(proc.count('class="pipe-step"'), 3,
                         "流水线看板应有 3 个步骤卡")
        for target in ("refine", "revise", "kb"):
            self.assertIn('data-goto="%s"' % target, proc,
                          "流水线看板缺跳转 %s" % target)

    def test_07_history_batches_collapsed(self):
        """历史批次改为折叠抽屉，默认收起。"""
        self.assertIn('id="historyDrawer"', self.html, "缺历史批次抽屉")
        self.assertIn("<details", self.html, "历史批次未用 details 折叠")
        self.assertIn('id="historyList"', self.html, "历史批次列表丢失")

    def test_08_nav_contract_unchanged(self):
        """本轮是纯布局改造：不新增/删除导航入口，不新增 API。"""
        import re
        pages = re.findall(r'data-page="([^"]+)"', self.html)
        self.assertEqual(len(pages), 7, "导航入口数变了：%s" % pages)
        for p in ("home", "process", "kb", "refine", "revise", "settings", "about"):
            self.assertIn(p, pages, "导航缺 %s" % p)
        # 不引入新的 API 路径
        for api in ("/api/layout", "/api/sidebar", "/api/workspace"):
            self.assertNotIn(api, self.js, "不应新增后端接口 %s" % api)


if __name__ == "__main__":
    unittest.main(verbosity=2)
