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

from typing import Generator, Any


class MessageStream:
    def __init__(self, generator: Generator):
        self.generator = generator  # 原始生成器
        if not isinstance(generator,Generator):
            #如果不是生成器，变成只有一个元素的生成器
            self.generator=(x for x in [generator])
        self._cache = []  # 缓存已产生的值
        self._current_index = 0  # 当前迭代位置

    def __iter__(self):
        return self

    def __next__(self) -> Any:
        if self._current_index < len(self._cache):
            value = self._cache[self._current_index]
            self._current_index += 1
            return value
        try:
            next_value = next(self.generator)
            self._cache.append(next_value)
            self._current_index += 1
            return next_value
        except StopIteration:
            self._current_index = 0  # 重置索引以便支持重新开始迭代
            raise StopIteration

    def to_text(self) -> str:
        # 如果缓存为空，则先尝试填充缓存
        if not self._cache:
            for item in self.generator:
                self._cache.append(item)
        # 使用存储的值来拼接字符串
        return ''.join(str(x) for x in self._cache)