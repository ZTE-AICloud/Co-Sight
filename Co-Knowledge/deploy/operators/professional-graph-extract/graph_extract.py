import json
import logging
import os
import re
import time
import uuid
from abc import abstractmethod, ABC
from typing import Dict, Union, Callable, List

from pydantic import BaseModel

from operator_api.graph import GraphChecker
from operator_api.llm import invoke_llm

message_dict = {
    "success": {
        "en": "Operator executed successfully",
        "zh": "算子执行成功"
    },
    "fail": {
        "en": "Operator execution failed",
        "zh": "算子执行错误"
    },
    "chunk_txt_exception": {
        "en": "The file is not a txt file",
        "zh": "文件不是txt文件"
    },
    "chunk2json_exception": {
        "en": "Failed to convert the chunk to json",
        "zh": "文本块内容转json失败"
    },
    "chunk_empty_exception": {
        "en": "The file is empty",
        "zh": "文件为空"
    },
    "empty_schema_exception": {
        "en": "The schema is empty",
        "zh": "schema为空"
    },
    "empty_entity_schema_exception": {
        "en": "The schema's 'entities' field is empty",
        "zh": 'schema中"entities"字段为空'
    },
    "entity_parse_exception": {
        "en": "Failed to parse the entity schema, format error",
        "zh": "解析实体的schema失败, schema格式错误"
    },
    "empty_edge_schema_exception": {
        "en": "The schema's 'edges' field is empty",
        "zh": 'schema中"edge"字段为空'
    },
    "edge_parse_exception": {
        "en": "Failed to parse the edge schema, format error",
        "zh": "解析关系的schema失败, 格式错误"
    },
    "schema_parse_exception": {
        "en": "Failed to parse the schema",
        "zh": "schema解析失败"
    },
    "merge_entity_exception": {
        "en": "Failed to merge entities, type error",
        "zh": "实体合并失败，类型错误"
    },
    "fix_json_exception": {
        "en": "Failed to fix the json format of the llm output",
        "zh": "修正llm输出的json格式失败"
    },
    "validate_json_exception": {
        "en": "Failed to validate the json output of the large model",
        "zh": '校验大模型输出的json操作失败'
    },
    "save_json_exception": {
        "en": "Failed to save the result to jsonl file",
        "zh": "结果存入jsonl文件失败"
    },
    "entity_extraction_retry_exception": {
        "en": "Failed to extract the entity, retry times exceeded",
        "zh": "实体提取失败，重试次数已达上限"
    },
    "edge_extraction_retry_exception": {
        "en": "Failed to extract the edge, retry times exceeded",
        "zh": "关系提取失败，重试次数已达上限"
    },
    "get_schema_exception": {
        "en": "Failed to get the schema",
        "zh": "获取schema中的内容失败"
    },
    "model_name_exception": {
        "en": "The model name is empty",
        "zh": "模型名称为空"
    },
    "error": {
        "en": "Error in operator execution",
        "zh": "算子执行过程中发生错误"
    },
    "merge_entity_properties_exception": {
        "en": "Error in merging entity properties",
        "zh": "合并实体属性时发生错误"
    },
    "no_entity_exception": {
        "en": "No valid entity related to the schema were extracted",
        "zh": "未提取到任何与schema相关的有效实体"
    },
    "get_file_exception": {
        "en": "Failed to get the input files",
        "zh": "未能获取到用户的输入文件"
    },
    "entity_properties_missing_exception": {
        "en": "The entity schema's 'properties' field is empty",
        "zh": '实体schema中"properties"字段为空'
    },
    "entity_schema_properties_exception": {
        "en": "Failed to parse the properties of the entity schema; required fields are missing.",
        "zh": "解析实体schema的属性失败, 缺少必要的字段"
    },
    "entity_schema_property_type_exception": {
        "en": "The entity schema's property type is invalid",
        "zh": "实体schema中的properties的格式必须为list[dict]"
    },
    "edge_schema_properties_exception": {
        "en": "Failed to parse the properties of the edge schema; required fields are missing.",
        "zh": "解析边schema的属性失败, 缺少必要的字段"
    },
    "edge_schema_property_type_exception": {
        "en": "The edge schema's property type is invalid",
        "zh": "边schema中的properties的格式必须为list[dict]"
    },
    "entity_schema_parse_exception": {
        "en": "Failed to parse entity schema; schema format is incorrect",
        "zh": "解析实体schema失败, schema格式错误"
    },
    "edge_schema_parse_exception": {
        "en": "Failed to parse edge schema; schema format is incorrect",
        "zh": "解析边schema失败, schema格式错误"
    },
    "primary_not_found_exception": {
        "en": "Each entity type in the schema must have a primary key",
        "zh": "schema中每一个实体类型都必须有一个主键"
    }
}
ner_system = """ ---目标---
给定一份文本文档和一个JSON Schema，从文本中识别出所需的所有实体类型以及所需的属性信息。

识别出给定实体类型(JSON Schema中的所有的entity_type字段)的所有实体。对于每个识别出的实体，根据实体类型提取对应的属性信息：
JSON Schema 中实体类型以及对应的属性信息如下：
{entity_properties_description}

---JSON Schema结构说明举例---
例如输入的JSON Schema为：
[
    {{
      "entity_type": "Function",
      "entity_desc": "功能",
      "properties": [
        {{
          "name": "name",
          "type": "STRING",
          "desc": "功能名称"
        }},
        {{
          "name": "description",
          "type": "STRING",
          "desc": "功能描述"
        }},
        {{
          "name": "entry_location",
          "type": "STRING",
          "desc": "入口位置"
        }}
      ]
    }},
    {{
      "entity_type": "OperationStep",
      "entity_desc": "操作步骤",
      "properties": [
        {{
          "name": "name",
          "type": "STRING",
          "desc": "操作步骤名称"
        }},
        {{
          "name": "description",
          "type": "STRING",
          "desc": "操作步骤描述"
        }},
        {{
          "name": "step_order",
          "type": "STRING",
          "desc": "步骤顺序"
        }}
      ]
    }}
]

结构说明：
entity_type字段的值即为需要提取的实体类型，上述例子中有Function和OperationStep两个实体类型。
对于Function类型的实体，需要提取name，description，entry_location三个属性信息。
对于OperationStep类型的实体，需要提取name，description，step_order三个属性信息。

---例子---
{example}

---抽取规则---
{rules}

---输出格式---
请将输出格式化为如下 JSON Schema结构：
```json
[{{
    "entity_type": "这里值为具体的实体类型名称",
    "properties": {{
        "这里为实体的属性名": "这里为属性名对应的属性值"
    }}
}}]
```
请确保：
- 不添加任何额外字段或解释性文字。
- 如果原文中没有对应实体的属性内容，请根据JSON Schema中的字段类型填充默认值，避免统一使用空字符串。数值类型(BYTE/SHORT/INTEGER/LONG/FLOAT/DOUBLE)无内容时填0，布尔类型(BOOLEAN)无内容时填false；仅STRING类型可留空字符串。

---输入文本---
{text}

输出：
"""

