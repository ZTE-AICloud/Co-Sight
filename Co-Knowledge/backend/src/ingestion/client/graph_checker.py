"""
知识图谱数据检查

用于验证实体数据和关系数据是否符合知识图谱定义的检查工具
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple


class GraphChecker:
    """知识图谱检查器"""

    def __init__(self, schema: Dict[str, Any]):
        """
        初始化检查器

        Args:
            schema: 知识图谱 schema 定义，包含 entities 和 edges
        """
        self.schema = schema
        self.entity_definitions = {}
        self.edge_definitions = {}

        # 解析实体定义
        if 'entities' in schema:
            for entity in schema['entities']:
                entity_type = entity.get('entity_type')
                if entity_type:
                    self.entity_definitions[entity_type] = entity

        # 解析边定义
        if 'edges' in schema:
            for edge in schema['edges']:
                edge_type = edge.get('edge_type')
                if edge_type:
                    self.edge_definitions[edge_type] = edge

    def _validate_non_empty_string(self, value: Any, field_name: str) -> Optional[str]:
        if value is None:
            return f"{field_name} cannot be empty"
        if not isinstance(value, str):
            return f"{field_name} must be a string, got {type(value).__name__}"
        if value.strip() == '':
            return f"{field_name} cannot be empty"
        return None

    def _validate_id_prefix(self, id_value: str, id_type: str, field_name: str) -> Optional[str]:
        expected_prefix = f"{id_type}_"
        if not id_value.startswith(expected_prefix):
            return f"{field_name} value must start with '{expected_prefix}'"
        return None

    def _validate_properties_field_count(self, properties: Dict[str, Any],
                                         expected_prop_names: set,
                                         exclude_chunk_id: bool = False) -> Optional[str]:
        actual_prop_names = set(properties.keys())
        if exclude_chunk_id and 'chunk_id' not in expected_prop_names:
            actual_prop_names = actual_prop_names - {'chunk_id'}

        if expected_prop_names != actual_prop_names:
            missing = expected_prop_names - actual_prop_names
            extra = actual_prop_names - expected_prop_names
            errors = []
            if missing:
                errors.append(f"Missing properties: {', '.join(missing)}")
            if extra:
                errors.append(f"Extra properties: {', '.join(extra)}")
            return f"Property fields mismatch: {'; '.join(errors)}"
        return None

    def _validate_property_value(self, prop_name: str, prop_value: Any,
                                 prop_def: Dict[str, Any]) -> Optional[str]:
        is_primary = prop_def.get('is_primary', False)
        prop_type = (prop_def.get('type') or '').upper()

        # 主键属性不能为空（不能是 None，也不能是空字符串）
        if is_primary:
            if prop_value is None or (isinstance(prop_value, str) and prop_value.strip() == ''):
                return f"Primary key property '{prop_name}' cannot be empty"

        # 非主键属性：允许为空字符串，但默认不允许为 None（None 表示字段不存在）
        if not is_primary:
            if prop_value is None:
                if prop_type in {'DATE', 'DATETIME'}:
                    return None
                return f"Property '{prop_name}' cannot be None"
            # 空字符串是允许的，直接返回 None 表示验证通过

        return None

    def validate_and_fix_entity_properties(
            self,
            properties: Dict[str, Any],
            entity_def: Dict[str, Any],
            chunk_index: int = 0
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        校验并修复实体属性值，确保类型匹配。

        Args:
            properties: 实体属性字典
            entity_def: 实体定义（包含 properties 数组）
            chunk_index: chunk 索引，用于日志

        Returns:
            (修复后的属性字典, 错误信息，如果没有错误则错误信息为 None)
        """
        expected_props = entity_def.get('properties', [])
        prop_def_map = {prop['name']: prop for prop in expected_props}

        fixed_properties = {}

        for prop_name, prop_value in properties.items():
            if prop_name == 'chunk_id':
                fixed_properties[prop_name] = prop_value
                continue

            if prop_name not in prop_def_map:
                # 跳过不在 schema 中定义的额外属性
                continue

            prop_def = prop_def_map[prop_name]
            fixed_value, error = self.validate_and_fix_property_value(
                prop_name, prop_value, prop_def, chunk_index, is_entity=True
            )
            if error:
                return {}, error
            fixed_properties[prop_name] = fixed_value

        # 检查缺失的属性并填默认值
        for prop_def in expected_props:
            prop_name = prop_def['name']
            if prop_name not in fixed_properties:
                prop_type = (prop_def.get('type') or '').upper()
                is_primary = prop_def.get('is_primary', False)
                if is_primary:
                    return {}, f"Chunk {chunk_index + 1} entity missing primary key property '{prop_name}'"
                default_val = self._default_value_for_type(prop_type)
                logging.warning(
                    f"Chunk {chunk_index + 1} entity missing property '{prop_name}', "
                    f"using schema default {repr(default_val)}")
                fixed_properties[prop_name] = default_val

        return fixed_properties, None

    def validate_and_fix_edge_properties(
            self,
            properties: Dict[str, Any],
            edge_def: Dict[str, Any],
            chunk_index: int = 0
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        校验并修复边属性值，确保类型匹配。

        Args:
            properties: 边属性字典
            edge_def: 边定义（包含 properties 数组）
            chunk_index: chunk 索引，用于日志

        Returns:
            (修复后的属性字典, 错误信息，如果没有错误则错误信息为 None)
        """
        expected_props = edge_def.get('properties', [])
        prop_def_map = {prop['name']: prop for prop in expected_props}

        fixed_properties = {}

        for prop_name, prop_value in properties.items():
            if prop_name not in prop_def_map:
                # 跳过不在 schema 中定义的额外属性
                continue

            prop_def = prop_def_map[prop_name]
            fixed_value, error = self.validate_and_fix_property_value(
                prop_name, prop_value, prop_def, chunk_index, is_entity=False
            )
            if error:
                return {}, error
            fixed_properties[prop_name] = fixed_value

        # 检查缺失的属性并填默认值
        for prop_def in expected_props:
            prop_name = prop_def['name']
            if prop_name not in fixed_properties:
                prop_type = (prop_def.get('type') or '').upper()
                default_val = self._default_value_for_type(prop_type)
                logging.warning(
                    f"Chunk {chunk_index + 1} edge missing property '{prop_name}', "
                    f"using schema default {repr(default_val)}")
                fixed_properties[prop_name] = default_val

        return fixed_properties, None

    def _validate_entity_type(self, entity_data: Dict[str, Any]) -> Tuple[Optional[Dict], Optional[str]]:
        if 'entity_type' not in entity_data:
            return None, "Entity data missing 'entity_type' field"

        entity_type = entity_data['entity_type']
        if entity_type not in self.entity_definitions:
            return None, f"Entity type '{entity_type}' is not defined in schema"

        return self.entity_definitions[entity_type], None

    def _validate_entity_id(self, entity_data: Dict[str, Any], entity_type: str) -> Optional[str]:
        if 'entity_id' not in entity_data:
            return "Entity data missing required 'entity_id' field"

        entity_id = entity_data['entity_id']
        error = self._validate_non_empty_string(entity_id, "Entity 'entity_id'")
        if error:
            return error

        return self._validate_id_prefix(entity_id, entity_type, "Entity 'entity_id'")

    def _validate_chunk_id(self, properties: Dict[str, Any]) -> Optional[str]:
        if 'chunk_id' not in properties:
            return "Entity data missing required 'chunk_id' field"

        chunk_id = properties.get('chunk_id')
        return self._validate_non_empty_string(chunk_id, "Entity 'chunk_id'")

    def _validate_entity_properties(self, properties: Dict[str, Any],
                                    entity_def: Dict[str, Any]) -> Optional[str]:
        expected_props = entity_def.get('properties', [])
        expected_prop_names = {prop['name'] for prop in expected_props}

        error = self._validate_properties_field_count(
            properties, expected_prop_names, exclude_chunk_id=True
        )
        if error:
            return error

        prop_def_map = {prop['name']: prop for prop in expected_props}

        for prop_name, prop_value in properties.items():
            if prop_name == 'chunk_id' and 'chunk_id' not in prop_def_map:
                continue

            if prop_name not in prop_def_map:
                return f"Property '{prop_name}' is not defined in schema"

            prop_def = prop_def_map[prop_name]
            error = self._validate_property_value(prop_name, prop_value, prop_def)
            if error:
                return error

        return None

    def _validate_edge_type(self, edge_data: Dict[str, Any]) -> Tuple[Optional[Dict], Optional[str]]:
        if 'edge_type' not in edge_data:
            return None, "Edge data missing 'edge_type' field"

        edge_type = edge_data['edge_type']
        if edge_type not in self.edge_definitions:
            return None, f"Edge type '{edge_type}' is not defined in schema"

        return self.edge_definitions[edge_type], None

    def _validate_edge_id(self, edge_data: Dict[str, Any], edge_type: str) -> Optional[str]:
        if 'edge_id' not in edge_data:
            return "Edge data missing required 'edge_id' field"

        edge_id = edge_data['edge_id']
        error = self._validate_non_empty_string(edge_id, "Edge 'edge_id'")
        if error:
            return error

        return self._validate_id_prefix(edge_id, edge_type, "Edge 'edge_id'")

    def _validate_source_target_id(self, edge_data: Dict[str, Any], field_name: str) -> Optional[str]:
        if field_name not in edge_data:
            return f"Edge data missing required '{field_name}' field"

        id_value = edge_data[field_name]
        return self._validate_non_empty_string(id_value, f"Edge '{field_name}'")

    def _validate_edge_properties(self, properties: Dict[str, Any],
                                  edge_def: Dict[str, Any]) -> Optional[str]:
        expected_props = edge_def.get('properties', [])
        expected_prop_names = {prop['name'] for prop in expected_props}

        error = self._validate_properties_field_count(
            properties, expected_prop_names, exclude_chunk_id=False
        )
        if error:
            return error

        prop_def_map = {prop['name']: prop for prop in expected_props}

        for prop_name, prop_value in properties.items():
            if prop_name not in prop_def_map:
                return f"Property '{prop_name}' is not defined in schema"

            prop_def = prop_def_map[prop_name]
            error = self._validate_property_value(prop_name, prop_value, prop_def)
            if error:
                return error

        return None

    def check_entity_data(self, entity_data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        检查实体数据是否符合知识图谱定义

        检验规则：
        1. entity_type: 必须存在且在 schema 中定义
        2. entity_id: 必须存在于根级别，且值必须以 {entity_type}_ 开头，不能为空
        3. properties: 必须存在
        4. chunk_id: 必须在 properties 中存在且不为空（默认必需字段）
        5. 属性字段个数: 必须与 schema 定义完全匹配（chunk_id 除外，如果不在 schema 中定义）
        6. 属性字段定义: 所有属性必须在 schema 中定义
        7. 属性值验证:
           - 主键属性 (is_primary=True) 不能为空（不能是 None，也不能是空字符串）
           - 非主键属性允许为空字符串（""），但不允许为 None

        Args:
            entity_data: 实体数据，应包含 entity_type、entity_id 和 properties

        Returns:
            (is_valid, error_message): 检查结果和错误信息
        """
        entity_def, error = self._validate_entity_type(entity_data)
        if error:
            return False, error

        entity_type = entity_data['entity_type']
        error = self._validate_entity_id(entity_data, entity_type)
        if error:
            return False, error

        if 'properties' not in entity_data:
            return False, "Entity data missing 'properties' field"

        properties = entity_data['properties']
        error = self._validate_chunk_id(properties)
        if error:
            return False, error

        error = self._validate_entity_properties(properties, entity_def)
        if error:
            return False, error

        return True, None

    def check_edge_data(self, edge_data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        检查关系数据是否符合知识图谱定义

        检验规则：
        1. edge_type: 必须存在且在 schema 中定义
        2. edge_id: 必须存在于根级别，且值必须以 {edge_type}_ 开头，不能为空
        3. source_id: 必须存在于根级别，不能为空
        4. target_id: 必须存在于根级别，不能为空
        5. properties: 必须存在
        6. 属性字段个数: 必须与 schema 定义完全匹配
        7. 属性字段定义: 所有属性必须在 schema 中定义
        8. 属性值验证:
           - 主键属性 (is_primary=True) 不能为空（不能是 None，也不能是空字符串）
           - 非主键属性允许为空字符串（""），但不允许为 None

        Args:
            edge_data: 关系数据，应包含 edge_type、edge_id、source_id、target_id 和 properties

        Returns:
            (is_valid, error_message): 检查结果和错误信息
        """
        edge_def, error = self._validate_edge_type(edge_data)
        if error:
            return False, error

        edge_type = edge_data['edge_type']
        error = self._validate_edge_id(edge_data, edge_type)
        if error:
            return False, error

        error = self._validate_source_target_id(edge_data, 'source_id')
        if error:
            return False, error

        error = self._validate_source_target_id(edge_data, 'target_id')
        if error:
            return False, error

        if 'properties' not in edge_data:
            return False, "Edge data missing 'properties' field"

        properties = edge_data['properties']
        error = self._validate_edge_properties(properties, edge_def)
        if error:
            return False, error

        return True, None

    # ==================== 类型转换和默认值填充方法 ====================

    def _default_value_for_type(self, type_name: str) -> Any:
        """根据类型返回默认值"""
        if not type_name:
            return ""
        normalized = type_name.upper()
        if normalized == "STRING":
            return ""
        if normalized in {"BYTE", "SHORT", "INTEGER", "LONG"}:
            return 0
        if normalized == "FLOAT":
            return 0.0
        if normalized == "DOUBLE":
            return 0.0
        if normalized == "BOOLEAN":
            return False
        if normalized == "DATE":
            return None
        if normalized == "DATETIME":
            return None
        if normalized in {"EMBEDDEDLIST", "EMBEDDEDSET", "LINKLIST", "LINKSET"}:
            return []
        if normalized in {"EMBEDDEDMAP", "LINKMAP"}:
            return {}
        if normalized == "EMBEDDED":
            return {}
        if normalized == "BINARY":
            return ""
        if normalized == "LINK":
            return ""
        return ""

    def _default_value_is_non_string(self, type_name: str) -> bool:
        """Return True if the schema type uses a non-string default (e.g. numeric, boolean)."""
        if not type_name:
            return False
        normalized = type_name.upper()
        return normalized in {"BYTE", "SHORT", "INTEGER", "LONG", "FLOAT", "DOUBLE", "BOOLEAN"}

    def _is_value_match_type(self, value: Any, type_name: str) -> bool:
        """检查值是否与类型匹配（已转换后的值）"""
        if value is None:
            return True
        if not type_name:
            return True
        normalized = type_name.upper()
        if normalized == "STRING":
            return isinstance(value, str)
        if normalized in {"BYTE", "SHORT", "INTEGER", "LONG"}:
            return isinstance(value, int) and not isinstance(value, bool)
        if normalized in {"FLOAT", "DOUBLE"}:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if normalized == "BOOLEAN":
            return isinstance(value, bool)
        return True

    def _try_convert_to_int(self, value: Any) -> Tuple[Optional[int], bool]:
        """尝试将值转换为整数类型，返回 (转换后的值, 是否需要填默认值)"""
        try:
            if isinstance(value, bool):
                return int(value), False
            if isinstance(value, (int, float)):
                return int(value), False
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    return None, True
                return int(float(value)), False
        except (ValueError, TypeError):
            pass
        return None, True

    def _try_convert_to_float(self, value: Any) -> Tuple[Optional[float], bool]:
        """尝试将值转换为浮点数类型，返回 (转换后的值, 是否需要填默认值)"""
        try:
            if isinstance(value, bool):
                return float(value), False
            if isinstance(value, (int, float)):
                return float(value), False
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    return None, True
                return float(value), False
        except (ValueError, TypeError):
            pass
        return None, True

    def _try_convert_to_bool(self, value: Any) -> Tuple[Optional[bool], bool]:
        """尝试将值转换为布尔类型，返回 (转换后的值, 是否需要填默认值)"""
        if isinstance(value, bool):
            return value, False
        if isinstance(value, str):
            value_lower = value.lower().strip()
            if value_lower in {"true", "是", "1", "yes", "y", "t"}:
                return True, False
            if value_lower in {"false", "否", "0", "no", "n", "f"}:
                return False, False
        if isinstance(value, (int, float)):
            return bool(value), False
        return None, True

    def _try_convert_to_date(self, value: Any) -> Tuple[Any, bool]:
        """
        尝试将值转换为日期/时间类型
        返回: (转换后的值, 是否需要填默认值)
        - 如果值是 None，直接返回 None
        - 如果值是空字符串或字符串 "None"，返回 None
        - 如果值非空，尝试格式化为日期时间，失败则打印错误并返回 None
        """
        # None 值直接返回
        if value is None:
            return None, False

        # 空字符串或字符串 "None" 转为 None
        if isinstance(value, str):
            value_stripped = value.strip()
            if value_stripped == "" or value_stripped.lower() == "none":
                return None, False

        # 非空值，尝试使用内置 datetime 解析常见日期格式
        date_formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
            "%Y年%m月%d日",
            "%Y-%m-%dT%H:%M:%S",
        ]
        value_str = str(value).strip()
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(value_str, fmt)
                # 返回 ISO 格式字符串，确保 json.dumps 可序列化
                return parsed_date.isoformat(), False
            except ValueError:
                continue

        # 所有格式都尝试失败
        logging.error(f"Failed to parse value '{value}' as date/time: no matching format")
        return None, False

    def _try_convert_value_to_type(self, value: Any, type_name: str) -> Tuple[Any, bool]:
        """
        尝试将属性值转换为schema定义的类型
        返回: (转换后的值, 是否需要填默认值)
        - 如果值已经是正确类型，返回 (原值, False)
        - 如果值可以转换，返回 (转换后的值, False)
        - 如果值无法转换（非空字符串转数值类型失败），返回 (None, True) 表示需要填默认值
        """
        if value is None or value == "":
            return value, False

        if not type_name:
            return value, False

        normalized = type_name.upper()

        # DATE/DATETIME 类型特殊处理：需要先解析验证并转换为 ISO 格式字符串
        # 必须放在 _is_value_match_type 检查之前处理，因为 _is_value_match_type 对 DATE/DATETIME
        # 类型的字符串会返回 True（默认匹配），导致 "未提及" 等无效字符串被直接返回
        if normalized in {"DATE", "DATETIME"}:
            return self._try_convert_to_date(value)

        # 如果值已经是正确类型，直接返回
        if self._is_value_match_type(value, normalized):
            return value, False

        # 尝试类型转换
        if normalized in {"BYTE", "SHORT", "INTEGER", "LONG"}:
            return self._try_convert_to_int(value)
        if normalized in {"FLOAT", "DOUBLE"}:
            return self._try_convert_to_float(value)
        if normalized == "BOOLEAN":
            return self._try_convert_to_bool(value)

        # 其他类型（STRING等）不强制转换
        return value, False

    def validate_and_fix_property_value(self, prop_name: str, prop_value: Any,
                                        prop_def: Dict[str, Any], entity_idx: int = 0,
                                        is_entity: bool = True) -> Tuple[Any, Optional[str]]:
        """
        校验并修复属性值，确保类型匹配。

        返回: (修复后的值, 错误信息，如果没有错误则错误信息为 None)
        """
        prop_type = (prop_def.get('type') or '').upper()
        is_primary = prop_def.get('is_primary', False)
        item_type = "entity" if is_entity else "edge"

        # 首先检查是否需要填默认值（None 或 空字符串且类型为数值/布尔）
        need_default = (
            prop_value is None
            or (prop_value == "" and self._default_value_is_non_string(prop_type))
        )

        if need_default:
            if is_primary:
                return None, (
                    f"Chunk {entity_idx + 1} {item_type} property '{prop_name}' "
                    f"is primary key and cannot be empty"
                )
            default_val = self._default_value_for_type(prop_type)
            logging.warning(
                f"Chunk {entity_idx + 1} {item_type} property '{prop_name}' "
                f"value={repr(prop_value)}, type={prop_type}, "
                f"converting to schema default {repr(default_val)}")
            return default_val, None

        # 尝试转换类型不匹配的属性值
        converted_value, needs_default = self._try_convert_value_to_type(
            prop_value, prop_type
        )

        if needs_default:
            if is_primary:
                return None, (
                    f"Chunk {entity_idx + 1} {item_type} property '{prop_name}' "
                    f"value={repr(prop_value)} cannot be converted to type "
                    f"{prop_type} and is primary key"
                )
            default_val = self._default_value_for_type(prop_type)
            logging.warning(
                f"Chunk {entity_idx + 1} {item_type} property '{prop_name}' "
                f"value={repr(prop_value)} type={prop_type}, "
                f"cannot be converted to schema type, "
                f"using schema default {repr(default_val)}")
            return default_val, None

        if converted_value != prop_value:
            logging.warning(
                f"Chunk {entity_idx + 1} {item_type} property '{prop_name}' "
                f"value={repr(prop_value)} converted to {repr(converted_value)} to match type={prop_type}")

        return converted_value, None
