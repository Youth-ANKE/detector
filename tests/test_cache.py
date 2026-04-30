"""
缓存模块测试
"""
import pytest
import time
from cache import MemoryCache, CacheManager, url_to_key


class TestMemoryCache:
    """测试内存缓存"""

    def test_cache_set_get(self):
        """测试基本的设置和获取"""
        cache = MemoryCache()
        cache.set("key1", "value1", ttl=3600)
        assert cache.get("key1") == "value1"

    def test_cache_expire(self):
        """测试缓存过期"""
        cache = MemoryCache()
        cache.set("key1", "value1", ttl=0.1)
        assert cache.get("key1") == "value1"
        time.sleep(0.2)
        assert cache.get("key1") is None

    def test_cache_delete(self):
        """测试删除缓存"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        assert cache.exists("key1") is True
        cache.delete("key1")
        assert cache.exists("key1") is False

    def test_cache_exists(self):
        """测试存在性检查"""
        cache = MemoryCache()
        assert cache.exists("nonexistent") is False
        cache.set("key1", "value1")
        assert cache.exists("key1") is True

    def test_cache_clear(self):
        """测试清空缓存"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.exists("key1") is False
        assert cache.exists("key2") is False


class TestCacheManager:
    """测试缓存管理器"""

    def test_cache_manager_get_set(self):
        """测试基本操作"""
        manager = CacheManager(use_redis=False)
        manager.set("test_key", "test_value", ttl=3600)
        assert manager.get("test_key") == "test_value"

    def test_cache_manager_exists(self):
        """测试存在性检查"""
        manager = CacheManager(use_redis=False)
        assert manager.exists("nonexistent") is False
        manager.set("key", "value")
        assert manager.exists("key") is True

    def test_cache_manager_delete(self):
        """测试删除"""
        manager = CacheManager(use_redis=False)
        manager.set("key", "value")
        manager.delete("key")
        assert manager.get("key") is None


class TestUrlToKey:
    """测试 URL 转键函数"""

    def test_url_to_key_consistent(self):
        """测试相同 URL 生成相同的键"""
        url1 = "http://example.com/page1"
        url2 = "http://example.com/page1"
        assert url_to_key(url1) == url_to_key(url2)

    def test_url_to_key_different(self):
        """测试不同 URL 生成不同的键"""
        url1 = "http://example.com/page1"
        url2 = "http://example.com/page2"
        assert url_to_key(url1) != url_to_key(url2)

    def test_url_to_key_length(self):
        """测试键的长度"""
        url = "http://example.com/page"
        key = url_to_key(url)
        assert len(key) == 16
