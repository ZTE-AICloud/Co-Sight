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

from mcp import Tool as MCPTool
from app.agent_dispatcher.infrastructure.entity.exception.error_code_consts import MCP_ERROR

from app.agent_dispatcher.infrastructure.entity.exception.ZaeFrameworkException import \
    NaeFrameworkException

from app.agent_dispatcher.domain.plan.action.skill.mcp.server import MCPServerStdio, MCPServerSse

mcp_servers = []


class MCPEngine:

    @staticmethod
    def get_server(name, config):
        if "command" in config:
            return MCPServerStdio(name, config, True)
        elif "url" in config:
            return MCPServerSse(name, config, True)
        else:
            raise NaeFrameworkException(MCP_ERROR, "This transport type is not supported.")

    @staticmethod
    async def get_mcp_tools(name, config) -> list[MCPTool]:
        """Get all function tools from a single MCP server."""
        server = None
        try:
            server = MCPEngine.get_server(name, config)
            await server.connect()
            tools = await server.list_tools()
            return tools
        except Exception as e:
            print(f"Error invoking MCP tool {name}: {e}")
            return []
        finally:
            if server:
                await server.cleanup()

    @staticmethod
    async def invoke_mcp_tool(name, config, tool_name, input_json: dict = {}):
        """Invoke an MCP tool and return the result as a string."""
        server = None
        try:
            server = MCPEngine.get_server(name, config)
            await server.connect()
            result = await server.call_tool(tool_name, input_json)
        except Exception as e:
            print(f"Error invoking MCP tool {tool_name}: {e}")
            raise NaeFrameworkException(MCP_ERROR, f"Error invoking MCP tool {tool_name}")
        finally:
            if server:
                await server.cleanup()

        # The MCP tool result is a list of content items, whereas OpenAI tool outputs are a single
        # string. We'll try to convert.
        content = result.content
        if content:
            tool_output_list = []
            for item in content:
                if item.type == "text":
                    tool_output_list.append(item.text)
                else:
                    tool_output_list.append(item.model_dump())
            tool_output = ";".join(tool_output_list)
        else:
            print(f"Errored MCP tool result: {result}")
            tool_output = "Error running tool."

        return tool_output