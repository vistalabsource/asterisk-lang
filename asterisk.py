from functools import lru_cache
import os
from pathlib import Path
import time

from colorama import Fore, init
from lark import Lark
from lark.exceptions import UnexpectedInput

from evaluation import Tree

init(autoreset=True)

GRAMMAR_PATH = Path(__file__).resolve().parent / "grammar" / "grammar.lark"

parser = Lark(
    GRAMMAR_PATH.read_text(encoding="utf-8"),
    parser="lalr",
)


@lru_cache(maxsize=256)
def parse_cached(src):
    return parser.parse(src)


def pretty_err(src, ex):
    if isinstance(ex, UnexpectedInput):
        ctx = ex.get_context(src)
        return f"{Fore.RED}Syntax error\n{"-"*20}\nLine  : {ex.line}\nColumn: {ex.column}\n{"-"*20}\n{ctx}"
    return str(ex)


def make_module_loader():
    module_cache = {}
    loading = set()

    def load_module(module_path, base_dir):
        path = Path(module_path)
        if not path.is_absolute():
            base = Path(base_dir).resolve() if base_dir else Path.cwd()
            path = base / path
        path = path.resolve()

        if path in module_cache:
            return module_cache[path]
        if path in loading:
            raise RuntimeError(f"{Fore.RED}Circular module import: {path}")

        loading.add(path)
        try:
            src = path.read_text(encoding="utf-8")
            tree = parse_cached(src)
            module_runtime = Tree(module_loader=load_module, current_dir=path.parent)
            module_runtime.transform(tree)
            exports = dict(module_runtime.env)
            module_cache[path] = exports
            return exports
        except FileNotFoundError:
            raise RuntimeError(f"{Fore.RED}Module not found: {path}") from None
        except Exception as ex:
            raise RuntimeError(f"{Fore.RED}Module error in {path}\n{pretty_err(src, ex)}") from None
        finally:
            loading.discard(path)

    return load_module


E = Tree(module_loader=make_module_loader(), current_dir=Path.cwd())


def run(src, source_path=None):
    try:
        if source_path is not None:
            E.current_dir = Path(source_path).resolve().parent
        else:
            E.current_dir = Path.cwd()
        tree = parse_cached(src)
        return E.transform(tree)
    except Exception as ex:
        raise RuntimeError(f"{Fore.RED}{pretty_err(src, ex)}") from None


def run_file(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    return run(src, source_path=path)


def _is_incomplete_source(src):
    try:
        parser.parse(src)
        return False
    except UnexpectedInput as ex:
        return ex.pos_in_stream >= len(src)


REPL_HELP = """Commands:
  :help                 show this help
  :exit / :quit         exit REPL
  :vars                 list current variables
  :reset                clear runtime variables
  :load <path>          execute a .sk file
  :pwd                  show current directory
  :cd <path>            change current directory
  :time                 toggle execution time display
  :cache clear          clear parse cache

Notes:
  - Multi-line input is supported for blocks and unfinished expressions.
  - Type 'exit' or 'quit' (without ':') to exit as well.
"""


def _handle_repl_command(line, show_timing):
    cmd = line.strip()
    if cmd in {":help", ":h"}:
        print(REPL_HELP)
        return False, show_timing
    if cmd in {":exit", ":quit"}:
        return True, show_timing
    if cmd == ":vars":
        if not E.env:
            print("(no variables)")
        else:
            for k in sorted(E.env):
                print(f"{k} = {E.env[k]!r}")
        return False, show_timing
    if cmd == ":reset":
        E.env.clear()
        print("Runtime variables cleared.")
        return False, show_timing
    if cmd == ":pwd":
        print(Path.cwd())
        return False, show_timing
    if cmd.startswith(":cd "):
        target = cmd[4:].strip()
        if not target:
            print(f"{Fore.RED}Usage: :cd <path>")
            return False, show_timing
        try:
            os.chdir(Path(target).expanduser())
            print(Path.cwd())
        except OSError as ex:
            print(f"{Fore.RED}{ex}")
        return False, show_timing
    if cmd.startswith(":load "):
        target = cmd[6:].strip()
        if not target:
            print(f"{Fore.RED}Usage: :load <path>")
            return False, show_timing
        try:
            started = time.perf_counter()
            v = run_file(target)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if v is not None:
                print(repr(v))
            if show_timing:
                print(f"[{elapsed_ms:.3f} ms]")
        except FileNotFoundError:
            print(f"{Fore.RED}Error: file not found - {target}")
        except RuntimeError as ex:
            print(f"{Fore.RED}{ex}")
        return False, show_timing
    if cmd == ":time":
        show_timing = not show_timing
        print(f"Timing: {'on' if show_timing else 'off'}")
        return False, show_timing
    if cmd == ":cache clear":
        parse_cached.cache_clear()
        print("Parse cache cleared.")
        return False, show_timing

    print(f"{Fore.RED}Unknown command: {cmd}")
    print("Type :help for available commands.")
    return False, show_timing


def repl():
    print(f"{Fore.GREEN}Asterisk REPL - Ctrl+C to clear line, :help for commands")
    lines = []
    show_timing = False

    while True:
        prompt = "... " if lines else ">>> "
        try:
            raw = input(prompt)
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            lines.clear()
            continue

        stripped = raw.strip()

        if not lines and stripped.startswith(":"):
            should_exit, show_timing = _handle_repl_command(stripped, show_timing)
            if should_exit:
                break
            continue

        if not lines and stripped in {"exit", "quit"}:
            break
        if not stripped and not lines:
            continue

        lines.append(raw)
        src = "\n".join(lines)
        if _is_incomplete_source(src):
            continue

        try:
            started = time.perf_counter()
            v = run(src)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if v is not None:
                print(repr(v))
            if show_timing:
                print(f"[{elapsed_ms:.3f} ms]")
        except RuntimeError as e:
            print(f"{Fore.RED}{e}")
        finally:
            lines.clear()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Asterisk Interpreter 1.0.0",
        usage="asterisk [options] [src]",
    )

    p.add_argument("src", nargs="?", default=None)
    p.add_argument("--version", action="version", help="show version", version="%(prog)s 1.0.0")
    p.add_argument("--repl", action="store_true")
    args = p.parse_args()

    if args.repl or not args.src:
        repl()
    elif args.src:
        try:
            run_file(args.src)
        except FileNotFoundError:
            print(f"{Fore.RED}Error: file not found - {args.src}")
        except RuntimeError as e:
            print(f"{Fore.RED}{e}")
