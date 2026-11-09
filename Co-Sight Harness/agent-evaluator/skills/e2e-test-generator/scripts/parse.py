#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse.py — S0 输入解析。

判类型 → 解包（tar.gz / zip）→ 定位 Agent 根并判定类型（COSIGHT.md / CLAUDE.md 锚点）
→ 归一 AgentAsset。

用法：
    python3 parse.py --agent <目录|.zip|.tar.gz> --work <中间态目录>
"""

import argparse
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

import config
from common import (
    GoldevalError,
    fail,
    sha256_tree,
    slug_from_path,
    work_path,
    write_json,
)

EXTRACT_DIRNAME = "extracted"


# ============================== 输入类型判定 ==============================

def sniff_magic(path, expected):
    """校验文件头魔数，防扩展名伪装。"""
    try:
        with path.open("rb") as handle:
            head = handle.read(len(expected))
    except OSError as exc:
        raise GoldevalError(f"无法读取输入文件：{path}（{exc}）") from exc
    return head == expected


def detect_kind(agent_path):
    """返回 'dir' / 'targz' / 'zip'；不支持的输入抛出 GoldevalError。"""
    if agent_path.is_dir():
        return "dir"

    if not agent_path.exists():
        raise GoldevalError(f"--agent 路径不存在：{agent_path}")

    name = agent_path.name.lower()
    size = agent_path.stat().st_size
    if size > config.MAX_ARCHIVE_BYTES:
        raise GoldevalError(
            f"压缩包超过体积上限 "
            f"({size} > {config.MAX_ARCHIVE_BYTES} 字节)：{agent_path}"
        )

    if name.endswith((".tar.gz", ".tgz")):
        if not sniff_magic(agent_path, config.TAR_MAGIC):
            raise GoldevalError(f"扩展名声明为 tar.gz 但魔数不匹配：{agent_path}")
        return "targz"

    if name.endswith(".zip"):
        if not sniff_magic(agent_path, config.ZIP_MAGIC):
            raise GoldevalError(f"扩展名声明为 zip 但魔数不匹配：{agent_path}")
        return "zip"

    raise GoldevalError(
        "不支持的输入格式，仅支持目录 / .zip / .tar.gz"
    )


# ============================== 安全解包 ==============================

def _assert_inside(target, dest_root):
    """校验解包目标仍在 dest_root 之内（防路径穿越 / zip-slip）。"""
    resolved = target.resolve()
    root = dest_root.resolve()
    if root != resolved and root not in resolved.parents:
        raise GoldevalError(f"压缩包含越界路径（疑似路径穿越）：{target}")


def _check_member(member_name, dest_root, counter):
    """对单个归档成员做安全校验，返回解包后的绝对路径。"""
    counter[0] += 1
    if counter[0] > config.MAX_EXTRACTED_FILES:
        raise GoldevalError(
            f"解包文件数超过上限（{config.MAX_EXTRACTED_FILES}）"
        )
    if member_name.startswith("/") or ".." in Path(member_name).parts:
        raise GoldevalError(f"压缩包含非法成员路径：{member_name}")
    dest = dest_root / member_name
    _assert_inside(dest, dest_root)
    return dest


def extract_targz(archive, dest_root):
    """安全解包 tar.gz：拒绝符号链接/硬链接/设备文件，校验体积。"""
    with tarfile.open(archive, "r:gz") as tar:
        counter = [0]
        for member in tar.getmembers():
            _check_member(member.name, dest_root, counter)
            if member.issym() or member.islnk():
                raise GoldevalError(
                    f"压缩包含链接成员（拒绝解包）：{member.name}"
                )
            if not (member.isfile() or member.isdir()):
                raise GoldevalError(
                    f"压缩包含非普通文件成员：{member.name}"
                )
            if member.isfile() and member.size > config.MAX_SINGLE_FILE_BYTES:
                raise GoldevalError(
                    f"压缩包内单文件超过上限：{member.name}（{member.size} 字节）"
                )
            tar.extract(member, dest_root, filter="data")


def extract_zip(archive, dest_root):
    """安全解包 zip：拒绝符号链接，校验体积。"""
    with zipfile.ZipFile(archive) as zf:
        counter = [0]
        for info in zf.infolist():
            dest = _check_member(info.filename, dest_root, counter)
            mode = info.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                raise GoldevalError(
                    f"压缩包含符号链接（拒绝解包）：{info.filename}"
                )
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            if info.file_size > config.MAX_SINGLE_FILE_BYTES:
                raise GoldevalError(
                    f"压缩包内单文件超过上限：{info.filename}"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)


def unpack(agent_path, kind, work_dir):
    """解包到 <work>/extracted/，返回解包根目录。"""
    dest_root = Path(work_dir) / EXTRACT_DIRNAME
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    if kind == "targz":
        extract_targz(agent_path, dest_root)
    else:
        extract_zip(agent_path, dest_root)
    return dest_root


# ============================== 锚点定位 ==============================

def _anchors_here(directory):
    """该目录下成立的工程类型（按 FLAVORS 顺序，COSIGHT.md 优先）。

    一个目录同时有 COSIGHT.md 与 CLAUDE.md 时返回两者，
    由调用方决定取哪个（取首个，并告警另一个被忽略）。
    """
    return [
        flavor for flavor in config.FLAVORS
        if config.has_flavor_layout(directory, flavor)
    ]


def _deep_candidates(scan_root):
    """深挖：返回 {flavor_id: [目录, ...]}，各类型锚点分别收集。"""
    found = {flavor["id"]: set() for flavor in config.FLAVORS}
    for flavor in config.FLAVORS:
        for path in scan_root.rglob(flavor["anchor"]):
            if path.is_file() and config.has_flavor_layout(path.parent, flavor):
                found[flavor["id"]].add(path.parent)
    return {key: sorted(value) for key, value in found.items()}


def locate_root(scan_root):
    """定位 Agent 根并判定类型（flavor）。

    用户指向的路径未必就是工程根——可能是版本号子目录（`.../v1`）、
    压缩包解包后的外层目录，或工程根之上的某一层。因此一律深挖：

        根层命中            → 采用根层（同类多个锚点也不歧义）
        唯一深层命中        → 采用该层
        多个深层命中        → 报错，无法确定扫哪个（要求用户明确指向）
        零命中              → 回退为扫描根本身，flavor 落 FALLBACK

    同一目录下 COSIGHT.md 与 CLAUDE.md 并存时取 COSIGHT（结构更规整），
    并记入 warnings。

    返回 (root, flavor_id, anchor_found, candidates, shadowed, warnings)。
    """
    here = _anchors_here(scan_root)
    if here:
        return (scan_root, here[0]["id"], True, [str(scan_root)],
                here[1:], [])

    deep = _deep_candidates(scan_root)
    present = {key: dirs for key, dirs in deep.items() if dirs}
    total = sum(len(dirs) for dirs in present.values())

    if total == 0:
        return scan_root, config.FALLBACK_FLAVOR, False, [], [], []
    if total > 1:
        flat = [str(d) for dirs in present.values() for d in dirs]
        raise GoldevalError(
            f"在 {scan_root} 下发现多个工程锚点，无法确定扫描哪个工程："
            + "、".join(flat[:5])
            + "；请把 --agent 指向其中某一个"
        )

    # 唯一命中：可能落在多个类型上（同类只算一次，因为 total 已按目录去重判断）
    for flavor in config.FLAVORS:
        dirs = present.get(flavor["id"]) or []
        if dirs:
            shadowed = [
                other for other in config.FLAVORS
                if other["id"] != flavor["id"]
                and any((d / other["anchor"]).is_file() for d in dirs)
            ]
            return dirs[0], flavor["id"], True, [str(dirs[0])], shadowed, []

    return scan_root, config.FALLBACK_FLAVOR, False, [], [], []


def top_level_listing(scan_root, limit=15):
    """列出扫描根顶层条目，供无锚点警告使用。"""
    try:
        entries = sorted(scan_root.iterdir(), key=lambda p: (p.is_file(), p.name))
    except OSError:
        return []
    return [f"{e.name}/" if e.is_dir() else e.name for e in entries[:limit]]


# ============================== 主流程 ==============================

def build_asset(agent_arg, work_dir):
    """执行 S0，写出 00-asset.json 并返回 asset。"""
    agent_path = Path(agent_arg).expanduser()
    kind = detect_kind(agent_path)

    warnings = []
    if kind == "dir":
        scan_root = agent_path.resolve()
        source_kind = "dir"
    else:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        scan_root = unpack(agent_path, kind, work_dir)
        source_kind = kind

    root, flavor_id, anchor_found, candidates, shadowed, anchor_warnings = \
        locate_root(scan_root)
    warnings.extend(anchor_warnings)

    flavor = config.flavor_of(flavor_id)

    if anchor_found and Path(candidates[0]) != scan_root:
        warnings.append(
            f"在输入路径之下深挖到锚点，已改以此为扫描根：{candidates[0]}"
        )

    if shadowed:
        ignored = "、".join(f"`{f['anchor']}`（{f['label']}）" for f in shadowed)
        warnings.append(
            f"同一目录下同时存在多个锚点，已按 `{flavor['anchor']}` "
            f"（{flavor['label']}）解析，忽略：{ignored}"
        )

    if not anchor_found:
        warnings.append(
            "未找到任何工程锚点（"
            + " / ".join(f"`{name}`" for name in config.ANCHOR_FILENAMES)
            + f"），已回退以输入路径自身为扫描根：{root}"
        )
        warnings.append(
            "扫描根顶层内容：" + "、".join(top_level_listing(root))
        )

    asset = {
        "input_path": str(agent_arg),
        # agent 的规范名：中间态目录名、产出目录名、data_id 前缀全用它。
        # 在 S0 就定下来并随画像一路带下去，避免各处各推一套导致漂移。
        "agent_slug": slug_from_path(agent_arg),
        "input_kind": source_kind,
        "scan_root": str(scan_root),
        "root": str(root),
        "flavor": flavor_id,
        # 锚点没找到时 flavor 只是回退的扫描布局，不代表识别出了类型——
        # 此时报「未识别」，免得出现"类型是 Claude 类但锚点未找到"的自相矛盾。
        "flavor_label": flavor["label"] if anchor_found else config.DEFAULT_LABEL,
        "anchor_found": anchor_found,
        "anchor_file": str(root / flavor["anchor"]),
        "root_sha256": sha256_tree(root),
        "warnings": warnings,
    }
    write_json(work_path(work_dir, "asset"), asset)
    return asset, work_dir


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="parse.py", description="S0 输入解析：判类型 → 解包 → 定位 Agent 根"
    )
    parser.add_argument("--agent", required=True, help="待评测 agent 目录或压缩包")
    parser.add_argument("--work", required=True, help="中间态目录")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        asset, _ = build_asset(args.agent, args.work)
    except GoldevalError as exc:
        fail(str(exc))

    print(f"S0 完成：kind={asset['input_kind']}  root={asset['root']}")
    print(f"    类型：{asset['flavor_label']}（flavor={asset['flavor']}）")
    print(f"    锚点 {Path(asset['anchor_file']).name}：" +
          ("已找到" if asset["anchor_found"] else "未找到（已回退）"))
    for warning in asset["warnings"]:
        print(f"    WARN: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
