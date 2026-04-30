"""
Flask Web 应用 — 网页图片批量下载工具（优化版）
"""
import os
import json
import threading
import uuid
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sock import Sock

from config import DEFAULT_CONFIG, load_config
from downloader import (
    download_images_from_page, download_pages_batch, download_image as dl_image,
    parse_video_info, download_video, download_videos_batch,
    sniff_media_from_page, download_audio, download_audios_batch, parse_audio_info,
    extract_images_from_page
)
from async_downloader import async_download_images_from_page, async_download_multiple_images
from url_generator import generate_pagination_urls, generate_template_urls, resolve_var_values
from concurrent.futures import ThreadPoolExecutor, as_completed
from cache import cache_manager, url_to_key, cached
from task_manager import task_manager, TaskStatus, TaskType
from logger import configure_logging, get_logger

# 配置日志
configure_logging(level="INFO", log_file="logs/app.log")
logger = get_logger("app")

# 加载配置
app_config = load_config()

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)
sock = Sock(app)

# WebSocket 连接管理
connected_clients = set()
_clients_lock = threading.Lock()


def make_serializable(cfg: dict) -> dict:
    """将配置转换为可 JSON 序列化的格式"""
    result = {}
    for k, v in cfg.items():
        if isinstance(v, set):
            result[k] = sorted(v)
        elif isinstance(v, bytes):
            result[k] = v.decode("utf-8", errors="replace")
        else:
            result[k] = v
    return result


def broadcast_progress(task_id: str, data: dict):
    """向所有连接的客户端广播进度更新"""
    message = json.dumps({"type": "progress", "task_id": task_id, "data": data})
    with _clients_lock:
        for client in list(connected_clients):
            try:
                client.send(message)
            except Exception:
                connected_clients.remove(client)


def update_progress(task_id: str, **kwargs):
    """线程安全的进度更新，同时广播到 WebSocket"""
    task_manager.update_task(task_id, **kwargs)
    task = task_manager.get_task(task_id)
    if task:
        broadcast_progress(task_id, task)


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ── 配置 API ──
@app.route("/api/config", methods=["GET", "POST"])
def config_api():
    global app_config
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict):
            for key, value in data.items():
                if key in app_config:
                    if isinstance(app_config[key], set) and isinstance(value, list):
                        app_config[key] = set(value)
                    elif isinstance(app_config[key], bool):
                        app_config[key] = bool(value) if not isinstance(value, str) else value.lower() in ("true", "1", "yes")
                    elif isinstance(app_config[key], int):
                        app_config[key] = int(value)
                    elif isinstance(app_config[key], float):
                        app_config[key] = float(value)
                    else:
                        app_config[key] = value
            # 保存配置到文件
            from config import save_config
            save_config(app_config)
        return jsonify({"status": "ok", "config": make_serializable(app_config)})
    return jsonify(make_serializable(app_config))


@app.route("/api/default-config", methods=["GET"])
def default_config_api():
    return jsonify(make_serializable(DEFAULT_CONFIG))


# ── URL 生成 API ──
@app.route("/api/generate-urls", methods=["POST"])
def generate_urls():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "pagination")
    try:
        if mode == "template":
            template = data.get("template", "")
            vars_map = data.get("vars", {})
            if not template or not vars_map:
                return jsonify({"status": "error", "message": "模板和变量不能为空"}), 400
            urls = generate_template_urls(template, vars_map)
        else:
            base_url = data.get("base_url", "")
            params = data.get("params", [])
            if not base_url or not params:
                return jsonify({"status": "error", "message": "基础 URL 和参数不能为空"}), 400
            urls = generate_pagination_urls(base_url, params)
        return jsonify({"status": "ok", "urls": urls, "total": len(urls)})
    except Exception as e:
        logger.error(f"生成 URL 失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/resolve-vars", methods=["POST"])
