"""
异步图片下载模块
基于 aiohttp 和 aiofiles 实现高性能异步下载
"""
import asyncio
import hashlib
import os
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiofiles
from bs4 import BeautifulSoup

from async_client import AsyncHTTPClient
from utils import sanitize_filename, is_safe_url
from config import DEFAULT_CONFIG


async def extract_images_from_page_async(
    url: str,
    config: Dict[str, Any] = None,
) -> List[str]:
    """异步从页面中提取所有图片 URL"""
    if config is None:
        config = DEFAULT_CONFIG

    async with AsyncHTTPClient(config) as client:
        try:
            status, content, _ = await client.get(url)
            if status != 200:
                raise RuntimeError(f"HTTP 请求失败 [{url}]: 状态码 {status}")
        except Exception as e:
            raise RuntimeError(f"请求页面失败 [{url}]: {e}")

    soup = BeautifulSoup(content, "html.parser")
    image_urls = []
    page_domain = urlparse(url).netloc

    def should_accept(img_url: str) -> bool:
        if not img_url:
            return False
        if config.get("skip_data_urls", True) and img_url.startswith("data:"):
            return False
        ext = os.path.splitext(urlparse(img_url).path)[1].lower()
        exts = config.get("image_extensions", DEFAULT_CONFIG["image_extensions"])
        if ext not in exts:
            return False
        if config.get("only_same_domain", False):
            return urlparse(img_url).netloc == page_domain
        return True

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        full_url = urljoin(url, src or "").strip() if src else ""
        if should_accept(full_url):
            image_urls.append(full_url)
        srcset = img.get("srcset")
        if srcset:
            for part in srcset.split(','):
                candidate = part.strip().split(' ')[0]
                full_url = urljoin(url, candidate).strip()
                if should_accept(full_url):
                    image_urls.append(full_url)

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        full_url = urljoin(url, href).strip()
        if should_accept(full_url):
            image_urls.append(full_url)

    return sorted(set(image_urls))


async def download_image_async(
    img_url: str,
    save_dir: str,
    config: Dict[str, Any] = None,
    index: int = 0,
) -> Dict[str, Any]:
    """异步下载单张图片"""
    if config is None:
        config = DEFAULT_CONFIG

    # 生成文件名
    parsed = urlparse(img_url)
    basename = os.path.basename(parsed.path)
    if not basename or "." not in basename:
        basename = "image.jpg"
    basename = sanitize_filename(basename)
    
    pattern = config.get("filename_pattern", "original")
    prefix = config.get("filename_prefix", "") or ""

    if pattern == "hash":
        name, ext = os.path.splitext(basename)
        digest = hashlib.sha256(img_url.encode('utf-8')).hexdigest()[:16]
        basename = f"{digest}{ext}"
    elif pattern == "sequential":
        name, ext = os.path.splitext(basename)
        basename = f"{index + 1:03d}{ext}"

    if prefix:
        name, ext = os.path.splitext(basename)
        basename = f"{sanitize_filename(prefix)}_{name}{ext}"

    filepath = os.path.join(save_dir, basename)
    counter = 1
    while os.path.exists(filepath):
        name, ext = os.path.splitext(basename)
        filepath = os.path.join(save_dir, f"{name}_{counter}{ext}")
        counter += 1

    min_size = config.get("min_image_size", 1024)
    retry = config.get("retry_times", 3)

    result = {"url": img_url, "success": False, "filename": "", "error": ""}
    last_error = ""

    for attempt in range(1, retry + 1):
        try:
            async with AsyncHTTPClient(config) as client:
                status, content, headers = await client.get_binary(img_url)
            
            if status != 200:
                last_error = f"HTTP 状态码: {status}"
                continue

            content_type = headers.get("Content-Type", "")
            if "image" not in content_type:
                last_error = f"非图片类型: {content_type}"
                continue

            if len(content) < min_size:
                last_error = f"图片太小: {len(content)} < {min_size} bytes"
                continue

            os.makedirs(save_dir, exist_ok=True)
            async with aiofiles.open(filepath, "wb") as f:
                await f.write(content)

            result["success"] = True
            result["filename"] = os.path.basename(filepath)
            return result

        except Exception as e:
            last_error = str(e)
            if attempt < retry:
                await asyncio.sleep(config.get("request_delay", 0))
            continue

    result["error"] = last_error
    return result


async def async_download_images_from_page(
    page_url: str,
    save_dir: str,
    config: Dict[str, Any] = None,
    progress_callback: Optional[callable] = None,
) -> Dict[str, Any]:
    """异步下载页面中的所有图片"""
    if config is None:
        config = DEFAULT_CONFIG

    max_workers = config.get("max_workers", 8)
    semaphore = asyncio.Semaphore(max_workers)

    if not save_dir:
        from utils import generate_folder_name
        save_dir = generate_folder_name(page_url, config)
    os.makedirs(save_dir, exist_ok=True)

    if progress_callback:
        progress_callback("正在解析网页中的图片链接...", "")
    
    image_urls = await extract_images_from_page_async(page_url, config)
    if not image_urls:
        return {"total": 0, "success": 0, "failed": 0, "images": [], "error": "未找到图片", "save_dir": save_dir}

    max_images = config.get("max_images_per_page", 0)
    if max_images > 0:
        image_urls = image_urls[:max_images]

    results = []
    total = len(image_urls)
    done = 0

    async def download_with_limit(img_url: str, index: int):
        nonlocal done
        async with semaphore:
            result = await download_image_async(img_url, save_dir, config, index)
            results.append(result)
            done += 1
            if progress_callback and (done % max(1, total // 10) == 0 or done == total):
                ok = sum(1 for x in results if x["success"])
                fail = sum(1 for x in results if not x["success"])
                progress_callback(
                    f"下载中 {done}/{total}  成功: {ok}  失败: {fail}",
                    result.get("filename", "")
                )
            return result

    tasks = [download_with_limit(img_url, idx) for idx, img_url in enumerate(image_urls)]
    await asyncio.gather(*tasks)

    success = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    return {
        "total": len(results),
        "success": len(success),
        "failed": len(failed),
        "images": results,
        "error": None,
        "save_dir": save_dir,
    }


async def async_download_multiple_images(
    image_urls: List[str],
    save_dir: str,
    config: Dict[str, Any] = None,
    progress_callback: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """异步批量下载图片 URL 列表"""
    if config is None:
        config = DEFAULT_CONFIG

    max_workers = config.get("max_workers", 8)
    semaphore = asyncio.Semaphore(max_workers)
    
    os.makedirs(save_dir, exist_ok=True)
    
    total = len(image_urls)
    done = 0
    results = []

    async def download_with_limit(img_url: str, index: int):
        nonlocal done
        async with semaphore:
            result = await download_image_async(img_url, save_dir, config, index)
            results.append(result)
            done += 1
            pct = int(done / total * 100)
            if progress_callback:
                progress_callback(pct, f"下载中 {done}/{total}")
            return result

    tasks = [download_with_limit(img_url, idx) for idx, img_url in enumerate(image_urls)]
    await asyncio.gather(*tasks)

    return results
