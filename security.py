"""
安全模块
提供 SSRF 防护、路径遍历防护、请求速率限制等安全功能
"""
import os
import re
import socket
import time
from typing import Optional, Dict, Set
from collections import defaultdict
from urllib.parse import urlparse

import ipaddress


# ==================== SSRF 防护 ====================

# 非公网IP段
_PRIVATE_RANGES = [
    (ipaddress.IPv4Address('10.0.0.0'), ipaddress.IPv4Address('10.255.255.255')),      # 10.0.0.0/8
    (ipaddress.IPv4Address('172.16.0.0'), ipaddress.IPv4Address('172.31.255.255')),    # 172.16.0.0/12
    (ipaddress.IPv4Address('192.168.0.0'), ipaddress.IPv4Address('192.168.255.255')),  # 192.168.0.0/16
    (ipaddress.IPv4Address('127.0.0.0'), ipaddress.IPv4Address('127.255.255.255')),    # 127.0.0.0/8
    (ipaddress.IPv4Address('169.254.0.0'), ipaddress.IPv4Address('169.254.255.255')),  # 169.254.0.0/16
    (ipaddress.IPv4Address('0.0.0.0'), ipaddress.IPv4Address('0.255.255.255')),        # 0.0.0.0/8
    (ipaddress.IPv4Address('224.0.0.0'), ipaddress.IPv4Address('239.255.255.255')),    # 多播地址
]

# 允许的端口白名单
ALLOWED_PORTS = {80, 443, 8080, 8443}

# 域名白名单（可选）
DOMAIN_WHITELIST: Set[str] = set()


def is_private_ip(ip: ipaddress.IPv4Address) -> bool:
    """检查 IP 是否为私有地址"""
    for start, end in _PRIVATE_RANGES:
        if start <= ip <= end:
            return True
    return False


def is_safe_url(url: str, check_port: bool = True) -> bool:
    """
    校验 URL 是否为公网可访问的 http/https 资源（避免 SSRF）
    
    Args:
        url: 待校验的 URL
        check_port: 是否检查端口白名单
    
    Returns:
        True 表示安全，False 表示危险
    """
    url = url.strip()
    if not url:
        return False
    
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    
    # 检查协议
    if parsed.scheme not in ('http', 'https'):
        return False
    
    hostname = parsed.hostname
    if not hostname:
        return False
    
    # 检查是否为 localhost 变体
    localhost_variants = {'localhost', '127.0.0.1', '0.0.0.0', '::1', 'localhost.localdomain'}
    if hostname.lower() in localhost_variants:
        return False
    
    # 解析 IP 地址
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except Exception:
        return False
    
    for family, _, _, _, sockaddr in addrs:
        try:
            if family == socket.AF_INET:
                ip = ipaddress.IPv4Address(sockaddr[0])
                if is_private_ip(ip):
                    return False
            elif family == socket.AF_INET6:
                ip6 = ipaddress.IPv6Address(sockaddr[0])
                if ip6.is_private or ip6.is_loopback or ip6.is_link_local or ip6.is_reserved:
                    return False
        except Exception:
            return False
    
    # 检查端口（如果启用）
    if check_port and parsed.port:
        if parsed.port not in ALLOWED_PORTS:
            return False
    
    # 检查域名白名单（如果配置了）
    if DOMAIN_WHITELIST:
        if hostname not in DOMAIN_WHITELIST:
            return False
    
    return True


def set_domain_whitelist(domains: Set[str]) -> None:
    """设置域名白名单"""
    global DOMAIN_WHITELIST
    DOMAIN_WHITELIST = domains


# ==================== 路径遍历防护 ====================

def is_safe_path(base_path: str, target_path: str) -> bool:
    """
    检查目标路径是否在基础路径之下（防止路径遍历攻击）
    
    Args:
        base_path: 允许访问的基础目录
        target_path: 用户请求的目标路径
    
    Returns:
        True 表示安全，False 表示存在路径遍历风险
    """
    # 规范化路径
    base_abs = os.path.abspath(base_path)
    target_abs = os.path.abspath(target_path)
    
    # 检查目标路径是否以基础路径开头
    return target_abs.startswith(base_abs + os.sep) or target_abs == base_abs


def sanitize_path(path: str) -> str:
    """
    清理路径，移除可能导致路径遍历的字符
    
    Args:
        path: 待清理的路径
    
    Returns:
        清理后的安全路径
    """
    # 移除 .. 和绝对路径前缀
    path = re.sub(r'(\.\.[/\\])+', '', path)
    path = re.sub(r'^[/\\]+', '', path)
    return path