def resolve_vars_api():
    data = request.get_json(silent=True) or {}
    var_def = data.get("var_def", {})
    try:
        values = resolve_var_values(var_def)
        return jsonify({"status": "ok", "values": values, "total": len(values)})
    except Exception as e:
        logger.error(f"解析变量失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── 视频 API ──
@app.route("/api/parse-video", methods=["POST"])
def parse_video():
    data = request.get_json(silent=True) or {}
    video_url = data.get("url", "")
    if not video_url:
        return jsonify({"status": "error", "message": "视频 URL 不能为空"}), 400
    try:
        info = parse_video_info(video_url, app_config)
        if 'error' in info:
            return jsonify({"status": "error", "message": info['error']}), 400
        return jsonify({"status": "ok", "info": info})
    except Exception as e:
        logger.error(f"解析视频信息失败 [{video_url}]: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/download-video", methods=["POST"])
def download_video_api():
    data = request.get_json(silent=True) or {}
    video_url = data.get("url", "")
    save_dir = data.get("save_dir", "")
    if not video_url:
        return jsonify({"status": "error", "message": "视频 URL 不能为空"}), 400
    
    task_id = str(uuid.uuid4())
    task_manager.create_task(task_id, TaskType.VIDEO_DOWNLOAD, {"url": video_url, "save_dir": save_dir})
    task_manager.update_task(task_id, status=TaskStatus.RUNNING.value, progress=0, message="开始下载视频...")
    
    def progress_callback(status, filename):
        if status == "downloading":
            update_progress(task_id, message=f"下载中: {filename}")
        elif status == "finished":
            update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100, message="下载完成")
    
    threading.Thread(
        target=_background_download_video,
        args=(task_id, video_url, save_dir, progress_callback),
        daemon=True
    ).start()
    
    return jsonify({"status": "ok", "task_id": task_id})


def _background_download_video(task_id: str, video_url: str, save_dir: str, progress_callback):
    """后台下载视频"""
    try:
        result = download_video(video_url, save_dir or "downloaded_videos", app_config, progress_callback)
        completed_at = datetime.now().isoformat()
        if result['success']:
            update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100, 
                           message="下载完成", completed_at=completed_at)
        else:
            update_progress(task_id, status=TaskStatus.ERROR.value, message=f"下载失败: {result.get('error', '')}",
                           completed_at=completed_at)
    except Exception as e:
        logger.error(f"视频下载失败 [{video_url}]: {e}")
        update_progress(task_id, status=TaskStatus.ERROR.value, progress=0, message=f"下载失败: {str(e)}",
                       completed_at=datetime.now().isoformat())


@app.route("/api/download-videos-batch", methods=["POST"])
def download_videos_batch_api():
    data = request.get_json(silent=True) or {}
    video_urls = data.get("urls", [])
    save_dir = data.get("save_dir", "")
    if not video_urls:
        return jsonify({"status": "error", "message": "视频 URL 列表不能为空"}), 400
    
    task_id = str(uuid.uuid4())
    task_manager.create_task(task_id, TaskType.VIDEO_DOWNLOAD, {"urls": video_urls, "save_dir": save_dir})
    task_manager.add_task_details(task_id, video_urls)
    task_manager.update_task(task_id, status=TaskStatus.RUNNING.value, progress=0, 
                            message=f"准备下载 {len(video_urls)} 个视频...")
    
    def progress_callback(message, filename):
        update_progress(task_id, message=message)
    
    threading.Thread(
        target=_background_download_videos_batch,
        args=(task_id, video_urls, save_dir, progress_callback),
        daemon=True
    ).start()
    
    return jsonify({"status": "ok", "task_id": task_id})


def _background_download_videos_batch(task_id: str, video_urls: list, save_dir: str, progress_callback):
    """后台批量下载视频"""
    try:
        results = download_videos_batch(video_urls, save_dir or "downloaded_videos", app_config, progress_callback)
        success_count = sum(1 for r in results if r['success'])
        completed_at = datetime.now().isoformat()
        update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100,
                       message=f"批量下载完成，成功 {success_count}/{len(results)}", completed_at=completed_at)
    except Exception as e:
        logger.error(f"批量视频下载失败: {e}")
        update_progress(task_id, status=TaskStatus.ERROR.value, progress=0, 
                       message=f"批量下载失败: {str(e)}", completed_at=datetime.now().isoformat())


