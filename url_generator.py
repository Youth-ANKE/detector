"""
URL 批量生成模块
支持：分页参数模式、模板替换模式、范围展开模式
"""
from itertools import product
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import List, Dict, Optional, Union

MAX_URLS = 5000  # 硬限制


def expand_range(start: Union[int, str], end: Union[int, str], step: Union[int, str] = 1) -> List[str]:
    """展开数值范围 [start, end]，步长为 step，返回字符串列表"""
    start = int(start)
    end = int(end)
    step = max(1, int(step))
    # 确保 start <= end，否则反向
    if start > end:
        start, end = end, start
    return [str(i) for i in range(start, end + 1, step)]


def expand_float_range(start: Union[float, str], end: Union[float, str], step: Union[float, str] = 1.0,
                       decimals: int = 2) -> List[str]:
    """展开浮点数范围"""
    start = float(start)
    end = float(end)
    step = abs(float(step))
    if step == 0:
        step = 1.0
    if start > end:
        start, end = end, start
    result = []
    i = 0
    while True:
        val = start + i * step
        if val > end + 1e-9:
            break
        result.append(f"{val:.{decimals}f}")
        i += 1
        if len(result) >= MAX_URLS:
            break
    return result


def resolve_var_values(var_def: dict) -> List[str]:
    """根据变量定义展开值列表"""
    mode = var_def.get("mode", "list")
    if mode == "range":
        start = var_def.get("start", 0)
        end = var_def.get("end", 10)
        step = var_def.get("step", 1)
        var_type = var_def.get("type", "int")
        if var_type == "float":
            decimals = var_def.get("decimals", 2)
            return expand_float_range(start, end, step, decimals)
        else:
            return expand_range(start, end, step)
    elif mode == "list":
        values = var_def.get("values", [])
        if isinstance(values, str):
            # 逗号/换行分隔
            import re
            values = re.split(r'[,\n]+', values.strip())
        return [str(v).strip() for v in values if str(v).strip()]
    elif mode == "chars":
        # 字符序列：如 a-z, A-Z, 0-9 或自定义
        chars = var_def.get("chars", "abcdefghijklmnopqrstuvwxyz")
        start_idx = var_def.get("start_index", 0)
        count = var_def.get("count", len(chars))
        return [c for c in chars[start_idx:start_idx + count]]
    return []


def generate_pagination_urls(base_url: str, params: List[Dict]) -> List[str]:
    """根据基础URL和参数定义列表生成所有URL"""
    parsed = urlparse(base_url)
    existing = parse_qs(parsed.query)

    # 展开每个参数的值列表
    param_names = []
    value_lists = []
    for p in params:
        name = p.get("name", "")
        if not name:
            continue
        param_names.append(name)
        values = resolve_var_values(p)
        if not values:
            values = [""]
        value_lists.append(values)

    if not param_names:
        return []

    urls = []
    for combo in product(*value_lists):
        if len(urls) >= MAX_URLS:
            break
        new_q = existing.copy()
        for name, val in zip(param_names, combo):
            new_q[name] = [val]
        qs = urlencode(new_q, doseq=True)
        full_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path,
                               parsed.params, qs, parsed.fragment))
        urls.append(full_url)
    return urls[:MAX_URLS]


def generate_template_urls(template: str, vars_map: Dict[str, Union[dict, list]]) -> List[str]:
    """根据模板和变量定义生成URL（支持范围/列表两种模式）"""
    import re
    placeholders = re.findall(r'\{(\w+)\}', template)

    keys = []
    value_lists = []
    for ph in placeholders:
        if ph not in keys:
            keys.append(ph)
            var_def = vars_map.get(ph, {"mode": "list", "values": [f"{{{ph}}}"]})
            if isinstance(var_def, list):
                var_def = {"mode": "list", "values": var_def}
            values = resolve_var_values(var_def)
            if not values:
                values = [f"{{{ph}}}"]
            value_lists.append(values)

    urls = []
    for combo in product(*value_lists):
        if len(urls) >= MAX_URLS:
            break
        url = template
        for k, v in zip(keys, combo):
            url = url.replace(f"{{{k}}}", v)
        urls.append(url)
    return urls[:MAX_URLS]