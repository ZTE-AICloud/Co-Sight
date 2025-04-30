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

# Started by AICoder, pid:d12e9a380f9642b29c16c88302bebc56
# Started by AICoder, pid:w6c88e50b9qa61c14c7f0810a05a791a38a2095d
import time
from datetime import datetime
from functools import wraps

from app.common.infrastructure.utils.log import logger


def timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logger.info(f'Function {func.__name__} took {end_time - start_time:.4f} seconds')
        return result
    return wrapper
# Ended by AICoder, pid:w6c88e50b9qa61c14c7f0810a05a791a38a2095d


def get_current_time_format():
    current_datetime = datetime.now()
    return current_datetime.strftime("%Y-%m-%d %H:%M:%S")
# Ended by AICoder, pid:d12e9a380f9642b29c16c88302bebc56