# ── 资源嗅探 API ──
@app.route("/api/sniff", methods=["POST"])
def sniff_resource():
    """嗅探页面中的视频和音频资源"""
    data = request.get_json(silent=True) or {}
    page_url = data.get("url", "")
    if not page_url:
        return jsonify({"status": "error", "message": "页面 URL 不能为空"}), 400
    
    # 尝试从缓存获取
    cache_key = url_to_key(f"sniff_{page_url}")
    cached_result = cache_manager.get(cache_key)
    if cached_result:
        return jsonify(cached_result)
    
    try:
        info = sniff_media_from_page(page_url, app_config)
        if info.get("error"):
            return jsonify({"status": "error", "message": info["error"]}), 400
        
        result = {
            "status": "ok",
            "videos": info["videos"],
            "audios": info["audios"],
            "total_videos": len(info["videos"]),
            "total_audios": len(info["audios"])
        }
        
        # 缓存结果
        cache_manager.set(cache_key, result, ttl=300)
        return jsonify(result)
    except Exception as e:
        logger.error(f"资源嗅探失败 [{page_url}]: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── 音频下载 API ──
@app.route("/api/download-audio", methods=["POST"])
def download_audio_api():
    """下载单个音频"""
    data = request.get_json(silent=True) or {}
    audio_url = data.get("url", "")
    save_dir = data.get("save_dir", "")
    if not audio_url:
        return jsonify({"status": "error", "message": "音频 URL 不能为空"}), 400
    
    task_id = str(uuid.uuid4())
    task_manager.create_task(task_id, TaskType.AUDIO_DOWNLOAD, {"url": audio_url, "save_dir": save_dir})
    task_manager.update_task(task_id, status=TaskStatus.RUNNING.value, progress=0, message="开始下载音频...")
    
    def progress_callback(message, filename):
        if "失败" in message:
            update_progress(task_id, message=message)
        elif "完成" in message:
            update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100, message=message)
    
    threading.Thread(
        target=_background_download_audio,
        args=(task_id, audio_url, save_dir, progress_callback),
        daemon=True
    ).start()
    
    return jsonify({"status": "ok", "task_id": task_id})


@app.route("/api/download-audios-batch", methods=["POST"])
def download_audios_batch_api():
    """批量下载音频"""
    data = request.get_json(silent=True) or {}
    audio_urls = data.get("urls", [])
    save_dir = data.get("save_dir", "")
    if not audio_urls:
        return jsonify({"status": "error", "message": "音频 URL 列表不能为空"}), 400
    
    task_id = str(uuid.uuid4())
    task_manager.create_task(task_id, TaskType.AUDIO_DOWNLOAD, {"urls": audio_urls, "save_dir": save_dir})
    task_manager.add_task_details(task_id, audio_urls)
    task_manager.update_task(task_id, status=TaskStatus.RUNNING.value, progress=0,
                            message=f"准备下载 {len(audio_urls)} 个音频...")
    
    def progress_callback(message, filename):
        update_progress(task_id, message=message)
    
    threading.Thread(
        target=_background_download_audios_batch,
        args=(task_id, audio_urls, save_dir, progress_callback),
        daemon=True
    ).start()
    
    return jsonify({"status": "ok", "task_id": task_id})


@app.route("/api/parse-audio", methods=["POST"])
def parse_audio():
    """解析音频信息"""
    data = request.get_json(silent=True) or {}
    audio_url = data.get("url", "")
    if not audio_url:
        return jsonify({"status": "error", "message": "音频 URL 不能为空"}), 400
    try:
        info = parse_audio_info(audio_url, app_config)
        if 'error' in info:
            return jsonify({"status": "error", "message": info['error']}), 400
        return jsonify({"status": "ok", "info": info})
    except Exception as e:
        logger.error(f"解析音频信息失败 [{audio_url}]: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def _background_download_audio(task_id: str, audio_url: str, save_dir: str, progress_callback):
    """后台下载音频"""
    try:
        result = download_audio(audio_url, save_dir or "downloaded_audios", app_config, progress_callback)
        completed_at = datetime.now().isoformat()
        if result['success']:
            update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100, 
                           message="下载完成", completed_at=completed_at)
        else:
            update_progress(task_id, status=TaskStatus.ERROR.value, message=f"下载失败: {result.get('error', '')}",
                           completed_at=completed_at)
    except Exception as e:
        logger.error(f"音频下载失败 [{audio_url}]: {e}")
        update_progress(task_id, status=TaskStatus.ERROR.value, progress=0, 
                       message=f"下载失败: {str(e)}", completed_at=datetime.now().isoformat())


