import logging
import os.path
import tempfile
import shutil
import re

from ingestion.service.operator.dangerous_function_visitor import validate_code_security
from ingestion.utility.self_operator import execute_function_in_sandbox, extract_params,check_operator_code
from ingestion.utility.manager import DiskClientManager

disk_manager = DiskClientManager()
disk_client = disk_manager.get_disk_client()

def file_parse_entry_string(file_parse_info: dict) -> str:
    # 创建一个临时目录，并在退出语句块时自动清理创建的临时目录
    with tempfile.TemporaryDirectory() as temp_dir_path:
        file_disk_path = file_parse_info.get('diskFileKey')
        python_disk_path = file_parse_info.get('pythonPath')
        file_format = file_parse_info.get('fileFormat')
        file_name = "upload_file." + file_format 
        temp_file_path = os.path.join(temp_dir_path, file_name)
        shutil.copy(file_disk_path, temp_file_path)
        py_name = "file_parse.py"
        temp_python_path = os.path.join(temp_dir_path, py_name)
        shutil.copy(python_disk_path, temp_python_path)
        custom_args = file_parse_info.get('args')
        params = extract_params(custom_args)
        params['file_path'] = temp_file_path
        result = execute_function_in_sandbox(temp_python_path, 'file_parse', **params)
        # 如果text_split返回的结果类型不是str，则报错
        if not type(result) == str:  # noqa: E721
            raise Exception("file_parse result type is not str")
        regex_list = file_parse_info.get('regexList')
        if regex_list is None:
            regex_list = []
        result = clean_string_with_multiple_patterns(result, regex_list)
        return result

def clean_string_with_multiple_patterns(input_string, patterns):
    cleaned_string = input_string
    for pattern in patterns:
        cleaned_string = re.sub(pattern, '', cleaned_string)
    return cleaned_string


def file_parse_entry(file_parse_info: dict):
    result = file_parse_entry_string(file_parse_info)
    logging.info("file parse operator exec success")
    with tempfile.TemporaryDirectory() as temp_dir_path:
        temp_file_path = os.path.join(temp_dir_path, "clean.md")
        with open(temp_file_path, 'w') as file:
            file.write(result)
        clean_file_path = disk_client.upload_clean_file(temp_file_path, 'admin')
    logging.info("清洗文件路径：" + clean_file_path)
    return clean_file_path


def code_check(script_path:str, parameters:dict):
    with tempfile.TemporaryDirectory() as temp_dir_path:
        py_name = "file_parse.py"
        temp_python_path = os.path.join(temp_dir_path, py_name)
        shutil.copy(script_path, temp_python_path)
        # 1. 先进行危险函数检查
        validate_code_security(temp_python_path)

        check_operator_code(temp_python_path, "file_parse", parameters)

if __name__ == '__main__':
    _storage = os.environ.get("STORAGE_MAIN_PATH", "/data/kb")
    test = {
        "operatorId": 12345,
        "args": [
            {
                "argName": "test",
                "argType": "String",
                "defaultValue": "default1",
                "description": "Description for param1"
            }
        ],
        "pythonPath": f"{_storage}/operator/dba0922bd0484458b408e5c5d6cbdd13",
        "fileFormat": "txt",
        "diskFileKey": f"{_storage}/core/09e4/09e40ed3777b4f719ea69adeaecf2b65"
    }
    print(file_parse_entry_string(test))