first_re_system = """---目标---
给定一份文档和文档中出现的实体，根据文档提取出实体之间的关系边。

根据文档和实体列表，识别出实体间所有的关系边，提取以下关系边属性信息：
JSON Schema 中实体类型对应的属性信息如下：
{edge_properties_description}

---JSON Schema结构说明举例---
例如输入的JSON Schema为：
[
    {{
      "edge_type": "Explain",
      "edge_desc": "解释",
      "direction": "one-way",
      "source_entity": "Term",
      "target_entity": "Product",
      "properties": [
        {{
          "name": "explanation_type",
          "type": "STRING",
          "desc": "解释类型"
        }}
      ]
    }},
    {{
      "edge_type": "Contain",
      "edge_desc": "包含",
      "direction": "one-way",
      "source_entity": "Product",
      "target_entity": "Function",
      "properties": [
        {{
          "name": "containment_type",
          "type": "STRING",
          "desc": "包含类型"
        }}
      ]
    }}
]

结构说明：
edge_type字段的值即为需要提取的关系类型，上述例子中有Explain和Contain两个关系类型。
边的指向有严格主宾关系，其中source_entity为主语的实体类型，target_entity为宾语的实体类型。
对于Explain类型的边，需要提取explanation_type这一属性信息。同时该边需要满足主语为Term实体类型，宾语为Product实体类型。
对于OperationStep类型的边，需要提取containment_type这一属性信息。同时该边需要满足主语为Product实体类型，宾语为Function实体类型。

---输出格式---
请将输出格式化为如下 JSON Schema：
```json
[{{
    "edge_type": "关系类型名称",
    "source_id": "源实体ID",
    "target_id": "目标实体ID",
    "properties": {{
        "属性名": "属性值"
    }}
}}]
```
请确保：
- 不添加任何额外字段或解释性文字。
- 如果原文中没有对应实体的属性内容，请根据JSON Schema中的字段类型填充默认值，避免统一使用空字符串。数值类型(BYTE/SHORT/INTEGER/LONG/FLOAT/DOUBLE)无内容时填0，布尔类型(BOOLEAN)无内容时填false；仅STRING类型可留空字符串。


---输入文本---:
{text}

---输入实体---:
{entity_list}

输出：
"""


def _get_message_by_lang(msg_code: str) -> dict:
    return message_dict.get(msg_code, {})


class GraphException(Exception):

    def __init__(self, code) -> None:
        self.code = code

    def get_code(self):
        return self.code


class EntityProperty(BaseModel):
    name: Union[str, int, float]
    type: str
    desc: str
    is_primary: bool
    is_embedding: bool
    is_index: bool


class EdgeProperty(BaseModel):
    name: Union[str, int, float]
    type: str
    desc: str
    is_embedding: bool
    is_index: bool


class Entity(BaseModel):
    entity_type: str
    entity_desc: str
    properties: list[dict]


class Edge(BaseModel):
    edge_type: str
    edge_desc: str
    direction: str
    source_entity: str
    target_entity: str
    properties: list


class SchemaParser(ABC):
    def __init__(self, schema: dict, p: Callable[[str], str] | None = None):
        self.schema = schema
        self.result = {}
        self.p = p or (lambda m: m)

    def parse(self):
        logging.info(self.p(f"Start parsing schema: {self.schema}"))
        if len(self.schema) == 0:
            logging.error(self.p("Schema is empty"))
            raise GraphException(code="empty_schema_exception")

        self.parse_entities()
        self.parse_edges()

        logging.info(self.p(
            f"Schema parsed, entities={len(self.result.get('entities', []))}, edges={len(self.result.get('edges', []))}"))

    def parse_entities(self):
        if "entities" in self.schema:
            logging.info(self.p("Validating entity schema"))
            entities = []
            for entity_data in self.schema["entities"]:
                try:
                    entity_schema = Entity(**entity_data)
                except Exception as e:
                    logging.error(self.p(f"Failed to parse entity schema, error: {e}, entity_data: {entity_data}"))
                    raise GraphException("entity_schema_parse_exception")
                # 校验 properties
                entity_properties = entity_data.get("properties", [])
                if not entity_properties:
                    logging.error(self.p(f"Entity properties are empty, entity_data: {entity_data}"))
                    raise GraphException("entity_properties_missing_exception")
                for prop in entity_properties:
                    try:
                        EntityProperty(**prop)  # 仅校验，构造失败即抛异常
                    except Exception as e:
                        logging.error(self.p(f"Failed to parse entity schema properties, error: {e}, prop: {prop}"))
                        raise GraphException("entity_schema_properties_exception")
                entities.append(entity_schema)
                logging.info(self.p(f"Validated entity schema: {entity_data}"))
            self.result["entities"] = entities
        else:
            logging.error(self.p("Entity schema is empty"))
            raise GraphException("empty_entity_schema_exception")

    def parse_edges(self):
        if "edges" in self.schema:
            logging.info(self.p("Validating edge schema"))
            edges = []
            for edge_data in self.schema["edges"]:
                try:
                    edge_schema = Edge(**edge_data)
                except Exception as e:
                    logging.error(self.p(f"Failed to parse edge schema, error: {e}, edge_data: {edge_data}"))
                    raise GraphException("edge_schema_parse_exception")
                edge_properties = edge_data.get("properties", [])
                if not edge_properties:
                    edges.append(edge_schema)
                    continue
                for prop in edge_properties:
                    try:
                        EdgeProperty(**prop)  # 仅校验，构造失败即抛异常
                    except Exception as e:
                        logging.error(self.p(f"Failed to parse edge schema properties, error: {e}, prop: {prop}"))
                        raise GraphException("edge_schema_properties_exception")
                edges.append(edge_schema)
                logging.info(self.p(f"Validated edge schema: {edge_data}"))
            self.result["edges"] = edges
        else:
            logging.error(self.p("Edge schema is empty"))
            raise GraphException("empty_edge_schema_exception")