def _background_download_audios_batch(task_id: str, audio_urls: list, save_dir: str, progress_callback):
    """后台批量下载音频"""
    try:
        results = download_audios_batch(audio_urls, save_dir or "downloaded_audios", app_config, progress_callback)
        success_count = sum(1 for r in results if r['success'])
        completed_at = datetime.now().isoformat()
        update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100,
                       message=f"批量下载完成，成功 {success_count}/{len(results)}", completed_at=completed_at)
    except Exception as e:
        logger.error(f"批量音频下载失败: {e}")
        update_progress(task_id, status=TaskStatus.ERROR.value, progress=0,
                       message=f"批量下载失败: {str(e)}", completed_at=datetime.now().isoformat())


# ── 进度跟踪 API ──
@app.route("/api/progress/<task_id>", methods=["GET"])
def get_progress(task_id):
    task = task_manager.get_task(task_id)
    if task is None:
        return jsonify({"status": "error", "message": "任务不存在"}), 404
    return jsonify(task)


@app.route("/api/result/<task_id>", methods=["GET"])
def get_result(task_id):
    task = task_manager.get_task(task_id)
    if task is None:
        return jsonify({"status": "error", "message": "任务不存在"}), 404
    
    # 获取任务详情
    details = task_manager.get_task_details(task_id)
    task["details"] = details
    return jsonify(task)


@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    status = request.args.get("status")
    task_type = request.args.get("type")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))
    
    tasks = task_manager.list_tasks(status=status, task_type=task_type, limit=limit, offset=offset)
    return jsonify({"status": "ok", "tasks": tasks})


@app.route("/api/task/<task_id>", methods=["POST"])
def manage_task(task_id):
    """任务管理：暂停/取消/恢复"""
    action = request.get_json(silent=True).get("action")
    
    if action == "pause":
        success = task_manager.pause_task(task_id)
        return jsonify({"status": "ok" if success else "error", "message": "任务已暂停" if success else "无法暂停任务"})
    elif action == "cancel":
        success = task_manager.cancel_task(task_id)
        return jsonify({"status": "ok" if success else "error", "message": "任务已取消" if success else "无法取消任务"})
    elif action == "resume":
        success = task_manager.resume_task(task_id)
        return jsonify({"status": "ok" if success else "error", "message": "任务已恢复" if success else "无法恢复任务"})
    else:
        return jsonify({"status": "error", "message": "未知操作"}), 400


# ── 异步下载 API ──
@app.route("/api/download-async", methods=["POST"])
def download_async():
    """异步下载图片（使用 aiohttp）"""
    data = request.get_json(silent=True) or {}
    urls = data.get("urls", [])
    save_dir = data.get("save_dir", "")
    
    if not urls:
        return jsonify({"status": "error", "message": "请提供至少一个 URL"}), 400
    
    task_id = str(uuid.uuid4())[:8]
    task_manager.create_task(task_id, TaskType.IMAGE_DOWNLOAD, {"urls": urls, "save_dir": save_dir})
    task_manager.add_task_details(task_id, urls)
    task_manager.update_task(task_id, status=TaskStatus.RUNNING.value, progress=0,
                            message="任务已创建，开始异步下载...")
    
    async def run_async_download():
        try:
            results = await async_download_multiple_images(urls, save_dir, app_config, 
                                                           lambda progress, msg: update_progress(task_id, progress=progress, message=msg))
            success_count = sum(1 for r in results if r["success"])
            completed_at = datetime.now().isoformat()
            update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100,
                           message=f"异步下载完成，成功 {success_count}/{len(results)}", completed_at=completed_at)
        except Exception as e:
            logger.error(f"异步下载失败: {e}")
            update_progress(task_id, status=TaskStatus.ERROR.value, progress=0,
                           message=f"下载失败: {str(e)}", completed_at=datetime.now().isoformat())
    
    # 在单独的线程中运行异步任务
    threading.Thread(target=lambda: asyncio.run(run_async_download()), daemon=True).start()
    
    return jsonify({"status": "ok", "task_id": task_id})


