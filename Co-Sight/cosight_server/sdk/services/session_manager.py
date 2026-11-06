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

from abc import  abstractmethod
import re
from fastapi import Request, Response

from cosight_server.sdk.common.singleton import SingletonMetaCls
from app.common.logger_util import logger


class SessionManagerBase(metaclass=SingletonMetaCls):
    @abstractmethod
    async def login(self, response: Response, cookie: str, referer: str):
        """
        登录处理的抽象方法
        :param response: Response对象
        :param cookie: cookie字符串
        :param referer: 来源页面
        """
        pass

    @abstractmethod
    def logout(self, response: Response, cookie: str):
        """
        登出处理的抽象方法
        :param response: Response对象
        :param cookie: cookie字符串
        """
        pass

    @abstractmethod
    def check_request(self, cookie: str):
        """
        检查请求有效性的抽象方法
        :param cookie: cookie字符串
        """
        pass

    @abstractmethod
    async def authority(self, request: Request):
        """
        权限验证的抽象方法
        :param request: Request对象
        """
        pass

    @abstractmethod
    def get_validation_info(self, cookie: str):
        """
        获取验证信息的抽象方法
        :param cookie: cookie字符串
        """
        pass

    @abstractmethod
    def get_req_session_id(self, cookie: str):
        """
        获取请求session ID的抽象方法
        :param cookie: cookie字符串
        """
        pass

    @abstractmethod
    def get_user_id(self, session_id: str):
        """
        获取用户ID的抽象方法
        :param session_id: 会话ID
        """
        pass
    
    def _read_user_id(self, cookie):
        return self._get_property_from_cookie(cookie, 'PORTALSSOUser') or \
            self._get_property_from_cookie(cookie, 'ZTEDPGSSOUser') or \
            self._get_property_from_cookie(cookie, 'ztewebstat') or \
            self._get_property_from_cookie(cookie, 'USERNAME')
            
    @staticmethod
    def _get_property_from_cookie(cookie, property_name, default_value=None):
        value = default_value if default_value is not None else ''
        if not cookie:
            return value

        regex = re.compile(r'(^|;)\s*' + re.escape(property_name) + r'=([\w-]+)(;|$)')
        match = regex.search(cookie)

        if not match:
            return value

        value = match.group(2)
        logger.info(f"sessionUtils.getProperty: {property_name}={value}")
        return value

class SessionManager():
    def __init__(self, session_manager: SessionManagerBase = None):
        """
        初始化SessionManagerWrapper
        :param session_manager: SessionManager实例，如果为None则创建新实例
        """
        self._session_manager = session_manager

    def set_session_manager(self, session_manager: SessionManagerBase):
        self._session_manager = session_manager

    async def login(self, response: Response, cookie: str, referer: str):
        """登录处理"""
        return await self._session_manager.login(response, cookie, referer)

    def logout(self, response: Response, cookie: str):
        """登出处理"""
        return self._session_manager.logout(response, cookie)

    def check_request(self, cookie: str):
        """检查请求有效性"""
        return self._session_manager.check_request(cookie)

    async def authority(self, request: Request):
        """权限验证"""
        return await self._session_manager.authority(request)

    def get_validation_info(self, cookie: str):
        """获取验证信息"""
        return self._session_manager.get_validation_info(cookie)

    def get_req_session_id(self, cookie: str):
        """获取请求session ID"""
        return self._session_manager.get_req_session_id(cookie)

    def get_user_id(self, session_id: str):
        """获取用户ID"""
        return self._session_manager.get_user_id(session_id)

session_manager = SessionManager()