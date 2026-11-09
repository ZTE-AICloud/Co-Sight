#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-soc-review —— 标书应答大模型并发复核器。

对 `*-已应答.json` 逐条把「客户需求」与「知识库匹配文本」提交给 LLM 比对，
检测品牌、数值、版本号等关键冲突，产出 `<stem>-已大模型复核.json`：
  - 每条新增 `llm_review_result` 字段（"符合 | 原因: ..." / "不符合 | 原因: ..."）
  - 判为不符合的条目强制写入 conflict=true + review_notes 警告

失败语义：
  - 单条 LLM 请求失败不阻塞整批（失败信息写入该条的 llm_review_result）；
  - 真实失败率（LLM/网络/JSON 解析错误）> 30% → 产物仍落盘，但 exit 1。

要点：
  - LLM 配置统一走 common.cosight_runtime.resolve_runtime_llm_config（纯环境变量）；
  - 入口前置 bootstrap（venv 重入 + data/.env 加载 + preflight）。
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-soc-review/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "soc"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap  # noqa: E402

bootstrap()  # venv 重入 + .env 加载 + preflight（失败 exit 3）

# 强制 UTF-8 输出
if sys.platform == 'win32':
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8', errors='replace')

try:
    import aiohttp
except ImportError:
    print("错误: 需要安装 aiohttp 库（pip install aiohttp，或运行 scripts/install.py）", flush=True)
    sys.exit(1)

from common.cosight_runtime import resolve_runtime_llm_config  # noqa: E402


def get_llm_config():
    """读取 LLM 配置（纯环境变量：OPENAI_* 主配置优先，ANTHROPIC_* 回退）。"""
    cfg = resolve_runtime_llm_config("soc_review")
    if not cfg:
        return None
    return {
        "base_url": cfg.get("base_url"),
        "api_key":  cfg.get("api_key"),
        "model":    cfg.get("model"),
    }


class LLMJsonExtractError(Exception):
    """LLM 返回内容里"看起来像 JSON"（有大括号对象起止符），但解析失败。"""


def extract_review_json(full_text: str) -> dict | None:
    """从大模型返回文本中稳健地提取复核结果 JSON。

    兼容以下几种"非纯 JSON"返回：

    1. **推理模型的 <think> 块**（DeepSeek R1 / Qwen3 等）。即使 prompt 明确要求
       "不要输出任何其他的分析过程"，推理模型仍会输出 ``<think>...</think>``，
       且常常在块内预先写出"输出JSON格式：{...}"作为示例。如果不做剥离，
       贪婪正则 ``\\{.*\\}`` 会把块内的示例 JSON 和块外的真实 JSON 拼成一个
       非法字符串，导致解析失败。

    2. **Markdown 代码块包裹**（```json ... ```）。

    3. **夹带客套话/说明文字**："好的，下面是结果：{...}"。

    返回值 vs 异常：

    - ``dict``：成功解析出 ``{"match": ..., "reason": ...}``
    - ``None``：输入里**没有任何** JSON-like 结构（连大括号都没有）。
    - ``LLMJsonExtractError``：输入里**看起来像 JSON**（找到 ``{...}`` 起止符）
      但解析失败 —— 这一档能告诉用户"模型想输出 JSON 但格式坏了"，
      比"格式不合法"信息更精准。

    实现要点：

    - 先用正则去掉推理块（不区分大小写，覆盖 think/thinking/reason/reasoning）。
    - 再用 ``json.JSONDecoder.raw_decode`` 逐位置扫描括号配对，定位第一个
      balanced JSON 对象；这比 ``re.search(r'\\{.*\\}', ..., DOTALL)`` 稳健得多。
    - 仅接受含 ``match`` 字段的对象，避免误抓正文里"看起来像 JSON"的噪声。
    """
    if not full_text:
        return None

    cleaned = full_text

    # 1) 剥离推理块：<think>...</think> / <thinking>...</thinking> /
    #    <reason>...</reason> / <reasoning>...</reasoning>
    cleaned = re.sub(
        r"<(think|thinking|reason|reasoning)>.*?</\1>",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 2) 去掉 Markdown 代码块标记（```json ... ``` / ``` ... ```）。
    cleaned = re.sub(r"```(?:json|JSON)?\s*", "", cleaned)
    cleaned = cleaned.replace("```", "")

    # 3) 兜底：清理掉 \r、零宽字符等可能干扰 raw_decode 的噪声
    cleaned = cleaned.replace("\r", "")

    # 4) 用括号配对解析寻找第一个含 match 字段的合法 JSON 对象
    decoder = json.JSONDecoder()
    saw_json_shaped = False
    last_err: json.JSONDecodeError | None = None
    for idx, ch in enumerate(cleaned):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(cleaned, idx)
        except json.JSONDecodeError as e:
            # 从 idx 开始的子串看起来像 JSON（以 { 开头）但坏了
            saw_json_shaped = True
            last_err = e
            continue
        if isinstance(obj, dict):
            if "match" in obj:
                return obj
            # 找到了 JSON 对象但没 match 字段（噪声）—— 继续往后找
            continue

    if saw_json_shaped:
        raise LLMJsonExtractError(
            f"输入里包含 JSON-like 结构但解析失败: {last_err}"
        ) from last_err

    return None


