# 网页图片批量下载工具（优化版）

一个强大的网页媒体批量下载工具，支持图片、视频和音频的异步下载，具有Web界面、任务管理和缓存功能。

## 功能特性

- **多媒体下载支持**：支持批量下载网页中的图片、视频和音频文件
- **异步下载**：使用aiohttp实现高并发异步下载，提高下载效率
- **Web界面**：基于Flask的现代化Web界面，支持实时进度查看
- **任务管理**：内置任务队列系统，支持任务状态跟踪和取消
- **智能缓存**：Redis缓存机制，避免重复下载
- **灵活配置**：支持环境变量和配置文件自定义设置
- **Docker支持**：提供Dockerfile和docker-compose.yml，便于部署
- **安全性**：内置安全检查和请求限制
- **日志系统**：完整的日志记录，便于调试和监控

## 技术栈

- **后端**：Python 3.8+, Flask, aiohttp
- **前端**：HTML5, JavaScript, WebSocket
- **数据库**：Redis (缓存), SQLite (任务管理)
- **下载引擎**：yt-dlp (视频/音频), requests/beautifulsoup4 (图片)
- **容器化**：Docker, Docker Compose

## 安装说明

### 环境要求

- Python 3.8 或更高版本
- Redis (可选，用于缓存)
- Docker (可选，用于容器化部署)

### 快速开始

1. **克隆项目**
   ```bash
   git clone https://github.com/Youth-ANKE/detector.git
   cd web2
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **启动Redis (可选)**
   ```bash
   # 如果使用缓存功能，需要启动Redis
   redis-server
   ```

4. **运行应用**
   ```bash
   python app.py
   ```

5. **访问Web界面**
   
   打开浏览器访问 `http://localhost:5000`

### Docker部署

```bash
# 构建并运行
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 使用方法

### Web界面使用

1. 打开浏览器访问应用首页
2. 输入目标网页URL
3. 选择下载类型（图片/视频/音频）
4. 配置下载参数（并发数、过滤条件等）
5. 点击开始下载，实时查看进度

### API接口

应用提供RESTful API接口：

- `POST /api/download/images` - 下载图片
- `POST /api/download/videos` - 下载视频
- `POST /api/download/audios` - 下载音频
- `GET /api/tasks` - 查看任务状态
- `DELETE /api/tasks/{task_id}` - 取消任务

### 命令行使用

```python
from downloader import download_images_from_page

# 下载网页中的所有图片
urls = download_images_from_page("https://example.com")
print(f"找到 {len(urls)} 个图片URL")
```

## 配置说明

### 环境变量

支持以下环境变量配置：

- `FLASK_ENV` - Flask环境 (development/production)
- `REDIS_URL` - Redis连接URL
- `DOWNLOAD_TIMEOUT` - 下载超时时间
- `MAX_WORKERS` - 最大并发数

### 配置文件

编辑 `config.py` 文件自定义配置：

```python
DEFAULT_CONFIG = {
    "max_workers": 8,          # 最大并发下载数
    "timeout": 10,             # 请求超时
    "min_image_size": 1024,    # 最小图片大小
    # ... 更多配置项
}
```

## 项目结构

```
web2/
├── app.py                 # Flask应用主文件
├── async_downloader.py    # 异步下载器
├── downloader.py          # 同步下载器
├── cache.py              # 缓存管理
├── config.py             # 配置文件
├── task_manager.py       # 任务管理
├── logger.py             # 日志配置
├── security.py           # 安全模块
├── url_generator.py      # URL生成器
├── utils.py              # 工具函数
├── index.html            # Web界面
├── requirements.txt      # Python依赖
├── Dockerfile            # Docker镜像
├── docker-compose.yml    # Docker编排
├── tests/                # 测试文件
│   ├── test_cache.py
│   ├── test_security.py
│   └── test_url_generator.py
└── logs/                 # 日志目录
```

## 开发指南

### 运行测试

```bash
pytest tests/
```

### 代码规范

- 使用Black格式化代码
- 使用Flake8检查代码质量
- 遵循PEP 8编码规范

### 贡献

1. Fork项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建Pull Request

## 许可证

本项目采用MIT许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 注意事项

- 请遵守目标网站的robots.txt和使用条款
- 下载大量文件时注意磁盘空间和网络带宽
- 建议在下载前测试小批量文件
- 对于商业用途请评估法律风险

## 更新日志

### v2.0.0 (最新)
- 重构为异步架构，提高并发性能
- 添加WebSocket实时进度更新
- 支持视频和音频下载
- 集成Redis缓存
- Docker容器化支持

---

如有问题或建议，请提交Issue或Pull Request。
