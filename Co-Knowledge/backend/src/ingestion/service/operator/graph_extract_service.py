import ast
import glob
import json
import os.path
import re
import shutil
import tempfile
import uuid

from parsing import corpus

from parsing.common.logutil import log
from ingestion.service.operator.dangerous_function_visitor import validate_code_security
from ingestion.split.system_split_manager import pg_manager
from ingestion.utility.self_operator import check_operator_code
from ingestion.utility.txlog import TxPrefixedLogger, get_tx_id_from_req


def _loggable_params(params: dict) -> dict:
    """DEBUG 日志用：端点凭据（``kwargs.llmConfig.api_key``）不进日志。

    该片段由父进程从模型注册表解析后下发（见 ``graph_extract_api._llm_endpoint_config``）。
    虽然本行只在 DEBUG 级别可见，但 dev 模式（``DEV_MODE=true``）就是真会落盘 ——
    密钥不该因为换了部署模式就多一处泄漏面。
    """
    if not isinstance(params, dict):
        return params
    kwargs = params.get('kwargs')
    config = kwargs.get('llmConfig') if isinstance(kwargs, dict) else None
    if not isinstance(config, dict) or config.get('api_key') is None:
        return params
    return {**params,
            'kwargs': {**kwargs, 'llmConfig': {**config, 'api_key': '***'}}}


def graph_extract_entry(graph_extract_info: dict, lang_id: str):
    """
    图提取算子的主要执行入口

    Args:
        graph_extract_info: 包含图提取所需信息的字典

    Returns:
        图提取结果
    """
    # 使用公共日志封装
    _tx_id = get_tx_id_from_req(graph_extract_info)
    _txlog = TxPrefixedLogger(_tx_id)
    kbId = graph_extract_info.get('kbId')
    try:
        _txlog.info("开始执行图提取算子")

        with tempfile.TemporaryDirectory() as temp_dir_path:
            # 获取输入文件路径和Python脚本路径
            file_disk_path = graph_extract_info.get('diskFileKey')
            python_disk_path = graph_extract_info.get('pythonPath')
            kwargs = graph_extract_info.get('kwargs')

            _txlog.info(f"file_disk_path = {file_disk_path}")
            _txlog.info(f"python_disk_path = {python_disk_path}")
            _txlog.debug(f"kwargs = {kwargs}")

            if not file_disk_path or not python_disk_path:
                raise ValueError("缺少必要的文件路径信息")
            chunk_size = 1024
            chunk_overlap = 256
            min_chunk_size = 512
            max_chunk_size = 2048
            if kwargs:
                chunk_size = int(kwargs.get('chunkSize', 1024))
                chunk_overlap = int(kwargs.get('overlap', 256))
                min_chunk_size = int(kwargs.get('minChunkSize', 512))
                max_chunk_size = int(kwargs.get('maxChunkSize', 2048))

            update_kbase_process(_txlog, kbId, 2, "20")
            workspace_dir = os.path.dirname(file_disk_path)
            corpus.load_corpus_file(input_path=file_disk_path, output_path=workspace_dir,
                                              chunk_size=chunk_size,chunk_overlap=chunk_overlap,
                                              min_chunk_size=min_chunk_size,max_chunk_size=max_chunk_size)
            update_kbase_process(_txlog, kbId, 2, "100")
            process_corpus_file(workspace_dir, kbId)

            # 使用固定的Python脚本名
            py_name = "graph_extract.py"
            temp_python_path = os.path.join(temp_dir_path, py_name)

            shutil.copy(python_disk_path, temp_python_path)

            # 准备graph_extract方法的固定入参
            # 所有参数都从args中获取
            custom_args = graph_extract_info.get('args', [])

            # 使用与FileParseService相同的传参方式：将所有参数作为关键字参数传递
            params = extract_params(custom_args)

            # 添加必要的文件路径参数
            params['file_path'] = workspace_dir
            params['lang'] = lang_id
            # 注入事务ID给知识图谱算子（键为 transaction_id）
            if _tx_id:
                params['transaction_id'] = _tx_id

            # 将kb_id放入kwargs中
            if 'kwargs' in params and isinstance(params['kwargs'], dict):
                params['kwargs']['kb_id'] = kbId
            else:
                params['kwargs'] = {'kb_id': kbId}

            _txlog.debug(f"params = {_loggable_params(params)}")
            update_kbase_process(_txlog, kbId, 3, "1")
            # 调用graph_extract方法，使用**params传递所有参数
            from ingestion.utility.self_operator import execute_function_in_sandbox
            result = execute_function_in_sandbox(temp_python_path, 'graph_extract', **params)

            _txlog.info(f"result = {result}")
            _txlog.info("图提取执行完成")
            update_kbase_process(_txlog, kbId, 3, "100")
            code, tip_info = handle_result(_txlog, kbId, lang_id, result)
            return {
                "code": code,
                "message": tip_info
            }
    except Exception as e:
        _txlog.exception(e)
        _txlog.error(f"图提取执行失败: {str(e)}")
        # 失败时返回标准错误格式
        update_kbase_process(_txlog, kbId, 103, "100")
        update_kbase_fail_reason(_txlog, kbId, "生成图谱失败：算子执行异常",
                                 "Failed to generate the graph: Operator execution exception")
        return {
            "code": "-1",
            "message": f"Failed to execute graph extract: {str(e)}"
        }


