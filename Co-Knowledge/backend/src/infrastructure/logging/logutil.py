# coding=utf-8
import gzip
import logging as origin_logging
import os
import re
import secrets
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from infrastructure.logging.trace import TraceIdFilter
from infrastructure.config import deployment
from infrastructure.fs import paths

FORMATTER = origin_logging.Formatter(
    "[%(asctime)s.%(msecs)03d][%(process)d][%(thread)d][%(levelname)1s]"
    "[trace=%(trace_id)s][%(filename)1s:%(lineno)1s] %(message)s",
    "%Y-%m-%d %H:%M:%S")


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
            try:
                mtime = os.path.getmtime(fullname)
            except OSError:
                # listdir 之后被别的进程转走/删掉：跳过即可，不该让构造日志 handler 失败
                continue
            if datetime.fromtimestamp(mtime) < (datetime.now() - timedelta(minutes=30)):
                dfn = os.path.join(self.backup_dir, os.path.basename(f) + ".gz")
                if os.path.exists(dfn):
                    os.remove(dfn)
                self.rotate(fullname, dfn)

    # overwrite
    def rotate(self, source, dest):
        """压缩归档并删除源文件。

        ⚠️ 源文件可能在 ``listdir`` 之后、``open``/``remove`` 之前就被**另一个进程**
        转走了（多个 handler 同时清理历史日志是常态；子进程重新导入应用时也会各建
        一个 handler）。以前这里裸 ``open``/``os.remove``，撞上就是
        ``FileNotFoundError`` 冒到 ``__init__`` —— 直接把那个进程打死
        （现场：算子沙箱子进程 exitcode=1，文件任务报 split.error）。
        归档这种「尽力而为」的清理动作，文件不在了就当它已经处理完。
        """
        # 先拿到源句柄再建目标文件：源文件已经不在了就什么都不做，
        # 避免留下一个被截断的空 gz（那会连对方的归档一起毁掉）。
        try:
            source_file = open(source, 'rb')
        except FileNotFoundError:
            return
        with source_file, gzip.open(dest, 'wb') as dest_file:
            while True:
                block = source_file.read(1024 * 1024)
                if not block:
                    break
                dest_file.write(block)
        try:
            os.remove(source)
        except FileNotFoundError:
            pass

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

    # 多个日志模块（infrastructure.logging 与其它日志工具）都往 root logger 挂 handler。
    # 不要挂两个 RotatingFileHandler：同一行日志会写进两个文件
    # （/app/logs 与 /data/rkb/logs），排查时要同时翻两处、且 /app/logs 不在卷上。
    # 用 root logger 上的标记保证**全进程只挂一个**（谁先 import 谁赢）。
    if not getattr(logger, '_ragstudio_file_handler', None):
        file_handler = get_file_handler('')
        file_handler.addFilter(TraceIdFilter())
        logger.addHandler(file_handler)
        logger._ragstudio_file_handler = file_handler

    if deployment.is_dev_mode():
        stream_handler = origin_logging.StreamHandler()
        stream_handler.setLevel(origin_logging.DEBUG)
        stream_handler.setFormatter(FORMATTER)
        stream_handler.addFilter(TraceIdFilter())
        logger.addHandler(stream_handler)

    return logger


def get_file_handler(suffix):
    log_file_name = "rag-knowledge-base{}".format(suffix)
    logs_dir_path = paths.get_log_dir()
    is_exist = os.path.exists(logs_dir_path)
    if not is_exist:
        os.makedirs(logs_dir_path)
    log_file = os.path.join(logs_dir_path, log_file_name)
    fh = CompressedRotatingFileHandler(log_file, max_bytes=100 * 1024 * 1024, backup_count=20)
    fh.setFormatter(FORMATTER)
    fh.addFilter(TraceIdFilter())
    fh.setLevel(origin_logging.DEBUG if deployment.is_dev_mode() else origin_logging.INFO)
    return fh


log = get_logger()
