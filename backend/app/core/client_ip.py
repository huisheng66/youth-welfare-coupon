"""
可信客户端 IP 解析。

规则（防 X-Forwarded-For 伪造）：
1. TCP 对端若是本机反代（127.0.0.1 / ::1），才读取反代写入的头。
2. 优先 CF-Connecting-IP（Cloudflare 在回源时设置；直连伪造的头在未信任对端时忽略）。
3. 其次 X-Real-IP（Nginx 应设为 $remote_addr；配合 real_ip 模块后为真实访客）。
4. 不使用 X-Forwarded-For 的「第一段」（客户端可控）。
5. 否则退回 TCP 对端地址。
"""
from __future__ import annotations

import ipaddress
import re
from typing import Iterable

from fastapi import Request

# 本机反代（uvicorn 前的 nginx）
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

# Cloudflare 公布的 IPv4/IPv6 回源段（定期可对照 https://www.cloudflare.com/ips/ 更新）
# 用于：仅当「对端」在这些网段内时，才信任 CF-Connecting-IP（直连源站时对端是攻击者 IP，不信任）
_CF_NETWORKS: tuple[ipaddress._BaseNetwork, ...] = tuple(
    ipaddress.ip_network(c)
    for c in (
        # IPv4
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        # IPv6
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)

_IP_RE = re.compile(
    r"^(?:"
    r"(?:\d{1,3}\.){3}\d{1,3}"  # v4
    r"|"
    r"[0-9a-fA-F:]+"  # v6 rough
    r")$"
)


def _parse_ip(value: str | None) -> str | None:
    if not value:
        return None
    s = value.strip().strip("[]")
    # 去掉端口（IPv4:port）
    if s.count(":") == 1 and "." in s:
        s = s.split(":", 1)[0]
    if not s or not _IP_RE.match(s):
        return None
    try:
        ipaddress.ip_address(s)
    except ValueError:
        return None
    return s


def _ip_in_networks(ip: str, networks: Iterable[ipaddress._BaseNetwork]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def is_cloudflare_ip(ip: str) -> bool:
    return _ip_in_networks(ip, _CF_NETWORKS)


def is_loopback_peer(ip: str | None) -> bool:
    if not ip:
        return False
    if ip in _LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    """解析用于限流/审计的客户端 IP（不可被任意 XFF 第一段伪造）。"""
    peer = request.client.host if request.client else None
    peer_ip = _parse_ip(peer) or (peer or "unknown")

    # TestClient / 直连应用：对端即客户端
    if not is_loopback_peer(peer_ip):
        # 对端是公网（含直连源站的攻击者）时：
        # 仅当对端本身是 Cloudflare 才信任 CF-Connecting-IP
        if is_cloudflare_ip(peer_ip):
            cf = _parse_ip(request.headers.get("cf-connecting-ip"))
            if cf:
                return cf
            true_ip = _parse_ip(request.headers.get("true-client-ip"))
            if true_ip:
                return true_ip
        # 直连：忽略客户端伪造的 CF / XFF 头
        return peer_ip

    # 对端是本机 Nginx：可读反代头，但仍不信任 XFF 第一段
    cf = _parse_ip(request.headers.get("cf-connecting-ip"))
    if cf:
        # 可选：校验 X-Real-IP 是否为 CF（Nginx 未做 real_ip 时 X-Real-IP=CF 边缘）
        real = _parse_ip(request.headers.get("x-real-ip"))
        if real is None or is_cloudflare_ip(real) or real == cf:
            return cf
        # real 不是 CF 且与 cf 不同：更可能是直连+伪造 CF 头，信 real（TCP 侧）
        return real

    true_ip = _parse_ip(request.headers.get("true-client-ip"))
    if true_ip:
        return true_ip

    real = _parse_ip(request.headers.get("x-real-ip"))
    if real:
        return real

    # 最后手段：XFF 取最后一段（通常由最近一级反代追加），而非第一段
    xff = request.headers.get("x-forwarded-for") or ""
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if parts:
        last = _parse_ip(parts[-1])
        if last:
            return last

    return peer_ip if peer_ip else "unknown"
