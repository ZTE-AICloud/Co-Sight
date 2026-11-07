class CorpusProcessException(Exception):

    def __init__(self, err_code, *args):
        self.err_code = err_code
        self.args = args

    def get_errcode(self):
        return self.err_code

    def get_args(self):
        return self.args
