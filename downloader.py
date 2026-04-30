"""
图片下载核心模块
"""
import hashlib
import os
import re
import requests
import time
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import yt_dlp
from utils import sanitize_filename, generate_folder_name, is_safe_url
from config import DEFAULT_CONFIG


def _normalize_image_url(url: str, page_url: str, config: dict) -> str:
    url = url.strip()
    if not url:
        return ""
    if url.startswith('data:'):
        return url
    full_url = urljoin(page_url, url)
    if not is_safe_url(full_url):
        return ""
    return full_url


def _matches_extension(url: str, config: dict) -> bool:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    exts = config.get("image_extensions", DEFAULT_CONFIG["image_extensions"])
    return ext in exts


def extract_images_from_page(url: str, config: dict = None) -> list:
    """从页面中提取所有图片 URL"""
    if config is None:
        config = DEFAULT_CONFIG
    headers = {"User-Agent": config.get("user_agent")}
    timeout = config.get("timeout", 10)
    proxy = config.get("proxy", "")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    allow_redirects = config.get("follow_redirects", True)
    ssl_verify = config.get("ssl_verify", True)

    try:
        resp = requests.get(
            url, headers=headers, timeout=timeout,
            proxies=proxies, allow_redirects=allow_redirects,
            verify=ssl_verify,
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
    except Exception as e:
        raise RuntimeError(f"请求页面失败 [{url}]: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")
    image_urls = []
    page_domain = urlparse(url).netloc

    def should_accept(img_url: str) -> bool:
        if not img_url:
            return False
        if config.get("skip_data_urls", True) and img_url.startswith("data:"):
            return False
        if not _matches_extension(img_url, config):
            return False
        if config.get("only_same_domain", False):
            return urlparse(img_url).netloc == page_domain
        return True

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        full_url = _normalize_image_url(src or "", url, config)
        if should_accept(full_url):
            image_urls.append(full_url)
        srcset = img.get("srcset")
        if srcset:
            for part in srcset.split(','):
                candidate = part.strip().split(' ')[0]
                full_url = _normalize_image_url(candidate, url, config)
                if should_accept(full_url):
                    image_urls.append(full_url)

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        full_url = _normalize_image_url(href, url, config)
        if should_accept(full_url):
            image_urls.append(full_url)

    return sorted(set(image_urls))


def _make_filename(img_url: str, save_dir: str, config: dict, index: int = 0) -> str:
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
    return filepath


def download_image(img_url: str, save_dir: str, config: dict = None, index: int = 0) -> dict:
    """下载单张图片，返回结果信息"""
    if config is None:
        config = DEFAULT_CONFIG
    headers = {"User-Agent": config.get("user_agent")}
    timeout = config.get("timeout", 10)
    min_size = config.get("min_image_size", 1024)
    retry = config.get("retry_times", 3)
    proxy = config.get("proxy", "")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    allow_redirects = config.get("follow_redirects", True)
    ssl_verify = config.get("ssl_verify", True)
    request_delay = config.get("request_delay", 0)

    result = {"url": img_url, "success": False, "filename": "", "error": ""}
    filepath = _make_filename(img_url, save_dir, config, index)

    last_error = ""
    for attempt in range(1, retry + 1):
        try:
            resp = requests.get(
                img_url, headers=headers, timeout=timeout,
                proxies=proxies, allow_redirects=allow_redirects,
                verify=ssl_verify, stream=True,
            )
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type:
                last_error = f"非图片类型: {content_type}"
                continue

            os.makedirs(save_dir, exist_ok=True)
            total_written = 0
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        total_written += len(chunk)

            if total_written < min_size:
                last_error = f"图片太小: {total_written} < {min_size} bytes"
                try:
                    os.remove(filepath)
                except OSError:
                    pass
                continue

            result["success"] = True
            result["filename"] = os.path.basename(filepath)
            return result

        except Exception as e:
            last_error = str(e)
            if request_delay and attempt < retry:
                time.sleep(request_delay)
            continue

    result["error"] = last_error
    return result


def download_images_from_page(
    page_url: str, save_dir: str, config: dict = None,
    progress_callback: callable = None
) -> dict:
    """下载页面中的所有图片"""
    if config is None:
        config = DEFAULT_CONFIG
    max_workers = config.get("max_workers", 8)
    if not save_dir:
        save_dir = generate_folder_name(page_url, config)
    os.makedirs(save_dir, exist_ok=True)

    if progress_callback:
        progress_callback("正在解析网页中的图片链接...", "")
    image_urls = extract_images_from_page(page_url, config)
    if not image_urls:
        return {"total": 0, "success": 0, "failed": 0, "images": [], "error": "未找到图片", "save_dir": save_dir}

    max_images = config.get("max_images_per_page", 0)
    if max_images > 0:
        image_urls = image_urls[:max_images]

    results = []
    total = len(image_urls)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(download_image, img_url, save_dir, config, idx): img_url
            for idx, img_url in enumerate(image_urls)
        }
        for future in as_completed(future_map):
            try:
                r = future.result()
            except Exception as e:
                img_url = future_map[future]
                r = {"url": img_url, "success": False, "filename": "", "error": str(e)}
            results.append(r)
            done += 1
            if progress_callback and (done % max(1, total // 10) == 0 or done == total):
                ok = sum(1 for x in results if x["success"])
                fail = sum(1 for x in results if not x["success"])
                progress_callback(
                    f"下载中 {done}/{total}  成功: {ok}  失败: {fail}",
                    r.get("filename", "")
                )

    if config.get("save_html", False):
        try:
            headers = {"User-Agent": config.get("user_agent")}
            timeout = config.get("timeout", 10)
            proxy = config.get("proxy", "")
            proxies = {"http": proxy, "https": proxy} if proxy else None
            allow_redirects = config.get("follow_redirects", True)
            ssl_verify = config.get("ssl_verify", True)
            resp = requests.get(
                page_url, headers=headers, timeout=timeout,
                proxies=proxies, allow_redirects=allow_redirects,
                verify=ssl_verify,
            )
            if resp.status_code == 200:
                html_path = os.path.join(save_dir, "page.html")
                with open(html_path, "w", encoding=resp.encoding or "utf-8") as f:
                    f.write(resp.text)
        except Exception:
            pass

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


def download_pages_batch(
    urls: list, config: dict = None
) -> list:
    """批量下载多个页面的图片，每个页面一个子文件夹"""
    results = []
    for page_url in urls:
        try:
            save_dir = generate_folder_name(page_url, config or DEFAULT_CONFIG)
            page_result = download_images_from_page(page_url, save_dir, config)
            page_result["page_url"] = page_url
            page_result["save_dir"] = save_dir
            results.append(page_result)
        except Exception as e:
            results.append({
                "page_url": page_url,
                "total": 0,
                "success": 0,
                "failed": 0,
                "images": [],
                "save_dir": "",
                "error": str(e),
            })
    return results


# ── 视频功能 ──

def parse_video_info(video_url: str, config: dict = None) -> dict:
    """解析视频信息，返回视频元数据"""
    if config is None:
        config = DEFAULT_CONFIG
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return {
                'title': info.get('title', 'Unknown'),
                'uploader': info.get('uploader', 'Unknown'),
                'duration': info.get('duration', 0),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', ''),
                'formats': [
                    {
                        'format_id': f.get('format_id'),
                        'ext': f.get('ext'),
                        'resolution': f.get('resolution', 'unknown'),
                        'filesize': f.get('filesize'),
                        'url': f.get('url')
                    } for f in info.get('formats', []) if f.get('ext') in ['mp4', 'webm', 'mkv']
                ],
                'thumbnail': info.get('thumbnail', ''),
                'description': info.get('description', '')[:200] + '...' if info.get('description') else '',
            }
    except Exception as e:
        return {'error': str(e)}


def download_video(video_url: str, save_dir: str, config: dict = None, progress_callback: callable = None) -> dict:
    """下载视频"""
    if config is None:
        config = DEFAULT_CONFIG
    
    quality = config.get('video_quality', 'best')
    format_pref = config.get('video_format', 'mp4')
    max_size = config.get('max_video_size', 0)
    
    ydl_opts = {
        'outtmpl': os.path.join(save_dir, '%(title)s.%(ext)s'),
        'format': f'bestvideo[height<={quality}]+bestaudio/best' if quality != 'best' else 'best',
        'merge_output_format': format_pref,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [lambda d: progress_callback(d.get('status'), d.get('filename', '')) if progress_callback else None],
    }
    
    if max_size > 0:
        ydl_opts['max_filesize'] = max_size
    
    try:
        os.makedirs(save_dir, exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            filename = ydl.prepare_filename(info)
            return {
                'success': True,
                'filename': os.path.basename(filename),
                'title': info.get('title', ''),
                'url': video_url
            }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'url': video_url
        }


def download_videos_batch(video_urls: list, save_dir: str, config: dict = None, progress_callback: callable = None) -> list:
    """批量下载视频"""
    if config is None:
        config = DEFAULT_CONFIG
    
    results = []
    total = len(video_urls)
    done = 0
    
    for video_url in video_urls:
        result = download_video(video_url, save_dir, config, progress_callback)
        results.append(result)
        done += 1
        if progress_callback:
            progress_callback(f"下载中 {done}/{total}", result.get('filename', ''))
    
    return results


# ── 资源嗅探功能 ──

def sniff_media_from_page(page_url: str, config: dict = None) -> dict:
    """从网页中嗅探所有媒体资源（视频、音频）
    
    返回格式:
    {
        "videos": [{"url": "...", "type": "direct|embed|iframe", "page_url": "..."}, ...],
        "audios": [{"url": "...", "type": "direct", "page_url": "..."}, ...],
        "error": None
    }
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    headers = {"User-Agent": config.get("user_agent")}
    timeout = config.get("timeout", 10)
    proxy = config.get("proxy", "")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    allow_redirects = config.get("follow_redirects", True)
    ssl_verify = config.get("ssl_verify", True)
    video_exts = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    audio_exts = config.get("audio_extensions", DEFAULT_CONFIG.get("audio_extensions", {".mp3", ".aac", ".wav", ".flac", ".ogg", ".m4a", ".wma", ".opus"}))
    
    result = {"videos": [], "audios": [], "error": None}
    
    try:
        resp = requests.get(
            page_url, headers=headers, timeout=timeout,
            proxies=proxies, allow_redirects=allow_redirects,
            verify=ssl_verify,
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
    except Exception as e:
        result["error"] = f"请求页面失败: {e}"
        return result
    
    soup = BeautifulSoup(resp.text, "html.parser")
    page_domain = urlparse(page_url).netloc
    
    def _normalize(url_str: str) -> str:
        if not url_str:
            return ""
        url_str = url_str.strip()
        if not url_str or url_str.startswith("data:"):
            return ""
        full = urljoin(page_url, url_str)
        return full
    
    def _get_ext(url_str: str) -> str:
        return os.path.splitext(urlparse(url_str).path)[1].lower()
    
    # 1. 检测 <video> 标签
    for video_tag in soup.find_all("video"):
        # src 属性
        src = video_tag.get("src")
        if src:
            full = _normalize(src)
            if full:
                result["videos"].append({"url": full, "type": "direct", "page_url": page_url})
        # <source> 子标签
        for source in video_tag.find_all("source"):
            ssrc = source.get("src")
            if ssrc:
                full = _normalize(ssrc)
                if full:
                    result["videos"].append({"url": full, "type": "direct", "page_url": page_url})
        # data-* 属性中的视频链接
        for attr, val in video_tag.attrs.items():
            if attr.startswith("data-") and isinstance(val, str) and any(ext in val.lower() for ext in video_exts):
                full = _normalize(val)
                if full:
                    result["videos"].append({"url": full, "type": "direct", "page_url": page_url})
    
    # 2. 检测 <audio> 标签
    for audio_tag in soup.find_all("audio"):
        src = audio_tag.get("src")
        if src:
            full = _normalize(src)
            if full:
                result["audios"].append({"url": full, "type": "direct", "page_url": page_url})
        for source in audio_tag.find_all("source"):
            ssrc = source.get("src")
            if ssrc:
                full = _normalize(ssrc)
                if full:
                    result["audios"].append({"url": full, "type": "direct", "page_url": page_url})
    
    # 3. 检测 <iframe> 嵌入（B站、YouTube 等）
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src")
        if src:
            full = _normalize(src)
            if full:
                # 常见视频平台关键字检测
                video_domains = ["youtube.com", "youtu.be", "bilibili.com", "b23.tv",
                                 "player.bilibili.com", "v.qq.com", "player.youku.com",
                                 "vimeo.com", "dailymotion.com", "tudou.com",
                                 "douyin.com", "ixigua.com"]
                parsed_src = urlparse(full)
                if any(d in parsed_src.netloc for d in video_domains):
                    result["videos"].append({"url": full, "type": "embed", "page_url": page_url})
                else:
                    # 其他 iframe 但包含视频扩展名
                    ext = _get_ext(full)
                    if ext in video_exts:
                        result["videos"].append({"url": full, "type": "direct", "page_url": page_url})
    
    # 4. 检测 <a> 链接指向视频/音频文件
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        full = _normalize(href)
        if not full:
            continue
        ext = _get_ext(full)
        if ext in video_exts:
            # 避免重复
            if not any(v["url"] == full for v in result["videos"]):
                result["videos"].append({"url": full, "type": "direct", "page_url": page_url})
        elif ext in audio_exts:
            if not any(a["url"] == full for a in result["audios"]):
                result["audios"].append({"url": full, "type": "direct", "page_url": page_url})
    
    # 5. 检测 <source> 标签（不在 video/audio 内但引用了媒体文件）
    for source in soup.find_all("source"):
        if source.parent and source.parent.name not in ("video", "audio"):
            ssrc = source.get("src")
            if ssrc:
                full = _normalize(ssrc)
                if not full:
                    continue
                ext = _get_ext(full)
                if ext in video_exts:
                    if not any(v["url"] == full for v in result["videos"]):
                        result["videos"].append({"url": full, "type": "direct", "page_url": page_url})
                elif ext in audio_exts:
                    if not any(a["url"] == full for a in result["audios"]):
                        result["audios"].append({"url": full, "type": "direct", "page_url": page_url})
    
    # 6. 检测页面中可能出现的 JSON-LD / script 中的视频信息 (简单检测)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string)
            # 简单处理 videoObject
            if isinstance(data, dict):
                if data.get("@type") in ("VideoObject", "Video"):
                    content_url = data.get("contentUrl") or data.get("url")
                    if content_url:
                        full = _normalize(str(content_url))
                        if full and not any(v["url"] == full for v in result["videos"]):
                            result["videos"].append({"url": full, "type": "direct", "page_url": page_url})
                elif data.get("@graph"):
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") in ("VideoObject", "Video"):
                            content_url = item.get("contentUrl") or item.get("url")
                            if content_url:
                                full = _normalize(str(content_url))
                                if full and not any(v["url"] == full for v in result["videos"]):
                                    result["videos"].append({"url": full, "type": "direct", "page_url": page_url})
        except (json.JSONDecodeError, AttributeError):
            pass
    
    return result


# ── 音频下载功能 ──

def download_audio(audio_url: str, save_dir: str, config: dict = None, progress_callback: callable = None) -> dict:
    """下载音频（使用 yt-dlp 引擎）"""
    if config is None:
        config = DEFAULT_CONFIG
    
    fmt = config.get("audio_format", "mp3")
    quality = config.get("audio_quality", "best")
    
    # 将 quality 映射为 yt-dlp 的音频比特率
    quality_map = {
        "best": "0",
        "320": "320000",
        "256": "256000",
        "192": "192000",
        "128": "128000",
        "64": "64000",
    }
    audio_quality_val = quality_map.get(str(quality), "0")
    
    ydl_opts = {
        'outtmpl': os.path.join(save_dir, '%(title)s.%(ext)s'),
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': fmt,
            'preferredquality': audio_quality_val,
        }],
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        os.makedirs(save_dir, exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(audio_url, download=True)
            # 提取后的文件名（youtube-dl 添加了扩展名）
            base = ydl.prepare_filename(info)
            base_no_ext = os.path.splitext(base)[0]
            final_filename = f"{os.path.basename(base_no_ext)}.{fmt}"
            
            # 如果 FFmpeg 提取后的文件存在
            if os.path.exists(os.path.join(save_dir, final_filename)):
                pass
            else:
                # 尝试查找实际文件名
                import glob
                matches = glob.glob(os.path.join(save_dir, os.path.basename(base_no_ext) + ".*"))
                if matches:
                    final_filename = os.path.basename(matches[0])
                else:
                    final_filename = os.path.basename(base)
            
            if progress_callback:
                progress_callback("下载完成", final_filename)
            
            return {
                'success': True,
                'filename': final_filename,
                'title': info.get('title', ''),
                'url': audio_url
            }
    except Exception as e:
        if progress_callback:
            progress_callback(f"失败: {str(e)}", "")
        return {
            'success': False,
            'error': str(e),
            'url': audio_url
        }


def download_audios_batch(audio_urls: list, save_dir: str, config: dict = None, progress_callback: callable = None) -> list:
    """批量下载音频"""
    if config is None:
        config = DEFAULT_CONFIG
    
    results = []
    total = len(audio_urls)
    done = 0
    
    for audio_url in audio_urls:
        result = download_audio(audio_url, save_dir, config, progress_callback)
        results.append(result)
        done += 1
        if progress_callback:
            progress_callback(f"下载中 {done}/{total}", result.get('filename', ''))
    
    return results


def parse_audio_info(audio_url: str, config: dict = None) -> dict:
    """解析音频信息（对标 parse_video_info）"""
    if config is None:
        config = DEFAULT_CONFIG
    
    return parse_video_info(audio_url, config)
