"""脱敏（security/）。

- mask.py：对 input/output 中的敏感信息打码
"""
from __future__ import annotations

import re
from typing import Any

# 内置默认脱敏规则（按设计文档 §5.1）
DEFAULT_MASK_RULES: dict[str, str] = {
    "phone": r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)",     # 手机号：保留前3后4
    "id_card": r"(?<!\d)(\d{6})\d{8}([\dXx])(?!\d)",     # 身份证：保留前6后4
    "email": r"([A-Za-z0-9])[A-Za-z0-9._%+-]*@",          # 邮箱：首字母 + ***@
}


def _mask_phone(m: re.Match[str]) -> str:
    return f"{m.group(1)}****{m.group(2)}"


def _mask_id_card(m: re.Match[str]) -> str:
    return f"{m.group(1)}********{m.group(2)}"


def _mask_email(m: re.Match[str]) -> str:
    return f"{m.group(1)}***@"


def mask_text(
    text: str,
    rules: dict[str, str | list | tuple] | None = None,
) -> str:
    """对文本按规则打码，返回新字符串。

    规则值支持三种形式：
      - str：正则表达式，命中后统一替换为 "***"（默认/内置规则）
      - [pattern, repl] 或 (pattern, repl)：pattern 为正则，repl 为自定义替换
        repl 可为：
          * 字符串：re.sub 替换串语义，可用 \\1、\\g<name> 引用捕获组，实现"保留前N后M"等
          * 可调用对象：re.Match -> str，与内置 _mask_phone 同签名，可完全自定义打码逻辑
    """
    rs = {**DEFAULT_MASK_RULES, **(rules or {})}
    out = text
    for name, spec in rs.items():
        # 解析规则形态：list/tuple → 自定义替换（repl 可为字符串或函数）；str → 统一 ***
        custom = isinstance(spec, (list, tuple))
        if custom:
            pattern, repl = spec[0], spec[1]
        else:
            pattern, repl = spec, "***"
        if name == "phone" and not custom:
            out = re.sub(pattern, _mask_phone, out)
        elif name == "id_card" and not custom:
            out = re.sub(pattern, _mask_id_card, out)
        elif name == "email" and not custom:
            out = re.sub(pattern, _mask_email, out)
        else:
            out = re.sub(pattern, repl, out)  # repl 为 str 或 callable，re.sub 均支持
    return out


def mask_value(value: Any, rules: dict[str, str] | None = None, enabled: bool = True) -> Any:
    """递归遍历 dict/list/str，只对字符串值打码，保留结构。"""
    if not enabled:
        return value
    if isinstance(value, str):
        return mask_text(value, rules)
    if isinstance(value, dict):
        return {k: mask_value(v, rules, enabled) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(v, rules, enabled) for v in value]
    return value
