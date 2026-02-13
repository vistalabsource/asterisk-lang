import ast
from pathlib import Path

from lark import Tree as LarkTree
from lark.visitors import Interpreter


class LoopBreak(Exception):
    pass


class LoopContinue(Exception):
    pass


class FunctionReturn(Exception):
    def __init__(self, value):
        super().__init__()
        self.value = value


class Tree(Interpreter):
    def __init__(self, module_loader=None, current_dir=None):
        super().__init__()
        self.env = {}
        self.local_scopes = []
        self.module_loader = module_loader
        self.current_dir = Path(current_dir).resolve() if current_dir else None
        self.loop_depth = 0
        self.function_depth = 0
        self.builtins = {
            "putln": lambda *x: print(*x),
            "scan": lambda x: input(x),
            "length": lambda x: len(x),
        }

    def transform(self, tree):
        return self.visit(tree)

    def _eval(self, node):
        if isinstance(node, LarkTree):
            return self.visit(node)
        return node

    def _lookup_var(self, name):
        for scope in reversed(self.local_scopes):
            if name in scope:
                return scope[name]
        if name in self.env:
            return self.env[name]
        if name in self.builtins:
            return self.builtins[name]
        raise KeyError(name)

    def _lookup_user_var(self, name):
        for scope in reversed(self.local_scopes):
            if name in scope:
                return scope[name]
        if name in self.env:
            return self.env[name]
        raise KeyError(name)

    def _set_var(self, name, value):
        if self.local_scopes:
            self.local_scopes[-1][name] = value
        else:
            self.env[name] = value
        return value

    def _current_scope(self):
        if self.local_scopes:
            return self.local_scopes[-1]
        return self.env

    def start(self, tree):
        last = None
        for stmt in tree.children:
            last = self._eval(stmt)
        return last

    def block(self, tree):
        last = None
        for stmt in tree.children:
            last = self._eval(stmt)
        return last

    def number(self, tree):
        s = str(tree.children[0])
        return float(s) if any(c in s for c in ".eE") else int(s)

    def string(self, tree):
        return ast.literal_eval(tree.children[0])

    def true(self, tree):
        return True

    def false(self, tree):
        return False

    def var(self, tree):
        n = str(tree.children[0])
        try:
            return self._lookup_var(n)
        except KeyError as ex:
            raise NameError(f"undefined variable: {n}") from ex

    def assign_var(self, tree):
        name = str(tree.children[0])
        value = self._eval(tree.children[1])
        return self._set_var(name, value)

    def assign_index(self, tree):
        name = str(tree.children[0])
        index = self._eval(tree.children[1])
        value = self._eval(tree.children[2])
        try:
            target = self._lookup_user_var(name)
        except KeyError as ex:
            raise NameError(f"undefined variable: {name}") from ex
        if isinstance(target, list):
            if not isinstance(index, int):
                raise TypeError("list index must be int")
            target[index] = value
            return value
        if isinstance(target, dict):
            try:
                target[index] = value
            except TypeError as ex:
                raise TypeError("dict key is not hashable") from ex
            return value
        raise TypeError(f"{name} is not indexable")

    def import_stmt(self, tree):
        if self.module_loader is None:
            raise RuntimeError("module system is not configured")

        raw_path = ast.literal_eval(tree.children[0])
        alias = tree.children[1] if len(tree.children) > 1 else None
        module_name = str(alias) if alias is not None else Path(raw_path).stem
        module_value = self.module_loader(raw_path, self.current_dir)
        return self._set_var(module_name, module_value)

    def params(self, tree):
        return [str(child) for child in tree.children]

    def func_def(self, tree):
        func_name = str(tree.children[0])
        if len(tree.children) == 3 and tree.children[1] is not None:
            param_names = self._eval(tree.children[1]) or []
        else:
            param_names = []
        block_node = tree.children[-1]

        def user_function(*args):
            if len(args) != len(param_names):
                raise TypeError(
                    f"{func_name}() takes {len(param_names)} argument(s) but {len(args)} were given"
                )

            local_env = {}
            for name, value in zip(param_names, args):
                local_env[name] = value

            self.local_scopes.append(local_env)
            self.function_depth += 1
            try:
                return self._eval(block_node)
            except FunctionReturn as returned:
                return returned.value
            finally:
                self.function_depth -= 1
                self.local_scopes.pop()

        self._set_var(func_name, user_function)
        return user_function

    def if_stmt(self, tree):
        condition = self._eval(tree.children[0])
        then_block = tree.children[1]

        if condition:
            return self._eval(then_block)

        for node in tree.children[2:]:
            if isinstance(node, LarkTree) and node.data == "elseif_clause":
                elseif_condition, elseif_block = self._eval(node)
                if elseif_condition:
                    return self._eval(elseif_block)
            else:
                return self._eval(node)

        return None

    def elseif_clause(self, tree):
        condition = self._eval(tree.children[0])
        block = tree.children[1]
        return condition, block

    def while_stmt(self, tree):
        condition_node = tree.children[0]
        block_node = tree.children[1]
        last = None
        self.loop_depth += 1
        try:
            while self._eval(condition_node):
                try:
                    last = self._eval(block_node)
                except LoopContinue:
                    continue
                except LoopBreak:
                    break
        finally:
            self.loop_depth -= 1
        return last

    def for_stmt(self, tree):
        loop_var = str(tree.children[0])
        iterable = self._eval(tree.children[1])
        block_node = tree.children[2]

        try:
            iterator = iter(iterable)
        except TypeError as ex:
            raise TypeError("for target is not iterable") from ex

        scope = self._current_scope()
        had_old = loop_var in scope
        old_value = scope.get(loop_var)
        last = None

        self.loop_depth += 1
        try:
            for item in iterator:
                scope[loop_var] = item
                try:
                    last = self._eval(block_node)
                except LoopContinue:
                    continue
                except LoopBreak:
                    break
        finally:
            self.loop_depth -= 1
            if had_old:
                scope[loop_var] = old_value
            else:
                scope.pop(loop_var, None)

        return last

    def break_stmt(self, tree):
        if self.loop_depth <= 0:
            raise RuntimeError("break used outside of loop")
        raise LoopBreak()

    def continue_stmt(self, tree):
        if self.loop_depth <= 0:
            raise RuntimeError("continue used outside of loop")
        raise LoopContinue()

    def return_stmt(self, tree):
        if self.function_depth <= 0:
            raise RuntimeError("return used outside of function")
        value = self._eval(tree.children[0]) if tree.children else None
        raise FunctionReturn(value)

    def add(self, tree):
        return self._eval(tree.children[0]) + self._eval(tree.children[1])

    def sub(self, tree):
        return self._eval(tree.children[0]) - self._eval(tree.children[1])

    def eq(self, tree):
        return self._eval(tree.children[0]) == self._eval(tree.children[1])

    def ne(self, tree):
        return self._eval(tree.children[0]) != self._eval(tree.children[1])

    def lt(self, tree):
        return self._eval(tree.children[0]) < self._eval(tree.children[1])

    def le(self, tree):
        return self._eval(tree.children[0]) <= self._eval(tree.children[1])

    def gt(self, tree):
        return self._eval(tree.children[0]) > self._eval(tree.children[1])

    def ge(self, tree):
        return self._eval(tree.children[0]) >= self._eval(tree.children[1])

    def and_op(self, tree):
        left = self._eval(tree.children[0])
        if not left:
            return False
        return bool(self._eval(tree.children[1]))

    def or_op(self, tree):
        left = self._eval(tree.children[0])
        if left:
            return True
        return bool(self._eval(tree.children[1]))

    def mul(self, tree):
        return self._eval(tree.children[0]) * self._eval(tree.children[1])

    def div(self, tree):
        x = self._eval(tree.children[0])
        y = self._eval(tree.children[1])
        if y == 0:
            raise ZeroDivisionError(f"division by zero: {x} / {y}")
        return x / y

    def neg(self, tree):
        return -self._eval(tree.children[0])

    def not_op(self, tree):
        return not self._eval(tree.children[0])

    def grouped(self, tree):
        return self._eval(tree.children[0])

    def tuple_empty(self, tree):
        return ()

    def tuple_literal(self, tree):
        head = self._eval(tree.children[0])
        tail = self._eval(tree.children[1]) if len(tree.children) > 1 else []
        if tail is None:
            tail = []
        return tuple([head, *tail])

    def list_literal(self, tree):
        if not tree.children:
            return []
        values = self._eval(tree.children[0])
        return values if values is not None else []

    def dict_item(self, tree):
        key = self._eval(tree.children[0])
        value = self._eval(tree.children[1])
        return key, value

    def dict_items(self, tree):
        return [self._eval(child) for child in tree.children]

    def dict_literal(self, tree):
        if not tree.children:
            return {}
        items = self._eval(tree.children[0])
        if items is None:
            return {}
        result = {}
        for key, value in items:
            try:
                result[key] = value
            except TypeError as ex:
                raise TypeError("dict key is not hashable") from ex
        return result

    def var_index(self, tree):
        name = str(tree.children[0])
        index = self._eval(tree.children[1])
        try:
            target = self._lookup_user_var(name)
        except KeyError as ex:
            raise NameError(f"undefined variable: {name}") from ex
        if isinstance(target, list):
            if not isinstance(index, int):
                raise TypeError("list index must be int")
            return target[index]
        if isinstance(target, tuple):
            if not isinstance(index, int):
                raise TypeError("tuple index must be int")
            return target[index]
        if isinstance(target, dict):
            try:
                return target[index]
            except TypeError as ex:
                raise TypeError("dict key is not hashable") from ex
            except KeyError as ex:
                raise KeyError(f"dict key not found: {index}") from ex
        raise TypeError(f"{name} is not indexable")

    def args(self, tree):
        return [self._eval(child) for child in tree.children]

    def module_var(self, tree):
        module_name = str(tree.children[0])
        member = str(tree.children[1])
        try:
            mod = self._lookup_user_var(module_name)
        except KeyError as ex:
            raise NameError(f"undefined module: {module_name}") from ex
        if not isinstance(mod, dict):
            raise NameError(f"undefined module: {module_name}")
        if member not in mod:
            raise NameError(f"undefined module member: {module_name}.{member}")
        return mod[member]

    def module_func_call(self, tree):
        module_name = str(tree.children[0])
        member_name = str(tree.children[1])
        try:
            mod = self._lookup_user_var(module_name)
        except KeyError as ex:
            raise NameError(f"undefined module: {module_name}") from ex
        if not isinstance(mod, dict):
            raise NameError(f"undefined module: {module_name}")
        if member_name not in mod:
            raise NameError(f"undefined module member: {module_name}.{member_name}")
        fn = mod[member_name]
        args = self._eval(tree.children[2]) if len(tree.children) > 2 else []
        if args is None:
            args = []
        if not callable(fn):
            raise TypeError(f"{module_name}.{member_name} is not callable")
        return fn(*args)

    def func_call(self, tree):
        n = str(tree.children[0])
        args = self._eval(tree.children[1]) if len(tree.children) > 1 else []
        if args is None:
            args = []
        try:
            fn = self._lookup_var(n)
        except KeyError:
            raise NameError(f"undefined function: {n}")
        if not callable(fn):
            raise TypeError(f"{n} is not callable")
        return fn(*args)

    # Backward compatibility in case grammar uses -> call.
    def call(self, tree):
        return self.func_call(tree)
