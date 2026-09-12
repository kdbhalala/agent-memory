"""L4: Native SQLite Structural Code Graph Layer (zero external dependencies).

Replaces heavy code graph tools (Graphify, tree-sitter binaries, language servers)
with pure Python standard library:
- Python stdlib `ast` for exact, microsecond Python AST parsing (classes, functions, calls, imports, inheritance)
- Fast streaming regex parsers for JavaScript, TypeScript, Go, Rust, and Dart
- SQLite FTS5 for microsecond symbol lookup (<0.2ms)
- SQLite Recursive CTEs (`WITH RECURSIVE`) for multi-hop callers, dependency chains, and impact blast-radius analysis (<0.5ms)
"""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from agi_memory.config import DEFAULT_DB, get_default_db
    from agi_memory.layers.base import Hit, MemoryLayer, open_db
except ImportError:
    try:
        from ..config import DEFAULT_DB, get_default_db
        from .base import Hit, MemoryLayer, open_db
    except (ImportError, ValueError):
        from config import DEFAULT_DB, get_default_db
        from layers.base import Hit, MemoryLayer

IGNORED_DIRS: Set[str] = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", "target", ".dart_tool",
    "vendor", ".idea", ".vscode", "coverage", ".next", ".nuxt", "site-packages"
}

SUPPORTED_EXTENSIONS: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".dart": "dart",
}


def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]


# ============================================================================
# Pure stdlib Parsers
# ============================================================================

