import os

from infrastructure.config.settings import Config

request_body_question = 'question'
request_body_type = 'type'
request_body_model = 'model'
request_body_bases = 'bases'
request_body_where = 'where'
request_body_score_threshold = 'score_threshold'
request_body_topk = 'top_k'
request_body_strategy = 'retrieve_strategy'

default_top_k = 8
default_score_threshold = 0.0
default_model = "text2vec-base-chinese"
default_type = 0
default_search_type = 'similarity'
default_schema = 'kb_index'

text_dir_name = 'text'
chunk_dir_name = 'chunk'
vector_dir_name = 'vector'
knowledgegraph_dir_name = 'knowledgegraph'
keyword_dir_name = 'keyword'
sql_dir_name = 'sql'

memory = os.environ.get('CURRENT_MEM_LIMIT')
DEFAULT_MEMORY = 8192
system_error = '系统错误，请联系管理员'
vector_asset_name = 'vector_entity'
keyword_asset_name = 'keyword_entity'
source_asset_name = 'source_entity'
graph_asset_name = 'graph_entity'
chunk_asset_name = 'chunk_entity'
GRAPH_KNOWLEDGE_BASE = 'graph_'

ES_DICT = {
    "host": os.environ.get("RKB_ES_HOST", "opensearch"),
    "port": os.environ.get("RKB_ES_PORT", "9200"),
    "user": os.environ.get("RKB_ES_USERNAME", ""),
    "password": os.environ.get("RKB_ES_PASSWORD", ""),
}

http_ok_code = 200
http_fail_code = 500
fail_code = -1
success_code = 0
success_message_en = 'Success'
success_message_zh = '成功'

process_success = 0
processing = 1
process_failure = 2
wait_to_be_process = 3
# 0: 处理成功, 1: 处理中, 2: 处理失败 3: 待处理
# 插件源文件目录
knowledge_file_path = Config.get('plugin_source_path')
