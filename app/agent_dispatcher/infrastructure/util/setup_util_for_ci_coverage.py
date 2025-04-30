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

import re

thought_pattern3 = r"Thought:(.*?)(?=\nAction:|$)"  # 匹配Thought内容直到换行符后紧跟Action:或字符串结束
action_pattern3 = r"Action:(.*?)(?=\nAction Input:|$)"  # 匹配Action内容直到换行符后紧跟Action Input:或字符串结束
action_input_pattern3 = r"Action Input:(.*)$"  # 匹配Action Input后面直到字符串结束的所有内容

thought_final_answer_pattern3 = r"Thought:(.*?)(?=\nFinal Answer:|$)"
final_answer_pattern3 = r"Final Answer:(.*)$"


#

def for_setup_one(input):
    thought = base(input, thought_final_answer_pattern3)
    final_answer = base(input, final_answer_pattern3)
    return {
        "thought": thought,
        "final_answer": final_answer
    }


def for_setup_two(input):
    thought3 = base(input, thought_pattern3)
    action3 = base(input, action_pattern3)
    action_input3 = base(input, action_input_pattern3)
    return {
        "thought": thought3,
        "action": action3,
        "action_input": action_input3
    }


def for_setup_three(input):
    thought3 = base(input, thought_final_answer_pattern3)
    action3 = ""
    action_input3_1 = "{}"
    return {
        "thought": thought3,
        "action": action3,
        "action_input": action_input3_1,
    }


def base(input, pattern):
    match = re.search(pattern, input, re.S)
    return match.group(1).strip()


def multi_branch(input1):
    if re.search(r"Thought:(.*?)(?=\nAction:|$)", input1, re.S):
        return "Branch 1"
    elif re.search(r"Action:(.*?)(?=\nAction Input:|$)", input1, re.S):
        return "Branch 2"
    elif re.search(r"Action Input:(.*)$", input1, re.S):
        return "Branch 3"
    else:
        return "Default Branch"


def simple_function(value):
    result = 0
    if value < 0:
        result = -1
    elif value == 0:
        result = 0
    elif value == 1:
        result = 1
    elif value == 2:
        result = 2
    else:
        result = 3
    return result
