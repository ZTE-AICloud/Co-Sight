import os
import os.path
import tempfile
import shutil

from parsing.exception import UnsupportedFormatError

from ingestion.split.result_convert import result_convert
from ingestion.split.system_split_manager import segment_file
from ingestion.split.node_transfer import identify_duplicate_chunks
from ingestion.utility.self_operator import execute_function_in_sandbox, extract_params, check_operator_code
from ingestion.service.operator.dangerous_function_visitor import validate_code_security


def safe_file_name(raw_name, file_format) -> str:
    """把上传文件名收敛成单个路径分量（落盘前必须调用）。

    ``os.path.join(tmp, '/abs/path')`` 会丢弃 ``tmp``，所以绝对路径、``..``、
    反斜杠分隔都必须在这里处理掉。
    """
    name = os.path.basename(str(raw_name or '').replace('\\', '/'))
    if not name or name in ('.', '..'):
        return f'clean_file.{file_format}'
    return name


def text_split_entry(text_split_info: dict):
    with tempfile.TemporaryDirectory() as temp_dir_path:
        file_clean_path = text_split_info.get('cleanPath')
        file_format = text_split_info.get('fileFormat')
        operator_id = text_split_info.get('operatorId')
        custom_args = text_split_info.get('args')
        # ``fileName`` 来自上传请求，可能带目录（甚至绝对路径）。落盘只用最后一段，
        # 否则 ``os.path.join`` 遇到绝对路径会丢弃临时目录，写到任意可写位置。
        file_name = safe_file_name(text_split_info.get('fileName'), file_format)
        temp_file_path = os.path.join(temp_dir_path, file_name)

        shutil.copy(file_clean_path, temp_file_path)
        
        # OFD 不在开源 8 格式内，v1 不解析 OFD（原依赖私有 OFD 转 PDF 库，已移除）。
        # 用 UnsupportedFormatError 而不是 NotImplementedError：后者会落兜底键
        # ``RetCode.operator.split.error``（"切分算子执行失败"），把「格式不支持」
        # 说成「算子坏了」。
        if file_format and file_format.lower() == 'ofd':
            raise UnsupportedFormatError(file_clean_path, source=file_format)

        params = extract_params(custom_args)
        params["format"] = file_format
        
        # 获取kbase_id和source
        # 优先从算子参数中取，其次从请求体顶层取（kbaseId / kbase_id）
        kbase_id = params.get("kbase_id") or text_split_info.get("kbaseId") or text_split_info.get("kbase_id")
        source = file_name
        
        if operator_id < 0:
            result = segment_file(temp_file_path, operator_id, text_split_info.get('splitPreview', False), **params)
            # 识别重复chunk并分配chunk_id（仅在非预览模式且有kbase_id时处理）
            if kbase_id and isinstance(result, list) and not text_split_info.get('splitPreview', False):
                nodes_with_chunk_id, chunks_list = identify_duplicate_chunks(result, kbase_id, source)
                return {"results": nodes_with_chunk_id, "chunks": chunks_list}
            # 预览模式或没有kbase_id时，保持原有返回格式
            return {"results": result}
        python_disk_path = text_split_info.get('pythonPath')
        py_name = "file_split.py"
        temp_python_path = os.path.join(temp_dir_path, py_name)
        shutil.copy(python_disk_path, temp_python_path)
        params['file_path'] = temp_file_path
        result = execute_function_in_sandbox(temp_python_path, 'file_split', **params)
        # 如果text_split返回的结果类型不是str，则报错
        converted_result = result_convert(result)
        
        # 检查是否为nodes格式（包含nodeId字段）
        if (kbase_id and isinstance(converted_result, list)
                and not text_split_info.get('splitPreview', False)
                and converted_result and isinstance(converted_result[0], dict)
                and "nodeId" in converted_result[0]):
            nodes_with_chunk_id, chunks_list = identify_duplicate_chunks(converted_result, kbase_id, source)
            return {"results": nodes_with_chunk_id, "chunks": chunks_list}
        return {"results": converted_result}


def code_check(script_path: str, parameters: dict):
    with tempfile.TemporaryDirectory() as temp_dir_path:
        py_name = "file_split.py"
        temp_python_path = os.path.join(temp_dir_path, py_name)
        shutil.copy(script_path, temp_python_path)
        
        # 1. 先进行危险函数检查
        validate_code_security(temp_python_path)
        
        # 2. 再进行原有的代码结构检查
        check_operator_code(temp_python_path, "file_split", parameters)


if __name__ == '__main__':
    test = {
        "operatorId": -2,
        "splitPreview": True,
        "args": [
            {
                "argName": "emp_no",
                "defaultValue": "1"
            },
            {
                "argName": "kbase_id",
                "defaultValue": "1"
            }
        ],
        "fileFormat": "docx",
        "fileName": "网元告警解决办法.docx",
        "cleanPath": "/tmp/sample.docx"
    }
    result = text_split_entry(test)
    for res in result['results']:
        print(res['metadata'])
