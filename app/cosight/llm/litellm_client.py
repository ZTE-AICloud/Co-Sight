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

"""
Drop-in replacement for openai.OpenAI() that routes through LiteLLM.

Provides the same .chat.completions.create() interface so ChatLLM
works without any changes to its calling code.
"""


class _Completions:
    def __init__(self, api_key=None, api_base=None):
        self._api_key = api_key
        self._api_base = api_base

    def create(self, **kwargs):
        try:
            import litellm
        except ImportError:
            raise ImportError(
                "litellm package not installed. Run: pip install litellm"
            )

        kwargs["drop_params"] = kwargs.get("drop_params", True)
        if self._api_key:
            kwargs.setdefault("api_key", self._api_key)
        if self._api_base:
            kwargs.setdefault("api_base", self._api_base)

        return litellm.completion(**kwargs)


class _Chat:
    def __init__(self, completions):
        self.completions = completions


class LiteLLMClient:
    """OpenAI-compatible client that delegates to litellm.completion().

    Usage::

        client = LiteLLMClient(api_key="sk-...", api_base="https://...")
        response = client.chat.completions.create(
            model="anthropic/claude-sonnet-4-6",
            messages=[{"role": "user", "content": "hi"}],
        )
    """

    def __init__(self, api_key=None, api_base=None):
        self.chat = _Chat(_Completions(api_key=api_key, api_base=api_base))
