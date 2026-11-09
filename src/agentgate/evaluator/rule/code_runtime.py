"""Bounded Python-syntax rule interpreter; never compiles or executes user Python.

This module also runs as an isolated child process using only the standard library.
The language deliberately has no imports, arbitrary attributes, or user-defined calls.
"""

import ast
import json
import math
import operator
import sys

MAX_SOURCE = 16384
MAX_INPUT = 1048576
MAX_ITEMS = 4096
MAX_STEPS = 20000
CALLS = {"len", "sum", "min", "max", "abs", "round", "any", "all", "EvalOutput"}
METHODS = {"get", "count", "startswith", "endswith", "lower", "upper", "strip"}
NODES = (
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign,
    ast.AugAssign, ast.For, ast.If, ast.Expr, ast.Name, ast.Load, ast.Store,
    ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Call,
    ast.keyword, ast.Attribute, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.BinOp,
    ast.IfExp, ast.ListComp, ast.comprehension, ast.Add, ast.Sub, ast.Mult,
    ast.Div, ast.Mod, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Is, ast.IsNot,
)


def parse_source(source):
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > MAX_SOURCE:
        raise ValueError("规则代码不能为空，且不能超过 16 KB")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"第 {exc.lineno} 行语法错误：{exc.msg}") from exc
    except RecursionError as exc:
        raise ValueError("规则代码嵌套过深") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("仅允许定义一个 exec_evaluation(trace) 函数")
    function = tree.body[0]
    args = function.args
    if (function.name != "exec_evaluation" or len(args.args) != 1
            or args.args[0].arg not in {"turn_data", "trace"} or args.posonlyargs or args.kwonlyargs
            or args.vararg or args.kwarg or args.defaults or function.decorator_list
            or function.returns or args.args[0].annotation):
        raise ValueError("函数签名必须为 def exec_evaluation(trace):（旧规则可使用 turn_data）")
    nodes = list(ast.walk(tree))
    if len(nodes) > 2000:
        raise ValueError("规则代码过于复杂")
    for node in nodes:
        if not isinstance(node, NODES) or (isinstance(node, ast.FunctionDef) and node is not function):
            raise ValueError(f"第 {getattr(node, 'lineno', 1)} 行：不支持 {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("不允许访问私有名称")
        if isinstance(node, ast.Attribute) and node.attr not in METHODS:
            raise ValueError(f"不允许访问属性 {node.attr}")
        if isinstance(node, ast.Call):
            if not ((isinstance(node.func, ast.Name) and node.func.id in CALLS)
                    or (isinstance(node.func, ast.Attribute) and node.func.attr in METHODS)):
                raise ValueError("仅允许调用受支持的内置函数和数据方法")
            if any(kw.arg is None for kw in node.keywords):
                raise ValueError("不支持展开关键字参数")
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.For, ast.comprehension)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(not isinstance(target, ast.Name) for target in targets):
                raise ValueError("仅允许赋值给局部变量，不可修改输入数据")
        if isinstance(node, ast.ListComp) and (len(node.generators) != 1 or node.generators[0].is_async):
            raise ValueError("列表推导式仅支持一个同步循环")
    if not any(isinstance(node, ast.Return) for node in nodes):
        raise ValueError("规则必须返回 EvalOutput(score=..., reason=...)")
    return function


class Returned(Exception):
    def __init__(self, value):
        self.value = value


