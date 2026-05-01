"""
配置文件 — 网页图片批量下载工具（优化版）
支持环境变量和外部配置文件
"""
import os
import json
from typing import Dict, Any

# 默认配置
DEFAULT_CONFIG = {
    # ======== HTTP 请求设置 ========
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "timeout": 10,                    # 请求超时（秒）
    "max_workers": 8,                 # 最大并发下载数
    "retry_times": 3,                 # 下载失败重试次数
    "request_delay": 0,               # 请求间隔（秒），避免被封
    "ssl_verify": True,               # SSL 证书验证
    "follow_redirects": True,         # 是否跟随重定向
    "proxy": "",                      # 代理（留空不使用）

    # ======== 图片过滤设置 ========
    "min_image_size": 1024,           # 最小图片大小（字节），小于此值跳过
    "max_image_size": 0,              # 最大图片大小（字节），0 表示不限制
    "min_image_width": 0,             # 最小图片宽度（像素），0 不限制
    "min_image_height": 0,            # 最小图片高度（像素），0 不限制
    "image_extensions": {              # 支持的图片扩展名
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif"
    },
    "skip_data_urls": True,           # 跳过 data: 协议的 URL
    "only_same_domain": False,        # 只下载同域名下的图片

    # ======== 视频设置 ========
    "video_extensions": {              # 支持的视频扩展名
        ".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".wmv"
    },
    "video_quality": "best",          # 视频质量：best / worst / 具体分辨率如 720p
    "video_format": "mp4",            # 首选视频格式
    "max_video_size": 0,              # 最大视频大小（字节），0 不限制
    "skip_existing_videos": True,     # 跳过已存在的视频文件

    # ======== 音频设置 ========
    "audio_extensions": {              # 支持的音频扩展名
        ".mp3", ".aac", ".wav", ".flac", ".ogg", ".m4a", ".wma", ".opus"
    },
    "audio_format": "mp3",            # 首选音频格式
    "audio_quality": "best",          # 音频质量：best / 128 / 192 / 320 (kbps)

    # ======== 保存设置 ========
    "custom_save_root": "",           # 自定义保存根目录（留空使用 downloaded_images/）
    "create_subfolder_per_page": True, # 每个页面创建独立子文件夹
    "filename_prefix": "",            # 文件名前缀
    "filename_pattern": "original",   # 文件名规则：original(原文件名) / sequential(序号) / hash(哈希)
    "overwrite_existing": False,      # 覆盖已存在的文件
    "save_html": False,               # 同时保存页面 HTML
    "max_images_per_page": 0,         # 每页最大下载图片数，0 不限制

    # ======== 下载完成后行为 ========
    "preview_after_download": True,   # 下载完成后自动预览（展开结果区域）
    "auto_show_result": True,         # 下载完成后自动滚动到结果区域

    # ======== URL 生成设置 ========
    "max_generated_urls": 5000,       # URL 生成数量上限

    # ======== Flask 服务设置 ========
    "port": 5000,
    "debug": False,

    # ======== 缓存设置 ========
    "use_redis": False,               # 是否使用 Redis 缓存
    "redis_host": "localhost",        # Redis 主机
    "redis_port": 6379,              # Redis 端口
    "redis_db": 0,                   # Redis 数据库
    "redis_password": "",             # Redis 密码

    # ======== 日志设置 ========
    "log_level": "INFO",              # 日志级别
    "log_file": "logs/app.log",       # 日志文件路径
}


def _load_from_env(config: Dict[str, Any]) -> Dict[str, Any]:
    """从环境变量加载配置"""
    env_prefix = "PICPILOT_"
    
    for key in config.keys():
        env_key = f"{env_prefix}{key.upper()}"
        if env_key in os.environ:
            value = os.environ[env_key]
            # 尝试转换类型
            if isinstance(config[key], bool):
                config[key] = value.lower() in ("true", "1", "yes")
            elif isinstance(config[key], int):
                try:
                    config[key] = int(value)
                except ValueError:
                    pass
            elif isinstance(config[key], float):
                try:
                    config[key] = float(value)
                except ValueError:
                    pass
            elif isinstance(config[key], set):
                config[key] = set(value.split(","))
            else:
                config[key] = value
    
    return config


def _load_from_file(filepath: str) -> Dict[str, Any]:
    """从 JSON 文件加载配置"""
    if not os.path.exists(filepath):
        return {}
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def load_config(config_file: str = "config.json") -> Dict[str, Any]:
    """
    加载配置（优先级：环境变量 > 配置文件 > 默认值）
    
    Args:
        config_file: 配置文件路径
    
    Returns:
        合并后的配置字典
    """
    # 从文件加载
    file_config = _load_from_file(config_file)
    
    # 合并到默认配置
    config = DEFAULT_CONFIG.copy()
    for key, value in file_config.items():
        if key in config:
            config[key] = value
    
    # 从环境变量覆盖
    config = _load_from_env(config)
    
    return config


def save_config(config: Dict[str, Any], filepath: str = "config.json") -> None:
    """
    保存配置到文件
    
    Args:
        config: 配置字典
        filepath: 保存路径
    """
    # 确保目录存在
    dir_path = os.path.dirname(filepath)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    
    # 转换集合为列表以便序列化
    serializable_config = {}
    for key, value in config.items():
        if isinstance(value, set):
            serializable_config[key] = sorted(value)
        else:
            serializable_config[key] = value
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serializable_config, f, indent=2, ensure_ascii=False)
