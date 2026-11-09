#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CoSightBot PKM 端到端回归冒烟脚本（可重复执行）。

用法（在本目录=包根下执行，需先 `python scripts/install.py` 完成首装）：

    python scripts/smoke_test.py                # 全量（LLM 走 data/.env 配置）
    python scripts/smoke_test.py --offline      # 只跑不依赖 LLM/embedding 的静态与闸门用例
    python scripts/smoke_test.py --keep         # 保留临时 HOME（调试用）

覆盖：
  S 系列  静态：compileall / 预检 exit 3 / install 幂等 / stamp 漂移
  O 系列  PKM 链：bind→自动首建→status 对账→retrieve 章节树→read-doc→scan→
          ingest（session + --global + 裸降级）→会话隔离→remove→增量链→unbind
  N 系列  负例：无 LLM 配置时构建必须硬失败（非零退出）

判定全部基于退出码 + 结构化 JSON 断言，零目测。任一 FAIL → 总退出码 1。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re as _re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
RUNTIME = WORKDIR / "runtime" / "pkm"
VENV_NAME = ".venv-pkm"
STAMP = ".install-stamp-pkm"
SKILLS = WORKDIR / "skills"
RESULTS: list[tuple[str, str, str]] = []  # (case, status, detail)

# 子进程环境：剔除外部 ANTHROPIC_*/代理，保证走 data/.env 的配置（可复现）
_STRIP_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY",
              "ANTHROPIC_MODEL", "all_proxy", "ALL_PROXY", "http_proxy", "https_proxy",
              # 宿主要是 CC 会话，这个变量会泄漏进子进程让裸 ingest 误判为会话级，
              # 必须剥离；需要会话级的用例通过 extra_env 显式注入
              "CLAUDE_CODE_SESSION_ID")


def _env(home: Path, extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    env["COSIGHTBOT_HOME"] = str(home)
    if Path("/etc/pki/tls/certs/ca-bundle.crt").exists():
        env.setdefault("SSL_CERT_FILE", "/etc/pki/tls/certs/ca-bundle.crt")
    if extra:
        env.update(extra)
    return env


def run(cmd: list[str], home: Path, timeout: int = 900, extra_env: dict | None = None,
        cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=_env(home, extra_env), cwd=cwd or WORKDIR)


def _state_root() -> Path:
    """数据根解析链（与 runtime/common/port_resolver.py 一致）。"""
    for env_key in ("COSIGHTBOT_HOME", "CLAUDE_PLUGIN_DATA"):
        v = (os.environ.get(env_key) or "").strip()
        if v:
            return Path(v).expanduser()
    return Path.home() / ".claude" / "plugins" / "data" / "cosightbot"


def py(home: Path, script: str) -> list[str]:
    return [str(home / VENV_NAME / "bin" / "python"), str(script)]


def cheap_install(home: Path) -> None:
    """轻量初始化（等价 install.py 的目录+stamp 部分，跳过 pip 安装）。

    用于"环境已装但无 LLM/embedding 配置"的负例空 HOME——完整 pip 安装
    由 S-03 的真实 install.py 调用覆盖，这里只为负例构造合法 stamp。
    """
    home.mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(exist_ok=True)
    stamp = hashlib.sha256((RUNTIME / "requirements.txt").read_bytes()).hexdigest()
    (home / STAMP).write_text(stamp, encoding="utf-8")


def record(case: str, ok: bool | None, detail: str = "") -> None:
    status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    RESULTS.append((case, status, detail))
    print(f"[{status}] {case}" + (f" — {detail}" if detail else ""), flush=True)


def last_json(stdout: str) -> dict | None:
    """从 stdout 提取最后一个 JSON 对象。"""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    i, j = stdout.find("{"), stdout.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(stdout[i:j + 1])
        except json.JSONDecodeError:
            return None
    return None


def skill(rel: str) -> str:
    return str(SKILLS / rel)


def _write_minimal_pdf(pdf_path: Path) -> None:
    """写一个两页的最小 PDF：第 1 页中英文文本，第 2 页一张纯色图。

    不依赖任何 PDF 生成库——`pypdfium2` 只能读不能写（PDFium 的公开 API 没有
    建字体/写字形的接口），而 AGPL 的 PyMuPDF 已整体移除。这里直接按 PDF 规范
    拼字节，冒烟用例要的就是「一个能被解析出文字与内嵌图的 PDF」。

    中文用 Type0 + `UniGB-UCS2-H` 预定义 CMap（不嵌字体，靠 PDF 阅读器的
    Adobe-GB1 映射），抽文本时能还原成正确的 Unicode。
    """
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    cjk_hex = "最大吞吐 SENTINEL_EPSILON_4096 Gbps。".encode("utf-16-be").hex().upper()
    stream1 = (b"BT /F1 18 Tf 72 700 Td (Epsilon PDF Sentinel Page) Tj ET\n"
               b"BT /F1 18 Tf 72 660 Td (Max throughput SENTINEL_EPSILON_4096 Gbps.) Tj ET\n"
               b"BT /F2 18 Tf 72 620 Td <" + cjk_hex.encode() + b"> Tj ET")
    stream2 = b"q 120 0 0 80 72 500 cm /Im0 Do Q"
    imgdata = bytes([255, 0, 0]) * 16  # 4x4 纯红 RGB

    # 对象编号要与下面的互相引用一致，按写入顺序分配
    cat = add(b"<< /Type /Catalog /Pages 2 0 R >>")                      # 1
    add(b"<< /Type /Pages /Kids [3 0 R 8 0 R] /Count 2 >>")               # 2
    add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "         # 3
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>")
    add(b"<< /Length " + str(len(stream1)).encode() + b" >>\nstream\n"   # 4
        + stream1 + b"\nendstream")
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>")                                # 5
    add(b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
        b"/Encoding /UniGB-UCS2-H /DescendantFonts [7 0 R] >>")           # 6
    add(b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 2 >> "
        b"/DW 1000 >>")                                                  # 7
    add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "         # 8
        b"/Resources << /XObject << /Im0 9 0 R >> >> /Contents 10 0 R >>")
    add(b"<< /Type /XObject /Subtype /Image /Width 4 /Height 4 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length "
        + str(len(imgdata)).encode() + b" >>\nstream\n"
        + imgdata + b"\nendstream")                                       # 9
    add(b"<< /Length " + str(len(stream2)).encode() + b" >>\nstream\n"   # 10
        + stream2 + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objs) + 1
    out += f"xref\n0 {n}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {n} /Root {cat} 0 R >>\nstartxref\n{xref_pos}\n"
            f"%%EOF\n").encode()
    pdf_path.write_bytes(bytes(out))


