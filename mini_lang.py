from lark import Lark, Transformer
from lark.exceptions import UnexpectedInput

GRAMMAR = r'''
?start: stmt+
?stmt: NAME "=" expr      -> assign
     | "print" "(" expr ")" -> print_stmt
     | expr                -> expr_stmt
?expr: expr "+" term      -> add
     | expr "-" term      -> sub
     | term
?term: term "*" atom      -> mul
     | term "/" atom      -> div
     | atom
?atom: NUMBER              -> number
     | ESCAPED_STRING      -> string
     | NAME                -> var
     | NAME "(" [args] ")" -> call
     | "(" expr ")"
?args: expr ("," expr)*
%import common.CNAME -> NAME
%import common.NUMBER
%import common.ESCAPED_STRING
%import common.WS
%ignore WS
'''

class Eval(Transformer):
    def __init__(self):
        self.vars, self.fn = {}, {
            'len': len, 'upper': lambda s: str(s).upper(), 'lower': lambda s: str(s).lower(),
            'str': str, 'int': int,
        }

    def number(self, t): return float(t[0]) if '.' in t[0] else int(t[0])
    def string(self, t): return t[0][1:-1]
    def add(self, t): return t[0] + t[1]
    def sub(self, t): return t[0] - t[1]
    def mul(self, t): return t[0] * t[1]
    def div(self, t): return t[0] / t[1]
    def expr_stmt(self, t): return t[0]
    def print_stmt(self, t): print(t[0]); return t[0]

    def var(self, t):
        n = str(t[0])
        if n not in self.vars: raise NameError(f"未定義の変数です: {n}")
        return self.vars[n]

    def assign(self, t):
        self.vars[str(t[0])] = t[1]
        return t[1]

    def call(self, t):
        n = str(t[0])
        if n not in self.fn: raise NameError(f"未定義の関数です: {n}")
        try: return self.fn[n](*t[1:])
        except Exception as e: raise ValueError(f"関数呼び出しエラー: {n}({', '.join(map(str, t[1:]))})") from e

class MiniLang:
    def __init__(self):
        self.parser = Lark(GRAMMAR, parser='lalr', transformer=Eval())

    def run(self, code: str):
        try: return self.parser.parse(code)
        except UnexpectedInput as e:
            exp = ", ".join(sorted(e.expected)) if hasattr(e, 'expected') else ""
            raise SyntaxError(f"構文エラー: {e.line}行{e.column}列 付近。期待: {exp}") from e

if __name__ == '__main__':
    src = 'name = "lark"\nprint(upper(name))\nprint(len(name)+2)'
    try: MiniLang().run(src)
    except Exception as e: print(f"Error: {e}")