class BaseOperator(ABC):

    def __init__(self, chunks: dict, schema: dict, output_dir: str, kwargs: Dict):
        self.chunks = chunks
        self.schema = schema
        self.output_dir = output_dir
        self.kwargs = kwargs

    @abstractmethod
    def operate(self):
        """
        算子处理过程完全开放

        算子执行正常：返回示例:{"code": 0, "message": {"en":"Success", "zh":"成功"}}， output_dir下生成两个文件 , 要求文件名固定：entities.jsonl, edges.jsonl
        算子执行异常：返回示例：{"code":-1, "message": {"en":"{self-defined Fail Reason}", "zh":"{自己定义失败原因}"}}, 此时不需要写jsonl文件
        """

        pass


class LGraphOperator(BaseOperator, ABC):

    def __init__(self, chunks: dict, schema: dict, output_dir: str, kwargs: Dict):
        super().__init__(chunks, schema, output_dir, kwargs)
        self.total_entities = {}
        self.total_edges = {}
        self.id_counter = {}
        self.entity_primary_type_name_dict = {}
        self.entity_primary_keys_list_dict = {}
        self.model = kwargs.get("llm", "")
        self.llm_config = kwargs.get("llmConfig") or None
        self.few_shot = kwargs.get("few_shot", "")
        self.extractRules = kwargs.get("extractRules", "")
        self.entities_schema = {}
        self.edges_schema = {}
        self.edge_direction_dict = {}
        self.total_time = 0
        # 日志前缀：未传入时使用默认值
        self.transaction_id = kwargs.get("transaction_id", "")
        self.prefix = f"[{self.transaction_id}]>>" if self.transaction_id else ""
        self.p = (lambda m: f"{self.prefix}{m}") if self.prefix else (lambda m: m)

        self.embedding_type_name_dict = {}
        self.failed_entity_index = []
        self.failed_edge_index = []
        # 初始化GraphChecker用于校验实体和边
        self.graph_checker = GraphChecker(self.schema)

    def _init_counter_primary_map(self):
        for entity in self.schema["entities"]:
            entity_type = entity["entity_type"]
            self.id_counter[entity_type] = 1
            primary_keys = []
            for property in entity["properties"]:
                if property["is_primary"]:
                    primary_keys.append(property["name"])
                    self.entity_primary_type_name_dict[entity_type] = property["name"]
                if property.get("is_embedding", False):
                    if entity_type not in self.embedding_type_name_dict:
                        self.embedding_type_name_dict[entity_type] = []
                    self.embedding_type_name_dict[entity_type].append(property["name"])
            self.entity_primary_keys_list_dict[entity_type] = primary_keys

        if len(self.entity_primary_type_name_dict) != len(self.schema["entities"]):
            raise GraphException("primary_not_found_exception")

        for edge in self.schema["edges"]:
            edge_type = edge["edge_type"]
            self.id_counter[edge_type] = 1
            for property in edge["properties"]:
                if property.get("is_embedding", False):
                    if edge_type not in self.embedding_type_name_dict:
                        self.embedding_type_name_dict[edge_type] = []
                    self.embedding_type_name_dict[edge_type].append(property["name"])

    def _get_edge_direction(self):
        for edge in self.schema["edges"]:
            self.edge_direction_dict[(edge["source_entity"], edge["target_entity"], edge["edge_type"])] = edge[
                "edge_type"]

    def _get_schema(self):
        try:
            for entity in self.schema['entities']:
                proerties_name_type_dict = {}
                for property in entity['properties']:
                    proerties_name_type_dict[property['name']] = property['type'].lower()
                self.entities_schema[entity['entity_type']] = proerties_name_type_dict
            for edge in self.schema['edges']:
                proerties_name_type_dict = {}
                for property in edge['properties']:
                    proerties_name_type_dict[property['name']] = property['type'].lower()
                self.edges_schema[edge['edge_type']] = proerties_name_type_dict
        except Exception as e:
            logging.error(self.p(f"Failed to get schema content, schema: {self.schema}, error: {e}"))
            raise GraphException("get_schema_exception")

    def operate(self):
        try:
            start_time = time.time()
            if not self.model:
                raise GraphException("model_name_exception")
            # 现在可以通过 logging 使用配置好的日志器
            logging.info(self.p(f"Chunks is {len(self.chunks) if self.chunks else 0}"))

            schema_parser = SchemaParser(self.schema, p=self.p)
            schema_parser.parse()
            self._init_counter_primary_map()
            self._get_schema()
            self._get_edge_direction()

            for index, (chunk_id, content) in enumerate(self.chunks.items()):
                entity_list = self.entity_extraction(content, index, chunk_id)
                if not entity_list:
                    continue
                self.edge_extraction(chunk=content, entity_list=entity_list, chunk_index=index)
            self.save_to_jsonl()
            end_time = time.time()
            logging.info(
                self.p(
                    f"Extract graph finished, entity count={len(self.total_entities)}, edge count={len(self.total_edges)}"))
            logging.info(
                self.p(
                    f"Running time: {end_time - start_time}, Total chunks: {len(self.chunks)}, "
                    f"Total failed entities index: {self.failed_entity_index}, num: {len(self.failed_entity_index)}, "
                    f"Total failed edges index: {self.failed_edge_index}, num: {len(self.failed_edge_index)}"))
        except Exception as e:
            logging.error(self.p(f"Entity extraction failed, error: {e}"))
            raise

    def entity_extraction(self, chunk: str, chunk_index: int, chunk_id: str):
        entity_result = '[]'
        ner_prompt = self.ner_prompt_builder(chunk)
        logging.info(self.p("Starting entity extraction"))
        content = [{"role": "user", "content": ner_prompt}]
        max_retries = 3
        for attempt in range(max_retries):
            try:
                entity_result = invoke_llm(content, self.model, endpoint=self.llm_config)
                logging.info(self.p(f"Entity extraction result: {entity_result}"))
                break
            except RuntimeError as e:
                logging.warning(self.p(f"Entity extraction encountered a RuntimeError, retry {attempt + 1}: {e}"))
                if attempt == max_retries - 1:
                    logging.error(
                        self.p("Entity extraction has reached the maximum number of retries and still failed."))
                    raise GraphException("entity_extraction_exception")
                time.sleep(180)
            except Exception as e:
                logging.exception(e)
                if attempt == max_retries - 1:
                    logging.error(
                        self.p("Entity extraction has reached the maximum number of retries and still failed."))
                    raise GraphException("entity_extraction_exception")
                time.sleep(180)

        valid_entity_result = self._validate_and_clean_content(entity_result)
        if valid_entity_result == "[]":
            self.failed_entity_index.append(chunk_index + 1)

        # logging.info(self.p(f"Final result after JSON format validation: {valid_entity_result}"))

        valid_json_entity_result = json.loads(valid_entity_result)
        valid_json_and_schema_entity_result = self.valid_entity_schema(valid_json_entity_result, chunk_index)
        # logging.info(self.p(f"Final result after entity schema validation: {valid_json_and_schema_entity_result}"))

        result_list = self.create_entity_id(valid_json_and_schema_entity_result, chunk_id)
        logging.info(self.p("End entity extraction"))
        return result_list

    def valid_entity_schema(self, entity_list: list[dict], chunk_index: int) -> list[dict]:
        entities = []
        for idx, entity in enumerate(entity_list):
            entity_type = entity.get("entity_type", "")
            if entity_type not in self.entities_schema:
                logging.warning(self.p(f"Unknown entity type: {entity_type}"))
                continue

            entity_property = entity.get("properties", "")
            if not entity_property:
                continue

            # 使用 GraphChecker 校验并修复实体属性
            entity_def = self.graph_checker.entity_definitions.get(entity_type)
            if not entity_def:
                logging.warning(self.p(f"Entity type '{entity_type}' not found in GraphChecker"))
                continue

            fixed_properties, error = self.graph_checker.validate_and_fix_entity_properties(
                entity['properties'], entity_def, chunk_index
            )
            if error:
                logging.warning(self.p(f"Chunk {chunk_index + 1} entity {idx} property validation failed: {error}"))
                continue

            entity['properties'] = fixed_properties
            entities.append(entity)
        return entities

    def edge_extraction(self, chunk: str, entity_list: list[dict], chunk_index: int = 0):
        entity_list_for_re = []
        for entity in entity_list:
            # 深拷贝实体，避免修改原始实体对象
            entity_copy = json.loads(json.dumps(entity))
            properties = entity_copy.get("properties", {})
            if properties:
                entity_copy["properties"].pop("chunk_id", None)
            entity_list_for_re.append(entity_copy)
        re_prompt = self.re_prompt_builder(chunk, entity_list_for_re)
        logging.info(self.p("Starting relation extraction"))
        content = [{"role": "user", "content": re_prompt}]
        max_retries = 3
        edge_result = "[]"
        for attempt in range(max_retries):
            try:
                edge_result = invoke_llm(content, self.model, endpoint=self.llm_config)
                logging.info(self.p(f"Relation extraction result: {edge_result}"))
                break
            except RuntimeError as e:
                logging.warning(self.p(f"Relation extraction encountered a RuntimeError, retry {attempt + 1}: {e}"))
                if attempt == max_retries - 1:
                    logging.error(self.p("Relation extraction reached max retries and still failed"))
                    raise GraphException("edge_extraction_exception")
                time.sleep(5)
        edge_result = self._validate_and_clean_content(edge_result)
        logging.info(self.p(f"Final result after JSON format validation: {edge_result}"))
        if edge_result == "[]":
            self.failed_edge_index.append(chunk_index + 1)
        edge_list = json.loads(edge_result)
        edge_list = self.valid_edges_schema(edge_list, chunk_index)
        logging.info(self.p(f"Final result after edge schema validation: {edge_list}"))
        self.create_relation_id(edge_list)
        logging.info(self.p("End relation extraction"))

    def valid_edges_schema(self, edge_list: list[dict], chunk_index: int) -> list[dict]:
        edges = []
        for idx, edge in enumerate(edge_list):
            edge_type = edge.get("edge_type", "")
            if edge_type not in self.edges_schema:
                logging.warning(self.p(f"Unknown edge type: {edge_type}"))
                continue

            edge_property = edge.get("properties", "")
            if not self.edges_schema[edge_type] and not edge_property:
                edges.append(edge)
                continue

            # 检查所有 embedding 属性是否都有值
            embedding_properties_keys = self.embedding_type_name_dict.get(edge_type, [])
            if embedding_properties_keys:
                missing_embedding_keys = [key for key in embedding_properties_keys if not edge_property.get(key, "")]
                if missing_embedding_keys:
                    logging.warning(self.p(
                        f"Missing embedding property values for: {', '.join(missing_embedding_keys)}, properties: {edge_property}"))
                    continue

            # 使用 GraphChecker 校验并修复边属性
            edge_def = self.graph_checker.edge_definitions.get(edge_type)
            if not edge_def:
                logging.warning(self.p(f"Edge type '{edge_type}' not found in GraphChecker"))
                continue

            fixed_properties, error = self.graph_checker.validate_and_fix_edge_properties(
                edge['properties'], edge_def, chunk_index
            )
            if error:
                logging.warning(self.p(f"Chunk {chunk_index + 1} edge {idx} property validation failed: {error}"))
                continue

            edge['properties'] = fixed_properties
            edges.append(edge)
        return edges

    def ner_prompt_builder(self, chunk: str) -> str:
        logging.info(self.p("Building NER prompt"))
        entity_schema = []
        for entity in self.schema["entities"]:
            new_entity_schema = {**entity}
            properties_schema = []
            for property in entity['properties']:
                properties_schema.append(
                    {
                        "name": property['name'],
                        "type": property['type'],
                        "desc": property['desc']
                    }
                )
            new_entity_schema['properties'] = properties_schema
            entity_schema.append(new_entity_schema)
        ner_prompt = ner_system.format(
            entity_properties_description=entity_schema,
            example=self.few_shot,
            rules=self.extractRules,
            text=chunk)
        logging.info(self.p(f"NER prompt built {ner_prompt}"))
        return ner_prompt

    def re_prompt_builder(
            self,
            chunk: str,
            entity_list: list[dict],
    ) -> str:

        logging.info(self.p("Building RE prompt"))
        edge_schema = []
        for edge in self.schema["edges"]:
            new_edge_schema = {**edge}
            properties_schema = []
            for property in edge['properties']:
                properties_schema.append(
                    {
                        "name": property['name'],
                        "type": property['type'],
                        "desc": property['desc']
                    }
                )
            new_edge_schema['properties'] = properties_schema
            edge_schema.append(new_edge_schema)

        re_prompt = first_re_system.format(
            edge_properties_description=edge_schema,
            example="",
            text=chunk,
            entity_list=entity_list)
        logging.info(self.p(f"RE prompt built {re_prompt}"))
        return re_prompt

    def create_entity_id(self, entity_list: list[dict], chunk_id: str):
        del_entity = []
        for index, response_entity in enumerate(entity_list):
            entity_type = response_entity.get("entity_type", "")
            entity_properties = response_entity.get("properties", "")
            if entity_type and entity_properties:
                logging.info(self.p(f"Entity type: {entity_type}"))

                primary_properties_keys = self.entity_primary_keys_list_dict.get(
                    entity_type,
                    [self.entity_primary_type_name_dict.get(entity_type, "")],
                )
                embedding_properties_keys = self.embedding_type_name_dict.get(entity_type, [])

                if not primary_properties_keys or not all(primary_properties_keys):
                    del_entity.append(index)
                    logging.warning(self.p(f"primary properties key of {entity_type} is empty"))
                    continue
                # if not embedding_properties_keys:
                #     del_entity.append(index)
                #     logging.warning(self.p(f"embedding properties keys of {entity_type} is empty"))
                #     continue

                primary_properties_value = tuple(
                    entity_properties.get(k, "") for k in primary_properties_keys
                )

                if not all(primary_properties_value):
                    logging.warning(self.p(
                        f"Missing primary property value, keys={primary_properties_keys}, "
                        f"properties: {entity_properties}"
                    ))
                    del_entity.append(index)
                    continue

                # 检查所有 embedding 属性是否都有值
                if embedding_properties_keys:
                    missing_embedding_keys = [key for key in embedding_properties_keys if
                                              not entity_properties.get(key, "")]
                    if missing_embedding_keys:
                        logging.warning(self.p(
                            f"Missing embedding property values for: {', '.join(missing_embedding_keys)}, properties: {entity_properties}"))
                        del_entity.append(index)
                        continue

                if (entity_type, primary_properties_value) in self.total_entities:
                    existing_entity = self.total_entities[(entity_type, primary_properties_value)]
                    merged_entity = self.merge_entity_properties(
                        existing_entity,
                        response_entity,
                        primary_properties_keys,
                    )
                    # 合并 chunk_id，避免以逗号开头和重复
                    existing_chunk_id = merged_entity["properties"].get("chunk_id", "")
                    if existing_chunk_id:
                        # 如果 chunk_id 不在现有值中，则添加
                        if chunk_id not in existing_chunk_id:
                            chunk_id_list = [existing_chunk_id, chunk_id]
                            merged_entity["properties"]["chunk_id"] = ",".join([cid for cid in chunk_id_list if cid])
                    else:
                        merged_entity["properties"]["chunk_id"] = chunk_id
                    self.total_entities[(entity_type, primary_properties_value)] = merged_entity
                    response_entity["entity_id"] = existing_entity["entity_id"]
                else:
                    entity_id = entity_type + "_" + str(self.id_counter[entity_type])
                    self.id_counter[entity_type] += 1
                    response_entity["entity_id"] = entity_id
                    response_entity["properties"]["chunk_id"] = chunk_id
                    self.total_entities[(entity_type, primary_properties_value)] = response_entity
            else:
                logging.warning(self.p(f"Entity type or properties missing: {response_entity}"))
                del_entity.append(index)
                continue
        del_entity.reverse()
        for index in del_entity:
            logging.info(self.p(f"Deleting {len(del_entity)} invalid entities"))
            del entity_list[index]
        return entity_list

    def merge_entity_properties(
            self,
            existing_entity: dict,
            response_entity: dict,
            primary_properties_keys: list,
    ) -> dict:
        """
        Merge properties from response_entity into existing_entity.
        Primary key properties are never overwritten if values differ (safeguard).
        Non-primary properties use 'longer string wins' for string type.
        """
        logging.info(self.p(
            f"Start merging entity properties: existing={existing_entity}\n\nnew={response_entity}"
        ))
        merged_entity = existing_entity.copy()
        merged_entity["properties"] = merged_entity["properties"].copy()
        for property_key, property_value in response_entity["properties"].items():
            if property_key == "chunk_id":
                continue
            if property_key in merged_entity["properties"]:
                existing_value = merged_entity["properties"][property_key]
                if property_key in primary_properties_keys:
                    if existing_value != property_value:
                        logging.warning(self.p(
                            f"Primary key conflict, keeping existing: key={property_key}, "
                            f"existing={existing_value!r}, new={property_value!r}"
                        ))
                        continue
                try:
                    new_value_length, existing_value_length = 0, 0
                    if isinstance(property_value, str):
                        new_value_length = len(property_value)
                    if isinstance(existing_value, str):
                        existing_value_length = len(existing_value)
                    if new_value_length > existing_value_length:
                        merged_entity["properties"][property_key] = property_value
                except (TypeError, ValueError) as e:
                    logging.error(self.p(f"Error merging entity properties: {e}"))
                    raise GraphException("merge_entity_properties_exception")
            else:
                merged_entity["properties"][property_key] = property_value
        logging.info(self.p(f"Entity properties merged: {merged_entity}"))
        return merged_entity

    def create_relation_id(self, edge_dict: list[dict]):
        for edge in edge_dict:
            source_id = edge.get("source_id", "")
            target_id = edge.get("target_id", "")
            edge_type = edge.get("edge_type", "")
            if source_id and target_id and edge_type:
                if (source_id, target_id, edge_type) in self.total_edges:
                    continue
                else:
                    try:
                        source_entity_type = source_id.split("_")[0]
                        target_entity_type = target_id.split("_")[0]
                    except Exception as e:
                        logging.error(self.p(f"Failed to get schema edge types: {source_id}->{target_id}, {e}"))
                        source_entity_type = source_id
                        target_entity_type = target_id
                    if (source_entity_type, target_entity_type, edge_type) in self.edge_direction_dict:
                        edge_type = self.edge_direction_dict[(source_entity_type, target_entity_type, edge_type)]
                    else:
                        logging.warning(self.p(f"egde direction is wrong : {edge}"))
                        continue
                    edge_id = edge_type + "_" + str(self.id_counter[edge_type])
                    self.id_counter[edge_type] += 1
                    edge["edge_id"] = edge_id
                    edge["edge_type"] = edge_type
                    self.total_edges[(source_id, target_id, edge_type)] = edge
            else:
                continue

    def _validate_and_clean_content(self, content: str) -> str:
        try:

            content = content.strip()
            start_idx = content.find('[')
            end_idx = content.rfind(']')

            if start_idx == -1 and end_idx == -1:
                logging.warning(self.p("Response missing both '[' and ']', trying to auto-fix"))
                json_content = '[' + content + ']'
            elif start_idx == -1:
                logging.warning(self.p("Response missing '[', trying to auto-fix"))
                json_content = '[' + content
            elif end_idx == -1:
                logging.warning(self.p("Response missing ']', trying to auto-fix"))
                json_content = content + ']'
            else:
                if start_idx >= end_idx:
                    logging.error(self.p(f"Invalid bracket positions in response: {content}"))
                    # raise GraphException("json")
                    return '[]'
                json_content = content[start_idx:end_idx + 1]

            try:
                json.loads(json_content)
                logging.info(self.p("JSON validation passed"))
                return json_content
            except json.JSONDecodeError as e:
                logging.warning(self.p(f"JSON invalid, trying to fix: {str(e)}"))
                corrected_content = self._fix_json_format(json_content)
                try:
                    json.loads(corrected_content)
                    logging.info(self.p("JSON fixed successfully"))
                    return corrected_content
                except json.JSONDecodeError as e2:
                    logging.error(self.p(f"Failed to fix JSON: {str(e2)}"))
                    # raise GraphException("fix_json_exception")
                    return '[]'
        except Exception as e:
            logging.error(self.p(f"Content validation failed: {str(e)}"))
            # raise GraphException("validate_json_exception")
            return '[]'

    def _fix_json_format(self, json_content: str) -> str:
        json_content = json_content.strip()
        logging.info(self.p("Start enhanced JSON format fixing"))

        # 1. 移除markdown标记
        json_content = re.sub(r'```json\s*', '', json_content)
        json_content = re.sub(r'```\s*$', '', json_content)

        # 2. 处理多余的大括号 - 这是关键修复
        # 检测连续的 {{ 模式
        json_content = re.sub(r'\{\s*\{', '{', json_content)
        # 检测 }} 模式
        json_content = re.sub(r'\}\s*\}', '}', json_content)

        # 3. 处理多余的逗号
        json_content = re.sub(r',\s*}', '}', json_content)
        json_content = re.sub(r',\s*]', ']', json_content)

        # 4. 确保对象之间有逗号分隔
        json_content = re.sub(r'}\s*{', '}, {', json_content)

        # 5. 处理括号不匹配
        brace_count = json_content.count('{') - json_content.count('}')
        bracket_count = json_content.count('[') - json_content.count(']')

        if brace_count > 0:
            json_content += '}' * brace_count
            logging.info(self.p(f"Appended {brace_count} missing '}}'"))
        elif brace_count < 0:
            # 移除多余的大括号
            for _ in range(abs(brace_count)):
                last_brace = json_content.rfind('}')
                if last_brace != -1:
                    json_content = json_content[:last_brace] + json_content[last_brace + 1:]
            logging.info(self.p(f"Removed {abs(brace_count)} extra '}}'"))

        if bracket_count > 0:
            json_content += ']' * bracket_count
            logging.info(self.p(f"Appended {bracket_count} missing ']'"))
        elif bracket_count < 0:
            # 移除多余的方括号
            for _ in range(abs(bracket_count)):
                last_bracket = json_content.rfind(']')
                if last_bracket != -1:
                    json_content = json_content[:last_bracket] + json_content[last_bracket + 1:]
            logging.info(self.p(f"Removed {abs(bracket_count)} extra ']'"))

        # 6. 清理空行和注释
        lines = json_content.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('//') and not line.startswith('#'):
                cleaned_lines.append(line)

        json_content = '\n'.join(cleaned_lines)

        # 7. 确保JSON数组格式正确
        if not json_content.startswith('['):
            json_content = '[' + json_content
        if not json_content.endswith(']'):
            last_brace = json_content.rfind('}')
            if last_brace != -1:
                json_content = json_content[:last_brace + 1] + '\n]'

        logging.info(self.p("Enhanced JSON format fixing completed"))
        return json_content

    def save_to_jsonl(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            logging.info(self.p(f"Created output directory: {self.output_dir}"))
        entity_id = []
        entities_file_path = os.path.join(self.output_dir, "entities.jsonl")
        entity_num = 0
        invalid_entity_count = 0
        try:
            with open(entities_file_path, "w", encoding='utf-8') as f:
                for entity in self.total_entities.values():
                    # 使用GraphChecker校验实体
                    is_valid, error_msg = self.graph_checker.check_entity_data(entity)
                    # pattern = r"Property '[^']*' cannot be empty"
                    # if re.search(pattern, error_msg):
                    #     is_valid = True
                    if not is_valid:
                        invalid_entity_count += 1
                        logging.warning(self.p(
                            f"Entity validation failed, skipping: {error_msg}, entity_id: {entity.get('entity_id', 'unknown')}"))
                        continue
                    entity_id.append(entity['entity_id'])
                    f.write(json.dumps(entity, ensure_ascii=False) + "\n")
                    entity_num += 1
                logging.info(self.p(
                    f"Saved {entity_num} entities to: {entities_file_path}, skipped {invalid_entity_count} invalid entities"))

            edges_file_path = os.path.join(self.output_dir, "edges.jsonl")
            edge_num = 0
            invalid_edge_count = 0
            with open(edges_file_path, "w", encoding='utf-8') as f:
                for edge in self.total_edges.values():
                    # 检查边的源实体和目标实体是否存在
                    if (edge.get('source_id') not in entity_id) or (edge.get('target_id') not in entity_id):
                        invalid_edge_count += 1
                        logging.warning(self.p(f"Edge source or target entity not found: {edge}"))
                        continue
                    # 使用GraphChecker校验边
                    is_valid, error_msg = self.graph_checker.check_edge_data(edge)
                    # pattern = r"Property '[^']*' cannot be empty"
                    # if re.search(pattern, error_msg):
                    #     is_valid = True
                    if not is_valid:
                        invalid_edge_count += 1
                        logging.warning(self.p(
                            f"Edge validation failed, skipping: {error_msg}, edge_id: {edge.get('edge_id', 'unknown')}"))
                        continue
                    f.write(json.dumps(edge, ensure_ascii=False) + "\n")
                    edge_num += 1
                logging.info(
                    self.p(f"Saved {edge_num} edges to: {edges_file_path}, skipped {invalid_edge_count} invalid edges"))
        except Exception as e:
            logging.exception(self.p(str(e)))
            raise GraphException("save_json_exception")
        if entity_num == 0:
            raise GraphException("no_entity_exception")


class Chapter:

    def __init__(self, title: str, level: int, start_line: int, end_line: int, content: str):
        self.title = title
        self.level = level
        self.start_line = start_line
        self.end_line = end_line
        self.content = content

    def __repr__(self):
        return f"Chapter(title='{self.title}', level={self.level})"


class ChapterChunker:

    def __init__(self, chunk_size):

        self.title_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        self.chunk_size = chunk_size

    def parse_chapters(self, text: str) -> List[Chapter]:

        lines = text.split('\n')
        chapters = []
        title_stack = []
        start = 0

        # 先收集开头的非标题文本
        prefix_text_start = 0
        while prefix_text_start < len(lines):
            match = self.title_pattern.match(lines[prefix_text_start])
            if match:
                break
            prefix_text_start += 1

        # 如果开头有非标题文本，创建一个章节包含这些文本
        if prefix_text_start > 0:
            prefix_content = '\n'.join(lines[:prefix_text_start]).strip()
            if prefix_content:
                chapter = Chapter(
                    title="",
                    level=0,
                    start_line=0,
                    end_line=prefix_text_start,
                    content=prefix_content
                )
                chapters.append(chapter)

        # 从第一个标题开始处理
        start = prefix_text_start
        while start < len(lines):

            start_line = start
            match = self.title_pattern.match(lines[start])
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                while title_stack and title_stack[-1][1] >= level:
                    title_stack.pop()
                title_stack.append((title, level))

                total_content = ""
                for j in range(start + 1, len(lines)):
                    next_match = self.title_pattern.match(lines[j])
                    if next_match:
                        start = j
                        total_content = '\n'.join(lines[start_line:j])
                        if len(next_match.group(1)) == 1:
                            break
                        next_level = len(next_match.group(1))
                        start = j
                        if len(total_content) > self.chunk_size:
                            break
                        else:
                            if title_stack and title_stack[-1][1] > next_level:
                                break
                            while title_stack and title_stack[-1][1] == next_level:
                                title_stack.pop()
                            title_stack.append((next_match.group(2).strip(), next_level))

                if total_content == "":
                    content = '\n'.join(lines[start_line:])
                    end_line = len(lines)
                    start = len(lines)
                else:
                    content = total_content
                    end_line = start_line + len(content)
                parent_titles = []
                content_level = content.split('\n')[0].count('#')
                for stack_title, stack_level in title_stack:
                    if stack_level < content_level:
                        parent_titles.append((stack_title, stack_level))

                if level != 1:
                    parent_headers = []
                    for parent_title, parent_level in parent_titles:
                        header_mark = '#' * parent_level
                        parent_headers.append(f"{header_mark} {parent_title}")

                    # 在内容前面添加所有父级标题
                    parent_header_text = '\n'.join(parent_headers) + '\n\n'
                    content = parent_header_text + content
                if start_line == end_line:
                    break
                chapter = Chapter(
                    title=title,
                    level=level,
                    start_line=start_line,
                    end_line=end_line,
                    content=content
                )
                chapters.append(chapter)
            else:
                start += 1

        return chapters

    def chunk_file(self, file_path: str) -> List[Chapter]:

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()

        return self.parse_chapters(text)

    def chunk_text(self, text: str) -> List[str]:
        """
        切分文本为章节块

        Args:
            text: 需要切分的文本内容（字符串）

        Returns:
            切分后的文本块列表，每个元素是字符串类型的文本内容
        """
        chapters = self.parse_chapters(text)
        return [chapter.content for chapter in chapters]


def get_chapter_chunks(file_path: str, chunk_size: int, p):
    try:
        output_dir = os.path.join(file_path, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "document_chunk.jsonl")
        md_names = []
        base_path = os.path.join(file_path, "input")
        input_files = os.listdir(base_path)
        for file_name in input_files:
            if file_name.endswith(".md"):
                md_names.append(file_name)
        if len(input_files) == len(md_names):
            result = {}
            chunk_id = 0
            with open(output_path, "w", encoding="utf-8") as out_f:
                for md_name in md_names:
                    md_path = os.path.join(base_path, md_name)
                    with open(md_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    chunker = ChapterChunker(chunk_size)
                    chunks = chunker.chunk_text(content)
                    for chunk in chunks:
                        chunk_uuid = str(uuid.uuid4())
                        item = {
                            "chunk_index": "",
                            "source": md_name,
                            "content_expand": chunk,
                            "chunk_id": chunk_id,
                            "type": 0,
                            "picf_info": {},
                            "id": chunk_uuid
                        }
                        out_f.write(json.dumps(item, ensure_ascii=False) + "\n")
                        chunk_id += 1
                        result[chunk_uuid] = chunk
            out_f.close()
            logging.info(p(f"按章节切分后得到 {len(result)} 个块"))
            return result
        else:
            chunks = {}
            table = ""
            chunk_id = set()
            jsonl_path = os.path.join(file_path, "output/document_chunk.jsonl")
            with open(jsonl_path, "r", encoding='utf-8') as f:
                for idx, line in enumerate(f):
                    try:
                        data = json.loads(line)
                        if "content_expand" in data and "id" in data:
                            if "label" in data and data["label"] == "table":
                                table += data.get("content_expand", "")
                                chunk_id.add(data["id"])
                            else:
                                if table:
                                    chunk_id_str = ",".join(list(chunk_id))
                                    chunks[chunk_id_str] = table
                                    chunk_id = set()
                                    table = ""
                                else:
                                    chunks[data["id"]] = data["content_expand"]
                        else:
                            logging.warning(p(f"Missing required fields 'content_expand' or 'id' in block {idx + 1}"))
                    except Exception:
                        logging.error(p(f"Failed to parse line {idx + 1} into JSON: {line}"))
                        raise GraphException(code="chunk2json_exception")

            if table:
                chunk_id_str = ",".join(list(chunk_id))
                chunks[chunk_id_str] = table
                logging.info(p(f"Saving table content at the end of the file, chunk_id: {chunk_id_str}"))
            return chunks
    except GraphException as e:
        logging.error(p(f"get input files failed : {e}"))
        raise GraphException("get_file_exception")


def _redact_llm_config(kwargs):
    """日志里不打印端点 key：``llmConfig`` 由平台下发（见 operator_api.llm）。"""
    if not isinstance(kwargs, dict):
        return kwargs
    config = kwargs.get("llmConfig")
    if not isinstance(config, dict) or not config.get("api_key"):
        return kwargs
    safe = dict(kwargs)
    safe["llmConfig"] = {**config, "api_key": "***"}
    return safe


def graph_extract(file_path: str, schema: dict, lang: str, transaction_id: str = "", kwargs: Dict = None):
    kwargs.setdefault("transaction_id", transaction_id)
    prefix = f"[{transaction_id}]>>" if transaction_id else ""
    p = (lambda m: f"{prefix}{m}") if prefix else (lambda m: m)
    try:
        if kwargs is None:
            kwargs = {}
        logging.info(p(f'Start to extract graph, file_path={file_path}, lang={lang}, kwargs={_redact_llm_config(kwargs)}'))

        chunk_size = kwargs.get("chapterChunkSize", 8000)
        if isinstance(chunk_size, str):
            chunk_size = int(chunk_size)
        chunks = get_chapter_chunks(file_path, chunk_size, p)
        if not chunks:
            raise GraphException(code="chunk_empty_exception")
        operator = LGraphOperator(chunks, schema, file_path, kwargs)
        operator.operate()
        logging.info(p('End to extract graph, Success'))
        success_message = _get_message_by_lang("success")
        return {"code": 0, "message": success_message}
    except GraphException as e:
        logging.exception(p(str(e)))
        exception_msg = _get_message_by_lang(e.get_code())
        return {"code": "-1", "message": exception_msg}
    except Exception as e:
        logging.exception(p(str(e)))
        exception_msg = _get_message_by_lang("error")
        return {"code": "-1", "message": exception_msg}
