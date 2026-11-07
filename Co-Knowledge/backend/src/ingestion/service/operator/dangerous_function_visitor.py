import ast
from typing import Dict, List


class DangerousCodeVisitor(ast.NodeVisitor):
    # 常见危险函数名（直接调用）
    DANGEROUS_BUILTINS = {'eval', 'exec', 'compile', 'input', '__import__'}

    # open() 敏感路径：这些路径的 open/read 视为危险
    SENSITIVE_FILE_PATTERNS = (
        '/etc/passwd',
        '/etc/shadow',
        '/etc/sudoers',
        '.env',
        '.secret',
        'id_rsa',
        'id_dsa',
    )

    # 危险的系统调用模块和函数
    DANGEROUS_MODULE_FUNCTIONS = {
        'os': ['system', 'popen', 'popen2', 'popen3', 'popen4', 'spawn*', 'execl*',
               'execv', 'execve', 'execvp', 'execvpe', 'fork', 'forkpty',
               'setuid', 'setgid', 'seteuid', 'setegid', 'chroot', 'chdir'],
        'subprocess': ['call', 'check_call', 'check_output', 'run', 'Popen'],
        'pickle': ['load', 'loads'],
        'shelve': ['open', 'DbfilenameShelf'],
        'tempfile': ['mktemp'],
        'xml.etree.ElementTree': ['parse', 'fromstring'],
        'xml.sax': ['parse', 'make_parser'],
        'http.server': ['HTTPServer'],
        'flask': ['run'],
        # 原生代码调用是绕过纯 Python 黑名单的常见路径。
        'ctypes': ['CDLL', 'PyDLL', 'cdll', 'windll', 'oledll', 'CFUNCTYPE',
                   'WINFUNCTYPE', 'pythonapi'],
        'importlib': ['import_module', 'reload'],
        # 网络外联：算子只应处理传入的文件，不应主动访问外部端点。
        # ``urllib.request.urlopen`` 会原样通过并成功入库。
        'urllib.request': ['urlopen', 'urlretrieve', 'Request', 'build_opener', 'OpenerDirector'],
        'urllib': ['urlopen', 'urlretrieve', 'Request'],
        'urllib3': ['request', 'PoolManager', 'ProxyManager'],
        'requests': ['get', 'post', 'put', 'delete', 'patch', 'head', 'request', 'Session'],
        'httpx': ['get', 'post', 'put', 'delete', 'patch', 'request', 'Client'],
        'aiohttp': ['request', 'ClientSession'],
        'socket': ['socket', 'create_connection', 'create_server'],
        'http.client': ['HTTPConnection', 'HTTPSConnection'],
        'ftplib': ['FTP', 'FTP_TLS'],
        'paramiko': ['SSHClient', 'Transport'],
    }
    DANGEROUS_CTYPE_FUNCTIONS = {'system'}

    def __init__(self, scope_info: Dict = None):
        self.issues = []
        self.scope_info = scope_info or {}
        self.scope_stack: List[ast.AST] = []

    def _get_constant_str(self, node: ast.AST) -> str:
        if node is None:
            return ''
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        ast_str = getattr(ast, 'Str', None)
        if ast_str and isinstance(node, ast_str):
            return getattr(node, 's', '')
        return ''

    def _is_sensitive_path(self, path: str) -> bool:
        if not path:
            return False
        path_lower = path.lower()
        for pattern in self.SENSITIVE_FILE_PATTERNS:
            if pattern in path or pattern in path_lower:
                return True
        return False

    def visit_Call(self, node):
        func = node.func

        # 绕过用例：getattr(module, 'dangerous_attr') 动态取属性后再调用
        if isinstance(func, ast.Call):
            self._check_getattr_call(node, func)
        # 绕过用例：__builtins__['eval'] / builtins['eval'] 下标访问后再调用
        elif isinstance(func, ast.Subscript):
            self._check_builtins_subscript(node, func)

        if isinstance(func, ast.Name) and func.id in self.DANGEROUS_BUILTINS:
            self.add_issue('dangerous_builtin', f"Use of dangerous builtin '{func.id}'", node)

        elif isinstance(func, ast.Name) and func.id == 'open':
            if node.args:
                path_str = self._get_constant_str(node.args[0])
                if self._is_sensitive_path(path_str):
                    self.add_issue('dangerous_file_access', f"Opening sensitive file: open({path_str!r})", node)

        elif isinstance(func, ast.Name) and self.scope_info:
            current_scope = self.scope_stack[-1] if self.scope_stack else None
            if current_scope and current_scope in self.scope_info:
                aliases = self.scope_info[current_scope].get('dangerous_aliases', {})
                if func.id in aliases:
                    full_attr = aliases[func.id]
                    self.add_issue(
                        'dangerous_module_call',
                        f"Potential dangerous call via alias: '{func.id}' -> {full_attr}",
                        node,
                    )
                # 绕过用例：from os import system; system(...)
                from_imports = self.scope_info[current_scope].get('from_imports', {})
                if func.id in from_imports and _is_dangerous_full_attr(from_imports[func.id]):
                    self.add_issue(
                        'dangerous_module_call',
                        f"Potential dangerous call via from-import: '{func.id}' -> {from_imports[func.id]}",
                        node,
                    )

        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Call):
                inner = func.value
                if isinstance(inner.func, ast.Name) and inner.func.id == 'open':
                    if inner.args:
                        path_str = self._get_constant_str(inner.args[0])
                        if self._is_sensitive_path(path_str):
                            self.add_issue(
                                'dangerous_file_access',
                                f"Reading sensitive file: open({path_str!r}).{func.attr}()",
                                node,
                            )
            self.check_attribute_call(node, func)

        self.generic_visit(node)

    def _check_getattr_call(self, node, inner_call):
        """绕过用例：getattr(os, 'system')(...) 之类动态取属性调用。"""
        inner_func = inner_call.func
        if not (isinstance(inner_func, ast.Name) and inner_func.id in ('getattr', '__getattribute__')):
            return
        if len(inner_call.args) < 2:
            return
        target = inner_call.args[0]
        attr_name = self._get_constant_str(inner_call.args[1])
        if not attr_name:
            return
        # 仅覆盖直接模块名（import os 后 getattr(os, 'system')）；别名场景已由 check_attribute_call 覆盖
        if isinstance(target, ast.Name):
            module_name = target.id
            for module, funcs in self.DANGEROUS_MODULE_FUNCTIONS.items():
                root = module.split('.')[0]
                if module_name != root:
                    continue
                if attr_name in funcs or any(
                    p.endswith('*') and attr_name.startswith(p[:-1]) for p in funcs
                ):
                    self.add_issue(
                        'dangerous_module_call',
                        f"Potential dangerous call via getattr: getattr({module_name}, {attr_name!r})",
                        node,
                    )
                    return

    def _check_builtins_subscript(self, node, subscript):
        """绕过用例：__builtins__['eval'](...) 下标访问危险内建。"""
        value = subscript.value
        if isinstance(value, ast.Name) and value.id in ('__builtins__', 'builtins'):
            key = self._get_constant_str(subscript.slice)
            if key in self.DANGEROUS_BUILTINS:
                self.add_issue(
                    'dangerous_builtin',
                    f"Use of dangerous builtin via subscript: {value.id}[{key!r}]",
                    node,
                )

    def visit_Module(self, node: ast.Module):
        self.scope_stack.append(node)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.scope_stack.append(node)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.scope_stack.append(node)
        self.generic_visit(node)
        self.scope_stack.pop()

    def check_attribute_call(self, node: ast.Call, attr_node: ast.Attribute):
        attr_path = []
        current = attr_node
        while isinstance(current, ast.Attribute):
            attr_path.insert(0, current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            attr_path.insert(0, current.id)

        full_attr = '.'.join(attr_path)

        current_scope = self.scope_stack[-1] if self.scope_stack else None
        if attr_path and current_scope and current_scope in self.scope_info and isinstance(current, ast.Name):
            # 解析 import 别名：import subprocess as sp -> sp.Popen -> subprocess.Popen
            imports = self.scope_info[current_scope].get('imports', {})
            from_imports = self.scope_info[current_scope].get('from_imports', {})
            dynamic_aliases = self.scope_info[current_scope].get('dynamic_module_aliases', {})
            root_name = attr_path[0]
            mapped_module = (
                imports.get(root_name, '')
                or from_imports.get(root_name, '')
                or dynamic_aliases.get(root_name, '')
            )
            if mapped_module:
                full_attr = '.'.join([mapped_module] + attr_path[1:])

        if attr_path and current_scope and current_scope in self.scope_info and isinstance(current, ast.Name):
            ctype_aliases = self.scope_info[current_scope].get('dangerous_ctype_aliases', {})
            root_name = attr_path[0]
            if root_name in ctype_aliases and attr_node.attr in self.DANGEROUS_CTYPE_FUNCTIONS:
                self.add_issue(
                    'dangerous_module_call',
                    f"Potential dangerous call via ctypes library handle: '{root_name}.{attr_node.attr}'",
                    node,
                )

        for module, funcs in self.DANGEROUS_MODULE_FUNCTIONS.items():
            for func_pattern in funcs:
                if func_pattern.endswith('*'):
                    if full_attr.startswith(module + '.' + func_pattern[:-1]):
                        self.add_issue('dangerous_module_call', f"Potential dangerous call '{full_attr}'", node)
                else:
                    if full_attr == f'{module}.{func_pattern}':
                        self.add_issue('dangerous_module_call', f"Potential dangerous call '{full_attr}'", node)

        if full_attr.startswith('subprocess.') and self.has_keyword_arg(node, 'shell', True):
            self.add_issue(
                'subprocess_shell_injection',
                f'subprocess call with shell=True detected: {full_attr} -> Command injection risk!',
                node,
            )

        if full_attr in ['pickle.load', 'pickle.loads']:
            self.add_issue(
                'insecure_deserialization',
                'Use of pickle.load() on untrusted data can lead to arbitrary code execution.',
                node,
            )

        if self.has_keyword_arg(node, 'debug', True):
            if full_attr == 'flask.Flask.run' or full_attr.endswith('.run'):
                self.add_issue(
                    'flask_debug_enabled',
                    'Flask app running with debug=True in production exposes security risks.',
                    node,
                )

    def has_keyword_arg(self, node: ast.Call, arg_name: str, expected_value) -> bool:
        for kw in node.keywords:
            if kw.arg == arg_name:
                if isinstance(kw.value, ast.Constant) and kw.value.value == expected_value:
                    return True
                if isinstance(kw.value, ast.NameConstant) and kw.value.value == expected_value:
                    return True
                if isinstance(kw.value, ast.Name) and hasattr(kw.value, 'id') and kw.value.id == 'True':
                    return expected_value is True
        return False

    def add_issue(self, issue_type: str, message: str, node: ast.AST):
        self.issues.append(
            {
                'type': issue_type,
                'message': message,
                'line': getattr(node, 'lineno', 'unknown'),
                'col': getattr(node, 'col_offset', 'unknown'),
            }
        )


#: 与 ``DangerousCodeVisitor.DANGEROUS_MODULE_FUNCTIONS`` 共用同一份清单，
#: 避免「类属性加了、from-import 匹配漏了」的漂移。
_DANGEROUS_MODULE_FUNCTIONS = DangerousCodeVisitor.DANGEROUS_MODULE_FUNCTIONS


def _is_dangerous_full_attr(full_attr: str) -> bool:
    for module, funcs in _DANGEROUS_MODULE_FUNCTIONS.items():
        for func_pattern in funcs:
            if func_pattern.endswith('*'):
                if full_attr.startswith(module + '.' + func_pattern[:-1]):
                    return True
            else:
                if full_attr == f'{module}.{func_pattern}':
                    return True
    return False


def _resolve_attr_to_full(
    attr_node: ast.Attribute,
    imports: Dict[str, str],
    from_imports: Dict[str, str],
    dynamic_module_aliases: Dict[str, str] = None,
) -> str:
    path = []
    current = attr_node
    while isinstance(current, ast.Attribute):
        path.insert(0, current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ''
    path.insert(0, current.id)
    dynamic_module_aliases = dynamic_module_aliases or {}
    if len(path) == 1:
        return from_imports.get(path[0], '') or (imports.get(path[0], '') or '')
    root = (
        imports.get(path[0], '')
        or (from_imports.get(path[0], '') if path[0] in from_imports else '')
        or dynamic_module_aliases.get(path[0], '')
    )
    if not root:
        return ''
    return root + '.' + '.'.join(path[1:])


def _collect_scope_stmts(body: list, out_imports: list, out_import_from: list, out_assigns: list):
    for node in body:
        if isinstance(node, ast.Import):
            out_imports.append(node)
        elif isinstance(node, ast.ImportFrom):
            out_import_from.append(node)
        elif isinstance(node, ast.Assign):
            out_assigns.append(node)
        elif isinstance(node, (ast.If, ast.For, ast.While, ast.With)):
            _collect_scope_stmts(getattr(node, 'body', []), out_imports, out_import_from, out_assigns)
            _collect_scope_stmts(getattr(node, 'orelse', []), out_imports, out_import_from, out_assigns)
        elif isinstance(node, ast.Try):
            _collect_scope_stmts(getattr(node, 'body', []), out_imports, out_import_from, out_assigns)
            for handler in getattr(node, 'handlers', []):
                _collect_scope_stmts(getattr(handler, 'body', []), out_imports, out_import_from, out_assigns)
            _collect_scope_stmts(getattr(node, 'orelse', []), out_imports, out_import_from, out_assigns)
            _collect_scope_stmts(getattr(node, 'finalbody', []), out_imports, out_import_from, out_assigns)


def _build_scope_info(tree: ast.AST) -> Dict[ast.AST, Dict]:
    scope_info = {}

    def _extract_dynamic_module_alias(value: ast.AST, imports: Dict[str, str], from_imports: Dict[str, str]) -> str:
        if not isinstance(value, ast.Call):
            return ''
        if not value.args:
            return ''
        module_name = ''
        first_arg = value.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            module_name = first_arg.value
        if not module_name:
            return ''
        if isinstance(value.func, ast.Attribute):
            func_full = _resolve_attr_to_full(value.func, imports, from_imports, {})
            if func_full == 'importlib.import_module':
                return module_name
        if isinstance(value.func, ast.Name):
            if value.func.id == '__import__':
                return module_name
            if from_imports.get(value.func.id, '') == 'builtins.__import__':
                return module_name
        return ''

    def _extract_ctype_library_alias(value: ast.AST, imports: Dict[str, str], from_imports: Dict[str, str]) -> bool:
        if not isinstance(value, ast.Call):
            return False
        func = value.func
        if isinstance(func, ast.Attribute):
            func_full = _resolve_attr_to_full(func, imports, from_imports, {})
            return func_full in {'ctypes.CDLL', 'ctypes.PyDLL', 'ctypes.cdll.LoadLibrary'}
        return False

    def process_scope(
        scope_node: ast.AST,
        body: list,
        inherited_imports: Dict[str, str] = None,
        inherited_from_imports: Dict[str, str] = None,
    ):
        imports = dict(inherited_imports or {})
        from_imports = dict(inherited_from_imports or {})
        out_imports, out_import_from, out_assigns = [], [], []
        _collect_scope_stmts(body, out_imports, out_import_from, out_assigns)

        for node in out_imports:
            for alias in node.names:
                name = alias.asname or alias.name
                mod = alias.name.split('.')[0] if alias.name else ''
                if mod:
                    imports[name] = mod
        for node in out_import_from:
            module = node.module or ''
            for alias in node.names:
                name = alias.asname or alias.name
                full = f'{module}.{alias.name}' if module else alias.name
                from_imports[name] = full

        dynamic_module_aliases = {}
        dangerous_ctype_aliases = set()
        for node in out_assigns:
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            dynamic_module = _extract_dynamic_module_alias(node.value, imports, from_imports)
            if dynamic_module:
                dynamic_module_aliases[target.id] = dynamic_module
            if _extract_ctype_library_alias(node.value, imports, from_imports):
                dangerous_ctype_aliases.add(target.id)

        dangerous_aliases = {}
        for node in out_assigns:
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if not isinstance(node.value, ast.Attribute):
                continue
            full_attr = _resolve_attr_to_full(node.value, imports, from_imports, dynamic_module_aliases)
            if full_attr and _is_dangerous_full_attr(full_attr):
                dangerous_aliases[target.id] = full_attr

        scope_info[scope_node] = {
            'imports': imports,
            'from_imports': from_imports,
            'dynamic_module_aliases': dynamic_module_aliases,
            'dangerous_ctype_aliases': dangerous_ctype_aliases,
            'dangerous_aliases': dangerous_aliases,
        }

    def walk(node: ast.AST, inherited_imports: Dict[str, str] = None, inherited_from_imports: Dict[str, str] = None):
        if isinstance(node, ast.Module):
            process_scope(node, node.body, inherited_imports, inherited_from_imports)
            current_imports = scope_info[node]['imports']
            current_from_imports = scope_info[node]['from_imports']
            for n in node.body:
                walk(n, current_imports, current_from_imports)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            process_scope(node, node.body, inherited_imports, inherited_from_imports)
            current_imports = scope_info[node]['imports']
            current_from_imports = scope_info[node]['from_imports']
            for n in node.body:
                walk(n, current_imports, current_from_imports)
        else:
            for child in ast.iter_child_nodes(node):
                walk(child, inherited_imports, inherited_from_imports)

    walk(tree)
    return scope_info


def scan_file_with_ast(file_path: str) -> List[Dict]:
    issues: List[Dict] = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        source = source.expandtabs(4)
        tree = ast.parse(source, filename=file_path)
        scope_info = _build_scope_info(tree)
        visitor = DangerousCodeVisitor(scope_info=scope_info)
        visitor.visit(tree)
        issues.extend(visitor.issues)
    except SyntaxError as e:
        issues.append({'type': 'syntax_error', 'message': str(e), 'line': e.lineno, 'col': e.offset})
    except Exception as e:
        # 带上异常类型：MemoryError 等异常的 str() 为空，只留 message 会得到
        # 「column unknown: 」这种无法定位的空报错。
        issues.append({'type': 'file_read_error', 'message': f'{type(e).__name__}: {e}'})
    return issues


def format_security_error(issues: List[Dict]) -> str:
    error_details = []
    for issue in issues:
        error_details.append(
            f"[{issue.get('type', 'unknown')}] line {issue.get('line', 'unknown')}, "
            f"column {issue.get('col', 'unknown')}: {issue.get('message', '')}"
        )
    return 'Code security check failed. The following potential risks were found:\n' + '\n'.join(error_details)


def validate_code_security(script_path: str) -> None:
    dangerous_issues = scan_file_with_ast(script_path)
    if dangerous_issues:
        raise Exception(format_security_error(dangerous_issues))