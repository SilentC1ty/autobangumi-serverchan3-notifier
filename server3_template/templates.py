"""供新集数与系统事件共用的安全变量替换。"""

import re
from collections.abc import Mapping

_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def render_template(template: str, context: Mapping[str, object]) -> str:
    """单次替换简单变量；未知值为空，表达式与未闭合占位符保留原样。"""
    def replace(match: re.Match[str]) -> str:
        """将当前变量转换为文本，不再次解析变量值里的模板。"""
        value = context.get(match.group(1))
        return "" if value is None else str(value)

    return _VARIABLE.sub(replace, template)