# ── WebSocket 端点 ──
@sock.route('/ws')
def websocket(ws):
    """WebSocket 连接处理"""
    with _clients_lock:
        connected_clients.add(ws)
    
    try:
        while True:
            data = ws.receive()
            if data is None:
                break
            try:
                message = json.loads(data)
                if message.get("type") == "subscribe":
                    task_id = message.get("task_id")
                    task = task_manager.get_task(task_id)
                    if task:
                        ws.send(json.dumps({"type": "progress", "task_id": task_id, "data": task}))
            except json.JSONDecodeError:
                pass
    finally:
        with _clients_lock:
            connected_clients.remove(ws)


def _background_download_pages(task_id: str, urls: list, save_dir: str):
    """后台下载多页图片（带进度报告）"""
    total_urls = len(urls)
    all_results = []
    total_images = 0
    success_images = 0
    failed_images = 0

    update_progress(task_id, status=TaskStatus.RUNNING.value, progress=0,
                   message=f"准备下载 {total_urls} 个页面...",
                   started_at=datetime.now().isoformat())

    for idx, page_url in enumerate(urls):
        # 检查任务状态（是否被暂停或取消）
        task = task_manager.get_task(task_id)
        if task and task["status"] in (TaskStatus.PAUSED.value, TaskStatus.CANCELLED.value):
            update_progress(task_id, message=f"任务已{task['status']}")
            return

        update_progress(task_id, message=f"正在处理: {page_url}")

        try:
            from utils import generate_folder_name
            if not save_dir:
                page_save_dir = generate_folder_name(page_url, app_config)
            else:
                if app_config.get('create_subfolder_per_page', True):
                    page_save_dir = os.path.join(save_dir, f"page_{idx+1}")
                else:
                    page_save_dir = save_dir

            page_result = download_images_from_page(page_url, page_save_dir, app_config,
                                                     progress_callback=lambda msg, file: update_progress(
                                                         task_id, message=msg))
            page_result["page_url"] = page_url
            page_result["save_dir"] = page_save_dir
        except Exception as e:
            logger.error(f"下载页面失败 [{page_url}]: {e}")
            page_result = {
                "page_url": page_url, "total": 0, "success": 0, "failed": 0,
                "images": [], "save_dir": "", "error": str(e)
            }

        all_results.append(page_result)
        total_images += page_result.get("total", 0)
        success_images += page_result.get("success", 0)
        failed_images += page_result.get("failed", 0)

        progress_pct = int((idx + 1) / total_urls * 100)
        update_progress(task_id, progress=progress_pct,
                       message=f"已完成 {idx+1}/{total_urls} 个页面")

    batch_result = {
        "batch": True,
        "pages": all_results,
        "total": total_images,
        "success": success_images,
        "failed": failed_images,
    }
    if not save_dir and all_results:
        batch_result["save_dir"] = all_results[0].get("save_dir", "")

    update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100,
                   message=f"下载完成: 成功 {success_images} / 总计 {total_images}",
                   completed_at=datetime.now().isoformat())


def _background_download_single(task_id: str, page_url: str, save_dir: str):
    """后台下载单页图片"""
    update_progress(task_id, status=TaskStatus.RUNNING.value, progress=0,
                   message=f"正在解析网页: {page_url}...",
                   started_at=datetime.now().isoformat())

    try:
        from utils import generate_folder_name
        if not save_dir:
            save_dir = generate_folder_name(page_url, app_config)

        page_result = download_images_from_page(page_url, save_dir, app_config,
                                                 progress_callback=lambda msg, file: update_progress(
                                                     task_id, message=msg))
        page_result["page_url"] = page_url
        page_result["save_dir"] = save_dir

        update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100,
                       message=f"下载完成: 成功 {page_result['success']} / 总计 {page_result['total']}",
                       completed_at=datetime.now().isoformat())
    except Exception as e:
        logger.error(f"单页下载失败 [{page_url}]: {e}")
        update_progress(task_id, status=TaskStatus.ERROR.value, progress=0,
                       message=str(e), completed_at=datetime.now().isoformat())


