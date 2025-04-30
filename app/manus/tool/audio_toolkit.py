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

from dotenv import load_dotenv

load_dotenv()
import os
from openai import OpenAI
import base64
import numpy as np
import soundfile as sf
import asyncio
from urllib.parse import urlparse
from .file_download_toolkit import download_file, get_filename_from_url


class AudioTool:
    def __init__(self, llm_config):
        self.llm_config = llm_config

    name: str = "Audio Tool"
    description: str = (
        "This tool uses OpenAI's Audio API to describe the contents of an audio."
    )
    _client: OpenAI = None

    @property
    def client(self) -> OpenAI:
        llm_config = {"api_key": self.llm_config['api_key'],
                      "base_url": self.llm_config['base_url']
                      }
        """Cached ChatOpenAI client instance."""
        if self._client is None:
            self._client = OpenAI(**llm_config)
        return self._client

    def encode_audio(self, audio_path):
        with open(audio_path, "rb") as audio_file:
            return base64.b64encode(audio_file.read()).decode("utf-8")

    def get_audio_extension(self, url):
        # 解析URL
        parsed = urlparse(url)
        # 获取路径部分
        path = parsed.path
        # 使用os.path.splitext获取扩展名
        ext = os.path.splitext(path)[1].lower()
        return ext

    def parse_param(self, audio_path):
        audio_url = ''
        audio_format = ''
        if audio_path.startswith('http://') or audio_path.startswith('https://'):
            workspace_path = os.getenv("WORKSPACE_PATH") or os.getcwd()
            file_name = get_filename_from_url(audio_path)
            absolute_path = os.path.join(workspace_path, file_name)
            download_file(audio_path, absolute_path)
            base64_audio = self.encode_audio(absolute_path)
            audio_url = f"data:;base64,{base64_audio}"
            audio_format = self.get_audio_extension(absolute_path)
        else:
            base64_audio = self.encode_audio(audio_path)
            audio_url = f"data:;base64,{base64_audio}"
            audio_format = os.path.splitext(audio_path)[-1].replace('.','')
        return audio_url, audio_format

    async def audio_recognition(self, audio_path, task_prompt):
        audio_url, audio_format = self.parse_param(audio_path)
        completion = self.client.chat.completions.create(
            extra_headers={'Content-Type': 'application/json',
                           'Authorization': 'Bearer %s' % self.llm_config['api_key']},
            model=self.llm_config['model'],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_url,
                                "format": audio_format,
                            },
                        },
                        {"type": "text", "text": task_prompt},
                    ],
                },
            ],
            # 设置输出数据的模态，当前支持两种：["text","audio"]、["text"]
            modalities=["text", "audio"],
            audio={"voice": "Cherry", "format": "wav"},
            # stream 必须设置为 True，否则会报错
            stream=True,
            stream_options={"include_usage": True},
        )

        full_response = ""

        for chunk in completion:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if hasattr(delta, "audio") and delta.audio:
                    try:
                        if delta.audio['transcript']:
                            full_response += delta.audio['transcript']
                    except Exception as ex:
                        pass
                if hasattr(delta, "content") and delta.content:
                    try:
                        full_response += delta.content
                    except Exception as ex:
                        pass
            else:
                pass
        print(f'audio_recognition inifo {full_response}')
        return full_response

    def speech_to_text(self, audio_path: str, task_prompt: str, ):
        print(f"Using Tool: {self.name}")
        return asyncio.run(self.audio_recognition(audio_path, task_prompt))