async def review_single_item(session, llm_config, index, total, req_desc, matched_desc, semaphore):
    async with semaphore:
        if isinstance(req_desc, int):
            print(f"[DEBUG] req_desc 是 int 类型: {req_desc}")
        req_desc = str(req_desc) if req_desc is not None else ""
        matched_desc = str(matched_desc) if matched_desc is not None else ""

        if not req_desc:
            return index, "需求描述为空，跳过复核。"

        if not matched_desc:
            return index, "未命中知识库，跳过大模型复核。"

        # 优化：如果是完全相同的文本，直接判为符合，不浪费大模型算力
        if req_desc.strip() == matched_desc.strip():
            print(f"  [{index}/{total}] 审核完成 -> 符合 (文本完全一致)")
            return index, "符合 | 原因: 文本完全一致"

        prompt = (
            "你是一个严谨的标书技术审核专家。请仔细判断以下两个需求描述是否在说同一件事（即技术要求或业务意图一致，没有本质冲突）。\n\n"
            f"待应答的客户需求：【{req_desc}】\n"
            f"知识库匹配到的参考文本：【{matched_desc}】\n\n"
            "判断原则：\n"
            "1. 只要两个句子表达的核心意图相同、或者参考文本能涵盖客户需求，就判定为符合。\n"
            "2. 只有当存在明确的冲突（例如：品牌互斥如思科vs华为、数值矛盾如100Gvs40G、技术路线不同如KVMvsVMware等），才判定为不符合。\n"
            "3. 如果需求只是通用描述（如“提供服务职责”），没有具体的指标或品牌，只要参考文本也是相关的通用描述，就视为符合，不要过度脑补缺失的细节。\n"
            "请直接输出一段严格的JSON格式结果，包含 match 和 reason 两个字段，不要输出任何其他的分析过程：\n"
            "{\"match\": true或false, \"reason\": \"简短说明判定原因\"}"
        )

        if not llm_config:
            # 影响结果的异常：没有 LLM 配置 = 所有复核结果都是假"已复核"
            # = 用户拿到结果完全无法验证准确性。直接终止整批任务。
            print(
                f"\n❌ LLM 配置错误: 调用复核任务 [{index}/{total}] 时发现配置缺失。",
                flush=True,
            )
            print(
                "❌ 当前技能 [cosightbot-soc-review] 无法继续，已立刻终止；"
                "请在 data/.env 中配置 ANTHROPIC_* 或 OPENAI_* 后重试。",
                flush=True,
            )
            sys.exit(1)

        url = f"{llm_config['base_url'].rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config['api_key']}"
        }
        payload = {
            "model": llm_config['model'],
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }

        try:
            async with session.post(url, json=payload, headers=headers, timeout=60) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    # 个别 LLM 请求失败不能终止整批次：其它项还能继续复核。
                    # 把失败信息塞进 result_str，由 review.main() 一起落盘。
                    print(
                        f"  [{index}/{total}] LLM 复核请求失败 (Status {resp.status}): {text[:100]}",
                        flush=True,
                    )
                    return index, f"LLM 请求失败 (Status {resp.status}): {text[:100]}"

                data = await resp.json()
                full_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            # 网络异常 / aiohttp 解析异常：同上，个别项失败不阻塞整批。
            print(
                f"  [{index}/{total}] 大模型请求异常: {e}",
                flush=True,
            )
            return index, f"大模型请求失败: {e}"

        # Parse JSON from full_text
        try:
            res_json = extract_review_json(full_text)
            if res_json is not None:
                is_match = res_json.get("match", False)
                reason = res_json.get("reason", "")
                status_str = "符合" if is_match else "不符合"
                result_str = f"{status_str} | 原因: {reason}"
                print(f"  [{index}/{total}] 审核完成 -> {status_str}", flush=True)
                return index, result_str
            # 返回内容连 JSON 大括号都没有：把诊断信息塞进 result_str 继续。
            print(f"  [{index}/{total}] 大模型返回格式不合法，跳过该项复核", flush=True)
            print(f"    原始返回: {full_text[:300]}", flush=True)
            return index, "大模型返回格式不合法"
        except Exception as e:
            # JSON 解析失败 = LLM 输出了内容但不是合法 JSON：同上，跳过该项。
            print(f"  [{index}/{total}] 大模型 JSON 解析失败: {e}", flush=True)
            print(f"    原始返回: {full_text[:300]}", flush=True)
            return index, f"JSON解析失败: {full_text}"


