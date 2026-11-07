from shared.errors.exception import EMException


class GraphException(EMException):
    """图数据库相关异常"""
    
    def __init__(self, err_code, *args):
        super().__init__(err_code, *args) 