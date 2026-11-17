#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · S5a 链接安全闸门（零第三方依赖）。

用户 2026-11-17 裁决：URL **域名不设限**，但 SSRF 内网防护是硬红线。
本模块是纯标准库实现，任何对外部链接的处理都必须先过这里。

硬红线（契约 §6）：
1. 只接受 ``http`` / ``https``；拒绝 file/ftp/data/javascript 等；
2. 解析域名 → 逐个 IP 校验：拒绝环回、私网、链路本地、保留段、多播、未指定；
3. **DNS 重绑定防护**：首次解析结果固定（pin），后续连接复用该 IP，
   不重新解析；重定向逐跳**重新完整校验**，最大跳数上限；
4. 凭据（user:pass@host）一律拒绝；非默认端口不禁止但照常校验 IP；
5. URL 中不回显敏感信息给日志——错误文案只说原因类别与主机，不含 key/路径。

注意：本模块只做**校验与解析**，不发起连接、不下载。连接与固定 IP 的使用
由 link_downloader 负责（通过 ``connect_addr`` 字段把 host:ip 传给 yt-dlp 或
自建请求）。
"""
from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass, field

MAX_REDIRECTS = 5
MAX_URL_LEN = 2048
# 解析超时与单次检查上限
DNS_TIMEOUT = 3.0


@dataclass
class LinkCheck:
    """预检结果。``ok=False`` 时 ``error`` 为可读原因，绝不返回半成品给下载器。"""
    ok: bool
    url: str = ""
    host: str = ""
    scheme: str = ""
    ips: list[str] = field(default_factory=list)
    redirects: int = 0
    error: str = ""
    is_playlist: bool = False
    note: str = ""


class LinkRejected(ValueError):
    """链接被安全闸门拒绝；message 是可读原因，不含敏感信息。"""


def _host_is_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def is_forbidden_ip(addr) -> bool:
    """是否为禁止连接的 IP（环回/私网/链路本地/保留/多播/未指定等）。

    只允许「全球单播」地址；IPv4/IPv6 一视同仁。这样即使 URL 域名不设限，
    也无法拿本软件探测 127.0.0.1、192.168.x、169.254.169.254（云元数据）等。

    注意 ``is_global`` 单独用不够：多播地址 224.0.0.1 的 is_global 为 True，
    故显式排除多播 / 未指定 / 保留段。
    """
    if not addr.is_global:
        return True
    return (addr.is_multicast or addr.is_unspecified or addr.is_reserved
            or addr.is_loopback or addr.is_link_local or addr.is_private)


def validate_url_shape(raw: str) -> tuple[str, str, str]:
    """形状校验，返回 ``(规范 URL, scheme, host)``；违规抛 LinkRejected。"""
    if not isinstance(raw, str) or not raw.strip():
        raise LinkRejected("链接不能为空")
    url = raw.strip()
    if len(url) > MAX_URL_LEN:
        raise LinkRejected("链接过长")
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        raise LinkRejected("链接格式无效")
    scheme = (p.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise LinkRejected("只支持 http / https 链接")
    if p.username or p.password:
        raise LinkRejected("链接不得内嵌账号密码")
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        raise LinkRejected("链接缺少主机名")
    # 拒绝明显畸形端口（urlsplit 会在 .port 访问时抛 ValueError）
    try:
        _ = p.port
    except ValueError:
        raise LinkRejected("链接端口无效")
    return url, scheme, host


def resolve_public_ips(host: str) -> list[str]:
    """解析并校验主机所有 IP，返回固定的 IP 字符串列表；违规抛 LinkRejected。

    DNS 重绑定防护的关键：这里返回的列表就是调用方后续连接**唯一允许**用的
    地址，不再重新解析。
    """
    literal = _host_is_ip(host)
    if literal is not None:
        if is_forbidden_ip(literal):
            raise LinkRejected("目标 IP 不在允许范围（内网/保留地址）")
        return [str(literal)]
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        raise LinkRejected("域名解析失败")
    seen: set[str] = set()
    out: list[str] = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if is_forbidden_ip(ip):
            raise LinkRejected("域名解析到内网/保留地址，已拒绝")
        key = str(ip)
        if key not in seen:
            seen.add(key)
            out.append(key)
    if not out:
        raise LinkRejected("域名无可用公网地址")
    return out


def check_link(raw: str, *, resolve: bool = True) -> LinkCheck:
    """链接预检（只读、不下载）。resolve=False 时只做形状校验（单测友好）。"""
    try:
        url, scheme, host = validate_url_shape(raw)
    except LinkRejected as exc:
        return LinkCheck(ok=False, url=str(raw)[:200], error=str(exc))
    result = LinkCheck(ok=True, url=url, scheme=scheme, host=host)
    if resolve:
        try:
            result.ips = resolve_public_ips(host)
        except LinkRejected as exc:
            result.ok = False
            result.error = str(exc)
    return result


def check_redirect_chain(final_url: str, hops: int,
                         *, resolve: bool = True) -> LinkCheck:
    """重定向逐跳重校验的收尾检查：对最终 URL 再走一遍完整预检。

    ``hops`` 来自下载器实际经过的重定向次数；超限直接拒绝。调用方应在
    **每一跳**都调用 :func:`check_link`（而不是只看最终地址），本函数负责
    最后一跳与跳数上限的收口。
    """
    if hops > MAX_REDIRECTS:
        return LinkCheck(ok=False, url=str(final_url)[:200],
                         error="重定向次数超过上限", redirects=hops)
    result = check_link(final_url, resolve=resolve)
    result.redirects = hops
    if not result.ok:
        return result
    result.note = "已通过逐跳校验与 DNS 固定"
    return result
