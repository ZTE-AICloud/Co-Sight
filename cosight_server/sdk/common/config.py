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

from typing import Dict, Any, Optional
from functools import lru_cache

class AppConfig:
    _instance: Optional['AppConfig'] = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._config: Dict[str, Any] = {}
            self._initialized = True
    
    @classmethod
    @lru_cache()
    def get_instance(cls) -> 'AppConfig':
        return cls()
    
    def initialize(self, config: Dict[str, Any]) -> None:
        """初始化配置，只能调用一次"""
        if self._config:
            raise RuntimeError("AppConfig already initialized")
        self._config = config
    
    def get(self, key: str, default: Any = None) -> Any:
        if not self._config:
            raise RuntimeError("AppConfig not initialized")
        return self._config.get(key, default)
    
    def __getattr__(self, name: str) -> Any:
        """允许通过属性访问配置项"""
        return self.get(name)
    
    def __getitem__(self, key: str) -> Any:
        """允许通过字典方式访问配置项: config['key']"""
        return self.get(key)
    
    def __contains__(self, key: str) -> bool:
        """支持 in 操作符: 'key' in config"""
        return key in self._config

# 创建一个全局实例
custom_config = AppConfig.get_instance()