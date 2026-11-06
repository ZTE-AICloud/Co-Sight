# 专属函数参数映射与必填项配置
# 仅当函数名命中此表时才进行映射；否则不做任何转换

from typing import Dict, List


# 结构：
# FUNCTION_ARG_MAPPING = {
#   'function_name_lower': {
#       'required': ['param1', 'param2'],
#       'aliases': {
#           'param1': ['alias_a', 'alias_b'],
#           'param2': ['alias_c']
#       }
#   }
# }

FUNCTION_ARG_MAPPING: Dict[str, Dict[str, Dict[str, List[str]]]] = {
    'file_saver': {
        'required': ['file_path', 'content'],
        'aliases': {
            'file_path': ['file', 'filepath', 'path', 'save_path', 'output', 'output_path', 'file_path','file_name','filename'],
            'content': ['text', 'data', 'body', 'contents', 'value','file_content'],
        }
    },
    'execute_code': {
        'required': ['code'],
        'aliases': {
            'code': ['script', 'source', 'python', 'py', 'content', 'text'],
        }
    },
    'search_baidu': {
        'required': ['query'],
        'aliases': {
            'query': ['q', 'keyword', 'keywords', 'search', 'prompt']
        }
    },
    'download_file': {
        'required': ['url'],
        'aliases': {
            'url': ['link', 'href', 'uri'],
            'filename': ['save_as', 'output', 'path', 'dest']
        }
    },
    'file_read': {
        'required': ['file'],
        'aliases': {
            'file': ['file_path', 'filepath', 'path', 'save_path', 'output', 'output_path', 'file_path','file_name','filename'],
        }
    }
}

