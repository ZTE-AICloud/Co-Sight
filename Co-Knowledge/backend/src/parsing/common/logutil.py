# coding=utf-8
import gzip
import logging as origin_logging
import os
import re
import platform
import secrets
import tempfile
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from parsing.common.profile import Profile

FORMATTER = origin_logging.Formatter(
    "[%(asctime)s.%(msecs)03d][%(process)d][%(thread)d][%(levelname)1s][%(filename)1s:%(lineno)1s] %(message)s",
    "%Y-%m-%d %H:%M:%S") if 'Linux' == platform.system() else origin_logging.Formatter(
    "[%(asctime)s.%(msecs)03d][%(process)d][%(thread)d][%(levelname)1s][%(filename)1s:%(lineno)1s] %(message)s")

DEBUG_MODE = True if Profile.dev() else False


class CompressedRotatingFileHandler(RotatingFileHandler):
    """
    example-202202121101-[xxx].log
    zip/example-202202121101-[xxx].log.gz
    """

    def __init__(self, filename, maxBytes, backupCount, encoding=None):
        # 日志文件名中使用的随机数
        self.random = self._get_rand_str()

        # 记录原始输入的文件名，用于每次构造日志文件名使用
        self.input_filename = filename
        filename = self._get_filename()
        os.makedirs(os.path.dirname(filename), mode=0o750, exist_ok=True)

        super().__init__(filename, maxBytes=maxBytes, backupCount=backupCount, encoding=encoding)

        # 匹配日志文件名的正则表达式
        # 格式: rkb-yyyyMMddHHmmssSSS-[xxxxxx].log 或 rkb-yyyyMMddHHmmssSSS-[xxxxxx].log.gz
        self.extMatch = re.compile(r"^rkb-\d{17}-\[\d{6}\]\.log(\.gz)?$", re.ASCII)

        # 创建归档目录
        self.backup_dir = os.path.join(os.path.dirname(self.baseFilename), 'zip')
        os.makedirs(self.backup_dir, mode=0o750, exist_ok=True)

        # 清理历史残留的未归档的log文件，修改时间超30分钟未修改，则认为是残留文件
        self._backup_remains()

    def _get_rand_str(self):
        rand_str = ""
        for i in range(6):
            rand_str += str(secrets.randbelow(10))
        return rand_str

    def _get_filename(self):
        """
        生成日志文件名
        格式: <log_dir>/rkb-yyyyMMddHHmmssSSS-[xxxxxx].log
        """
        log_dir = os.path.dirname(os.fspath(self.input_filename))
        # 获取当前时间，包含毫秒（17位：yyyyMMddHHmmssSSS）
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]  # 保留3位毫秒
        filename = "rkb-{}-[{}].log".format(timestamp, self.random)
        return os.path.join(log_dir, filename)

    def get_files_to_delete(self):
        result = []
        for f in os.listdir(self.backup_dir):
            fullname = os.path.join(self.backup_dir, f)
            if not os.path.isfile(fullname):
                continue
            suffix = f.replace(os.path.basename(self.input_filename), "")
            if self.extMatch.match(suffix):
                result.append(os.path.join(self.backup_dir, f))
        result.sort()
        if len(result) < self.backupCount:
            result = []
        else:
            result = result[:len(result) - self.backupCount]
        return result

    def _backup_remains(self):
        """
        归档残留的日志文件
        修改时间超过30分钟才压缩
        """
        dir_name = os.path.dirname(self.baseFilename)

        for f in os.listdir(dir_name):
            fullname = os.path.join(dir_name, f)
            if not os.path.isfile(fullname):
                continue

            is_log_file = self.extMatch.match(f)

            if is_log_file:
                # 统一检查文件最后修改时间，超过30分钟才压缩
                if datetime.fromtimestamp(os.path.getmtime(fullname)) < (datetime.now() - timedelta(minutes=30)):
                    dfn = os.path.join(self.backup_dir, os.path.basename(f) + ".gz")
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    try:
                        self.rotate(fullname, dfn)
                    except Exception as e:
                        # 如果压缩失败，记录错误但不中断程序
                        import logging as log_module
                        log_module.error(f"Failed to compress log file {fullname}: {e}")

    # overwrite
    def rotate(self, source, dest):
        with open(source, 'rb') as sf, gzip.open(dest, 'wb') as df:
            df.write(sf.read())
        os.remove(source)

    # overwrite
    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        self._backup_remains()
        dfn = os.path.join(self.backup_dir, os.path.basename(self.baseFilename) + ".gz")
        if os.path.exists(dfn):
            os.remove(dfn)
        self.rotate(self.baseFilename, dfn)
        self.baseFilename = self._get_filename()
        if self.backupCount > 0:
            for s in self.get_files_to_delete():
                os.remove(s)
        if not self.delay:
            self.stream = self._open()


def get_logger():
    logger = origin_logging.getLogger()
    logger.setLevel(origin_logging.INFO)
    file_handler = get_file_handler('')
    logger.addHandler(file_handler)

    if Profile.dev():
        stream_handler = origin_logging.StreamHandler()
        stream_handler.setLevel(origin_logging.DEBUG)
        stream_handler.setFormatter(FORMATTER)
        logger.addHandler(stream_handler)

    return logger


def get_file_handler(suffix):
    log_file_name = "rkb-{}".format(suffix)
    # 日志目录由 LOG_DIR 指定，默认落在系统临时目录
    logs_dir_path = (os.environ.get('LOG_DIR')
                     or os.path.join(tempfile.gettempdir(), 'rkb-logs'))
    # 不能先 exists 再 makedirs：并发解析时多个子进程同时走到这里，
    # 后到者会 FileExistsError，连带整份文档解析失败。
    os.makedirs(logs_dir_path, exist_ok=True)
    log_file = os.path.join(logs_dir_path, log_file_name)
    # 50MB阈值，保留9个归档文件
    fh = CompressedRotatingFileHandler(log_file, maxBytes=52428800, backupCount=9)
    fh.setFormatter(FORMATTER)
    if Profile.dev():
        fh.setLevel(origin_logging.DEBUG)
    else:
        fh.setLevel(origin_logging.INFO)
    return fh


ucli_logger = get_logger()
log = ucli_logger


def new_exception(msg, *args, **kwargs):
    kwargs['exc_info'] = 1
    log.warning(msg, *args, **kwargs)


log.exception = new_exception

