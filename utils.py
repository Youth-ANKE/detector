import re
import os
import socket
import datetime
import ipaddress
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

# 非公网IP段
_PRIVATE_RANGES = [
    (ipaddress.IPv4Address('10.0.0.0'), ipaddress.IPv4Address('10.255.255.255')),      # 10.0.0.0/8
    (ipaddress.IPv4Address('172.16.0.0'), ipaddress.IPv4Address('172.31.255.255')),    # 172.16.0.0/12
    (ipaddress.IPv4Address('192.168.0.0'), ipaddress.IPv4Address('192.168.255.255')),  # 192.168.0.0/16
    (ipaddress.IPv4Address('127.0.0.0'), ipaddress.IPv4Address('127.255.255.255')),    # 127.0.0.0/8
    (ipaddress.IPv4Address('169.254.0.0'), ipaddress.IPv4Address('169.254.255.255')),  # 169.254.0.0/16
]

def is_safe_url(url: str) -> bool:
    """校验URL是否为公网可访问的 http/https 资源（避免 SSRF）。"""
    url = url.strip()
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except Exception:
        return False
    for family, _, _, _, sockaddr in addrs:
        try:
            if family == socket.AF_INET:
                ip = ipaddress.IPv4Address(sockaddr[0])
                for start, end in _PRIVATE_RANGES:
                    if start <= ip <= end:
                        return False
            elif family == socket.AF_INET6:
                ip6 = ipaddress.IPv6Address(sockaddr[0])
                if ip6.is_private or ip6.is_loopback or ip6.is_link_local or ip6.is_reserved:
                    return False
        except Exception:
            return False
    return True

def sanitize_filename(filename: str) -> str:
    """移除非法文件名字符"""
    filename = re.sub(r'[\\/*?:"<>|]', '', filename)
    return filename[:100].strip() or "untitled"

def generate_folder_name(url: str, config: dict) -> str:
    """根据页面标题+时间戳生成文件夹名"""
    headers = {'User-Agent': config.get('user_agent')}
    timeout = 5
    proxy = config.get('proxy', '')
    proxies = {'http': proxy, 'https': proxy} if proxy else None
    title = None
    try:
        allow_redirects = config.get('follow_redirects', True)
        ssl_verify = config.get('ssl_verify', True)
        resp = requests.get(
            url, headers=headers, timeout=timeout, proxies=proxies,
            allow_redirects=allow_redirects, verify=ssl_verify,
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, 'html.parser')
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            title = sanitize_filename(title)
    except:
        pass
    if not title:
        title = urlparse(url).netloc.replace('.', '_')
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    folder_name = f"{title}_{timestamp}"
    custom_root = config.get('custom_save_root', '').strip()
    if custom_root:
        base = os.path.abspath(custom_root)
    else:
        base = os.path.join(os.getcwd(), 'downloaded_images')
    return os.path.join(base, folder_name)