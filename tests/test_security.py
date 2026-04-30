"""
安全模块测试
"""
import pytest
from security import (
    is_safe_url,
    is_safe_path,
    sanitize_path,
    validate_save_path,
    RateLimiter,
    validate_url,
    validate_filename,
)


class TestSSRFProtection:
    """测试 SSRF 防护"""

    def test_safe_public_url(self):
        """测试合法公网 URL"""
        assert is_safe_url("http://example.com/image.jpg") is True
        assert is_safe_url("https://google.com/path") is True

    def test_unsafe_private_ip(self):
        """测试私有 IP 地址"""
        assert is_safe_url("http://192.168.1.1/image.jpg") is False
        assert is_safe_url("http://10.0.0.1/api") is False
        assert is_safe_url("http://127.0.0.1:8080") is False

    def test_unsafe_localhost(self):
        """测试 localhost"""
        assert is_safe_url("http://localhost/image.jpg") is False
        assert is_safe_url("http://localhost:8080") is False

    def test_unsafe_protocol(self):
        """测试非法协议"""
        assert is_safe_url("file:///etc/passwd") is False
        assert is_safe_url("ftp://example.com/file.txt") is False
        assert is_safe_url("data:image/png;base64,xxx") is False

    def test_url_with_port(self):
        """测试带端口的 URL"""
        assert is_safe_url("http://example.com:8080/image.jpg") is True
        assert is_safe_url("https://example.com:443/path") is True
        assert is_safe_url("http://example.com:22") is False  # SSH 端口不在白名单


class TestPathTraversalProtection:
    """测试路径遍历防护"""

    def test_safe_path(self):
        """测试安全路径"""
        base = "/home/user/downloads"
        assert is_safe_path(base, "/home/user/downloads/file.jpg") is True
        assert is_safe_path(base, "/home/user/downloads/subdir/file.jpg") is True

    def test_unsafe_path_traversal(self):
        """测试路径遍历攻击"""
        base = "/home/user/downloads"
        assert is_safe_path(base, "/home/user/file.jpg") is False
        assert is_safe_path(base, "/etc/passwd") is False
        assert is_safe_path(base, "/home/user/downloads/../file.jpg") is False

    def test_sanitize_path(self):
        """测试路径清理"""
        assert sanitize_path("../../etc/passwd") == "etc/passwd"
        assert sanitize_path("/../../../../../etc/passwd") == "etc/passwd"
        assert sanitize_path("valid/path/file.jpg") == "valid/path/file.jpg"

    def test_validate_save_path(self):
        """测试保存路径验证"""
        assert validate_save_path("downloads/images") == "downloads/images"
        
        with pytest.raises(ValueError):
            validate_save_path("../../etc/passwd")


class TestRateLimiter:
    """测试速率限制器"""

    def test_rate_limiter_allow(self):
        """测试允许请求"""
        limiter = RateLimiter(max_requests=5, window_seconds=10)
        for i in range(5):
            assert limiter.allow_request("client1") is True

    def test_rate_limiter_block(self):
        """测试超过限制被阻止"""
        limiter = RateLimiter(max_requests=5, window_seconds=10)
        for i in range(5):
            limiter.allow_request("client1")
        
        # 第 6 次请求应该被阻止
        assert limiter.allow_request("client1") is False

    def test_rate_limiter_get_remaining(self):
        """测试获取剩余请求数"""
        limiter = RateLimiter(max_requests=5, window_seconds=10)
        assert limiter.get_remaining("client1") == 5
        
        limiter.allow_request("client1")
        assert limiter.get_remaining("client1") == 4


class TestInputValidation:
    """测试输入验证"""

    def test_validate_url(self):
        """测试 URL 验证"""
        assert validate_url("http://example.com") is True
        assert validate_url("https://example.com/path") is True
        assert validate_url("ftp://example.com") is False
        assert validate_url("not_a_url") is False
        assert validate_url("") is False

    def test_validate_filename(self):
        """测试文件名验证"""
        assert validate_filename("image.jpg") is True
        assert validate_filename("valid_file_name.png") is True
        assert validate_filename("file/name.jpg") is False  # 包含路径分隔符
        assert validate_filename("..") is False  # 路径遍历
        assert validate_filename("") is False  # 空字符串
        assert validate_filename("*invalid*.txt") is False  # 包含非法字符
