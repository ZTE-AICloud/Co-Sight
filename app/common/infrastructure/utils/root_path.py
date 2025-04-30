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
import os.path
from app.common.infrastructure.utils.log import logger


# Started by AICoder, pid:c19a7r30dap18c41456b08d470c487032a48ab1c

def fetch_abs_path_from_target(relative_path_from_project):
    current_dir = os.path.dirname(__file__)
    logger.info(f'for debug, current_dir:{current_dir}')
    for _ in range(4):
        current_dir = os.path.dirname(current_dir)
    return os.path.abspath(os.path.join(current_dir, relative_path_from_project))


# Ended by AICoder, pid:c19a7r30dap18c41456b08d470c487032a48ab1c

if __name__ == '__main__':
    print(fetch_abs_path_from_target("tests/resource/agents_information/zae_agent_tempalte"))
