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

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class Value(BaseModel):
    type: str
    text: str
    nodeId: Optional[str] = None


class Props(BaseModel):
    required: Optional[bool] = None
    description: Optional[Dict[str, Any]] = None
    defaultValue: Optional[str] = None
    maxLength: Optional[int] = None
    minValue: Optional[str] = None
    maxValue: Optional[str] = None
    options: Optional[List[str]] = None


class Parameter(BaseModel):
    name: str
    type: str
    category: Optional[str] = None
    elementType: Optional[str] = None
    props: Optional[Props] = None
    value: Optional[Value] = None
    items: Optional[List['Parameter']] = None


class Parameters(BaseModel):
    inputs: Optional[List[Parameter]] = Field(default_factory=list)
    outputs: Optional[List[Parameter]] = Field(default_factory=list)
    runParameters: Optional[Dict[str, Any]] = Field(default_factory=dict)


class Position(BaseModel):
    x: int
    y: int


class NodeProps(BaseModel):
    title: Optional[Dict[str, str]] = None
    description: Optional[Dict[str, str]] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    position: Optional[Position] = None


class Edge(BaseModel):
    sourceNodeId: str
    targetNodeId: str
    sourcePortId: Optional[str] = None
    targetPortId: Optional[str] = None


class Node(BaseModel):
    id: str
    code: str
    props: Optional[Dict[str, Any]] = None
    parameters: Optional[Dict[str, Any]] = None
    childNodes: Optional[List[Any]] = None
    edges: Optional[List[Any]] = None


class SchemaProps(BaseModel):
    ignore_status_transfer: Optional[bool] = False


class Schema(BaseModel):
    nodes: Optional[List[Node]] = None
    edges: Optional[List[Edge]] = None
    props: Optional[SchemaProps] = None


class SkillsOrchestration(BaseModel):
    id: Optional[str] = None
    workflowId: Optional[str] = None
    title: Optional[Dict[str, str]] = None
    description: Dict[str, str] = Field(default_factory=dict)
    version: Optional[str] = None
    bussinessId: Optional[str] = None
    tags: Optional[List[Any]] = None
    schema: Optional[Schema] = None
    createBy: Optional[str] = None
    createDate: Optional[str] = None
    lastUpdateBy: Optional[str] = None
    lastUpdateDate: Optional[str] = None
    type: Optional[str] = None
    status: Optional[int] = None

    def get_node_configs(self) -> List[Any]:
        """获取节点配置列表"""
        node_configs = []
        if self.schema and self.schema.nodes:
            edges = self.schema.edges if self.schema.edges else []
            for node in self.schema.nodes:
                node_config = NodeConfig(
                    id=node.id,
                    node=node,
                    edges=[edge for edge in edges if edge.sourceNodeId == node.id]
                )
                node_configs.append(node_config)
        return node_configs


class NodeConfig(BaseModel):
    id: str
    node: Node
    edges: List[Edge]


Parameter.update_forward_refs()
Node.update_forward_refs()