async def main_async(args):
    in_json = Path(args.in_json).absolute()
    if not in_json.exists():
        print(f"错误: 找不到输入文件 {in_json}", flush=True)
        sys.exit(1)

    out_json = in_json.with_name(f"{in_json.stem.replace('-已应答', '')}-已大模型复核.json")

    llm_config = get_llm_config()
    if not llm_config:
        print(
            "错误: 无法获取 LLM 配置——请在 data/.env 中配置 OPENAI_BASE_URL/"
            "OPENAI_API_KEY/OPENAI_MODEL（未配时将回退会话继承的 ANTHROPIC_*）后重试。",
            flush=True,
        )
        sys.exit(1)

    try:
        with open(in_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"错误: 读取 JSON 失败: {e}", flush=True)
        sys.exit(1)

    # 保存原始 JSON 结构，以便后续按原格式输出
    original_structure = None
    if isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            # 标准格式：{"source_file": "...", "items": [...]}
            original_structure = {k: v for k, v in data.items() if k != "items"}
            data = data["items"]
        else:
            # 单个对象格式或列表
            if not isinstance(data, list):
                data = [data]

    print(f"[审核] 开始对 {len(data)} 条已应答数据进行大模型语义复核...", flush=True)
    print(f"  - 最大并发数: {args.concurrency}", flush=True)

    semaphore = asyncio.Semaphore(args.concurrency)
    timeout = aiohttp.ClientTimeout(total=900)

    # trust_env=True: aiohttp 默认忽略 HTTP_PROXY / HTTPS_PROXY / NO_PROXY（与 requests 不同），
    # 不开启则在需要代理的环境永远直连失败。
    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        tasks = []
        for i, item in enumerate(data, 1):
            req_desc = item.get(args.req_field, "")
            matched_desc = item.get(args.matched_field, "")
            task = review_single_item(session, llm_config, i, len(data), req_desc, matched_desc, semaphore)
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # 把结果合并回 JSON
        for idx, result_str in results:
            data[idx-1][args.result_field] = result_str

            # 如果大模型判定不符合，进一步加粗提示或修改 conflict 标志
            if result_str.startswith("不符合"):
                data[idx-1]["conflict"] = True
                data[idx-1]["review_notes"] = "大模型复核警告: " + result_str

        # 失败率统计：超过 30% 失败 = 整批视为不可信，必须立刻终止。
        # 这里"失败"指的是 review_single_item 真撞 LLM/网络/JSON 错误的项
        # ——"需求描述为空""未命中知识库"这类软跳过不算失败（设计上跳过合法）。
        failure_markers = (
            "LLM 请求失败",
            "大模型请求失败",
            "大模型返回格式不合法",
            "JSON解析失败",
        )
        total = len(results)
        failed_items = [
            (idx, result_str)
            for idx, result_str in results
            if any(result_str.startswith(m) for m in failure_markers)
        ]
        fail_count = len(failed_items)
        fail_ratio = fail_count / total if total > 0 else 0.0
        if total > 0 and fail_ratio > 0.30:
            print(
                f"\n❌ 复核失败率过高: {fail_count}/{total} ({fail_ratio*100:.0f}%) "
                "超过 30% 阈值。",
                flush=True,
            )
            print("   失败明细（前 10 项）：", flush=True)
            for idx, s in failed_items[:10]:
                print(f"      · 第 [{idx}/{total}] 项: {s}", flush=True)
            print(
                "❌ 当前技能 [cosightbot-soc-review] 立刻终止；"
                "请先排查 LLM 服务/网络后重试。已成功的部分已写入下方的 JSON 里。",
                flush=True,
            )

    # 按照原始格式输出
    if original_structure is not None:
        # 恢复原始结构
        output_data = original_structure.copy()
        output_data["items"] = data
    else:
        # 直接输出列表或单个对象
        output_data = data if len(data) != 1 else data[0]

    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 落盘后再决定是否退出：保留已成功项的产物，避免用户啥也没拿到
    if total > 0 and fail_ratio > 0.30:
        print(f"\n[部分失败] 已落盘: {out_json.name}", flush=True)
        sys.exit(1)

    print(f"\n[成功] 大模型复核完成！结果已保存至: {out_json.name}", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="标书应答大模型复核工具")
    parser.add_argument("in_json", help="已应答的 JSON 文件路径")
    parser.add_argument("--req_field", default="requirement", help="客户需求描述字段名")
    parser.add_argument("--matched_field", default="matched_req", help="知识库匹配结果字段名")
    parser.add_argument("--result_field", default="llm_review_result", help="大模型审核结果保存字段名")
    parser.add_argument("--concurrency", type=int, default=6, help="请求并发数 (默认 6)")
    args = parser.parse_args()

    asyncio.run(main_async(args))
