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

from fastapi import APIRouter

from cosight_server.sdk.common.api_result import json_result
from cosight_server.sdk.common.logger_util import logger

feedbackRouter = APIRouter()


@feedbackRouter.get("/feedback/reasons")
def feedback_reasons(lang: str):
    logger.info(f"feedback_reasons >>>>>>>>>>>>>>>>> is called, lang: {lang}")
    return json_result(0, "", [])
