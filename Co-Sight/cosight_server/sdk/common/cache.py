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

import threading
import time


class Cache:
    _cache = {}
    _lock = threading.Lock()

    @classmethod
    def put(cls, key, value, timeout=None):
        """存入缓存。
        :param key: 缓存的唯一标识，字符串类型
        :param value: 待缓存的内容，任意类型
        :param timeout: 老化时间，整型，单位秒，可选参数
        """
        with cls._lock:
            expiration = time.time() + timeout if timeout else None
            cls._cache[key] = (value, expiration)
            if timeout:
                threading.Timer(timeout, cls._expire, args=[key]).start()

    @classmethod
    def get(cls, key):
        """读取缓存。
        :param key: 缓存的唯一标识，字符串类型
        :return: 缓存值，任意类型
        """
        with cls._lock:
            if key in cls._cache:
                value, expiration = cls._cache[key]
                if not expiration or expiration > time.time():
                    return value
                else:
                    del cls._cache[key]
            return None

    @classmethod
    def delete(cls, key):
        """删除缓存。
        :param key: 缓存的唯一标识，字符串类型
        :return: 删除成功返回 True，否则返回 False
        """
        with cls._lock:
            if key in cls._cache:
                del cls._cache[key]
                return True
            return False

    @classmethod
    def _expire(cls, key):
        """内部方法，用于在缓存过期时删除缓存项。
        :param key: 缓存的唯一标识，字符串类型
        """
        with cls._lock:
            if key in cls._cache:
                _, expiration = cls._cache[key]
                if expiration and expiration <= time.time():
                    del cls._cache[key]


# 示例使用方法
if __name__ == "__main__":
    Cache.put("test", "This is a test", 3)  # 3秒后过期
    # print(Cache.get("test"))  # 输出: This is a test
    time.sleep(4)
    # print(Cache.get("test"))  # 输出: None，因为缓存已过期

    Cache.put("permanent", "This is permanent")  # 不会过期
    # print(Cache.get("permanent"))  # 输出: This is permanent
    time.sleep(4)
    # print(Cache.get("permanent"))  # 输出: This is permanent

    Cache.delete("permanent")
    # print(Cache.get("permanent"))  # 输出: None，因为缓存已被删除