def make_pkm_docs(docs_dir: Path) -> dict[str, str]:
    """生成带哨兵字符串的PKM 测试文档（md/docx/pdf），返回 {文件名: 哨兵}。"""
    docs_dir.mkdir(parents=True, exist_ok=True)
    sentinels = {}
    md1 = docs_dir / "阿尔法网关手册.md"
    md1.write_text("# 阿尔法网关手册\n\n## 端口规格\n\n阿尔法 AG-100 提供 24 个千兆电口与 4 个万兆光口。\n\n"
                   "## 默认口令\n\n首次登录口令为 SENTINEL_ALPHA_7749。\n", encoding="utf-8")
    sentinels[md1.name] = "SENTINEL_ALPHA_7749"
    md2 = docs_dir / "贝塔交换机发布说明.md"
    md2.write_text("# 贝塔交换机发布说明\n\n## V2.3 变更\n\n新增 SENTINEL_BETA_3310 流量调度算法。\n", encoding="utf-8")
    sentinels[md2.name] = "SENTINEL_BETA_3310"
    md3 = docs_dir / "伽马路由器规格.md"
    md3.write_text("# 伽马路由器规格\n\n## 无线参数\n\n支持 Wi-Fi 6，并发带机量 SENTINEL_GAMMA_1024 台。\n", encoding="utf-8")
    sentinels[md3.name] = "SENTINEL_GAMMA_1024"
    try:
        import docx  # type: ignore
        d = docx.Document()
        d.add_heading("德尔塔 AC 控制器白皮书", level=1)
        d.add_paragraph("并发接入能力 SENTINEL_DELTA_2048 客户端。")
        docx_path = docs_dir / "德尔塔AC控制器白皮书.docx"
        d.save(str(docx_path))
        sentinels[docx_path.name] = "SENTINEL_DELTA_2048"
    except ImportError:
        print("[warn] python-docx 不可用，跳过 docx 用例生成")
    try:
        pdf_path = docs_dir / "伊普西龙性能报告.pdf"
        _write_minimal_pdf(pdf_path)
        sentinels[pdf_path.name] = "SENTINEL_EPSILON_4096"
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 最小 PDF 生成失败，跳过 pdf 用例生成: {e}")
    return sentinels


