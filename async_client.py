"""
异步 HTTP 客户端模块
基于 aiohttp 实现高性能异步请求
"""
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple, AsyncGenerator
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp import ClientSession, ClientTimeout, TCPConnector

from utils import is_safe_url

logger = logging.getLogger(__name__)


class AsyncHTTPClient:
    """异步 HTTP 客户端，支持请求频率限制和连接池管理"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._session: Optional[ClientSession] = None
        self._rate_limit_semaphore: Optional[asyncio.Semaphore] = None
        self._request_delay = config.get("request_delay", 0)
        self._max_concurrent = config.get("max_workers", 8)
        self._timeout = ClientTimeout(total=config.get("timeout", 30))

    async def __aenter__(self):
        await self._init_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._close_session()

    async def _init_session(self):
        """初始化 HTTP 会话"""
        connector = TCPConnector(
            limit=self._max_concurrent,
            limit_per_host=self._max_concurrent // 2,
            ssl=self.config.get("ssl_verify", True),
        )
        
        headers = {"User-Agent": self.config.get("user_agent", "")}
        
        self._session = ClientSession(
            connector=connector,
            timeout=self._timeout,
            headers=headers,
            trust_env=True,
        )
        
        # 速率限制信号量
        if self._request_delay > 0:
            self._rate_limit_semaphore = asyncio.Semaphore(1)

    async def _close_session(self):
        """关闭 HTTP 会话"""
        if self._session:
            await self._session.close()
            self._session = None

    async def _apply_rate_limit(self):
        """应用请求频率限制"""
        if self._rate_limit_semaphore:
            async with self._rate_limit_semaphore:
                await asyncio.sleep(self._request_delay)

    async def get(
        self,
        url: str,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        allow_redirects: bool = True,
    ) -> Tuple[int, str, Dict[str, str]]:
        """
        发送 GET 请求
        
        Returns:
            (status_code, content, headers)
        """
        if not is_safe_url(url):
            raise ValueError(f"URL 不安全: {url}")

        await self._apply_rate_limit()
        
        try:
            async with self._session.get(
                url,
                params=params,
                headers=headers,
                allow_redirects=allow_redirects,
                proxy=self.config.get("proxy"),
            ) as resp:
                content = await resp.text(encoding=resp.charset or "utf-8")
                return resp.status, content, dict(resp.headers)
        except Exception as e:
            logger.error(f"GET 请求失败 [{url}]: {e}")
            raise

    async def get_binary(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        allow_redirects: bool = True,
    ) -> Tuple[int, bytes, Dict[str, str]]:
        """
        发送 GET 请求，返回二进制内容
        
        Returns:
            (status_code, content, headers)
        """
        if not is_safe_url(url):
            raise ValueError(f"URL 不安全: {url}")

        await self._apply_rate_limit()
        
        try:
            async with self._session.get(
                url,
                headers=headers,
                allow_redirects=allow_redirects,
                proxy=self.config.get("proxy"),
            ) as resp:
                content = await resp.read()
                return resp.status, content, dict(resp.headers)
        except Exception as e:
            logger.error(f"GET 二进制请求失败 [{url}]: {e}")
            raise

    async def stream_download(
        self,
        url: str,
        chunk_size: int = 8192,
        headers: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[bytes, None]:
        """
        流式下载内容
        
        Yields:
            数据块
        """
        if not is_safe_url(url):
            raise ValueError(f"URL 不安全: {url}")

        await self._apply_rate_limit()
        
        try:
            async with self._session.get(
                url,
                headers=headers,
                proxy=self.config.get("proxy"),
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.content.iter_chunked(chunk_size):
                    yield chunk
        except Exception as e:
            logger.error(f"流式下载失败 [{url}]: {e}")
            raise


async def fetch_page_async(
    url: str,
    config: Dict[str, Any],
    timeout: int = 10,
) -> str:
    """
    异步获取页面内容
    
    Args:
        url: 页面 URL
        config: 配置字典
        timeout: 超时时间（秒）
    
    Returns:
        页面 HTML 内容
    """
    async with AsyncHTTPClient(config) as client:
        status, content, _ = await client.get(url)
        if status != 200:
            raise RuntimeError(f"HTTP 请求失败 [{url}]: 状态码 {status}")
        return content


async def fetch_multiple_pages(
    urls: list[str],
    config: Dict[str, Any],
    max_concurrent: int = 8,
) -> list[Tuple[str, str]]:
    """
    并发获取多个页面
    
    Args:
        urls: URL 列表
        config: 配置字典
        max_concurrent: 最大并发数
    
    Returns:
        (url, content) 元组列表
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def fetch_with_limit(url: str) -> Tuple[str, str]:
        async with semaphore:
            try:
                content = await fetch_page_async(url, config)
                return (url, content)
            except Exception as e:
                logger.error(f"获取页面失败 [{url}]: {e}")
                return (url, "")
    
    tasks = [fetch_with_limit(url) for url in urls]
    return await asyncio.gather(*tasks)