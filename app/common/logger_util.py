# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# coding=utf-8
import gzip
import logging as origin_logging
import os
import re
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

FORMATTER = origin_logging.Formatter(
    "[%(asctime)s.%(msecs)03d][%(process)d][%(thread)d][%(levelname)1s][%(filename)1s:%(lineno)1s] %(message)s",
    "%Y-%m-%d %H:%M:%S")



class CompressedRotatingFileHandler(RotatingFileHandler):

    def __init__(self, filename, max_bytes, backup_count):
        # 记录原始输入的文件名，用于每次构造日志文件名使用
        self.input_filename = filename
        filename = self._get_filename()
        if not os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename), mode=0o750)

        super().__init__(filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")

        # 匹配日志文件名的正则表达式
        self.extMatch = re.compile(r"^-\d{4}\d{2}\d{2}\d{2}\d{2}\d{2}.log(\.\w+)?$", re.ASCII)

        # 创建归档目录
        self.backup_dir = os.path.join(os.path.dirname(self.baseFilename), 'bak')
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir, mode=0o750)

        # 清理历史残留的未归档的log文件，修改时间超12小时未修改，则认为是残留文件
        self._backup_remains()

    def _get_filename(self):
        filename = os.fspath(self.input_filename)
        return "%s-%s.log" % (os.path.abspath(filename), datetime.strftime(datetime.now(), "%Y%m%d%H%M%S"))

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
            if datetime.fromtimestamp(os.path.getmtime(fullname)) < (datetime.now() - timedelta(hours=12)):
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


def get_logger(name="core-sight"):
    log = origin_logging.getLogger(name)
    log.setLevel(origin_logging.INFO)

    if not log.handlers:
        log.addHandler(get_file_handler(name))

        # 可选：同时输出到控制台
        stream_handler = origin_logging.StreamHandler()
        stream_handler.setLevel(origin_logging.DEBUG)
        stream_handler.setFormatter(FORMATTER)
        log.addHandler(stream_handler)

    return log


def get_file_handler(suffix):
    # 创建 logs 目录，如果不存在的话
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 日志文件路径
    log_file = os.path.join(log_dir, suffix)

    fh = CompressedRotatingFileHandler(log_file, max_bytes=20 * 1024 * 1024, backup_count=100)
    fh.setFormatter(FORMATTER)
    fh.setLevel(origin_logging.INFO)
    return fh


logger = get_logger()


def new_exception(msg, *args, **kwargs):
    kwargs['exc_info'] = 1
    logger.warning(msg, *args, **kwargs)


logger.exception = new_exception


def raise_if(condition: bool, message: str = ""):
    if condition:
        logger.error("co-sight error: " + message)
        raise Exception(message)
