"""
日志配置模块
提供结构化日志输出
"""
import os
import logging
import logging.config
from typing import Optional


def configure_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """
    配置日志系统
    
    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        log_file: 日志文件路径，为 None 时仅输出到控制台
        max_file_size: 单个日志文件最大大小（字节）
        backup_count: 保留的备份日志文件数量
    """
    # 创建日志目录
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    
    # 日志格式
    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(funcName)s | %(message)s"
    )
    
    # 结构化日志格式（JSON）
    json_format = (
        '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", '
        '"file": "%(filename)s", "line": %(lineno)d, "func": "%(funcName)s", "message": "%(message)s"}'
    )
    
    handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "level": level,
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        }
    }
    
    if log_file:
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": level,
            "formatter": "json",
            "filename": log_file,
            "maxBytes": max_file_size,
            "backupCount": backup_count,
            "encoding": "utf-8",
        }
    
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": log_format,
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "format": json_format,
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": handlers,
        "loggers": {
            "": {  # root logger
                "handlers": list(handlers.keys()),
                "level": level,
                "propagate": True,
            },
            "app": {
                "handlers": list(handlers.keys()),
                "level": level,
                "propagate": False,
            },
            "downloader": {
                "handlers": list(handlers.keys()),
                "level": level,
                "propagate": False,
            },
            "async_client": {
                "handlers": list(handlers.keys()),
                "level": level,
                "propagate": False,
            },
            "task_manager": {
                "handlers": list(handlers.keys()),
                "level": level,
                "propagate": False,
            },
        },
    })


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志器"""
    return logging.getLogger(name)