def validate_save_path(save_path: str, allowed_base: Optional[str] = None) -> str:
    """
    验证并清理保存路径
    
    Args:
        save_path: 用户提供的保存路径
        allowed_base: 允许的基础目录（默认为当前工作目录）
    
    Returns:
        验证通过的安全路径
    
    Raises:
        ValueError: 如果路径不安全
    """
    if not save_path:
        return save_path
    
    # 清理路径
    clean_path = sanitize_path(save_path)
    
    # 检查路径遍历
    if '..' in clean_path:
        raise ValueError("路径包含非法字符")
    
    # 如果指定了允许的基础目录，检查是否在范围内
    if allowed_base:
        if not is_safe_path(allowed_base, clean_path):
            raise ValueError("路径超出允许范围")
    
    return clean_path


# ==================== 请求速率限制 ====================

class RateLimiter:
    """
    请求速率限制器
    使用滑动窗口算法实现
    """
    
    def __init__(self, max_requests: int, window_seconds: int = 60):
        """
        初始化速率限制器
        
        Args:
            max_requests: 时间窗口内最大请求数
            window_seconds: 时间窗口大小（秒）
        """
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._client_requests: Dict[str, list] = defaultdict(list)
        self._lock = __import__('threading').Lock()
    
    def _clean_old_requests(self, timestamps: list) -> list:
        """清理时间窗口外的请求记录"""
        cutoff = time.time() - self._window_seconds
        return [ts for ts in timestamps if ts >= cutoff]
    
    def allow_request(self, client_id: str) -> bool:
        """
        检查是否允许请求
        
        Args:
            client_id: 客户端标识（通常是 IP 地址）
        
        Returns:
            True 表示允许请求，False 表示超过速率限制
        """
        with self._lock:
            timestamps = self._client_requests[client_id]
            timestamps = self._clean_old_requests(timestamps)
            
            if len(timestamps) >= self._max_requests:
                return False
            
            timestamps.append(time.time())
            self._client_requests[client_id] = timestamps
            return True
    
    def get_remaining(self, client_id: str) -> int:
        """
        获取剩余可用请求数
        
        Args:
            client_id: 客户端标识
        
        Returns:
            剩余请求数
        """
        with self._lock:
            timestamps = self._client_requests[client_id]
            timestamps = self._clean_old_requests(timestamps)
            return max(0, self._max_requests - len(timestamps))
    
    def reset(self, client_id: str) -> None:
        """重置指定客户端的请求计数"""
        with self._lock:
            self._client_requests[client_id] = []


# 创建全局速率限制器实例
# 默认：每分钟最多 100 次请求
global_rate_limiter = RateLimiter(max_requests=100, window_seconds=60)


def get_client_ip(request) -> str:
    """
    从请求中获取客户端真实 IP 地址
    
    Args:
        request: Flask 请求对象
    
    Returns:
        客户端 IP 地址
    """
    # 检查代理头部
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    
    x_real_ip = request.headers.get('X-Real-IP')
    if x_real_ip:
        return x_real_ip
    
    return request.remote_addr


# ==================== XSS 防护 ====================

def sanitize_html(content: str) -> str:
    """
    清理 HTML 内容，移除危险标签和属性
    
    Args:
        content: 待清理的 HTML 内容
    
    Returns:
        安全的 HTML 内容
    """
    if not content:
        return content
    
    # 移除 script 标签
    content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
    
    # 移除 on* 事件属性
    content = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', content, flags=re.IGNORECASE)
    
    # 移除 javascript: 伪协议
    content = re.sub(r'href\s*=\s*["\']javascript:[^"\']*["\']', '', content, flags=re.IGNORECASE)
    
    return content


# ==================== 输入验证 ====================

def validate_url(url: str) -> bool:
    """
    验证 URL 格式是否合法
    
    Args:
        url: 待验证的 URL
    
    Returns:
        True 表示格式合法，False 表示非法
    """
    if not url or not isinstance(url, str):
        return False
    
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https') and parsed.netloc
    except Exception:
        return False


def validate_filename(filename: str) -> bool:
    """
    验证文件名是否合法
    
    Args:
        filename: 待验证的文件名
    
    Returns:
        True 表示合法，False 表示包含非法字符
    """
    if not filename or not isinstance(filename, str):
        return False
    
    # 检查非法字符
    illegal_chars = r'[\\/*?:"<>|]'
    if re.search(illegal_chars, filename):
        return False
    
    # 检查是否为空或仅包含空白
    if not filename.strip():
        return False
    
    # 检查路径遍历
    if '..' in filename:
        return False
    
    return True
