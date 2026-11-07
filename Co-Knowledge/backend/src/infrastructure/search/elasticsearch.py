from infrastructure.search.es_restful import ESRestfulClientWrapper
from infrastructure.config.constants import ES_DICT
from infrastructure.logging.logutil import log


def get_ik_analyzer_status(es_client: ESRestfulClientWrapper):
    """
    检查 ES 是否安装了 ik_analyzer 插件
    
    Args:
        es_client: ES RESTful 客户端
        
    Returns:
        是否安装了 ik 分词器
    """
    try:
        # 使用_cat/plugins端点获取插件信息
        plugins_list = es_client.cat.plugins(format="json")
        return any(plugin.get('component') == 'analysis-ik' for plugin in plugins_list)
    except Exception as e:
        log.exception(e)
        log.warning("request to es client to get ik_analyzer status is failed.")
        return False


class ESClientSingleton:
    """
    ES 客户端单例
    使用 RESTful API 替代 elasticsearch Python 客户端
    """
    _instance = None
    _init_password = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance.es_client = None
            cls._instance.analysis_ik = False
            cls._init_password = ES_DICT.get('password', '')
        return cls._instance

    def get_client(self) -> ESRestfulClientWrapper:
        """
        获取 ES RESTful 客户端
        
        Returns:
            ES RESTful 客户端实例
        """
        if not self.es_client or self._init_password != ES_DICT.get('password', ''):
            # 使用 RESTful API 客户端替代原 elasticsearch 客户端
            self.es_client = ESRestfulClientWrapper(
                host=ES_DICT.get('host'),
                port=ES_DICT.get('port'),
                user=ES_DICT.get('user'),
                password=ES_DICT.get('password', ''),
                scheme='http'
            )
            self.analysis_ik = get_ik_analyzer_status(self.es_client)
        return self.es_client

    def get_analysis_ik(self) -> bool:
        """
        获取 ik 分词器状态
        
        Returns:
            是否安装了 ik 分词器
        """
        return self.analysis_ik
