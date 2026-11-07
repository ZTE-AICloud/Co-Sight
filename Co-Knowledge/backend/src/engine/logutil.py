# coding=utf-8
import gzip
import logging as origin_logging
import os
import platform
import re
import secrets
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from engine.settings import Config
from engine import path_utils
from infrastructure.logging.trace import TraceIdFilter

# 日志级别管理器
_log_level = origin_logging.INFO


def get_log_level():
    """获取当前日志级别"""
    return origin_logging.getLevelName(_log_level)


def set_log_level(level: str):
    """动态设置日志级别"""
    global _log_level
    level = level.upper()
    level_map = {
        'DEBUG': origin_logging.DEBUG,
        'INFO': origin_logging.INFO,
        'WARNING': origin_logging.WARNING,
        'ERROR': origin_logging.ERROR,
        'CRITICAL': origin_logging.CRITICAL
    }
    _log_level = level_map.get(level, origin_logging.INFO)
    # 动态修改所有已存在的 handler 级别
    logger = origin_logging.getLogger()
    for handler in logger.handlers:
        handler.setLevel(_log_level)
    logger.setLevel(_log_level)
    return origin_logging.getLevelName(_log_level)


_LOG_FORMAT = ("[%(asctime)s.%(msecs)03d][%(process)d][%(thread)d][%(levelname)1s]"
               "[trace=%(trace_id)s][%(filename)1s:%(lineno)1s] %(message)s")
FORMATTER = origin_logging.Formatter(
    _LOG_FORMAT, "%Y-%m-%d %H:%M:%S") if 'Linux' == platform.system() \
    else origin_logging.Formatter(_LOG_FORMAT)


def _get_rand_str():
    rand_str = ""
    for i in range(6):
        rand_str += str(secrets.randbelow(10))
    return rand_str


class CompressedRotatingFileHandler(RotatingFileHandler):
    """
    example-202202121101-[xxx].log
    zip/example-202202121101-[xxx].log.gz
    """

    def __init__(self, filename, max_bytes, backup_count):
        # 日志文件名中使用的随机数
        self.random = _get_rand_str()

        # 记录原始输入的文件名，用于每次构造日志文件名使用
        self.input_filename = filename
        filename = self._get_filename()
        if not os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename), mode=0o750)

        super().__init__(filename, maxBytes=max_bytes, backupCount=backup_count)

        # 匹配日志文件名的正则表达式
        self.extMatch = re.compile(r"^-\d{4}\d{2}\d{2}\d{2}\d{2}\d{2}-\[\d+\].log(\.\w+)?$", re.ASCII)

        # 创建归档目录
        self.backup_dir = os.path.join(os.path.dirname(self.baseFilename), 'zip')
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir, mode=0o750)

        # 清理历史残留的未归档的log文件，修改时间超30分钟未修改，则认为是残留文件
        self._backup_remains()

    def _get_filename(self):
        filename = os.fspath(self.input_filename)
        return "%s-%s-[%s].log" % (
            os.path.abspath(filename), datetime.strftime(datetime.now(), "%Y%m%d%H%M%S"), self.random)

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
        dir_name = os.path.dirname(self.baseFilename)
        for f in os.listdir(dir_name):
            fullname = os.path.join(dir_name, f)
            if not os.path.isfile(fullname):
                continue
            suffix = f.replace(os.path.basename(self.input_filename), "")
            if not self.extMatch.match(suffix):
                continue
            if datetime.fromtimestamp(os.path.getmtime(fullname)) < (datetime.now() - timedelta(minutes=30)):
                dfn = os.path.join(self.backup_dir, os.path.basename(f) + ".gz")
                if os.path.exists(dfn):
                    os.remove(dfn)
                self.rotate(fullname, dfn)

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


def is_dev_mode():
    return Config.get('dev_mode') == 'true'


def get_logger():
    logger = origin_logging.getLogger()
    logger.setLevel(origin_logging.INFO)

    # 与 tool.log.logutil 共用同一个 root logger：**全进程只挂一个文件 handler**。
    # 两个模块都挂 = 每行日志写两份（一个在 /app/logs、一个在 /data/rkb/logs），
    # 排查时很难判断哪份是完整的。谁先 import 谁创建，后到的复用。
    if not getattr(logger, '_ragstudio_file_handler', None):
        file_handler = get_file_handler('')
        file_handler.addFilter(TraceIdFilter())
        logger.addHandler(file_handler)
        logger._ragstudio_file_handler = file_handler

    if is_dev_mode():
        stream_handler = origin_logging.StreamHandler()
        stream_handler.setLevel(origin_logging.DEBUG)
        stream_handler.setFormatter(FORMATTER)
        stream_handler.addFilter(TraceIdFilter())
        logger.addHandler(stream_handler)

    return logger


def get_file_handler(suffix):
    log_file_name = "rag-component-service{}".format(suffix)
    logs_dir_path = path_utils.get_log_dir()
    is_exist = os.path.exists(logs_dir_path)
    if not is_exist:
        os.makedirs(logs_dir_path)
    log_file = os.path.join(logs_dir_path, log_file_name)
    fh = CompressedRotatingFileHandler(log_file, max_bytes=100 * 1024 * 1024, backup_count=20)
    fh.setFormatter(FORMATTER)
    fh.addFilter(TraceIdFilter())
    fh.setLevel(origin_logging.INFO)
    return fh


logger = get_logger()


def new_exception(msg, *args, **kwargs):
    kwargs['exc_info'] = 1
    logger.warning(msg, *args, **kwargs)


logger.exception = new_exception
