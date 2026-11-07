import json

from ingestion.split.system_split_manager import pg_manager
from ingestion.utility.txlog import TxPrefixedLogger


class GraphProcess:

    def __init__(self, transaction_id=None):
        self.tx_log = TxPrefixedLogger(transaction_id)

    def update_kbase_process(self, kb_id: str, process: str, process_info_zh: str, process_info_en: str):
        """
        更新进度

        Args:
            kbId: 知识库id，必填
            process: 进度，如：“30”
            process_info_zh: 进度，如：“总共有3457块，正在处理第423块。”
            process_info_en: 进度，如：“”
        """
        try:
            process_info = {"zh_CN": process_info_zh, "en_US": process_info_en}
            process_obj = json.dumps(process_info)
            update_sql = "UPDATE kb_kbase SET process = %s, process_obj = %s WHERE kbase_id = %s"
            pg_manager.get_pg_client().execute(update_sql, (process, process_obj, kb_id))
        except Exception as e:
            self.tx_log.error(f"图提取更新进度失败: {str(e)}")
