"""开源红线自检：源码与构建输入里不得出现私有包依赖 / 私有网络地址 / 凭据字面量。

为什么 import 用 AST 查而不是 grep：部分模块的 docstring 会说明「某能力由外部服务提供」
这类边界，grep 会把说明文字也判成违规。真正要拦的是可执行代码里的依赖。

检查项：
  * 私有包 import；
  * 私有网络域名后缀与 IP 字面量（构建输入同样扫描）；
  * 源码里的密码 / token 字面量、JWT、私钥块；
  * 配置默认值里不能有非空凭据。

注意：本文件自己也会被扫。所以域名模式由片段拼出来（不在源码里写完整域名），
否则这个守卫会把自己判成违规。
"""
import ast
import pathlib
import re

# 扫描整个服务源码 + 构建输入。本文件在 <服务根>/tests/engine/ 下，parents[2] 是服务根。
HOST_ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVICE_SRC = HOST_ROOT / 'src'
SCAN_DIRS = [SERVICE_SRC]
BUILD_INPUTS = [HOST_ROOT / 'Dockerfile', HOST_ROOT / 'requirements.txt']

PRIVATE_PACKAGE_ROOTS = ('nae_sm_agent', 'naecommonbase4py', 'text2sql', 'retrofit_py', 'msb')

_INTERNAL_DOMAINS = ('zte' + r'\.intra', 'zte' + r'\.com\.cn', r'\.zte' + r'\.')
INTERNAL_HOST_RE = re.compile(
    r'(?i)(' + '|'.join(_INTERNAL_DOMAINS) + r'|https?://\d{1,3}(?:\.\d{1,3}){3})')

SECRET_RE = re.compile(
    r"""(?ix)
    \b(?:password|passwd|secret|access[_-]?key|access[_-]?token|api[_-]?key|auth[_-]?token)
    \s*[:=]\s*(['"])(?P<value>[^'"]{8,})\1
    """)

JWT_RE = re.compile(r'eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.')
PRIVATE_KEY_RE = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')


def _python_files():
    for directory in SCAN_DIRS:
        for path in sorted(directory.rglob('*.py')):
            if '__pycache__' not in path.parts:
                yield path


def test_no_private_package_imports():
    """AST 层面：没有一行代码真的 import 私有包。"""
    violations = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            else:
                continue
            for name in names:
                root = name.split('.')[0]
                if root in PRIVATE_PACKAGE_ROOTS:
                    violations.append(f'{path.relative_to(HOST_ROOT)}:{node.lineno} -> {name}')
    assert violations == [], f'发现私有包依赖：{violations}'


def test_no_internal_hosts_in_code_or_build_files():
    violations = []
    missing = [str(path) for path in BUILD_INPUTS if not path.exists()]
    # 构建输入必须被真实扫描。路径算错时**硬失败**，不能静默 continue ——
    # 否则「扫了 0 个构建文件」会伪装成绿色。
    assert not missing, f'构建输入不存在，无法执行红线扫描：{missing}'
    targets = list(_python_files()) + BUILD_INPUTS
    for path in targets:
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
            if INTERNAL_HOST_RE.search(line):
                violations.append(f'{path.relative_to(HOST_ROOT)}:{lineno}: {line.strip()}')
    assert violations == [], f'发现私有网络地址：{violations}'


def test_no_credentials_in_source():
    violations = []
    for path in _python_files():
        text = path.read_text(encoding='utf-8')
        for lineno, line in enumerate(text.splitlines(), start=1):
            if SECRET_RE.search(line) or JWT_RE.search(line) or PRIVATE_KEY_RE.search(line):
                violations.append(f'{path.relative_to(HOST_ROOT)}:{lineno}: {line.strip()}')
    assert violations == [], f'发现疑似凭据字面量：{violations}'


def test_config_has_no_baked_credentials():
    """`config.py` 的默认值里不能有凭据类字段的**非空**默认值
    （约定：只读环境变量，源码不放任何默认凭据）。

    判定按字段名后缀（`*_key` / `*_token` / `*_password` / `*_secret`），
    所以 `generation_max_tokens` 这类「名字里有 token 但不是凭据」的不会被误判。
    """
    import engine.settings as config

    suspicious = {key: value for key, value in config.Config.items()
                  if key.endswith(('_key', '_token', '_password', '_secret')) and value}
    assert suspicious == {}, f'配置里有非空默认凭据：{suspicious}'
