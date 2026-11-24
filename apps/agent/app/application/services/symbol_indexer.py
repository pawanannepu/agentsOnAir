"""Repository symbol indexer service for full repository context code reviews."""

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SymbolDefinition:
    """Indexed symbol in the repository."""

    name: str
    kind: str  # "function", "class", "method"
    file_path: str
    line_number: int
    end_line_number: int
    signature: str
    docstring: str | None = None
    enclosing_symbol: str | None = None


@dataclass(slots=True)
class SymbolCallGraph:
    """Extracted symbol graph of the repository."""

    symbols: dict[str, SymbolDefinition] = field(default_factory=dict)
    # caller_symbol_key -> set of callee names
    calls: dict[str, set[str]] = field(default_factory=dict)
    # callee_name -> set of caller_symbol_keys
    callers: dict[str, set[str]] = field(default_factory=dict)
    file_symbols: dict[str, list[str]] = field(default_factory=dict)


class PythonSymbolVisitor(ast.NodeVisitor):
    """AST visitor that extracts functions, classes, methods, and calls."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.symbols: dict[str, SymbolDefinition] = {}
        self.calls: dict[str, set[str]] = {}
        self.callers: dict[str, set[str]] = {}
        self.file_symbols: list[str] = []
        self._current_enclosing: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_key = f"{self.file_path}::{node.name}"
        self.symbols[class_key] = SymbolDefinition(
            name=node.name,
            kind="class",
            file_path=self.file_path,
            line_number=node.lineno,
            end_line_number=getattr(node, "end_lineno", node.lineno),
            signature=f"class {node.name}",
            docstring=ast.get_docstring(node),
            enclosing_symbol="::".join(self._current_enclosing)
            if self._current_enclosing
            else None,
        )
        self.file_symbols.append(class_key)
        self._current_enclosing.append(node.name)
        self.generic_visit(node)
        self._current_enclosing.pop()

    def _extract_signature(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> str:
        prefix = "async def " if is_async else "def "
        args = [a.arg for a in node.args.args]
        return f"{prefix}{node.name}({', '.join(args)})"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_func(node, is_async=True)

    def _handle_func(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> None:
        enclosing = (
            "::".join(self._current_enclosing) if self._current_enclosing else None
        )
        kind = "method" if self._current_enclosing else "function"
        key = (
            f"{self.file_path}::{enclosing}::{node.name}"
            if enclosing
            else f"{self.file_path}::{node.name}"
        )

        self.symbols[key] = SymbolDefinition(
            name=node.name,
            kind=kind,
            file_path=self.file_path,
            line_number=node.lineno,
            end_line_number=getattr(node, "end_lineno", node.lineno),
            signature=self._extract_signature(node, is_async),
            docstring=ast.get_docstring(node),
            enclosing_symbol=enclosing,
        )
        self.file_symbols.append(key)
        self.calls[key] = set()

        prev_enclosing = list(self._current_enclosing)
        self._current_enclosing.append(node.name)

        # Inspect calls within this function
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func_name = None
                if isinstance(child.func, ast.Name):
                    func_name = child.func.id
                elif isinstance(child.func, ast.Attribute):
                    func_name = child.func.attr
                if func_name:
                    self.calls[key].add(func_name)
                    if func_name not in self.callers:
                        self.callers[func_name] = set()
                    self.callers[func_name].add(key)

        self._current_enclosing = prev_enclosing


class SymbolIndexer:
    """Indexes repository source files into a unified symbol call graph."""

    def __init__(self, repo_dir: str | Path) -> None:
        self.repo_dir = Path(repo_dir)

    def build_graph(self) -> SymbolCallGraph:
        """Parse source files and construct symbol call graph (AC-2)."""
        graph = SymbolCallGraph()

        if not self.repo_dir.exists():
            return graph

        for file_path in self.repo_dir.rglob("*.py"):
            rel_path = str(file_path.relative_to(self.repo_dir))
            # Skip ignored paths
            if any(
                part in rel_path.split("/")
                for part in ("venv", ".venv", "__pycache__", "dist", "build")
            ) or rel_path.startswith("."):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=rel_path)
            except Exception:
                continue

            visitor = PythonSymbolVisitor(rel_path)
            visitor.visit(tree)

            graph.symbols.update(visitor.symbols)
            graph.calls.update(visitor.calls)
            for callee, caller_keys in visitor.callers.items():
                if callee not in graph.callers:
                    graph.callers[callee] = set()
                graph.callers[callee].update(caller_keys)
            graph.file_symbols[rel_path] = visitor.file_symbols

        return graph
