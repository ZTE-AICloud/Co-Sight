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

import os

# 代理服务器地址
proxy = "http://proxyhk.zte.com.cn:80"

# 设置 HTTP 和 HTTPS 代理
os.environ['ALL_PROXY'] = ''
os.environ['all_proxy'] = ''
os.environ['SOCKS_PROXY'] = ''
os.environ['socks_proxy'] = ''
os.environ['HTTPS_PROXY'] = proxy
os.environ['https_proxy'] = proxy
os.environ['HTTP_PROXY'] = proxy
os.environ['http_proxy'] = proxy
os.environ['ALL_PROXY'] = proxy
os.environ['all_proxy'] = proxy