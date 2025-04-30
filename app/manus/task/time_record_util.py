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

import time
from functools import wraps

def time_record(func):
    """
    记录函数执行时间的装饰器
    :param func: 被装饰的函数
    :return: 装饰后的函数
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
        finally:
            end_time = time.time()
            elapsed_time = end_time - start_time
            current_time = time.strftime("%H:%M:%S", time.localtime())
            print(f"[{current_time}] Function '{func.__name__}' called with args: {kwargs.get('function_name','') or kwargs.get('step_index','')}: executed in {elapsed_time:.4f} seconds")
        return result
    return wrapper
