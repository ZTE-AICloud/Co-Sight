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
from .file_download_toolkit import *


class VideoTool:
    def __init__(self, llm_config):
        self.llm_config = llm_config

    name: str = "Video Tool"
    description: str = (
        "This tool uses OpenAI's Video API to describe the contents of an video."
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

    #  Base64 编码格式
    def encode_video(self, video_path):
        with open(video_path, "rb") as video_file:
            return base64.b64encode(video_file.read()).decode("utf-8")

    def parse_param(self, video_path):
        video_url = ''
        if video_path.startswith('http://') or video_path.startswith('https://'):
            workspace_path = os.getenv("WORKSPACE_PATH") or os.getcwd()
            absolute_path = ''
            if is_youtube_url(video_path):
                absolute_path = download_youtube_audio_and_subs(url=video_path, output_dir=workspace_path)
            else:
                file_name = get_filename_from_url(video_path)
                absolute_path = os.path.join(workspace_path, file_name)
                download_file(video_path, absolute_path)
            base64_video = self.encode_video(absolute_path)
            video_url = f"data:;base64,{base64_video}"
        else:
            base64_video = self.encode_video(video_path)
            video_url = f"data:;base64,{base64_video}"
        return video_url

    async def video_analy(self, video_path: str, question: str):
        video_url = self.parse_param(video_path)
        completion = self.client.chat.completions.create(
            extra_headers={'Content-Type': 'application/json',
                           'Authorization': 'Bearer %s' % self.llm_config['api_key']},
            model=self.llm_config['model'],
            messages=[
                # {
                #     "role": "system",
                #     "content": [
                #         {"type": "text",
                #          "text": "你是一个非常有用的人工智能助手，请详细完整的回答用户问题,提供更多的细节，不要省略关键信息。"},
                #     ],
                # },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {"url": video_url},
                        },
                        {"type": "text", "text": question},
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
                            # print(delta.audio['transcript'], end="", flush=True)
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
        print(f'ask_question_about_video result {full_response}')
        return full_response

    def ask_question_about_video(self, video_path: str, question: str, ):
        print(f"Using Tool: {self.name}")
        return asyncio.run(self.video_analy(video_path, question))