#: 图谱构建的进度/失败原因只对图谱库（``category = 10``）生效。
#:
#: 文档库的 ``kb_kbase.status`` 恒为 0 —— 文档处理进度记在 ``kb_directory`` 行上。
#: 抽图状态写进文档库会与这条不变量冲突，且没有任何链路会把它改回来（文档重新
#: 解析只改文档行），库会一直停在「生成失败」。这两条 WHERE 从写入端保证该不变量。
UPDATE_STATUS_SQL = ('UPDATE kb_kbase SET status = %s, process = %s '
                     'WHERE kbase_id = %s AND category = 10')
UPDATE_FAIL_REASON_SQL = ('UPDATE kb_kbase SET fail_reason_obj = %s '
                          'WHERE kbase_id = %s AND category = 10')


def update_kbase_process(_txlog, kbId, status, process):
    try:
        pg_manager.get_pg_client().execute(UPDATE_STATUS_SQL, (status, process, kbId))
    except Exception as e:
        _txlog.error(f"图提取更新进度失败: {str(e)}")


def update_kbase_fail_reason(_txlog, kbId, zh_CN, en_US):
    try:
        fail_reason_obj = {"zh_CN": zh_CN, "en_US": en_US}
        fail_reason = json.dumps(fail_reason_obj)
        pg_manager.get_pg_client().execute(UPDATE_FAIL_REASON_SQL, (fail_reason, kbId))
    except Exception as e:
        _txlog.error(f"图提取更新失败原因失败: {str(e)}")


def handle_result(_txlog, kbId, lang_id, result):
    code = result.get("code")
    tip_info = ''
    message = result.get("message")
    try:
        if "0" != code and message:
            update_kbase_fail_reason(_txlog, kbId, message.get("zh"), message.get("en"))
        if message:
            tip_info = message.get("en")
            if lang_id == 'zh_CN':
                tip_info = message.get("zh")
    except Exception as e:
        tip_info = message
        _txlog.error(f"图提取处理算子返回失败: {str(e)}")
    return code, tip_info


def extract_params(operator_param_list):
    """
    从算子参数列表中提取参数字典

    Args:
        operator_param_list: 算子参数列表

    Returns:
        参数字典
    """
    params = {}
    if operator_param_list is None:
        return params

    for param in operator_param_list:
        arg_name = param.get('argName')
        default_value = param.get('defaultValue')
        if arg_name and default_value is not None:
            params[arg_name] = default_value

    return params


def code_check(script_path: str, parameters: dict):
    """
    检查graph_extract算子的代码

    Args:
        script_path: Python脚本路径
        parameters: 参数类型字典

    Raises:
        Exception: 如果代码检查失败
    """
    log.info(f"开始检查图提取算子代码: {script_path}")

    with tempfile.TemporaryDirectory() as temp_dir_path:
        # 使用固定的Python脚本名，与FileParseService保持一致
        py_name = "graph_extract.py"
        temp_python_path = os.path.join(temp_dir_path, py_name)
        shutil.copy(script_path, temp_python_path)

        # 1. 先进行危险函数检查
        validate_code_security(temp_python_path)

        # 2. 再进行原有的代码结构检查
        check_operator_code(temp_python_path, "graph_extract", parameters)

        log.info("图提取算子代码检查通过")


def process_corpus_file(workspace_dir: str, kbId: str):
    """
    处理corpus_file.txt文件，实现去重和添加ID功能

    Args:
        workspace_dir: 工作目录路径
    """
    try:
        log.info(f"开始处理corpus_file.txt文件，工作目录: {workspace_dir}")

        # 功能1：递归查找corpus_file.txt文件
        corpus_files = find_corpus_files(workspace_dir)
        if not corpus_files:
            log.warning("未找到corpus_file.txt文件")
            return

        log.info(f"找到 {len(corpus_files)} 个corpus_file.txt文件")

        # 处理每个找到的文件
        for corpus_file in corpus_files:
            process_single_corpus_file(corpus_file)

        log.info("corpus_file.txt文件处理完成")

    except Exception as e:
        log.exception(f"处理corpus_file.txt文件时发生错误: {str(e)}")


def find_corpus_files(workspace_dir: str) -> list:
    """
    递归查找workspace_dir目录下的corpus_file.txt文件

    Args:
        workspace_dir: 工作目录路径

    Returns:
        corpus_file.txt文件路径列表
    """
    pattern = os.path.join(workspace_dir, "**", "corpus_file.txt")
    corpus_files = glob.glob(pattern, recursive=True)
    return corpus_files


