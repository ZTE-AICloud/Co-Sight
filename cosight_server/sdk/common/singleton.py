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

import functools
import threading


# 装饰器实现的单例，不推荐，没有属性提示
def singleton(cls_obj):
    """单例装饰器"""

    _instance_dic = {}
    _instance_lock = threading.Lock()

    @functools.wraps(cls_obj)
    def wrapper(*args, **kwargs):
        if cls_obj in _instance_dic:
            # 实例字典中存在，则直接返回
            return _instance_dic.get(cls_obj)

        # 互斥锁，防止多线程竞争时导致创建多实例
        with _instance_lock:
            if cls_obj not in _instance_dic:
                # 实例字典中不存在，则创建实例对象，并存入字典中
                _instance_dic[cls_obj] = cls_obj(*args, **kwargs)

        return _instance_dic.get(cls_obj)

    return wrapper


class SingletonMetaCls(type):
    """单例元类"""

    _instance_lock = threading.Lock()

    def __init__(cls, *args, **kwargs):
        cls._instance = None
        super().__init__(*args, **kwargs)

    def __call__(cls, *args, **kwargs):
        if cls._instance:
            # 存在实例则直接返回，减少锁竞争，提高性能
            return cls._instance

        # 互斥锁，防止多线程竞争时导致创建多实例
        with cls._instance_lock:
            if not cls._instance:
                cls._instance = super().__call__(*args, **kwargs)

        return cls._instance
