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

# coding: utf-8

import datetime
import logging
import logging.handlers
import os
import sys
from logging.handlers import RotatingFileHandler

_src_file = os.path.normcase(sys._getframe().f_code.co_filename)


class LogFormatter(logging.Formatter):
    def __init__(self):
        message_fmt = "%(asctime)s\t[%(levelname)s]\t[%(filename)s.%(lineno)d]\t%(message)s"
        date_fmt = "%Y-%m-%d %H:%M:%S"
        logging.Formatter.__init__(self, message_fmt, date_fmt)

    def formatTime(self, record, datefmt=None):
        now = datetime.datetime.now()
        now_date_str = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        return now_date_str


class FileLogHandler(RotatingFileHandler):
    def __init__(self, dir_path, log_name):
        log_file = os.path.abspath(os.path.join(dir_path, log_name))
        log_size = 1024 * 1024 * 30
        log_num = 10
        RotatingFileHandler.__init__(self, log_file, maxBytes=log_size, backupCount=log_num, encoding='utf-8')
        self.setLevel(logging.INFO)
        self.setFormatter(LogFormatter())


class Logger(logging.Logger):
    def __init__(self, service_name):
        logging.Logger.__init__(self, service_name)
        self.service_name = service_name
        self.base_message = "[{0}]\t{1}"
        self.__logger_flag = False

    def set_dir_path(self, dir_path):
        if not self.__logger_flag:
            self.addHandler(FileLogHandler(dir_path, "{}.log".format(self.service_name)))
            self.__logger_flag = True

    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=None, stack_level=None):
        if _src_file:
            try:
                file_name, lno, func, _ = self.findCaller(stacklevel=3)
            except ValueError:
                file_name, lno, func = "(unknown file)", 0, "(unknown function)"
        else:
            file_name, lno, func = "(unknown file)", 0, "(unknown function)"
        if exc_info and not isinstance(exc_info, tuple):
            exc_info = sys.exc_info()
        record = self.makeRecord(self.name, level, file_name, lno, msg, args, exc_info, func, extra)
        self.handle(record)

    def info(self, msg, service_specific_fields='', *args, **kwargs):
        message = self.base_message.format(service_specific_fields, msg)
        if self.isEnabledFor(logging.INFO):
            self._log(logging.INFO, message, args, **kwargs)

    def warn(self, msg, service_specific_fields='', *args, **kwargs):
        message = self.base_message.format(service_specific_fields, msg)
        if self.isEnabledFor(logging.WARN):
            self._log(logging.INFO, message, args, **kwargs)

    def error(self, msg, service_specific_fields='', *args, **kwargs):
        message = self.base_message.format(service_specific_fields, msg)
        if self.isEnabledFor(logging.ERROR):
            self._log(logging.ERROR, message, args, **kwargs)

    def debug(self, msg, service_specific_fields='', *args, **kwargs):
        message = self.base_message.format(service_specific_fields, msg)
        if self.isEnabledFor(logging.DEBUG):
            self._log(logging.DEBUG, message, args, **kwargs)


logger = Logger("zagents_framework")


def set_parameters(dir_path):
    logger.set_dir_path(dir_path)
