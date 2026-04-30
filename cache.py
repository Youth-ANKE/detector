"""
缓存模块
支持内存缓存和 Redis 缓存
"""
import hashlib
import time
from typing import Optional, Dict, Any, List
from functools import wraps

import redis


class CacheBase:
    """缓存基类"""

    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class MemoryCache(CacheBase):
    """内存缓存实现"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._cache.get(key)
        if item:
            if item["expire_at"] > time.time():
                return item["value"]
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        self._cache[key] = {
            "value": value,
            "expire_at": time.time() + ttl,
            "created_at": time.time(),
        }

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    def exists(self, key: str) -> bool:
        item = self._cache.get(key)
        if item:
            if item["expire_at"] > time.time():
                return True
            else:
                del self._cache[key]
        return False

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self):
        now = time.time()
        # 清理过期项并返回有效项数量
        keys_to_delete = [k for k, v in self._cache.items() if v["expire_at"] <= now]
        for k in keys_to_delete:
            del self._cache[k]
        return len(self._cache)


class RedisCache(CacheBase):
    """Redis 缓存实现"""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: Optional[str] = None):
        self._client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
        )

    def get(self, key: str) -> Optional[Any]:
        value = self._client.get(key)
        if value:
            try:
                import json
                return json.loads(value)
            except:
                return value
        return None

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        import json
        serialized = json.dumps(value)
        self._client.setex(key, ttl, serialized)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def exists(self, key: str) -> bool:
        return self._client.exists(key) > 0

    def clear(self) -> None:
        self._client.flushdb()


class CacheManager:
    """缓存管理器，支持多级缓存"""

    def __init__(self, use_redis: bool = False, redis_config: Optional[Dict[str, Any]] = None):
        self._memory_cache = MemoryCache()
        self._redis_cache: Optional[RedisCache] = None
        
        if use_redis:
            try:
                self._redis_cache = RedisCache(**(redis_config or {}))
                # 测试连接
                self._redis_cache.set("_test_connection", "ok", ttl=10)
            except Exception:
                self._redis_cache = None

    def get(self, key: str) -> Optional[Any]:
        # 先查内存缓存
        value = self._memory_cache.get(key)
        if value is not None:
            return value
        
        # 再查 Redis 缓存
        if self._redis_cache:
            value = self._redis_cache.get(key)
            if value is not None:
                # 同步到内存缓存
                self._memory_cache.set(key, value)
            return value
        
        return None

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        # 同时设置两个缓存
        self._memory_cache.set(key, value, ttl)
        if self._redis_cache:
            self._redis_cache.set(key, value, ttl)

    def delete(self, key: str) -> None:
        self._memory_cache.delete(key)
        if self._redis_cache:
            self._redis_cache.delete(key)

    def exists(self, key: str) -> bool:
        if self._memory_cache.exists(key):
            return True
        if self._redis_cache:
            return self._redis_cache.exists(key)
        return False

    def clear(self) -> None:
        self._memory_cache.clear()
        if self._redis_cache:
            self._redis_cache.clear()


def url_to_key(url: str) -> str:
    """将 URL 转换为缓存键"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def cached(ttl: int = 3600, key_func=None):
    """缓存装饰器"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 生成缓存键
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = f"{func.__name__}_{hash(tuple(args))}_{hash(frozenset(kwargs.items()))}"
            
            # 尝试从缓存获取
            from app import cache_manager
            cached_value = cache_manager.get(key)
            if cached_value is not None:
                return cached_value
            
            # 执行函数并缓存结果
            result = await func(*args, **kwargs)
            cache_manager.set(key, result, ttl)
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = f"{func.__name__}_{hash(tuple(args))}_{hash(frozenset(kwargs.items()))}"
            
            from app import cache_manager
            cached_value = cache_manager.get(key)
            if cached_value is not None:
                return cached_value
            
            result = func(*args, **kwargs)
            cache_manager.set(key, result, ttl)
            return result
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


# 全局缓存管理器实例
import asyncio
cache_manager = CacheManager()
