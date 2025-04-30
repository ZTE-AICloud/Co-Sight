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

# flake8: noqa

select_example1_cn = """
### 样例一

- 针对**当前问题:"2023年中兴通讯的总经营收入是多少"**，如果搜索结果不包含问题答案，例如：
为了找到中兴通讯在2023年的总经营收入，我需要寻找包含相关财务信息的网页。初步浏览搜索结果后，发现网页0、1、2、3和4的摘要中均未提及中兴通讯的财务信息。因此，这些网页不包含我需要的信息。
此时请严格按照如下格式进行输出：
1. 输出各个网页的内容摘要
2. 输出：<|action_start|><|plugin|>{"name": "yourTool.select", "parameters": {"select_ids": []}}<|action_end|>

> 注意：样例里的yourTool只是举个例子，并不是实际可以调用的工具
> 请一定要输出选择的动作，不能直接总结

### 样例二

- 针对**当前问题:"2023年中兴通讯的总经营收入是多少"**，如果搜索结果是空的，例如：
为了找到中兴通讯在2023年的总经营收入，我需要寻找包含相关财务信息的网页。初步浏览搜索结果后，发现搜索结果是空的。
此时请严格按照如下格式进行输出：
1. 输出：<|action_start|><|plugin|>{"name": "yourTool.select", "parameters": {"select_ids": []}}<|action_end|>

> 注意：样例里的yourTool只是举个例子，并不是实际可以调用的工具
> 请一定要输出选择的动作，不能直接总结

### 样例三

- 针对**当前问题:"2023年awade团队的业绩是多少"**，如果搜索结果包含问题答案，例如：
搜索结果中，文档0提到了awade团队的业绩为11.3123亿人民币[[0]]。这是关于2023年awade团队业绩的具体数据。因此，我选择了网页0进行进一步阅读。
此时请严格按照如下格式进行输出：
1. 输出各个网页的内容摘要
2. 输出：<|action_start|><|plugin|>{"name": "yourTool.select", "parameters": {"select_ids": [0]}}<|action_end|>

> 注意：样例里的yourTool只是举个例子，并不是实际可以调用的工具
> 请一定要输出选择的动作，不能直接总结
"""

select_example2_cn = """
针对**当前问题**搜索的结果中，如果已经包含了问题的答案，则：
- 输出内容摘要信息
- 一定不要包含 <|action_start|><|plugin|>...<|action_end|> 这样的内容
"""