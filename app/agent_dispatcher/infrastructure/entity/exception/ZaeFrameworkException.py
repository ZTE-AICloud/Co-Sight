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

class ZaeFrameworkException(Exception):
    def __init__(self, error_code, message):
        super().__init__(f"Error {error_code}: {message}")
        self.error_code = error_code


class NaeFrameworkException(ZaeFrameworkException):
    def __init__(self, error_code, message):
        super().__init__(error_code, message)


# Started by AICoder, pid:025a4a02719e4bd69a769bc7b22fabad
class FunctionTimeoutException(NaeFrameworkException):
    def __init__(self, error_code, message):
        super().__init__(error_code, message)
# Ended by AICoder, pid:025a4a02719e4bd69a769bc7b22fabad
