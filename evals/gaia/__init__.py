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

from .dataset import gaia_dataset
from .gaia import (
    gaia,
    gaia_level1,
    gaia_level2,
    gaia_level3,
)
from .hle import hle, post_judge_hle, post_judge_hle_four_route, post_judge_hle_one_route, simple_judge_hle_four_route
from .ChineseSimpleQA import chinesesimpleqa, chinesesimpleqa_multi_route
from .simpleQA import simpleqa
from .scorer import question_scorer

__all__ = [
    "gaia",
    "gaia_level1",
    "gaia_level2",
    "gaia_level3",
    "question_scorer",
    "gaia_dataset",
    "hle",
    "post_judge_hle_one_route",
    "post_judge_hle",
    "post_judge_hle_four_route",
    "simple_judge_hle_four_route",
    "chinesesimpleqa",
    "chinesesimpleqa_multi_route",
    "simpleqa",
]
