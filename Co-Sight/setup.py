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
# -*- coding: UTF-8 -*-
from setuptools import setup, find_packages

### 修改版本号的时候，表示要外发的版本，那么请同步修改deploy_pypi.sh中的auto为true，然后在提交一次代码，将auto改成false
setup(
    name="Core_Sight",
    version="1.0",
    author='',
    packages=find_packages(include=['app', 'config', 'app.*', 'config.*']),
    py_modules=['llm', 'CoSight'],
    python_requires='>=3.10',
    include_package_data=True,
    install_requires=["aiohttp==3.11.18",
                        "bottle==0.13.2",
                        "requests==2.32.3",
                        "wheel==0.45.1",
                        "setuptools==77.0.3",
                        "mcp==1.6.0",
                        "lagent==0.2.4",
                        "docx2markdown==0.1.1",
                        "ffmpeg-python==0.2.0",
                        "baidusearch==1.0.3",
                        "retry==0.9.2",
                        "loguru==0.7.3",
                        "googlesearch-python==1.3.0",
                        "browser-use==0.1.41",
                        "xmltodict==0.14.2",
                        "soundfile==0.13.1",
                        "pysqlite3==0.5.4",
                        "arxiv2text==0.1.14",
                        "wikipedia==1.4.0",
                        "linkup==0.1.3",
                        "wolframalpha==5.1.3",
                        "soundfile==0.13.1",
                        "python-pptx==1.0.2",
                        "seaborn",
                        "markdown",
                        "plotly",
                        "kaleido"])

# 任务根目录执行python setup.py sdist
# 将文件复制到根目录中，使用pip install安装