class Interpreter:
    def __init__(self):
        self.steps = 0

    def tick(self):
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise ValueError("规则超过执行步数上限")

    def bounded(self, value):
        if isinstance(value, (str, list, tuple, dict)) and len(value) > MAX_ITEMS:
            raise ValueError("规则中间值超过长度上限 4096")
        if isinstance(value, int) and value.bit_length() > 256:
            raise ValueError("整数超出允许范围")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("不允许非有限数值")
        return value

    def binary(self, op, left, right):
        if isinstance(op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            if len(left) + len(right) > MAX_ITEMS:
                raise ValueError("字符串超出长度上限")
            return left + right
        if type(left) not in (int, float) or type(right) not in (int, float):
            raise ValueError("算术运算只支持数字；字符串只支持加法")
        functions = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                     ast.Div: operator.truediv, ast.Mod: operator.mod}
        return self.bounded(functions[type(op)](left, right))

    def expr(self, node, env):
        self.tick()
        value = self._expr(node, env)
        return self.bounded(value)

    def _expr(self, node, env):
        if isinstance(node, ast.Constant):
            if type(node.value) not in (str, int, float, bool, type(None)):
                raise ValueError("仅支持 JSON 常量")
            return node.value
        if isinstance(node, ast.Name):
            return env[node.id]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self.expr(item, env) for item in node.elts]
        if isinstance(node, ast.Dict):
            return {self.expr(k, env): self.expr(v, env) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Subscript):
            return self.expr(node.value, env)[self.expr(node.slice, env)]
        if isinstance(node, ast.BinOp):
            return self.binary(node.op, self.expr(node.left, env), self.expr(node.right, env))
        if isinstance(node, ast.UnaryOp):
            v = self.expr(node.operand, env)
            return not v if isinstance(node.op, ast.Not) else self.binary(ast.Mult(), v, -1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.IfExp):
            return self.expr(node.body if self.expr(node.test, env) else node.orelse, env)
        if isinstance(node, ast.BoolOp):
            result = None
            for item in node.values:
                result = self.expr(item, env)
                if (isinstance(node.op, ast.And) and not result) or (isinstance(node.op, ast.Or) and result):
                    break
            return result
        if isinstance(node, ast.Compare):
            functions = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                         ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
                         ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
                         ast.Is: operator.is_, ast.IsNot: operator.is_not}
            left = self.expr(node.left, env)
            for op, item in zip(node.ops, node.comparators):
                right = self.expr(item, env)
                if not functions[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.ListComp):
            gen = node.generators[0]
            values = self.expr(gen.iter, env)
            result = []
            for item in values:
                self.tick()
                local = {**env, gen.target.id: item}
                if all(self.expr(test, local) for test in gen.ifs):
                    result.append(self.expr(node.elt, local))
            return result
        if isinstance(node, ast.Call):
            args = [self.expr(item, env) for item in node.args]
            kwargs = {item.arg: self.expr(item.value, env) for item in node.keywords}
            if isinstance(node.func, ast.Name):
                functions = {"len": len, "sum": sum, "min": min, "max": max, "abs": abs,
                             "round": round, "any": any, "all": all, "EvalOutput": lambda **kw: kw}
                return functions[node.func.id](*args, **kwargs)
            owner = self.expr(node.func.value, env)
            method = node.func.attr
            allowed = {dict: {"get"}, list: {"count"}, str: METHODS - {"get"}}
            if method not in allowed.get(type(owner), set()):
                raise ValueError("该数据类型不支持此方法")
            return getattr(owner, method)(*args, **kwargs)
        raise ValueError("不支持的表达式")

    def block(self, statements, env):
        for node in statements:
            self.tick()
            if isinstance(node, ast.Return):
                raise Returned(self.expr(node.value, env))
            if isinstance(node, ast.Assign):
                value = self.expr(node.value, env)
                for target in node.targets:
                    env[target.id] = value
            elif isinstance(node, ast.AugAssign):
                env[node.target.id] = self.binary(node.op, env[node.target.id], self.expr(node.value, env))
            elif isinstance(node, ast.If):
                self.block(node.body if self.expr(node.test, env) else node.orelse, env)
            elif isinstance(node, ast.For):
                for value in self.expr(node.iter, env):
                    self.tick()
                    env[node.target.id] = value
                    self.block(node.body, env)
                self.block(node.orelse, env)
            elif isinstance(node, ast.Expr):
                self.expr(node.value, env)
            else:
                raise ValueError("不支持的语句")


def interpret(source, data):
    function = parse_source(source)
    try:
        Interpreter().block(function.body, {function.args.args[0].arg: data})
    except Returned as result:
        return result.value
    raise ValueError("规则未返回结果")


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        # Darwin does not support lowering RLIMIT_AS reliably. Input, AST,
        # intermediate-value and step limits still apply on every platform.
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        request = json.loads(sys.stdin.buffer.read(MAX_INPUT + 1))
        result = interpret(request["source"], request["data"])
        response = {"result": result}
    except Exception as exc:
        response = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    encoded = json.dumps(response, ensure_ascii=True, allow_nan=False)
    if len(encoded) > 65536:
        encoded = json.dumps({"error": "规则返回值超过 64 KB"})
    sys.stdout.write(encoded)


if __name__ == "__main__":
    main()
