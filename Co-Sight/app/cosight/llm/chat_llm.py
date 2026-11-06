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
import json
import os
import time
from json import JSONDecodeError
from typing import List, Dict, Any, Optional
from contextvars import ContextVar

from openai import OpenAI
from openai.types.chat import ChatCompletion

from app.agent_dispatcher.infrastructure.entity.exception.ZaeFrameworkException import ZaeFrameworkException
from app.cosight.task.time_record_util import time_record
from app.common.logger_util import logger

# 检查是否启用了 Langfuse
langfuse_enabled = os.environ.get("LANGFUSE_ENABLED", "false").lower() in ("true", "1", "yes")
langfuse_client = None
propagate_attributes = None

if langfuse_enabled:
    try:
        from langfuse import Langfuse, propagate_attributes
        # 初始化 Langfuse 客户端
        langfuse_client = Langfuse()
        logger.info("✅ Langfuse client initialized for custom tracing")
    except ImportError:
        logger.warning("❌ Langfuse not installed, custom tracing disabled")
        langfuse_enabled = False
    except Exception as e:
        logger.warning(f"❌ Failed to initialize Langfuse client: {e}")
        langfuse_enabled = False

# 使用 ContextVar 来存储当前的 trace 对象（线程安全）
current_trace_context: ContextVar[Optional[object]] = ContextVar('current_trace_context', default=None)