def main() -> int:
    ap = argparse.ArgumentParser(description="CoSightBot PKM 端到端回归冒烟")
    ap.add_argument("--home", default=None, help="测试数据 HOME（默认临时目录）")
    ap.add_argument("--offline", action="store_true", help="跳过依赖 LLM 的用例")
    ap.add_argument("--keep", action="store_true", help="保留临时 HOME")
    args = ap.parse_args()

    home = Path(args.home) if args.home else Path(tempfile.mkdtemp(prefix="cosightbot-pkm-smoke-"))
    home.mkdir(parents=True, exist_ok=True)
    docs = home / "docs"
    print(f"=== smoke home: {home} ===", flush=True)

    offline = args.offline
    env_file = _state_root() / ".env"
    has_llm_cfg = env_file.exists() and "OPENAI_API_KEY=" in env_file.read_text(encoding="utf-8")
    if not offline and not has_llm_cfg:
        print("[warn] data/.env 无 LLM 配置，自动降级 --offline")
        offline = True

    # ---- S 系列：静态 / 安装链路 ----
    p = subprocess.run([sys.executable, "-m", "compileall", "-q",
                        str(RUNTIME), str(SKILLS), str(WORKDIR / "scripts")],
                       capture_output=True, text=True)
    record("S-01 compileall 全量语法", p.returncode == 0, p.stderr.strip()[:200])

    p = run([sys.executable, skill("cosightbot-material/scripts/material_cli.py"), "status"], home)
    j = last_json(p.stdout)
    record("S-02 未首装预检 exit 3", p.returncode == 3 and bool(j and j.get("hint") == "please_run_install"),
           f"exit={p.returncode} hint={(j or {}).get('hint')}")

    p = run([sys.executable, "scripts/install.py"], home)
    record("S-03 install.py 初始化 smoke HOME", p.returncode == 0 and (home / STAMP).exists())
    p2 = run([sys.executable, "scripts/install.py"], home)
    record("S-04 install.py 幂等重跑", p2.returncode == 0)

    # stamp 漂移：preflight 比对 requirements.txt 的 sha256，追加注释行即应触发 exit 3
    req = RUNTIME / "requirements.txt"
    orig_bytes = req.read_bytes()
    req.write_bytes(orig_bytes + b"\n# smoke-drift-probe\n")
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["status"], home)
    j = last_json(p.stdout)
    record("S-05 requirements 漂移检测", p.returncode == 3 and bool(j and "requirements" in str(j.get("reason", ""))),
           f"exit={p.returncode}")
    req.write_bytes(orig_bytes)
    run([sys.executable, "scripts/install.py"], home)  # 恢复 stamp

    # S-06：ASCII tokenizer 不得把句末标点带进 token（M3PROMOTED. → m3promoted）
    tokenizer_probe = (
        "import sys; "
        f"sys.path.insert(0, {str(RUNTIME)!r}); "
        "from common.text_tokenize import tokenize; "
        "t = tokenize('keyword M3PROMOTED. Done, next.'); "
        "assert 'm3promoted' in t and 'm3promoted.' not in t; "
        "assert 'err_401_02' in tokenize('ERR_401_02'); "
        "print('OK')"
    )
    p = subprocess.run([str(home / VENV_NAME / "bin" / "python"), "-c", tokenizer_probe],
                       capture_output=True, text=True, cwd=WORKDIR)
    record("S-06 tokenizer 句末标点", p.returncode == 0 and "OK" in p.stdout,
           (p.stderr or "").strip()[:200])

    # S-07：M-3 / 动态引擎 / FTS 的离线单测门禁（runtime/pkm 为包根）
    p = run([str(home / VENV_NAME / "bin" / "python"), "-m", "unittest",
             "common.auto_tests.test_fts_index",
             "common.auto_tests.test_dynamic_engine",
             "common.auto_tests.test_overview_resolver_node_ids",
             "watch_dog.file_watcher.auto_tests.test_overview_stable_ids",
             "watch_dog.file_watcher.auto_tests.test_section_index"], home,
            timeout=300, cwd=RUNTIME)
    record("S-07 M-3/动态/FTS 离线单测", p.returncode == 0,
           (p.stderr or "").strip().splitlines()[-1] if p.stderr else "")

    # 把包内 data/.env 的有效配置复制进 smoke HOME（模拟用户配置）
    smoke_env = home / ".env"
    if env_file.exists():
        lines = [l for l in env_file.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        with smoke_env.open("a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(lines) + "\n")

    # ---- N-01：无 LLM 配置时构建必须硬失败 ----
    empty_home = home / "empty-env-home"
    cheap_install(empty_home)
    sentinels = make_pkm_docs(docs)
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["bind", str(docs)], empty_home)
    j = last_json(p.stdout)
    record("N-01 无 LLM 配置构建硬失败",
           p.returncode != 0 and bool(j and j.get("auto_build") is False),
           f"exit={p.returncode} auto_build={(j or {}).get('auto_build')}")

    if offline:
        print_summary(home, args.keep)
        return summarize_exit()

    # ---- O 系列：PKM 链 ----
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["bind", str(docs)], home, timeout=1800)
    j = last_json(p.stdout)
    record("O-01 bind + 自动首建", p.returncode == 0 and bool(j and j.get("auto_build") is True),
           f"exit={p.returncode}")
    record("O-02 进度行实时流出", "[progress]" in p.stdout)

    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["status"], home)
    j = last_json(p.stdout)
    pc = (j or {}).get("pending_changes", {})
    record("O-03 status 对账 ready 且无待入库",
           bool(j and j.get("index_status") == "ready" and pc == {"new": 0, "modified": 0, "deleted": 0}),
           f"index_status={(j or {}).get('index_status')} pending={pc}")

    p = run(py(home, skill("cosightbot-retrieve/scripts/retrieve_cli.py")) + ["--agent-id", "main"], home)
    j = last_json(p.stdout)
    ov = (j or {}).get("merged_overview", "")
    record("O-04 retrieve 章节树 ready + F 节点",
           bool(j and j.get("ready") is True and "[f" in ov.lower()), f"ready={(j or {}).get('ready')}")

    # read-doc：找 F 节点读全文，验证哨兵字符串可达
    node_ids = _re.findall(r"\[f\d{3,}\]", ov, flags=_re.I)
    read_ok, scanned = False, 0
    for nid in node_ids[:8]:
        q = run(py(home, skill("cosightbot-retrieve/scripts/retrieve_cli.py")) +
                ["--agent-id", "main", "read-doc", "--node-id", nid.strip("[]")], home)
        jj = last_json(q.stdout)
        content = json.dumps(jj, ensure_ascii=False) if jj else ""
        scanned += 1
        if any(s in content.replace("\\", "") for s in sentinels.values()):
            read_ok = True
            break
    record("O-05 read-doc 实读命中哨兵", read_ok, f"扫描 {scanned} 节点")

    p = run(py(home, skill("cosightbot-retrieve/scripts/retrieve_cli.py")) +
            ["--agent-id", "main", "scan", "--terms", "SENTINEL_GAMMA_1024"], home)
    j = last_json(p.stdout)
    record("O-06 scan 术语命中", p.returncode == 0 and "SENTINEL_GAMMA_1024" in p.stdout
           and (j is None or j.get("ok", True) is not False), f"exit={p.returncode}")

    # ingest --global（agent 级 inbox 路由）
    extra_doc = home / "西格玛补充说明.md"
    extra_doc.write_text("# 西格玛补充说明\n\n备件编码 SENTINEL_SIGMA_555。\n", encoding="utf-8")
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["ingest", "--global", str(extra_doc)],
            home, timeout=900)
    j = last_json(p.stdout)
    record("O-07 ingest --global 入 inbox + 自动入库",
           p.returncode == 0 and '"scope": "global"' in p.stdout and bool(j and j.get("auto_build") is True),
           f"exit={p.returncode}")
    p = run(py(home, skill("cosightbot-retrieve/scripts/retrieve_cli.py")) + ["--agent-id", "main"], home)
    j = last_json(p.stdout)
    record("O-08 inbox 路由进章节树", "inbox:agent" in ((j or {}).get("merged_overview", "")))

    # ingest session（显式注入 session id）
    sess_doc = home / "欧米茄会话资料.md"
    sess_doc.write_text("# 欧米茄会话资料\n\n会话令牌 SENTINEL_OMEGA_999。\n", encoding="utf-8")
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["ingest", str(sess_doc)],
            home, timeout=900, extra_env={"CLAUDE_CODE_SESSION_ID": "smoke-session-0001"})
    j = last_json(p.stdout)
    record("O-09 ingest 会话级入库", p.returncode == 0 and bool(j and j.get("auto_build") is True),
           f"exit={p.returncode}")
    p = run(py(home, skill("cosightbot-retrieve/scripts/retrieve_cli.py")) + ["--agent-id", "main"],
            home, extra_env={"CLAUDE_CODE_SESSION_ID": "smoke-session-0001"})
    j = last_json(p.stdout)
    record("O-10 会话路由进章节树", "SENTINEL_OMEGA" in json.dumps(j, ensure_ascii=False)
           or "欧米茄" in ((j or {}).get("merged_overview", "")))

    # 会话隔离断言：不带 session id 检索时不得看到会话路由
    p = run(py(home, skill("cosightbot-retrieve/scripts/retrieve_cli.py")) + ["--agent-id", "main"], home)
    j = last_json(p.stdout)
    record("O-10b 会话隔离：无 session id 不可见会话资料",
           "欧米茄" not in ((j or {}).get("merged_overview", "")))

    # 降级路径：无 session id 的裸 ingest → global_fallback + notice
    fb_doc = home / "陶氏降级资料.md"
    fb_doc.write_text("# 陶氏降级资料\n\n降级哨兵 SENTINEL_TAU_777。\n", encoding="utf-8")
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["ingest", str(fb_doc)], home, timeout=900)
    record("O-10c 裸 ingest 无 session → global_fallback + notice",
           p.returncode == 0 and '"scope": "global_fallback"' in p.stdout and "notice" in p.stdout,
           f"exit={p.returncode}")

    # remove --global + unbind
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["remove", "--global", extra_doc.name], home)
    ok1 = p.returncode == 0 and '"ok": true' in p.stdout
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["remove", "--global", fb_doc.name], home)
    ok2 = p.returncode == 0 and '"ok": true' in p.stdout
    record("O-11 remove --global（含降级入库文件）", ok1 and ok2)
    p = run(py(home, skill("cosightbot-retrieve/scripts/retrieve_cli.py")) + ["--agent-id", "main"], home)
    j = last_json(p.stdout)
    record("O-12 删除后 inbox 路由消失", "inbox:agent" not in ((j or {}).get("merged_overview", "")))

    # 增量链：改动绑定目录文件 → status 报 modified → build → 归零 → 新内容可检索
    alpha = docs / "阿尔法网关手册.md"
    alpha.write_text(alpha.read_text(encoding="utf-8") + "\n## 附录\n\n新增 SENTINEL_ALPHA_APPEND_888 说明。\n",
                     encoding="utf-8")
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["status"], home)
    j = last_json(p.stdout)
    drift = ((j or {}).get("pending_changes") or {}).get("modified") == 1
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["build"], home, timeout=1800)
    p2 = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["status"], home)
    j2 = last_json(p2.stdout)
    clean = (j2 or {}).get("pending_changes") == {"new": 0, "modified": 0, "deleted": 0}
    p3 = run(py(home, skill("cosightbot-retrieve/scripts/retrieve_cli.py")) +
             ["--agent-id", "main", "scan", "--terms", "SENTINEL_ALPHA_APPEND_888"], home)
    j3 = last_json(p3.stdout)
    record("O-14 改动→漂移检测→增量构建→新内容可检索",
           drift and p.returncode == 0 and clean and bool(j3 and j3.get("files_with_hits") == 1),
           f"drift={drift} build_exit={p.returncode} clean={clean} hits={(j3 or {}).get('files_with_hits')}")

    src_hash_before = hash(tuple(sorted(p_.name for p_ in docs.iterdir())))
    p = run(py(home, skill("cosightbot-material/scripts/material_cli.py")) + ["unbind"], home)
    j = last_json(p.stdout)
    record("O-13 unbind 清索引不动原件",
           p.returncode == 0 and bool(j and j.get("unbound")) and src_hash_before == hash(tuple(sorted(p_.name for p_ in docs.iterdir()))),
           f"exit={p.returncode}")

    print_summary(home, args.keep)
    return summarize_exit()


def print_summary(home: Path, keep: bool) -> None:
    total = len(RESULTS)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    skipped = sum(1 for _, s, _ in RESULTS if s == "SKIP")
    print("\n===== 冒烟汇总 =====")
    print(f"total={total} pass={passed} fail={len(failed)} skip={skipped}")
    for case, _, detail in failed:
        print(f"  ❌ {case} — {detail}")
    if failed:
        print(f"home 保留于: {home}")
    elif not keep:
        shutil.rmtree(home, ignore_errors=True)
        print("（临时 HOME 已清理）")


def summarize_exit() -> int:
    return 1 if any(s == "FAIL" for _, s, _ in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
