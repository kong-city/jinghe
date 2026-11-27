#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.8.1 · 组件下载源国内镜像化 + sha256 完整性校验守护。

用户 2026-11-27 裁决：组件尽量从阿里 / 清华等国内大厂镜像站下载，
不走外网；镜像内容必须有固定摘要兜底，防止源被替换后静默安装。
"""
# JINGHE_LAYOUT_BOOTSTRAP
import sys as _jinghe_sys
from pathlib import Path as _jinghe_Path
_jinghe_root = _jinghe_Path(__file__).resolve().parent
for _jinghe_sub in ("core", "media", "knowledge", "link", "subs"):
    _jinghe_p = str(_jinghe_root / _jinghe_sub)
    if _jinghe_p not in _jinghe_sys.path:
        _jinghe_sys.path.insert(0, _jinghe_p)
# END JINGHE_LAYOUT_BOOTSTRAP

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "knowledge"))


class _Resp:
    """模拟 urlopen 响应（支持流式 read 与上下文管理）。"""

    headers = {}

    def __init__(self, payload: bytes):
        self.payload = payload
        self.pos = 0
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, n):
        chunk = self.payload[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestDomesticMirrorSources(unittest.TestCase):
    def setUp(self):
        import components as c
        self.c = c
        self._optin = dict(c._USER_OPT_IN)

    def tearDown(self):
        self.c._USER_OPT_IN.update(self._optin)

    # ---------- 源指向 ---------- #
    def test_01_ffmpeg_uses_aliyun_pypi(self):
        self.assertIn("mirrors.aliyun.com", self.c.FFMPEG_URL)
        self.assertIn("imageio_ffmpeg", self.c.FFMPEG_URL)
        for bad in ("gyan.dev", "github.com", "python.org"):
            self.assertNotIn(bad, self.c.FFMPEG_URL)

    def test_02_runtime_uses_tsinghua_mirror(self):
        self.assertIn("mirrors.tuna.tsinghua.edu.cn", self.c.RUNTIME_URL)
        self.assertIn("embed", self.c.RUNTIME_URL)
        self.assertNotIn("python.org", self.c.RUNTIME_URL)

    def test_03_pip_index_stays_domestic(self):
        self.assertIn("mirrors.aliyun.com", self.c.PIP_INDEX)
        comp = [x for x in self.c.COMPONENTS if x["id"] == "ffmpeg"][0]
        self.assertEqual(comp["url"], self.c.FFMPEG_URL)

    def test_04_no_foreign_download_host_in_components(self):
        for comp in self.c.COMPONENTS:
            url = comp.get("url", "") or ""
            for bad in ("gyan.dev", "python.org/ftp", "github.com",
                        "openaipublic.azureedge.net"):
                self.assertNotIn(bad, url, "%s 仍指向外网 %s" % (comp["id"], bad))

    # ---------- 摘要固定 ---------- #
    def test_05_sha256_constants_are_pinned(self):
        for name in ("FFMPEG_SHA256", "RUNTIME_SHA256"):
            value = getattr(self.c, name)
            self.assertRegex(value, r"^[0-9a-f]{64}$", name)
        comp = [x for x in self.c.COMPONENTS if x["id"] == "ffmpeg"][0]
        self.assertEqual(comp.get("sha256"), self.c.FFMPEG_SHA256)

    def test_06_install_worker_passes_sha256(self):
        import inspect
        src = inspect.getsource(self.c._install_worker)
        self.assertIn('sha256=comp.get("sha256", "")', src)

    def test_07_runtime_download_passes_sha256(self):
        import inspect
        src = inspect.getsource(self.c._ensure_runtime_python)
        self.assertIn("sha256=RUNTIME_SHA256", src)

    # ---------- 校验行为 ---------- #
    def test_08_download_rejects_sha256_mismatch(self):
        """摘要不符必须拒绝，且 .part 被清理、目标文件不落地。"""
        self.c._USER_OPT_IN.update({"granted": True, "component_id": "ffmpeg"})
        good = hashlib.sha256(b"good-content").hexdigest()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "pkg.bin"
            part = dest.with_name(dest.name + ".part")
            with mock.patch.object(self.c.urllib.request, "urlopen",
                                   lambda req, timeout=None: _Resp(b"bad-content")):
                with self.assertRaises(RuntimeError) as ctx:
                    self.c._download("https://example.com/x.bin", dest,
                                     "ffmpeg", sha256=good)
            self.assertIn("校验失败", str(ctx.exception))
            self.assertFalse(dest.exists(), "摘要不符却落盘了")
            self.assertFalse(part.exists(), "摘要不符却残留 .part")

    def test_09_download_accepts_sha256_match(self):
        self.c._USER_OPT_IN.update({"granted": True, "component_id": "ffmpeg"})
        payload = b"good-content"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "pkg.bin"
            with mock.patch.object(self.c.urllib.request, "urlopen",
                                   lambda req, timeout=None: _Resp(payload)):
                self.c._download("https://example.com/x.bin", dest,
                                 "ffmpeg", sha256=digest)
            self.assertEqual(dest.read_bytes(), payload)

    def test_10_download_without_sha256_still_works(self):
        """旧调用方不传摘要时行为不变（向后兼容）。"""
        self.c._USER_OPT_IN.update({"granted": True, "component_id": "ffmpeg"})
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "pkg.bin"
            with mock.patch.object(self.c.urllib.request, "urlopen",
                                   lambda req, timeout=None: _Resp(b"anything")):
                self.c._download("https://example.com/x.bin", dest, "ffmpeg")
            self.assertEqual(dest.read_bytes(), b"anything")

    # ---------- wheel 解压 ---------- #
    def test_11_extract_wheel_style_ffmpeg(self):
        """imageio-ffmpeg wheel 内的 ffmpeg-win-x86_64-v*.exe 必须重命名。"""
        with tempfile.TemporaryDirectory() as td:
            zp = Path(td) / "pkg.zip"
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v9.0.2.exe",
                            b"MZfake-ffmpeg")
                zf.writestr("imageio_ffmpeg/binaries/README", b"doc")
            bindir = Path(td) / "bin"
            old = self.c.BIN_DIR
            self.c.BIN_DIR = bindir
            try:
                result = self.c._extract_ffmpeg(zp)
            finally:
                self.c.BIN_DIR = old
            self.assertIn("ffmpeg.exe", result)
            self.assertEqual((bindir / "ffmpeg.exe").read_bytes(), b"MZfake-ffmpeg")

    def test_12_extract_legacy_zip_still_works(self):
        """原 gyan.dev 布局（bin/ffmpeg.exe）不能退化。"""
        with tempfile.TemporaryDirectory() as td:
            zp = Path(td) / "pkg.zip"
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("ffmpeg-7.1/bin/ffmpeg.exe", b"MZlegacy")
                zf.writestr("ffmpeg-7.1/bin/ffprobe.exe", b"MZprobe")
            bindir = Path(td) / "bin"
            old = self.c.BIN_DIR
            self.c.BIN_DIR = bindir
            try:
                result = self.c._extract_ffmpeg(zp)
            finally:
                self.c.BIN_DIR = old
            self.assertIn("ffmpeg.exe", result)
            self.assertIn("ffprobe.exe", result)

    def test_13_wheel_without_ffmpeg_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            zp = Path(td) / "pkg.zip"
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("README", b"no binary here")
            bindir = Path(td) / "bin"
            old = self.c.BIN_DIR
            self.c.BIN_DIR = bindir
            try:
                with self.assertRaises(RuntimeError):
                    self.c._extract_ffmpeg(zp)
            finally:
                self.c.BIN_DIR = old


if __name__ == "__main__":
    unittest.main()
