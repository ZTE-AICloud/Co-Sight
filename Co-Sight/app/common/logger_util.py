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
import logging as origin_logging
import os
import re
import tarfile
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

# 日志文件目录
LOG_DIR = "logs"
# 单个日志文件大小限制为20MB
SINGLE_LOG_SIZE = 20 * 1024 * 1024
# 定义日志文件总大小限制为500MB
MAX_TOTAL_LOG_SIZE = 500 * 1024 * 1024

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

        # 匹配日志文件名的正则表达式（现在匹配固定文件名格式）
        self.extMatch = re.compile(r"^\.log(\.\w+)?$", re.ASCII)

        # 创建归档目录
        self.backup_dir = os.path.join(os.path.dirname(self.baseFilename), 'bak')
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir, mode=0o750)

        # 清理历史残留的未归档的log文件，修改时间超12小时未修改，则认为是残留文件
        self._backup_remains()

        # 检查并清理日志文件
        self.clean_old_logs()

    def _find_existing_log_file(self):
        """查找现有的日志文件，如果存在则返回文件名，否则返回None"""
        dir_name = os.path.dirname(os.path.abspath(self.input_filename))
        base_name = os.path.basename(self.input_filename)

        # 查找匹配的现有日志文件（固定文件名格式）
        log_file = os.path.join(dir_name, f"{base_name}.log")
        if os.path.exists(log_file) and os.path.isfile(log_file):
            # 检查文件是否可写（没有被其他进程占用）
            try:
                with open(log_file, 'a'):
                    pass
                return log_file
            except (IOError, OSError):
                # 文件被占用，跳过这个文件
                pass
        return None

    def _get_filename(self):
        """获取日志文件名，优先使用现有文件，否则创建新文件"""
        # 首先尝试查找现有的日志文件
        existing_file = self._find_existing_log_file()
        if existing_file:
            return existing_file

        # 如果没有找到现有文件，则创建新的固定文件名
        filename = os.fspath(self.input_filename)
        return "%s.log" % (os.path.abspath(filename))

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
                # 生成带时间戳的压缩备份文件名
                current_time = datetime.strftime(datetime.now(), "%Y%m%d%H%M%S")
                dfn = os.path.join(self.backup_dir, f"{os.path.basename(f)}-{current_time}.tar.gz")
                if os.path.exists(dfn):
                    try:
                        os.remove(dfn)
                    except OSError:
                        continue
                try:
                    self.rotate(fullname, dfn)
                except (OSError, PermissionError):
                    # 文件被占用，跳过这个文件
                    continue

    # overwrite
    def rotate(self, source, dest):
        try:
            # 使用tarfile创建tar.gz格式的压缩文件，兼容Linux tar命令
            with tarfile.open(dest, 'w:gz') as tar:
                tar.add(source, arcname=os.path.basename(source))
            os.remove(source)
        except (OSError, PermissionError) as e:
            # 如果无法删除源文件，至少尝试压缩备份
            print(f"Warning: Could not remove source file {source}: {e}")
            pass

    # overwrite
    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        self._backup_remains()

        # 生成带时间戳的压缩备份文件名
        current_time = datetime.strftime(datetime.now(), "%Y%m%d%H%M%S")
        base_name = os.path.basename(self.baseFilename)
        dfn = os.path.join(self.backup_dir, f"{base_name}-{current_time}.tar.gz")
        if os.path.exists(dfn):
            os.remove(dfn)
        self.rotate(self.baseFilename, dfn)

        # 轮转时必须创建新文件，不能重用现有文件
        filename = os.fspath(self.input_filename)
        self.baseFilename = "%s.log" % (os.path.abspath(filename))
        if self.backupCount > 0:
            for s in self.get_files_to_delete():
                os.remove(s)
        if not self.delay:
            self.stream = self._open()

        # 检查并清理日志文件
        self.clean_old_logs()

    def get_total_log_size(self):
        """获取logs目录下所有日志文件的总大小（包括bak目录下的备份文件）"""
        total_size = 0
        # 遍历logs目录下的所有文件
        for root, _, files in os.walk(LOG_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    total_size += os.path.getsize(file_path)
        return total_size

    def get_oldest_timestamp_files(self):
        """获取所有日志文件中修改时间最早的文件列表"""
        bak_dir = os.path.join(LOG_DIR, "bak")
        file_times = {}

        # 遍历bak目录下的所有文件
        for file in os.listdir(bak_dir):
            if not file.endswith(".tar.gz"):
                continue
            file_path = os.path.join(bak_dir, file)
            if os.path.isfile(file_path):
                # 使用文件修改时间作为排序依据
                mtime = os.path.getmtime(file_path)
                if mtime not in file_times:
                    file_times[mtime] = []
                file_times[mtime].append(file_path)

        # 按修改时间排序
        if file_times:
            oldest_time = min(file_times.keys())
            return file_times[oldest_time]
        return []

    def clean_old_logs(self):
        """清理最旧的日志文件，直到总大小小于限制"""
        while self.get_total_log_size() >= MAX_TOTAL_LOG_SIZE:
            oldest_files = self.get_oldest_timestamp_files()
            if not oldest_files:
                break
            # 删除最旧时间戳的所有文件
            for file in oldest_files:
                try:
                    os.remove(file)
                except OSError:
                    continue


def get_logger(name="co-sight"):
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
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    # 日志文件路径
    log_file = os.path.join(LOG_DIR, suffix)

    fh = CompressedRotatingFileHandler(log_file, max_bytes=SINGLE_LOG_SIZE, backup_count=100)
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