def _background_download_direct(task_id: str, image_urls: list, save_dir: str):
    """后台直接下载图片 URL 列表"""
    total = len(image_urls)
    max_workers = app_config.get("max_workers", 8)
    os.makedirs(save_dir, exist_ok=True)

    update_progress(task_id, status=TaskStatus.RUNNING.value, progress=0,
                   message=f"准备下载 {total} 张图片...",
                   started_at=datetime.now().isoformat())

    results = []
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(dl_image, img_url, save_dir, app_config): img_url
            for img_url in image_urls
        }
        for future in as_completed(future_map):
            try:
                result = future.result()
            except Exception as e:
                img_url = future_map[future]
                result = {"url": img_url, "success": False, "filename": "", "error": str(e)}
            results.append(result)
            done += 1
            pct = int(done / total * 100)
            success_count = sum(1 for r in results if r["success"])
            failed_count = sum(1 for r in results if not r["success"])
            update_progress(task_id, progress=pct,
                           message=f"下载中 {done}/{total} 成功: {success_count} 失败: {failed_count}")

    success = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    update_progress(task_id, status=TaskStatus.COMPLETED.value, progress=100,
                   message=f"下载完成: 成功 {len(success)} / 总计 {total}",
                   completed_at=datetime.now().isoformat())


# ── 下载 API ──
@app.route("/api/download", methods=["POST"])
def download():
    """启动下载任务，返回 task_id"""
    data = request.get_json(silent=True) or {}
    urls = data.get("urls", [])
    save_dir = data.get("save_dir", "")

    if not urls:
        return jsonify({"status": "error", "message": "请提供至少一个 URL"}), 400

    task_id = str(uuid.uuid4())[:8]
    task_manager.create_task(task_id, TaskType.BATCH_DOWNLOAD if len(urls) > 1 else TaskType.IMAGE_DOWNLOAD,
                            {"urls": urls, "save_dir": save_dir})
    task_manager.add_task_details(task_id, urls)
    task_manager.update_task(task_id, status=TaskStatus.QUEUED.value, progress=0,
                            message="任务已创建，等待执行...")

    if len(urls) == 1:
        t = threading.Thread(target=_background_download_single, args=(task_id, urls[0], save_dir), daemon=True)
    else:
        t = threading.Thread(target=_background_download_pages, args=(task_id, urls, save_dir), daemon=True)
    t.start()

    return jsonify({"status": "ok", "task_id": task_id})


@app.route("/api/download-urls", methods=["POST"])
def download_urls():
    """直接下载图片 URL 列表"""
    data = request.get_json(silent=True) or {}
    image_urls = data.get("image_urls", [])
    save_dir = data.get("save_dir", "")

    if not image_urls:
        return jsonify({"status": "error", "message": "请提供图片 URL 列表"}), 400

    if not save_dir:
        save_dir = os.path.join(os.getcwd(), "downloaded_images",
                                f"direct_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

    task_id = str(uuid.uuid4())[:8]
    task_manager.create_task(task_id, TaskType.IMAGE_DOWNLOAD, {"urls": image_urls, "save_dir": save_dir})
    task_manager.add_task_details(task_id, image_urls)
    task_manager.update_task(task_id, status=TaskStatus.QUEUED.value, progress=0, message="任务已创建...")

    t = threading.Thread(target=_background_download_direct, args=(task_id, image_urls, save_dir), daemon=True)
    t.start()

    return jsonify({"status": "ok", "task_id": task_id})


# ── 健康检查 API ──
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


if __name__ == "__main__":
    port = app_config.get("port", 5000)
    debug = app_config.get("debug", False)
    print("=" * 60)
    print("  PicPilot - 网页图片批量下载工具 (优化版)")
    print(f"  http://127.0.0.1:{port}")
    print(f"  并发: {app_config['max_workers']} | 超时: {app_config['timeout']}s | 重试: {app_config['retry_times']}次")
    print(f"  日志级别: INFO | 缓存: 已启用 | 任务持久化: SQLite")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=debug)