"""
命令行工具 — 网页图片批量下载
用法: python tool.py <URL> [--dir <保存目录>] [--workers <并发数>]
"""
import os
import sys
import json
import argparse
from downloader import download_images_from_page, download_pages_batch
from url_generator import generate_pagination_urls, generate_template_urls
from config import DEFAULT_CONFIG


def main():
    parser = argparse.ArgumentParser(
        description="网页图片批量下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tool.py https://example.com
  python tool.py https://example.com --dir ./my_images --workers 4
  python tool.py --generate-urls "https://example.com/page={page}" --vars '{"page":["1","2","3"]}'
        """,
    )
    parser.add_argument("url", nargs="?", help="目标网页 URL")
    parser.add_argument("--dir", help="图片保存目录")
    parser.add_argument("--workers", type=int, default=8, help="并发下载数 (默认: 8)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    parser.add_argument("--generate-urls", help="URL 模板，配合 --vars 使用")
    parser.add_argument("--vars", help="模板变量 JSON，如 {\"page\":[\"1\",\"2\"]}")
    parser.add_argument("--params", help="分页参数 JSON，如 [{\"name\":\"page\",\"values\":[\"1\",\"2\"]}]")

    args = parser.parse_args()

    # 配置
    config = DEFAULT_CONFIG.copy()
    if args.workers:
        config["max_workers"] = args.workers

    # URL 生成模式
    if args.generate_urls:
        if args.vars:
            vars_map = json.loads(args.vars)
            urls = generate_template_urls(args.generate_urls, vars_map)
        else:
            print("错误: 使用 --generate-urls 时必须提供 --vars")
            sys.exit(1)
        print(f"生成了 {len(urls)} 个 URL:")
        for u in urls:
            print(f"  {u}")
        return

    if args.params:
        params = json.loads(args.params)
        if args.url:
            urls = generate_pagination_urls(args.url, params)
            print(f"生成了 {len(urls)} 个 URL:")
            for u in urls:
                print(f"  {u}")
        else:
            print("错误: 使用 --params 时必须提供 URL")
            sys.exit(1)
        return

    # 下载模式
    if not args.url:
        parser.print_help()
        return

    url = args.url.strip()
    save_dir = args.dir or ""

    print(f"正在处理: {url}")
    print(f"并发数: {config['max_workers']}")
    if save_dir:
        print(f"保存到: {save_dir}")
        result = download_images_from_page(url, save_dir, config)
    else:
        result = download_images_from_page(url, None, config)
        save_dir = result.get("save_dir", "")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n✅ 完成! 总计: {result['total']}, "
              f"成功: {result['success']}, 失败: {result['failed']}")
        if result.get("save_dir"):
            print(f"📁 保存目录: {result['save_dir']}")
        if result.get("error"):
            print(f"⚠️  错误: {result['error']}")
        if result["failed"] > 0:
            print(f"\n失败的图片:")
            for img in result["images"]:
                if not img["success"]:
                    print(f"  ❌ {img['url']} — {img['error']}")


if __name__ == "__main__":
    main()