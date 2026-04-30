"""
URL 生成模块测试
"""
import pytest
from url_generator import (
    expand_range,
    expand_float_range,
    resolve_var_values,
    generate_pagination_urls,
    generate_template_urls,
)


class TestExpandRange:
    """测试范围展开函数"""

    def test_expand_range_basic(self):
        """测试基本整数范围展开"""
        result = expand_range(1, 5)
        assert result == ["1", "2", "3", "4", "5"]

    def test_expand_range_with_step(self):
        """测试带步长的范围展开"""
        result = expand_range(1, 10, 2)
        assert result == ["1", "3", "5", "7", "9"]

    def test_expand_range_reverse(self):
        """测试倒序范围（start > end）"""
        result = expand_range(5, 1)
        assert result == ["1", "2", "3", "4", "5"]

    def test_expand_range_single(self):
        """测试单值范围"""
        result = expand_range(5, 5)
        assert result == ["5"]


class TestExpandFloatRange:
    """测试浮点数范围展开"""

    def test_expand_float_range_basic(self):
        """测试基本浮点数范围"""
        result = expand_float_range(1.0, 3.0, 0.5)
        assert result == ["1.00", "1.50", "2.00", "2.50", "3.00"]

    def test_expand_float_range_decimals(self):
        """测试自定义小数位数"""
        result = expand_float_range(1.0, 2.0, 0.333, decimals=3)
        assert result == ["1.000", "1.333", "1.666", "1.999"]


class TestResolveVarValues:
    """测试变量解析"""

    def test_resolve_var_list(self):
        """测试列表模式"""
        var_def = {"mode": "list", "values": ["a", "b", "c"]}
        result = resolve_var_values(var_def)
        assert result == ["a", "b", "c"]

    def test_resolve_var_range(self):
        """测试范围模式"""
        var_def = {"mode": "range", "start": 1, "end": 3}
        result = resolve_var_values(var_def)
        assert result == ["1", "2", "3"]

    def test_resolve_var_chars(self):
        """测试字符序列模式"""
        var_def = {"mode": "chars", "chars": "abcdef", "start_index": 1, "count": 3}
        result = resolve_var_values(var_def)
        assert result == ["b", "c", "d"]

    def test_resolve_var_string_values(self):
        """测试逗号分隔的字符串值"""
        var_def = {"mode": "list", "values": "x,y,z"}
        result = resolve_var_values(var_def)
        assert result == ["x", "y", "z"]


class TestGeneratePaginationUrls:
    """测试分页URL生成"""

    def test_generate_pagination_single_param(self):
        """测试单个参数生成"""
        base_url = "http://example.com/page"
        params = [{"name": "page", "mode": "range", "start": 1, "end": 3}]
        result = generate_pagination_urls(base_url, params)
        assert len(result) == 3
        assert "page=1" in result[0]
        assert "page=2" in result[1]
        assert "page=3" in result[2]

    def test_generate_pagination_multiple_params(self):
        """测试多个参数组合"""
        base_url = "http://example.com/search"
        params = [
            {"name": "page", "mode": "range", "start": 1, "end": 2},
            {"name": "size", "mode": "list", "values": ["10", "20"]}
        ]
        result = generate_pagination_urls(base_url, params)
        assert len(result) == 4  # 2 * 2 = 4


class TestGenerateTemplateUrls:
    """测试模板URL生成"""

    def test_generate_template_basic(self):
        """测试基本模板替换"""
        template = "http://example.com/{category}/{page}"
        vars_map = {
            "category": {"mode": "list", "values": ["news", "tech"]},
            "page": {"mode": "range", "start": 1, "end": 2}
        }
        result = generate_template_urls(template, vars_map)
        assert len(result) == 4
        assert "news/1" in result[0]
        assert "news/2" in result[1]
        assert "tech/1" in result[2]
        assert "tech/2" in result[3]

    def test_generate_template_with_list_values(self):
        """测试直接列表值"""
        template = "http://example.com/{id}"
        vars_map = {"id": ["100", "200", "300"]}
        result = generate_template_urls(template, vars_map)
        assert len(result) == 3
        assert "100" in result[0]
        assert "200" in result[1]
        assert "300" in result[2]