def parse_python_code(content: str, rel_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse Python source into symbols and edges using stdlib ast."""
    symbols: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    try:
        tree = ast.parse(content, filename=rel_path)
    except SyntaxError:
        return symbols, edges

    lines = content.splitlines()

    class SymbolVisitor(ast.NodeVisitor):
        def __init__(self):
            self.scope_stack: List[str] = []

        def _get_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
            args = []
            # Positional / keyword args
            for a in node.args.args:
                ann = f": {ast.unparse(a.annotation)}" if getattr(a, "annotation", None) else ""
                args.append(f"{a.arg}{ann}")
            ret = f" -> {ast.unparse(node.returns)}" if getattr(node, "returns", None) else ""
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            return f"{prefix}{node.name}({', '.join(args)}){ret}"

        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                edges.append({
                    "source": rel_path,
                    "relation": "IMPORTS",
                    "target": alias.name,
                    "line": node.lineno
                })
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                full_tgt = f"{mod}.{alias.name}" if mod else alias.name
                edges.append({
                    "source": rel_path,
                    "relation": "IMPORTS",
                    "target": full_tgt,
                    "line": node.lineno
                })
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef):
            parent = self.scope_stack[-1] if self.scope_stack else None
            qname = f"{parent}.{node.name}" if parent else node.name
            doc = ast.get_docstring(node) or ""
            end_line = getattr(node, "end_lineno", node.lineno)

            symbols.append({
                "name": node.name,
                "qualified_name": qname,
                "kind": "class",
                "signature": f"class {node.name}",
                "docstring": doc,
                "start_line": node.lineno,
                "end_line": end_line,
                "parent_symbol": parent
            })

            edges.append({
                "source": rel_path,
                "relation": "DEFINES",
                "target": qname,
                "line": node.lineno
            })

            for b in node.bases:
                base_name = ast.unparse(b)
                edges.append({
                    "source": qname,
                    "relation": "EXTENDS",
                    "target": base_name,
                    "line": node.lineno
                })

            self.scope_stack.append(qname)
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._handle_function(node, is_async=False)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._handle_function(node, is_async=True)

        def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool):
            parent = self.scope_stack[-1] if self.scope_stack else None
            qname = f"{parent}.{node.name}" if parent else node.name
            kind = "method" if parent else "function"
            doc = ast.get_docstring(node) or ""
            sig = self._get_signature(node)
            end_line = getattr(node, "end_lineno", node.lineno)

            symbols.append({
                "name": node.name,
                "qualified_name": qname,
                "kind": kind,
                "signature": sig,
                "docstring": doc,
                "start_line": node.lineno,
                "end_line": end_line,
                "parent_symbol": parent
            })

            edges.append({
                "source": parent or rel_path,
                "relation": "DEFINES",
                "target": qname,
                "line": node.lineno
            })

            # Look for function calls inside this function
            caller_name = qname
            for sub_node in ast.walk(node):
                if isinstance(sub_node, ast.Call):
                    callee = ""
                    if isinstance(sub_node.func, ast.Name):
                        callee = sub_node.func.id
                    elif isinstance(sub_node.func, ast.Attribute):
                        callee = sub_node.func.attr
                    if callee and callee not in ("print", "len", "range", "str", "int", "dict", "list", "set", "isinstance"):
                        edges.append({
                            "source": caller_name,
                            "relation": "CALLS",
                            "target": callee,
                            "line": getattr(sub_node, "lineno", node.lineno)
                        })

            self.scope_stack.append(qname)
            self.generic_visit(node)
            self.scope_stack.pop()

    visitor = SymbolVisitor()
    visitor.visit(tree)
    return symbols, edges


# Reserved words that look like calls: `if (x)`, `switch (y)`, `for (...)`.
# Kept per-family rather than one blob so a Go keyword cannot mask a JS function.
_CALL_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "with", "do", "else",
    "function", "await", "typeof", "instanceof", "new", "throw", "super",
    "constructor", "defer", "go", "select", "range", "make", "len", "cap",
    "append", "panic", "recover", "match", "loop", "unsafe", "impl", "fn",
    "let", "const", "var", "print", "assert", "require", "import", "export",
}

_CALL_RE = re.compile(r"(?:\.\s*)?\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")


def extract_call_edges(lines: List[str], symbols: List[Dict[str, Any]],
                       rel_path: str) -> List[Dict[str, Any]]:
    """Attribute call sites to the enclosing function for the regex parsers.

    The AST parser resolves scope properly; the regex parsers only know where
    each symbol starts, so a call is attributed to the nearest function
    declared above it. That is exact for flat code and approximate for nested
    closures, which is the accuracy the regex tier already offers elsewhere.
    Without this, code_callers/code_dependencies/code_impact answer only for
    Python while claiming to cover every indexed language.
    """
    starts = sorted(
        ((sym["start_line"], sym.get("qualified_name") or sym["name"], sym["name"])
         for sym in symbols if sym.get("kind") in ("function", "method")),
        key=lambda t: t[0],
    )
    if not starts:
        return []

    edges: List[Dict[str, Any]] = []
    seen = set()
    pos = 0
    current = None
    for idx, line in enumerate(lines, start=1):
        while pos < len(starts) and starts[pos][0] <= idx:
            current = starts[pos]
            pos += 1
        if current is None or idx == current[0]:
            continue  # the declaration line itself is not a call site
        code = line.split("//")[0].split("#")[0]
        for match in _CALL_RE.finditer(code):
            callee = match.group(1)
            if callee in _CALL_KEYWORDS or callee == current[2]:
                continue
            key = (current[1], callee)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": current[1], "relation": "CALLS",
                          "target": callee, "line": idx})
    return edges


def parse_js_ts_code(content: str, rel_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fast streaming regex parser for JavaScript and TypeScript."""
    symbols: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.splitlines()

    current_class: Optional[str] = None

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue

        # Imports: import { x } from 'y'; or import x from 'y';
        m_imp = re.search(r'''import\s+(?:\{[^}]*\}|[\w*\s,]+)\s+from\s+['"]([^'"]+)['"]''', stripped)
        if m_imp:
            edges.append({
                "source": rel_path,
                "relation": "IMPORTS",
                "target": m_imp.group(1),
                "line": idx
            })
            continue

        # Classes: class Foo extends Bar implements Baz
        m_cls = re.search(r'''(?:export\s+)?class\s+([A-Za-z0-9_$]+)(?:\s+extends\s+([A-Za-z0-9_$]+))?(?:\s+implements\s+([A-Za-z0-9_$,\s]+))?''', stripped)
        if m_cls:
            cname = m_cls.group(1)
            current_class = cname
            symbols.append({
                "name": cname,
                "qualified_name": cname,
                "kind": "class",
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": None
            })
            edges.append({"source": rel_path, "relation": "DEFINES", "target": cname, "line": idx})
            if m_cls.group(2):
                edges.append({"source": cname, "relation": "EXTENDS", "target": m_cls.group(2), "line": idx})
            continue

        # Interfaces / Types: interface Foo or type Bar =
        m_if = re.search(r'''(?:export\s+)?(?:interface|type)\s+([A-Za-z0-9_$]+)''', stripped)
        if m_if:
            iname = m_if.group(1)
            symbols.append({
                "name": iname,
                "qualified_name": iname,
                "kind": "interface",
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": None
            })
            edges.append({"source": rel_path, "relation": "DEFINES", "target": iname, "line": idx})
            continue

        # Functions: function foo(...) or const foo = (...) =>
        m_fn = re.search(r'''(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\(([^)]*)\)''', stripped)
        if not m_fn:
            m_fn = re.search(r'''(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>''', stripped)

        if m_fn:
            fname = m_fn.group(1)
            qname = f"{current_class}.{fname}" if current_class else fname
            kind = "method" if current_class else "function"
            symbols.append({
                "name": fname,
                "qualified_name": qname,
                "kind": kind,
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": current_class
            })
            edges.append({"source": current_class or rel_path, "relation": "DEFINES", "target": qname, "line": idx})
            continue

        # Method inside class: foo(...) {
        if current_class and re.search(r'''^(?:async\s+)?([A-Za-z0-9_$]+)\s*\(([^)]*)\)\s*(?::\s*[^\{]+)?\s*\{''', stripped):
            m_m = re.search(r'''^(?:async\s+)?([A-Za-z0-9_$]+)\s*\(([^)]*)\)''', stripped)
            if m_m and m_m.group(1) not in ("if", "for", "while", "switch", "catch"):
                mname = m_m.group(1)
                qname = f"{current_class}.{mname}"
                symbols.append({
                    "name": mname,
                    "qualified_name": qname,
                    "kind": "method",
                    "signature": stripped.split("{")[0].strip(),
                    "docstring": "",
                    "start_line": idx,
                    "end_line": idx,
                    "parent_symbol": current_class
                })
                edges.append({"source": current_class, "relation": "DEFINES", "target": qname, "line": idx})

        if stripped.endswith("}") and current_class and line.startswith("}"):
            current_class = None

    edges.extend(extract_call_edges(lines, symbols, rel_path))
    return symbols, edges


def parse_go_code(content: str, rel_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fast streaming regex parser for Go."""
    symbols: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        m_imp = re.search(r'''import\s+["']([^"']+)["']''', stripped)
        if m_imp:
            edges.append({"source": rel_path, "relation": "IMPORTS", "target": m_imp.group(1), "line": idx})
            continue

        m_type = re.search(r'''type\s+([A-Za-z0-9_]+)\s+(struct|interface)''', stripped)
        if m_type:
            tname = m_type.group(1)
            kind = m_type.group(2)
            symbols.append({
                "name": tname,
                "qualified_name": tname,
                "kind": kind,
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": None
            })
            edges.append({"source": rel_path, "relation": "DEFINES", "target": tname, "line": idx})
            continue

        m_fn = re.search(r'''func\s+(?:\((?:[A-Za-z0-9_*\s]+)\s+([*]?[A-Za-z0-9_]+)\)\s+)?([A-Za-z0-9_]+)\s*\(([^)]*)\)''', stripped)
        if m_fn:
            recv = m_fn.group(1)
            fname = m_fn.group(2)
            recv_clean = recv.lstrip("*") if recv else None
            qname = f"{recv_clean}.{fname}" if recv_clean else fname
            kind = "method" if recv_clean else "function"
            symbols.append({
                "name": fname,
                "qualified_name": qname,
                "kind": kind,
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": recv_clean
            })
            edges.append({"source": recv_clean or rel_path, "relation": "DEFINES", "target": qname, "line": idx})

    edges.extend(extract_call_edges(lines, symbols, rel_path))
    return symbols, edges


def parse_rust_code(content: str, rel_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fast streaming regex parser for Rust."""
    symbols: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        m_use = re.search(r'''use\s+([^;]+);''', stripped)
        if m_use:
            edges.append({"source": rel_path, "relation": "IMPORTS", "target": m_use.group(1).strip(), "line": idx})
            continue

        m_type = re.search(r'''(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z0-9_]+)''', stripped)
        if m_type:
            tname = m_type.group(1)
            symbols.append({
                "name": tname,
                "qualified_name": tname,
                "kind": "struct",
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": None
            })
            edges.append({"source": rel_path, "relation": "DEFINES", "target": tname, "line": idx})
            continue

        m_fn = re.search(r'''(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)''', stripped)
        if m_fn:
            fname = m_fn.group(1)
            symbols.append({
                "name": fname,
                "qualified_name": fname,
                "kind": "function",
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": None
            })
            edges.append({"source": rel_path, "relation": "DEFINES", "target": fname, "line": idx})

    edges.extend(extract_call_edges(lines, symbols, rel_path))
    return symbols, edges


def parse_dart_code(content: str, rel_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fast streaming regex parser for Dart."""
    symbols: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.splitlines()

    current_class: Optional[str] = None

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        m_imp = re.search(r'''import\s+['"]([^'"]+)['"];''', stripped)
        if m_imp:
            edges.append({"source": rel_path, "relation": "IMPORTS", "target": m_imp.group(1), "line": idx})
            continue

        m_cls = re.search(r'''class\s+([A-Za-z0-9_]+)(?:\s+extends\s+([A-Za-z0-9_]+))?(?:\s+with\s+([A-Za-z0-9_,\s]+))?(?:\s+implements\s+([A-Za-z0-9_,\s]+))?''', stripped)
        if m_cls:
            cname = m_cls.group(1)
            current_class = cname
            symbols.append({
                "name": cname,
                "qualified_name": cname,
                "kind": "class",
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": None
            })
            edges.append({"source": rel_path, "relation": "DEFINES", "target": cname, "line": idx})
            if m_cls.group(2):
                edges.append({"source": cname, "relation": "EXTENDS", "target": m_cls.group(2), "line": idx})
            continue

        m_m = re.search(r'''(?:[A-Za-z0-9_<>,?\s]+)\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)\s*(?:async\s*)?\{''', stripped)
        if m_m and m_m.group(1) not in ("if", "for", "while", "switch", "catch"):
            mname = m_m.group(1)
            qname = f"{current_class}.{mname}" if current_class else mname
            kind = "method" if current_class else "function"
            symbols.append({
                "name": mname,
                "qualified_name": qname,
                "kind": kind,
                "signature": stripped.split("{")[0].strip(),
                "docstring": "",
                "start_line": idx,
                "end_line": idx,
                "parent_symbol": current_class
            })
            edges.append({"source": current_class or rel_path, "relation": "DEFINES", "target": qname, "line": idx})

        if stripped.endswith("}") and current_class and line.startswith("}"):
            current_class = None

    edges.extend(extract_call_edges(lines, symbols, rel_path))
    return symbols, edges


def parse_source_code(content: str, rel_path: str, language: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Dispatcher for language-specific AST and regex parsers.

    A file that cannot be parsed yields no symbols; it never breaks the index
    run. The guard lives here so it covers every parser, and it is broader than
    SyntaxError on purpose: ast.parse reports NUL bytes as ValueError on Python
    3.10 and as SyntaxError from 3.12 on, and pathological nesting in either the
    AST or a regex parser surfaces as RecursionError.
    """
    try:
        return _dispatch_parser(content, rel_path, language)
    except (SyntaxError, ValueError, RecursionError, MemoryError, UnicodeError):
        return [], []


def _dispatch_parser(content: str, rel_path: str, language: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if language == "python":
        return parse_python_code(content, rel_path)
    elif language in ("javascript", "typescript"):
        return parse_js_ts_code(content, rel_path)
    elif language == "go":
        return parse_go_code(content, rel_path)
    elif language == "rust":
        return parse_rust_code(content, rel_path)
    elif language == "dart":
        return parse_dart_code(content, rel_path)
    return [], []


# ============================================================================
# CodeLayer Implementation
# ============================================================================

class CodeLayer(MemoryLayer):
    """Native SQLite Structural Code Graph layer."""
    name = "code"

    def __init__(self, db_path: Path | str | None = None, project: str | None = None):
        self.db_path = Path(db_path) if db_path else get_default_db()
        self.project = project
        self._init_db()

    def _get_con(self, mode: str = "rw") -> sqlite3.Connection:
        if mode == "ro":
            return open_db(self.db_path, readonly=True)
        return open_db(self.db_path)

    def _init_db(self) -> None:
        """Create code graph schema, FTS5 virtual tables, and indexes."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = self._get_con(mode="rw")
        cur = con.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS code_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                file_path TEXT NOT NULL,
                language TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                symbol_count INTEGER DEFAULT 0,
                lines_of_code INTEGER DEFAULT 0,
                last_indexed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project, file_path)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS code_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                project TEXT NOT NULL,
                file_path TEXT NOT NULL,
                name TEXT NOT NULL,
                qualified_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                signature TEXT,
                docstring TEXT,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                parent_symbol TEXT,
                FOREIGN KEY(file_id) REFERENCES code_files(id) ON DELETE CASCADE
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_code_symbols_name ON code_symbols(project, name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_code_symbols_file ON code_symbols(project, file_path)")

        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS code_symbols_fts USING fts5(
                name, qualified_name, kind, signature, docstring, file_path,
                content='code_symbols', content_rowid='id'
            )
        """)

        # Triggers to keep code_symbols_fts synchronized
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS code_symbols_ai AFTER INSERT ON code_symbols BEGIN
                INSERT INTO code_symbols_fts(rowid, name, qualified_name, kind, signature, docstring, file_path)
                VALUES (new.id, new.name, new.qualified_name, new.kind, new.signature, new.docstring, new.file_path);
            END
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS code_symbols_ad AFTER DELETE ON code_symbols BEGIN
                INSERT INTO code_symbols_fts(code_symbols_fts, rowid, name, qualified_name, kind, signature, docstring, file_path)
                VALUES ('delete', old.id, old.name, old.qualified_name, old.kind, old.signature, old.docstring, old.file_path);
            END
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS code_symbols_au AFTER UPDATE ON code_symbols BEGIN
                INSERT INTO code_symbols_fts(code_symbols_fts, rowid, name, qualified_name, kind, signature, docstring, file_path)
                VALUES ('delete', old.id, old.name, old.qualified_name, old.kind, old.signature, old.docstring, old.file_path);
                INSERT INTO code_symbols_fts(rowid, name, qualified_name, kind, signature, docstring, file_path)
                VALUES (new.id, new.name, new.qualified_name, new.kind, new.signature, new.docstring, new.file_path);
            END
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS code_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                source_symbol TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_symbol TEXT NOT NULL,
                file_path TEXT NOT NULL,
                line_number INTEGER DEFAULT 0,
                UNIQUE(project, source_symbol, relation, target_symbol, file_path)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_code_edges_source ON code_edges(project, source_symbol, relation)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_code_edges_target ON code_edges(project, target_symbol, relation)")

        con.commit()
        con.close()

    def index_file(
        self,
        file_path: Path | str,
        project: Optional[str] = None,
        content: Optional[str] = None,
        root_dir: Path | str | None = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """Index a single file into SQLite code graph incrementally."""
        proj = project or self.project or "global"
        p = Path(file_path)
        root = Path(root_dir) if root_dir else Path.cwd()

        try:
            rel_path = str(p.relative_to(root))
        except ValueError:
            rel_path = str(p)

        ext = p.suffix.lower()
        lang = SUPPORTED_EXTENSIONS.get(ext)
        if not lang:
            return {"file_path": rel_path, "skipped": True, "reason": f"unsupported extension {ext}"}

        if content is None:
            if not p.is_file():
                return {"file_path": rel_path, "skipped": True, "reason": "file not found"}
            content = p.read_text(encoding="utf-8", errors="replace")

        chash = _compute_hash(content)
        loc = len(content.splitlines())

        con = self._get_con(mode="rw")
        cur = con.cursor()

        # Check existing hash
        if not force:
            cur.execute("""
                SELECT id, content_hash, symbol_count FROM code_files
                WHERE project = ? AND file_path = ?
            """, (proj, rel_path))
            existing = cur.fetchone()
            if existing and existing[1] == chash:
                con.close()
                return {
                    "file_path": rel_path,
                    "language": lang,
                    "symbols_indexed": existing[2],
                    "cached": True
                }

        # Parse source
        symbols, edges = parse_source_code(content, rel_path, lang)

        # Clear existing file records
        cur.execute("SELECT id FROM code_files WHERE project = ? AND file_path = ?", (proj, rel_path))
        f_row = cur.fetchone()
        if f_row:
            cur.execute("DELETE FROM code_symbols WHERE file_id = ?", (f_row[0],))
            cur.execute("DELETE FROM code_edges WHERE project = ? AND file_path = ?", (proj, rel_path))
            cur.execute("DELETE FROM code_files WHERE id = ?", (f_row[0],))

        cur.execute("""
            INSERT INTO code_files (project, file_path, language, content_hash, symbol_count, lines_of_code)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (proj, rel_path, lang, chash, len(symbols), loc))
        file_id = cur.lastrowid

        for sym in symbols:
            cur.execute("""
                INSERT INTO code_symbols (
                    file_id, project, file_path, name, qualified_name, kind,
                    signature, docstring, start_line, end_line, parent_symbol
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                file_id, proj, rel_path, sym["name"], sym["qualified_name"], sym["kind"],
                sym.get("signature"), sym.get("docstring"), sym["start_line"],
                sym["end_line"], sym.get("parent_symbol")
            ))

        for ed in edges:
            cur.execute("""
                INSERT OR IGNORE INTO code_edges (
                    project, source_symbol, relation, target_symbol, file_path, line_number
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (proj, ed["source"], ed["relation"], ed["target"], rel_path, ed.get("line", 0)))

        con.commit()
        con.close()

        return {
            "file_path": rel_path,
            "language": lang,
            "symbols_indexed": len(symbols),
            "edges_indexed": len(edges),
            "cached": False
        }

    def index_directory(
        self,
        dir_path: Path | str = ".",
        project: Optional[str] = None,
        force: bool = False,
        max_files: int = 1000
    ) -> Dict[str, Any]:
        """Recursively scan and index directory source files into SQLite code graph."""
        start_t = time.perf_counter()
        proj = project or self.project or "global"
        root = Path(dir_path).resolve()

        files_scanned = 0
        files_indexed = 0
        files_cached = 0
        total_syms = 0
        total_edges = 0

        for cur_root, dirs, files in os.walk(root):
            # Prune ignored dirs in place
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]

            for fname in files:
                if files_scanned >= max_files:
                    break
                p = Path(cur_root) / fname
                if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                    files_scanned += 1
                    res = self.index_file(p, project=proj, root_dir=root, force=force)
                    if res.get("cached"):
                        files_cached += 1
                        total_syms += res.get("symbols_indexed", 0)
                    elif not res.get("skipped"):
                        files_indexed += 1
                        total_syms += res.get("symbols_indexed", 0)
                        total_edges += res.get("edges_indexed", 0)

        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        return {
            "project": proj,
            "files_scanned": files_scanned,
            "files_indexed": files_indexed,
            "files_cached": files_cached,
            "total_symbols": total_syms,
            "total_edges": total_edges,
            "elapsed_ms": round(elapsed_ms, 2)
        }

    def search_symbols(self, query: str, project: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Microsecond symbol search via SQLite FTS5 with fallback to prefix match."""
        proj = project or self.project
        con = self._get_con(mode="ro")
        cur = con.cursor()

        cleaned = re.sub(r"[^\w*]", " ", query).strip()
        terms = [t for t in cleaned.split() if t]
        if not terms:
            con.close()
            return []

        fts_query = " OR ".join(f"{t}*" for t in terms)

        rows = []
        try:
            if proj:
                cur.execute("""
                    SELECT s.id, s.name, s.qualified_name, s.kind, s.signature, s.file_path, s.start_line, s.end_line
                    FROM code_symbols_fts f
                    JOIN code_symbols s ON s.id = f.rowid
                    WHERE code_symbols_fts MATCH ? AND s.project = ?
                    LIMIT ?
                """, (fts_query, proj, limit))
            else:
                cur.execute("""
                    SELECT s.id, s.name, s.qualified_name, s.kind, s.signature, s.file_path, s.start_line, s.end_line
                    FROM code_symbols_fts f
                    JOIN code_symbols s ON s.id = f.rowid
                    WHERE code_symbols_fts MATCH ?
                    LIMIT ?
                """, (fts_query, limit))
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            pass

        # Fallback to LIKE if FTS produced 0 results
        if not rows:
            pattern = f"%{query}%"
            if proj:
                cur.execute("""
                    SELECT id, name, qualified_name, kind, signature, file_path, start_line, end_line
                    FROM code_symbols
                    WHERE (name LIKE ? OR qualified_name LIKE ?) AND project = ?
                    LIMIT ?
                """, (pattern, pattern, proj, limit))
            else:
                cur.execute("""
                    SELECT id, name, qualified_name, kind, signature, file_path, start_line, end_line
                    FROM code_symbols
                    WHERE (name LIKE ? OR qualified_name LIKE ?)
                    LIMIT ?
                """, (pattern, pattern, limit))
            rows = cur.fetchall()

        con.close()

        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "name": r[1],
                "qualified_name": r[2],
                "kind": r[3],
                "signature": r[4] or "",
                "file_path": r[5],
                "start_line": r[6],
                "end_line": r[7]
            })
        return results

    def get_structure(self, target_path: Path | str = ".", project: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get structural outline of symbols in a file or directory."""
        proj = project or self.project
        con = self._get_con(mode="ro")
        cur = con.cursor()

        target_str = str(target_path).strip()
        if target_str in (".", "", "./"):
            # Whole project structure
            sql = """
                SELECT file_path, name, qualified_name, kind, signature, start_line, end_line, parent_symbol
                FROM code_symbols
            """
            args: list = []
            if proj:
                sql += " WHERE project = ?"
                args.append(proj)
            sql += " ORDER BY file_path, start_line"
            cur.execute(sql, args)
        else:
            pattern = f"%{target_str}%"
            sql = """
                SELECT file_path, name, qualified_name, kind, signature, start_line, end_line, parent_symbol
                FROM code_symbols
                WHERE file_path LIKE ?
            """
            args = [pattern]
            if proj:
                sql += " AND project = ?"
                args.append(proj)
            sql += " ORDER BY file_path, start_line"
            cur.execute(sql, args)

        rows = cur.fetchall()
        con.close()

        results = []
        for r in rows:
            results.append({
                "file_path": r[0],
                "name": r[1],
                "qualified_name": r[2],
                "kind": r[3],
                "signature": r[4] or "",
                "start_line": r[5],
                "end_line": r[6],
                "parent_symbol": r[7]
            })
        return results

    def get_callers(self, symbol_name: str, project: Optional[str] = None, max_depth: int = 3) -> List[Dict[str, Any]]:
        """Recursive CTE: Find all inbound callers and dependents of a symbol (<0.5ms)."""
        proj = project or self.project
        con = self._get_con(mode="ro")
        cur = con.cursor()

        base_proj_clause = "project = ?" if proj else "1=1"
        rec_proj_clause = "e.project = ?" if proj else "1=1"

        query = f"""
            WITH RECURSIVE callers_cte(symbol, relation, target, file_path, line_number, depth, path) AS (
                SELECT source_symbol, relation, target_symbol, file_path, line_number, 1,
                       source_symbol || ' -[' || relation || ']-> ' || target_symbol
                FROM code_edges
                WHERE {base_proj_clause}
                  AND (target_symbol = ? OR target_symbol LIKE ?)
                  AND relation IN ('CALLS', 'IMPORTS', 'EXTENDS', 'IMPLEMENTS')
                UNION ALL
                SELECT e.source_symbol, e.relation, e.target_symbol, e.file_path, e.line_number, c.depth + 1,
                       e.source_symbol || ' -[' || e.relation || ']-> ' || c.path
                FROM code_edges e
                -- Qualified vs bare names must still connect: a method is
                -- recorded as AuthService.authenticate, while its call sites
                -- reference bare authenticate. Strict equality here truncated
                -- every transitive chain at the first method boundary.
                JOIN callers_cte c ON (
                    e.target_symbol = c.symbol
                    OR c.symbol LIKE '%.' || e.target_symbol
                    OR e.target_symbol LIKE '%.' || c.symbol
                )
                WHERE {rec_proj_clause}
                  AND c.depth < ?
                  AND INSTR(c.path, e.source_symbol) = 0
            )
            SELECT DISTINCT symbol, relation, target, file_path, line_number, depth, path
            FROM callers_cte
            ORDER BY depth, file_path, line_number;
        """

        args: list = []
        if proj:
            args.append(proj)
        args.extend([symbol_name, f"%.{symbol_name}"])
        if proj:
            args.append(proj)
        args.append(max_depth)

        cur.execute(query, args)
        rows = cur.fetchall()
        con.close()

        results = []
        for r in rows:
            results.append({
                "caller": r[0],
                "relation": r[1],
                "callee": r[2],
                "file_path": r[3],
                "line_number": r[4],
                "depth": r[5],
                "call_chain": r[6]
            })
        return results

    def get_dependencies(self, symbol_or_module: str, project: Optional[str] = None, max_depth: int = 3) -> List[Dict[str, Any]]:
        """Recursive CTE: Find all outbound dependencies and calls made by a symbol (<0.5ms)."""
        proj = project or self.project
        con = self._get_con(mode="ro")
        cur = con.cursor()

        base_proj_clause = "project = ?" if proj else "1=1"
        rec_proj_clause = "e.project = ?" if proj else "1=1"

        query = f"""
            WITH RECURSIVE deps_cte(source, relation, target, file_path, line_number, depth, path) AS (
                SELECT source_symbol, relation, target_symbol, file_path, line_number, 1,
                       source_symbol || ' -[' || relation || ']-> ' || target_symbol
                FROM code_edges
                WHERE {base_proj_clause}
                  AND (source_symbol = ? OR source_symbol LIKE ? OR file_path LIKE ?)
                UNION ALL
                SELECT e.source_symbol, e.relation, e.target_symbol, e.file_path, e.line_number, d.depth + 1,
                       d.path || ' -[' || e.relation || ']-> ' || e.target_symbol
                FROM code_edges e
                -- Same qualified/bare reconciliation as callers_cte, outbound.
                JOIN deps_cte d ON (
                    e.source_symbol = d.target
                    OR d.target LIKE '%.' || e.source_symbol
                    OR e.source_symbol LIKE '%.' || d.target
                )
                WHERE {rec_proj_clause}
                  AND d.depth < ?
                  AND INSTR(d.path, e.target_symbol) = 0
            )
            SELECT DISTINCT source, relation, target, file_path, line_number, depth, path
            FROM deps_cte
            ORDER BY depth, file_path, line_number;
        """

        args: list = []
        if proj:
            args.append(proj)
        args.extend([symbol_or_module, f"%.{symbol_or_module}", f"%{symbol_or_module}%"])
        if proj:
            args.append(proj)
        args.append(max_depth)

        cur.execute(query, args)
        rows = cur.fetchall()
        con.close()

        results = []
        for r in rows:
            results.append({
                "source": r[0],
                "relation": r[1],
                "target": r[2],
                "file_path": r[3],
                "line_number": r[4],
                "depth": r[5],
                "dependency_chain": r[6]
            })
        return results

    def get_impact(self, target: str, project: Optional[str] = None, max_depth: int = 5) -> Dict[str, Any]:
        """Blast-radius analysis: Transitive callers/importers across the codebase when modifying a target."""
        con = self._get_con(mode="ro")
        cur = con.cursor()

        # If target looks like a file or path, also check symbols defined in that file
        file_syms: List[str] = []
        target_clean = str(target).strip()
        proj_filter = project or self.project

        cur.execute("""
            SELECT DISTINCT name, qualified_name FROM code_symbols
            WHERE (file_path = ? OR file_path LIKE ?) AND (? IS NULL OR project = ?)
        """, (target_clean, f"%{target_clean}%", proj_filter, proj_filter))
        for r in cur.fetchall():
            file_syms.append(r[0])
            file_syms.append(r[1])
        con.close()

        all_callers: List[Dict[str, Any]] = []
        seen_chains: Set[str] = set()

        targets_to_check = [target_clean]
        if "." in target_clean or "/" in target_clean:
            stem = Path(target_clean).stem
            if stem not in targets_to_check:
                targets_to_check.append(stem)
        for s in file_syms[:20]:
            if s not in targets_to_check:
                targets_to_check.append(s)

        for t in targets_to_check:
            callers = self.get_callers(t, project=project, max_depth=max_depth)
            for c in callers:
                if c["call_chain"] not in seen_chains:
                    seen_chains.add(c["call_chain"])
                    all_callers.append(c)

        impacted_symbols = set()
        impacted_files = set()
        chains = []

        for c in all_callers:
            impacted_symbols.add(c["caller"])
            impacted_files.add(c["file_path"])
            chains.append(f"{c['depth']} hop(s): {c['call_chain']}")

        risk_level = "LOW"
        if len(impacted_files) >= 5 or len(impacted_symbols) >= 10:
            risk_level = "HIGH"
        elif len(impacted_files) >= 2 or len(impacted_symbols) >= 3:
            risk_level = "MEDIUM"

        return {
            "target": target,
            "project": project or self.project or "global",
            "impact_risk": risk_level,
            "impacted_symbol_count": len(impacted_symbols),
            "impacted_file_count": len(impacted_files),
            "impacted_symbols": sorted(list(impacted_symbols)),
            "impacted_files": sorted(list(impacted_files)),
            "dependency_chains": chains[:15]
        }

    def search(self, query: str, limit: int = 5) -> List[Hit]:
        """Search code symbols and return as standard MemoryLayer Hits."""
        syms = self.search_symbols(query, limit=limit)
        hits = []
        for s in syms:
            txt = f"{s['kind'].upper()} {s['qualified_name']} ({s['file_path']}:{s['start_line']}-{s['end_line']})"
            if s.get("signature"):
                txt += f" :: {s['signature']}"
            hits.append(Hit(text=txt, source=self.name, ref=s["file_path"], score=1.0))
        return hits

    @staticmethod
    def format_structure(symbols: List[Dict[str, Any]]) -> str:
        """Format structural outline into readable markdown."""
        if not symbols:
            return "(no symbols found)"

        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for s in symbols:
            by_file.setdefault(s["file_path"], []).append(s)

        lines = []
        for fp, sym_list in by_file.items():
            lines.append(f"### `{fp}` ({len(sym_list)} symbols)")
            for s in sym_list:
                prefix = "  - " if s.get("parent_symbol") else "- "
                sig = f"`{s['signature']}`" if s.get("signature") else f"`{s['qualified_name']}`"
                lines.append(f"{prefix}**{s['kind']}** {sig} (L{s['start_line']}-L{s['end_line']})")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def format_callers(callers: List[Dict[str, Any]], symbol: str) -> str:
        """Format callers query results."""
        if not callers:
            return f"No inbound callers or references found for `{symbol}`."

        lines = [f"### Callers & Inbound References for `{symbol}` ({len(callers)} found)"]
        for c in callers:
            lines.append(f"- **{c['caller']}** [{c['relation']}] (L{c['line_number']} in `{c['file_path']}`) [depth {c['depth']}]")
            lines.append(f"  *Chain*: {c['call_chain']}")
        return "\n".join(lines)

    @staticmethod
    def format_dependencies(deps: List[Dict[str, Any]], symbol: str) -> str:
        """Format dependencies query results."""
        if not deps:
            return f"No outbound dependencies or calls found for `{symbol}`."

        lines = [f"### Outbound Dependencies & Calls for `{symbol}` ({len(deps)} found)"]
        for d in deps:
            lines.append(f"- **{d['target']}** [{d['relation']}] (L{d['line_number']} in `{d['file_path']}`) [depth {d['depth']}]")
            lines.append(f"  *Chain*: {d['dependency_chain']}")
        return "\n".join(lines)

    @staticmethod
    def format_impact(impact: Dict[str, Any]) -> str:
        """Format impact analysis results."""
        lines = [
            f"### Blast Radius Impact Analysis: `{impact['target']}`",
            f"- **Risk Level**: `{impact['impact_risk']}`",
            f"- **Impacted Files**: {impact['impacted_file_count']}",
            f"- **Impacted Symbols**: {impact['impacted_symbol_count']}",
        ]
        if impact.get("impacted_files"):
            lines.append(f"- **Files Affected**: {', '.join(impact['impacted_files'][:10])}")
        if impact.get("impacted_symbols"):
            lines.append(f"- **Symbols Affected**: {', '.join(impact['impacted_symbols'][:15])}")
        if impact.get("dependency_chains"):
            lines.append("\n**Upstream Dependency Paths**:")
            for ch in impact["dependency_chains"][:8]:
                lines.append(f"  - {ch}")
        return "\n".join(lines)
