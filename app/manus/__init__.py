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
from datetime import datetime

# 获取当前文件所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 获取当前时间并格式化
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')

# 构造路径：/xxx/xxx/work_space/work_space_时间戳
WORKSPACE_PATH = os.path.join(BASE_DIR, 'work_space', f'work_space_{timestamp}')
