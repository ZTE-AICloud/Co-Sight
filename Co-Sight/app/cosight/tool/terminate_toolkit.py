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

from app.common.logger_util import logger
class TerminateToolkit:
    r"""A class representing a toolkit for terminating interactions when the request is met OR if the assistant cannot proceed further with the task."""

    def __init__(self):
        pass

    def terminate(self, status: str, reason: str) -> str:
        r"""Finish the current execution.

        Args:
            status (str): The finish status of the interaction.
            reason (str): The finish reason of the interaction.

        Returns:
            str: The termination message.
        """
        logger.info(f"Terminating interaction with status: {status}, with reason: {reason}")
        return f"The interaction has been completed with status: {status}, with reason: {reason}"