def process_single_corpus_file(corpus_file_path: str):
    """
    处理单个corpus_file.txt文件

    Args:
        corpus_file_path: corpus_file.txt文件路径
    """
    try:
        log.info(f"处理文件: {corpus_file_path}")

        # 读取文件内容
        with open(corpus_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 解析文件内容
        parsed_data = parse_corpus_content(content)

        # 功能2：通过source和content_expand进行去重
        deduplicated_data = deduplicate_metadata(parsed_data)

        # 功能3：为metadata添加id字段
        data_with_ids = add_id_to_metadata(deduplicated_data)

        # 功能4：保存处理后的数据到新文件
        save_processed_data(corpus_file_path, data_with_ids)

        log.info(f"文件处理完成: {corpus_file_path}")

    except Exception as e:
        log.exception(f"处理文件 {corpus_file_path} 时发生错误: {str(e)}")
        raise


def parse_corpus_content(content: str) -> list:
    """
    解析corpus文件内容，只提取metadata字段后面的值

    Args:
        content: 文件内容

    Returns:
        只包含metadata值的列表
    """
    parsed_data = []

    # 使用正则表达式匹配metadata字段后面的值，支持嵌套花括号
    pattern = r"metadata=(\{(?:[^{}]|{[^{}]*})*\})"
    matches = re.findall(pattern, content, re.DOTALL)

    for metadata_str in matches:
        try:
            metadata = parse_metadata_manually(metadata_str)
            if metadata is not None:
                parsed_data.append(metadata)
        except Exception as e:
            log.warning(f"解析metadata失败: {metadata_str}, 错误: {str(e)}")
            continue

    log.info(f"解析出 {len(parsed_data)} 条metadata数据")
    return parsed_data


def parse_metadata_manually(metadata_str: str) -> dict:
    """
    手动解析metadata字符串（备用方案）。
    corpus_file.txt 中 metadata 多为 Python repr 格式（单引号、值内可含双引号），
    简单替换会破坏结构，故先尝试 json.loads，失败则用 ast.literal_eval 解析 Python 字面量。

    Args:
        metadata_str: metadata字符串（可能是 JSON 或 Python dict 字面量）

    Returns:
        解析后的字典
    """
    # 1) 已是合法 JSON 时直接解析
    try:
        metadata = json.loads(metadata_str)
        log.info(f"手动解析成功(json)，解析出 {len(metadata)} 个字段")
        return metadata
    except (json.JSONDecodeError, TypeError):
        pass

    # 2) Python dict 字面量（如 corpus 生成的 'source': 'xx', 'content_expand': "# 表汇总\n..."）
    try:
        metadata = ast.literal_eval(metadata_str)
        if isinstance(metadata, dict):
            log.info(f"手动解析成功(ast.literal_eval)，解析出 {len(metadata)} 个字段")
            return metadata
    except (ValueError, SyntaxError) as e:
        log.error(f"手动解析metadata失败: {e}，metadata_str 前200字符：{metadata_str[:200]!r}")

    return {}


def deduplicate_metadata(parsed_data: list) -> list:
    """
    通过source和content_expand字段进行去重

    Args:
        parsed_data: 解析后的数据列表

    Returns:
        去重后的数据列表
    """
    seen_combinations = set()
    deduplicated_data = []

    for metadata in parsed_data:
        source = metadata.get('source', '')
        content_expand = metadata.get('content_expand', '')

        # 创建唯一标识
        unique_key = f"{source}|{content_expand}"

        if unique_key not in seen_combinations:
            seen_combinations.add(unique_key)
            deduplicated_data.append(metadata)
        else:
            log.debug(f"发现重复数据，已跳过: source={source}, content_expand={content_expand}")

    log.info(f"去重前: {len(parsed_data)} 条数据，去重后: {len(deduplicated_data)} 条数据")
    return deduplicated_data


def add_id_to_metadata(deduplicated_data: list) -> list:
    """
    为metadata数据添加id字段

    Args:
        deduplicated_data: 去重后的数据列表

    Returns:
        添加id后的数据列表
    """
    for item in deduplicated_data:
        # 生成UUID作为id
        item['id'] = str(uuid.uuid4())

    log.info(f"为 {len(deduplicated_data)} 条数据添加了ID")
    return deduplicated_data


def save_processed_data(original_file_path: str, processed_data: list):
    """
    保存处理后的数据到新文件

    Args:
        original_file_path: 原始文件路径
        processed_data: 处理后的数据列表
    """
    # 获取原始文件所在目录
    original_dir = os.path.dirname(original_file_path)
    new_file_path = os.path.join(original_dir, "document_chunk.jsonl")

    try:
        with open(new_file_path, 'w', encoding='utf-8') as f:
            for item in processed_data:
                f.write(f"{json.dumps(item)}\n")
        log.info(f"处理后的数据已保存到: {new_file_path}")
    except Exception as e:
        log.exception(f"保存处理后的数据时发生错误: {str(e)}")
        raise