class ChatLLM:
    def __init__(self, base_url: str, api_key: str, model: str, client: OpenAI, max_tokens: int = 8192,
                 temperature: float = 0.0, stream: bool = False, tools: List[Any] = None, thinking_mode: bool = False):
        self.tools = tools or []
        self.client = client
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.stream = stream
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.thinking_mode = thinking_mode
        
        # Langfuse追踪配置
        self.current_trace_id = None  # 当前任务的trace_id
        self.current_session_id = None  # 当前任务的session_id
        self.current_user_id = None  # 当前用户ID
        self.current_tags = []  # 当前任务的标签
        self.current_metadata = {}  # 当前任务的元数据
        self.langfuse_trace = None  # 当前的 Langfuse trace 对象
        # 消息截断配置：从环境变量读取，默认保留最近20条消息
        self.max_messages = int(os.environ.get("MAX_MESSAGES", "20"))
        # 工具返回内容的最大长度（字符数），默认50000字符
        self.max_tool_content_length = int(os.environ.get("MAX_TOOL_CONTENT_LENGTH", "50000"))
        
        # 上下文压缩配置
        self.compression_enabled = os.environ.get("ENABLE_CONTEXT_COMPRESSION", "false").lower() in ("true", "1", "yes")
        self.max_context_tokens = int(os.environ.get("MAX_CONTEXT_TOKENS", "128000"))  # 128k
        self.compression_threshold = float(os.environ.get("COMPRESSION_THRESHOLD", "0.8"))  # 80%
        self.keep_recent_turns = int(os.environ.get("KEEP_RECENT_TURNS", "3"))  # 保留最近3轮
        self.keep_initial_turns = int(os.environ.get("KEEP_INITIAL_TURNS", "2"))  # 保留最初2轮
        logger.info(f"Context compression: enabled={self.compression_enabled}, max_tokens={self.max_context_tokens}, threshold={self.compression_threshold}, keep_initial={self.keep_initial_turns}, keep_recent={self.keep_recent_turns}")

    @staticmethod
    def clean_none_values(data):
        """
        递归遍历数据结构，将所有 None 替换为 ""
        静态方法，无需实例化类即可调用
        """
        if isinstance(data, dict):
            return {k: ChatLLM.clean_none_values(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [ChatLLM.clean_none_values(item) for item in data]
        elif data is None:
            return ""
        else:
            return data

    def _count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """计算消息列表的token数量
        
        使用简化的估算方法：英文约4字符=1token，中文约1.5字符=1token
        """
        try:
            import tiktoken
            try:
                encoding = tiktoken.encoding_for_model(self.model)
            except KeyError:
                encoding = tiktoken.get_encoding("cl100k_base")
            
            total_tokens = 0
            for message in messages:
                # 每条消息的固定开销
                total_tokens += 4
                
                for key, value in message.items():
                    if isinstance(value, str):
                        total_tokens += len(encoding.encode(value))
                    elif key == "tool_calls" and isinstance(value, list):
                        for tool_call in value:
                            if hasattr(tool_call, 'function'):
                                total_tokens += len(encoding.encode(str(tool_call.function.name)))
                                total_tokens += len(encoding.encode(str(tool_call.function.arguments)))
            
            # 对话固定开销
            total_tokens += 2
            return total_tokens
            
        except ImportError:
            # 如果tiktoken不可用，使用简化估算
            logger.debug("tiktoken not available, using simplified token estimation")
            return self._estimate_tokens_simple(messages)

    def _estimate_tokens_simple(self, messages: List[Dict[str, Any]]) -> int:
        """简化的token估算（不依赖tiktoken）"""
        total_chars = 0
        for message in messages:
            content = str(message.get("content", ""))
            # 统计中文字符
            chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
            # 统计其他字符
            other_chars = len(content) - chinese_chars
            
            # 中文约1.5字符=1token，英文约4字符=1token
            total_chars += chinese_chars / 1.5 + other_chars / 4
        
        return int(total_chars) + len(messages) * 4  # 加上消息开销

    def _should_compress_context(self, messages: List[Dict[str, Any]]) -> tuple:
        """判断是否需要压缩上下文
        
        Returns:
            (需要压缩, 当前token数)
        """
        if not self.compression_enabled:
            return False, 0
        
        current_tokens = self._count_tokens(messages)
        threshold_tokens = int(self.max_context_tokens * self.compression_threshold)
        
        if current_tokens >= self.max_context_tokens:
            logger.warning(f"Context exceeds max tokens ({current_tokens} >= {self.max_context_tokens})")
            return True, current_tokens
        elif current_tokens >= threshold_tokens:
            logger.info(f"Context reached compression threshold ({current_tokens} >= {threshold_tokens}, {self.compression_threshold*100}%)")
            return True, current_tokens
        else:
            logger.debug(f"Current tokens: {current_tokens} / {threshold_tokens} ({current_tokens/threshold_tokens*100:.1f}%)")
        
        return False, current_tokens

    def _format_messages_for_compression(self, messages: List[Dict[str, Any]]) -> str:
        """将消息格式化为适合压缩的文本"""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"助手: {content}")
                # 包含工具调用信息
                if msg.get("tool_calls"):
                    for tool_call in msg["tool_calls"]:
                        if hasattr(tool_call, 'function'):
                            lines.append(f"  调用工具: {tool_call.function.name}")
            elif role == "tool":
                tool_name = msg.get("name", "unknown")
                # 截断过长的工具结果
                if len(content) > 1000:
                    content = content[:1000] + "..."
                lines.append(f"工具结果[{tool_name}]: {content}")
        
        return "\n".join(lines)

    def _compress_message_group(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """压缩一组消息"""
        if not messages:
            return []
        
        try:
            conversation_text = self._format_messages_for_compression(messages)
            is_chinese = any('\u4e00' <= c <= '\u9fff' for c in conversation_text[:100])
            
            if is_chinese:
                compress_prompt = f"""你是一个信息压缩专家。请将以下对话历史压缩为简洁的摘要，保留所有关键信息。

**压缩要求：**
1. 保留所有重要的事实、数据、结论和文件路径
2. 保留任务目标和当前进展
3. 保留关键的推理逻辑和工具调用结果
4. 删除冗余的解释和重复内容
5. 使用简洁的语言，目标压缩比：50%

**原始对话：**
{conversation_text}

**请输出压缩后的摘要（仅输出摘要内容，不要额外说明）：**
"""
            else:
                compress_prompt = f"""You are an information compression expert. Compress the following conversation into a concise summary while preserving all key information.

**Requirements:**
1. Preserve all important facts, data, conclusions, and file paths
2. Preserve task objectives and current progress
3. Preserve key reasoning logic and tool execution results
4. Remove redundant explanations
5. Target compression ratio: 50%

**Original Conversation:**
{conversation_text}

Keep facts, data, file paths. Remove redundancy. Output summary only:"""
            
            # 4. 调用LLM进行压缩（添加长度限制和错误处理）
            logger.info(f"Compressing {len(messages)} messages (input: {len(conversation_text)} chars)...")
            
            try:
                # 使用较短的max_tokens避免响应过长和超时
                compressed_text = self.chat_to_llm(
                    [{"role": "user", "content": compress_prompt}],
                    max_tokens=2000  # 限制响应长度
                )
                
                # 5. 验证压缩结果
                if not compressed_text or len(compressed_text.strip()) < 10:
                    logger.warning("Compression result too short, using fallback")
                    raise ValueError("Compression result invalid")
                
                # 6. 创建压缩后的消息
                compressed_message = {
                    "role": "assistant",
                    "content": f"[压缩摘要] {compressed_text}" if is_chinese else f"[Compressed Summary] {compressed_text}"
                }
                
                # 如果使用thinking mode，添加reasoning_content字段
                if self.thinking_mode or "reasoner" in self.model.lower():
                    compressed_message["reasoning_content"] = ""
                
                logger.info(f"Successfully compressed {len(messages)} messages into 1 summary ({len(compressed_text)} chars)")
                return [compressed_message]
                
            except Exception as compress_error:
                logger.error(f"LLM compression call failed: {type(compress_error).__name__}: {str(compress_error)}")
                raise  # 抛出让外层处理
            
        except Exception as e:
            logger.error(f"Compression failed: {e}, falling back to keep recent messages")
            return messages[-5:] if len(messages) > 5 else messages

    def _emergency_truncate(self, messages: List[Dict[str, Any]], target_ratio: float = 0.9) -> List[Dict[str, Any]]:
        """紧急截断到目标比例，保持消息组完整性"""
        target_tokens = int(self.max_context_tokens * target_ratio)
        current_tokens = self._count_tokens(messages)
        
        if current_tokens <= target_tokens:
            return messages
        
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        non_system_messages = [msg for msg in messages if msg.get("role") != "system"]
        
        # 构建消息组（assistant + tool_calls + tool responses）
        message_groups = self._build_message_groups(non_system_messages)
        
        # 从后往前保留完整的消息组
        result = system_messages.copy()
        for group in reversed(message_groups):
            test_result = result + group
            if self._count_tokens(test_result) <= target_tokens:
                # 在system_messages之后插入这个组
                result = system_messages + group + result[len(system_messages):]
            else:
                break
        
        logger.warning(f"Emergency truncated: {len(messages)} -> {len(result)} messages")
        return result
    
    def _build_message_groups(self, messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """将消息构建为组，确保assistant+tool_calls和对应的tool消息配对"""
        groups = []
        current_group = []
        
        for msg in messages:
            role = msg.get("role")
            
            if role == "assistant":
                # 保存当前组
                if current_group:
                    groups.append(current_group)
                # 开始新组
                current_group = [msg]
            elif role == "tool":
                # tool消息属于当前组
                if current_group and current_group[0].get("role") == "assistant":
                    current_group.append(msg)
                else:
                    # 孤立的tool消息，单独成组（虽然不应该发生）
                    if current_group:
                        groups.append(current_group)
                    current_group = [msg]
            else:
                # user或其他消息
                if current_group:
                    groups.append(current_group)
                current_group = [msg]
        
        # 添加最后一组
        if current_group:
            groups.append(current_group)
        
        return groups

    def _compress_context(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """压缩上下文消息，保持消息组完整性"""
        current_tokens = self._count_tokens(messages)
        
        # 如果超过最大长度，先紧急截断
        if current_tokens > self.max_context_tokens:
            logger.warning(f"Emergency truncation triggered: {current_tokens} > {self.max_context_tokens}")
            messages = self._emergency_truncate(messages, target_ratio=0.9)
            current_tokens = self._count_tokens(messages)
        
        # 分离消息
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        non_system_messages = [msg for msg in messages if msg.get("role") != "system"]
        
        # 构建消息组
        message_groups = self._build_message_groups(non_system_messages)
        
        # 计算需要保留的消息组数量
        min_required_groups = self.keep_initial_turns + self.keep_recent_turns
        
        if len(message_groups) <= min_required_groups:
            logger.info(f"Too few message groups to compress (need > {min_required_groups}, have {len(message_groups)})")
            return messages
        
        # 分离最初、中间、最近的消息组
        initial_groups = message_groups[:self.keep_initial_turns]
        recent_groups = message_groups[-self.keep_recent_turns:]
        middle_groups = message_groups[self.keep_initial_turns:-self.keep_recent_turns]
        
        # 展平消息组
        initial_messages = [msg for group in initial_groups for msg in group]
        recent_messages = [msg for group in recent_groups for msg in group]
        middle_messages = [msg for group in middle_groups for msg in group]
        
        logger.info(f"Keeping {len(initial_messages)} initial messages ({len(initial_groups)} groups), compressing {len(middle_messages)} middle messages ({len(middle_groups)} groups), keeping {len(recent_messages)} recent messages ({len(recent_groups)} groups)")
        
        # 压缩中间消息
        compressed_middle = self._compress_message_group(middle_messages)
        
        # 合并结果：系统消息 + 最初消息 + 压缩的中间消息 + 最近消息
        result = system_messages + initial_messages + compressed_middle + recent_messages
        
        # 验证压缩效果
        new_tokens = self._count_tokens(result)
        compression_ratio = new_tokens / current_tokens if current_tokens > 0 else 1
        logger.info(f"Compression complete: {current_tokens} -> {new_tokens} tokens ({compression_ratio:.1%})")
        
        return result

    def _truncate_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        截断消息历史，防止上下文长度超限
        
        策略：
        1. 保留系统消息（role="system"）
        2. 按消息组截断，确保 assistant 消息和对应的 tool 消息配对
        3. 保留最近的 N 条消息（由 max_messages 配置）
        4. 截断工具返回的冗长内容（超过 max_tool_content_length 的部分）
        
        Args:
            messages: 原始消息列表
            
        Returns:
            截断后的消息列表
        """
        # 分离系统消息和非系统消息
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        non_system_messages = [msg for msg in messages if msg.get("role") != "system"]
        
        # 如果消息数量未超过限制，只截断工具返回的冗长内容
        if len(non_system_messages) <= self.max_messages:
            result = system_messages.copy()
            for msg in non_system_messages:
                msg_copy = msg.copy()
                # 截断工具返回的冗长内容
                if msg_copy.get("role") == "tool" and isinstance(msg_copy.get("content"), str):
                    content = msg_copy["content"]
                    if len(content) > self.max_tool_content_length:
                        truncated_content = content[:self.max_tool_content_length]
                        msg_copy["content"] = (
                            f"{truncated_content}\n\n[内容已截断：原始长度 {len(content)} 字符，"
                            f"已截断至 {self.max_tool_content_length} 字符]"
                        )
                        logger.warning(
                            f"Truncated tool response from {msg_copy.get('name', 'unknown')}: "
                            f"{len(content)} -> {self.max_tool_content_length} characters"
                        )
                result.append(msg_copy)
            return result
        
        # 如果消息数量超过限制，需要按消息组进行截断
        # 消息组定义：一个 assistant 消息（可能包含 tool_calls）+ 对应的所有 tool 消息 = 一个组
        message_groups = []
        current_group = []
        
        for msg in non_system_messages:
            role = msg.get("role")
            
            if role == "assistant":
                # 如果当前组不为空，先保存它
                if current_group:
                    message_groups.append(current_group)
                # 开始新的组
                current_group = [msg]
            elif role == "tool":
                # tool 消息属于当前组（如果当前组是 assistant 且有 tool_calls）
                if current_group and current_group[0].get("role") == "assistant":
                    # 检查前一个 assistant 消息是否有 tool_calls
                    prev_assistant = current_group[0]
                    if prev_assistant.get("tool_calls"):
                        current_group.append(msg)
                    else:
                        # 如果前一个 assistant 没有 tool_calls，这个 tool 消息是孤立的，需要移除
                        logger.warning(
                            f"Found orphaned tool message without preceding assistant tool_calls, removing it"
                        )
                else:
                    # 如果当前组为空或不是 assistant，这个 tool 消息是孤立的，需要移除
                    logger.warning(
                        f"Found orphaned tool message without preceding assistant message, removing it"
                    )
            else:
                # user 或其他角色的消息，开始新的组
                if current_group:
                    message_groups.append(current_group)
                current_group = [msg]
        
        # 添加最后一个组
        if current_group:
            message_groups.append(current_group)
        
        # 保留最近的 N 个消息组（但确保总消息数不超过 max_messages）
        # 从后往前取组，直到达到限制
        result_messages = []
        total_count = 0
        
        for group in reversed(message_groups):
            group_size = len(group)
            if total_count + group_size <= self.max_messages:
                result_messages.insert(0, group)
                total_count += group_size
            else:
                # 如果加上这个组会超过限制，检查是否可以部分保留
                # 如果组是 assistant + tool 的配对，必须完整保留或完整丢弃
                if group[0].get("role") == "assistant" and group[0].get("tool_calls"):
                    # 这是一个包含 tool_calls 的组，必须完整保留或丢弃
                    # 如果空间不够，就丢弃
                    break
                else:
                    # 其他类型的组，可以部分保留
                    remaining = self.max_messages - total_count
                    if remaining > 0:
                        result_messages.insert(0, group[:remaining])
                    break
        
        # 展平结果
        truncated_messages = []
        for group in result_messages:
            truncated_messages.extend(group)
        
        truncated_count = len(non_system_messages) - len(truncated_messages)
        if truncated_count > 0:
            logger.warning(
                f"Truncated message history: {len(non_system_messages)} -> {len(truncated_messages)} messages "
                f"(removed {truncated_count} old messages, preserved {len(message_groups) - len(result_messages)} message groups)"
            )
        
        # 合并系统消息和截断后的消息，并截断工具返回的冗长内容
        result = system_messages.copy()
        for msg in truncated_messages:
            msg_copy = msg.copy()
            # 截断工具返回的冗长内容
            if msg_copy.get("role") == "tool" and isinstance(msg_copy.get("content"), str):
                content = msg_copy["content"]
                if len(content) > self.max_tool_content_length:
                    truncated_content = content[:self.max_tool_content_length]
                    msg_copy["content"] = (
                        f"{truncated_content}\n\n[内容已截断：原始长度 {len(content)} 字符，"
                        f"已截断至 {self.max_tool_content_length} 字符]"
                    )
                    logger.warning(
                        f"Truncated tool response from {msg_copy.get('name', 'unknown')}: "
                        f"{len(content)} -> {self.max_tool_content_length} characters"
                    )
            result.append(msg_copy)
        
        return result

    def set_trace_context(self, trace_id: str = None, session_id: str = None, user_id: str = None, tags: List[str] = None, metadata: Dict = None):
        """设置Langfuse追踪上下文，用于组织和标识traces
        
        Args:
            trace_id: 追踪ID（可选，如果为None则每次调用自动生成新的trace）
            session_id: 会话ID（用于将多个traces组合在一起）
            user_id: 用户ID（可选）
            tags: 标签列表（可选）
            metadata: 元数据（可选）
        
        Note:
            推荐用法：
            - trace_id=None：让每个Agent调用自动生成独立的trace
            - session_id=plan_id：用session_id关联整个任务的所有traces
            这样在Langfuse中可以看到完整的session replay
        """
        # 保存上下文信息
        self.current_trace_id = trace_id
        self.current_session_id = session_id or trace_id  # session_id默认等于trace_id
        self.current_user_id = user_id
        self.current_tags = tags or []
        self.current_metadata = metadata or {}
        
        if langfuse_enabled and langfuse_client:
            if trace_id:
                # 如果指定了 trace_id，创建固定的 trace 对象（旧模式）
                try:
                    self.langfuse_trace = langfuse_client.trace(
                        id=trace_id,
                        name=f"CoSight-{trace_id[:8]}",
                        session_id=session_id or trace_id,
                        user_id=user_id,
                        tags=tags,
                        metadata=metadata or {}
                    )
                    current_trace_context.set(self.langfuse_trace)
                    logger.info(f"✅ Created fixed Langfuse trace: id={trace_id}, session={session_id}")
                except Exception as e:
                    logger.warning(f"Failed to create Langfuse trace: {e}")
                    self.langfuse_trace = None
            else:
                # 如果没有指定 trace_id，使用 session 模式（推荐）
                # 每次 LLM 调用会自动生成新的 trace，但都关联到同一个 session
                self.langfuse_trace = None  # 不预创建 trace
                logger.info(f"✅ Set Langfuse session mode: session_id={session_id} (traces will be auto-generated)")
        else:
            self.langfuse_trace = None
            logger.info(f"Set trace context: trace_id={trace_id}, session_id={session_id} (Langfuse disabled)")
    
    @time_record
    def create_with_tools(self, messages: List[Dict[str, Any]], tools: List[Dict]):
        """
        Create a chat completion with support for function/tool calls
        """
        # 清洗提示词，去除None
        messages = ChatLLM.clean_none_values(messages)
        
        # 如果使用 thinking mode（deepseek-reasoner 或显式启用），确保历史消息中的 assistant 消息包含 reasoning_content
        use_thinking = self.thinking_mode or "reasoner" in self.model.lower()
        if use_thinking:
            # 为历史消息中的 assistant 消息补充空的 reasoning_content（如果缺失）
            for msg in messages:
                if msg.get("role") == "assistant" and "reasoning_content" not in msg:
                    msg["reasoning_content"] = ""
        
        # 【新增】检查是否需要压缩上下文
        should_compress, current_tokens = self._should_compress_context(messages)
        if should_compress:
            logger.info(f"Triggering context compression (tokens: {current_tokens})...")
            try:
                messages = self._compress_context(messages)
                # 确保压缩后的消息也包含reasoning_content（如果使用thinking mode）
                if use_thinking:
                    for msg in messages:
                        if msg.get("role") == "assistant" and "reasoning_content" not in msg:
                            msg["reasoning_content"] = ""
                            logger.debug(f"Added reasoning_content to compressed message")
            except Exception as e:
                logger.error(f"Context compression failed: {e}, falling back to truncation")
                messages = self._truncate_messages(messages)
        # 如果不需要压缩，保留完整消息，不做任何截断处理
        
        max_retries = 5
        response = None
        for attempt in range(max_retries):
            try:
                # 构建API调用参数
                api_params = {
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": self.temperature
                }
                
                # 如果启用了 thinking mode，添加 extra_body 参数
                if use_thinking:
                    api_params["extra_body"] = {"thinking": {"type": "enabled"}}
                
                # Langfuse 追踪逻辑
                if langfuse_enabled:
                    if self.langfuse_trace:
                        # 固定 trace 模式：手动创建 generation
                        generation = self.langfuse_trace.generation(
                            name=f"LLM-{self.model}",
                            model=self.model,
                            model_parameters={
                                "temperature": self.temperature,
                                "max_tokens": self.max_tokens
                            },
                            input=messages,
                            metadata={
                                "has_tools": True,
                                "tool_count": len(tools),
                                **self.current_metadata
                            }
                        )
                        response = self.client.chat.completions.create(**api_params)
                        if hasattr(response, 'usage'):
                            generation.update(
                                output=response.choices[0].message if response.choices else None,
                                usage={
                                    "input": response.usage.prompt_tokens if response.usage else 0,
                                    "output": response.usage.completion_tokens if response.usage else 0,
                                    "total": response.usage.total_tokens if response.usage else 0
                                }
                            )
                        generation.end()
                    elif self.current_session_id and propagate_attributes:
                        # Session 模式（推荐）：使用 propagate_attributes
                        # 根据官方文档：https://langfuse.com/docs/observability/features/sessions
                        attrs = {"session_id": self.current_session_id}
                        if self.current_user_id:
                            attrs["user_id"] = self.current_user_id
                        if self.current_tags:
                            attrs["tags"] = self.current_tags
                        if self.current_metadata:
                            attrs["metadata"] = self.current_metadata
                        
                        with propagate_attributes(**attrs):
                            response = self.client.chat.completions.create(**api_params)
                    else:
                        # 没有设置 trace 或 session，直接调用
                        response = self.client.chat.completions.create(**api_params)
                else:
                    # Langfuse 未启用，直接调用
                    response = self.client.chat.completions.create(**api_params)
                # 为了避免日志过大，这里不再打印完整响应，只记录一次成功信息
                logger.info("LLM with tools chat completions finished successfully.")
                if hasattr(response, 'choices') and response.choices and len(response.choices) > 0:
                    self.check_and_fix_tool_call_params(response)
                elif hasattr(response, 'message') and response.message:
                    raise Exception(response.message)
                else:
                    raise Exception(response)
                break
            except json.JSONDecodeError as json_error:
                logger.error(f"JSON decode error on attempt {attempt + 1}: {json_error}")
                
                # 更详细的错误信息记录
                response_info = "No response object"
                if response is not None:
                    if hasattr(response, 'content'):
                        response_info = f"Response content: {response.content}"
                    elif hasattr(response, 'text'):
                        response_info = f"Response text: {response.text}"
                    elif hasattr(response, 'choices') and response.choices:
                        try:
                            content = response.choices[0].message.content if response.choices[0].message else "No message content"
                            response_info = f"Response message content: {content[:500]}..." if len(str(content)) > 500 else f"Response message content: {content}"
                        except Exception:
                            response_info = f"Response object: {type(response)} - {str(response)[:500]}..."
                    else:
                        response_info = f"Response object: {type(response)} - {str(response)[:500]}..."
                
                logger.error(f"Response details: {response_info}")
                
                if attempt == max_retries - 1:
                    raise ZaeFrameworkException(400, f"JSON decode error after {max_retries} attempts: {json_error}")
                time.sleep(5)  # 增加等待时间
            except Exception as e:
                error_str = str(e)
                # 检查是否是上下文长度超限错误
                if "maximum context length" in error_str.lower() or "context length" in error_str.lower():
                    logger.warning(
                        f"Context length exceeded on attempt {attempt + 1}. "
                        f"Truncating messages more aggressively..."
                    )
                    # 更激进地截断消息：减少保留的消息数量
                    original_max = self.max_messages
                    self.max_messages = max(5, self.max_messages - 5)  # 每次减少5条，最少保留5条
                    messages = self._truncate_messages(messages)
                    logger.info(
                        f"Reduced max_messages from {original_max} to {self.max_messages}, "
                        f"current message count: {len(messages)}"
                    )
                    # 继续重试
                    time.sleep(2)
                    continue
                
                logger.warning(f"chat with LLM error: {e} on attempt {attempt + 1}, retrying...", exc_info=True)
                if "TPM limit reached" in error_str:
                    time.sleep(60)
                elif "rate limit" in error_str.lower():
                    time.sleep(30)
                elif "timeout" in error_str.lower():
                    time.sleep(10)
                if attempt == max_retries-1:
                    logger.error(f"Failed to create after {max_retries} attempts.")
                    raise ZaeFrameworkException(400, f"chat with LLM failed, please check LLM config. reason：{e}")
                time.sleep(3)  # 增加等待时间，避免频繁重试

        if response and isinstance(response, ChatCompletion):
            # 去除think标签
            content = response.choices[0].message.content
            if content is not None and '</think>' in content:
                response.choices[0].message.content = content.split('</think>')[-1].strip('\n')
            return response.choices[0].message
        else:
            raise ZaeFrameworkException(400, f"chat with LLM failed, LLM response：{response}")

    def check_and_fix_tool_call_params(self, response):
        if response.choices[0].message.tool_calls:
            for attempt in range(3):
                try:
                    tool_call = response.choices[0].message.tool_calls[0].function
                    json.loads(tool_call.arguments)
                    break
                except JSONDecodeError as jsone:
                    logger.warning(f"Tool call arguments JSON decode error on attempt {attempt + 1}: {jsone}")
                    logger.warning(f"Invalid arguments: {tool_call.arguments}")
                    
                    try:
                        # 尝试修复JSON格式
                        fixed_arguments = self.chat_to_llm([{"role": "user",
                                                           "content": f"下面的json字符串格式有错误，请帮忙修正。重要：仅输出修正的字符串。\n{tool_call.arguments}"}])
                        # 验证修复后的JSON是否有效
                        json.loads(fixed_arguments)
                        tool_call.arguments = fixed_arguments
                        logger.info(f"Successfully fixed tool call arguments on attempt {attempt + 1}")
                        break
                    except Exception as fix_error:
                        logger.error(f"Failed to fix tool call arguments on attempt {attempt + 1}: {fix_error}")
                        if attempt == 2:  # 最后一次尝试
                            # 如果修复失败，使用默认的空JSON对象
                            tool_call.arguments = "{}"
                            logger.warning("Using empty JSON object as fallback for tool call arguments")
                            break

    @time_record
    def chat_to_llm(self, messages: List[Dict[str, Any]], max_tokens: int = None):
        # 清洗提示词，去除None
        messages = ChatLLM.clean_none_values(messages)
        
        # 如果使用 thinking mode（deepseek-reasoner 或显式启用），确保历史消息中的 assistant 消息包含 reasoning_content
        use_thinking = self.thinking_mode or "reasoner" in self.model.lower()
        if use_thinking:
            # 为历史消息中的 assistant 消息补充空的 reasoning_content（如果缺失）
            for msg in messages:
                if msg.get("role") == "assistant" and "reasoning_content" not in msg:
                    msg["reasoning_content"] = ""
        
        # 【新增】检查是否需要压缩上下文
        should_compress, current_tokens = self._should_compress_context(messages)
        if should_compress:
            logger.info(f"Triggering context compression (tokens: {current_tokens})...")
            try:
                messages = self._compress_context(messages)
                # 确保压缩后的消息也包含reasoning_content（如果使用thinking mode）
                if use_thinking:
                    for msg in messages:
                        if msg.get("role") == "assistant" and "reasoning_content" not in msg:
                            msg["reasoning_content"] = ""
                            logger.debug(f"Added reasoning_content to compressed message")
            except Exception as e:
                logger.error(f"Context compression failed: {e}, falling back to truncation")
                messages = self._truncate_messages(messages)
        # 如果不需要压缩，保留完整消息，不做任何截断处理
        
        # 构建API调用参数
        api_params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature
        }
        
        # 如果指定了max_tokens，或者实例有max_tokens配置，则使用它
        if max_tokens is not None:
            api_params["max_tokens"] = max_tokens
        elif self.max_tokens is not None:
            api_params["max_tokens"] = self.max_tokens
        
        # 如果启用了 thinking mode，添加 extra_body 参数
        if use_thinking:
            api_params["extra_body"] = {"thinking": {"type": "enabled"}}
        
        # Langfuse 追踪逻辑
        if langfuse_enabled:
            if self.langfuse_trace:
                # 固定 trace 模式
                generation = self.langfuse_trace.generation(
                    name=f"LLM-{self.model}",
                    model=self.model,
                    model_parameters={
                        "temperature": self.temperature,
                        "max_tokens": api_params.get("max_tokens")
                    },
                    input=messages,
                    metadata={
                        "has_tools": False,
                        **self.current_metadata
                    }
                )
                response = self.client.chat.completions.create(**api_params)
                if hasattr(response, 'usage'):
                    generation.update(
                        output=response.choices[0].message if response.choices else None,
                        usage={
                            "input": response.usage.prompt_tokens if response.usage else 0,
                            "output": response.usage.completion_tokens if response.usage else 0,
                            "total": response.usage.total_tokens if response.usage else 0
                        }
                    )
                generation.end()
            elif self.current_session_id and propagate_attributes:
                # Session 模式（推荐）：使用 propagate_attributes
                attrs = {"session_id": self.current_session_id}
                if self.current_user_id:
                    attrs["user_id"] = self.current_user_id
                if self.current_tags:
                    attrs["tags"] = self.current_tags
                if self.current_metadata:
                    attrs["metadata"] = self.current_metadata
                
                with propagate_attributes(**attrs):
                    response = self.client.chat.completions.create(**api_params)
            else:
                response = self.client.chat.completions.create(**api_params)
        else:
            response = self.client.chat.completions.create(**api_params)
        # 为了避免日志过大，这里不再打印完整响应，只记录一次成功信息
        logger.info("LLM chat completions finished successfully.")
        # 去除think标签
        content = response.choices[0].message.content
        if content is not None and '</think>' in content:
            response.choices[0].message.content = content.split('</think>')[-1].strip('\n')

        return response.choices[0].message.content
