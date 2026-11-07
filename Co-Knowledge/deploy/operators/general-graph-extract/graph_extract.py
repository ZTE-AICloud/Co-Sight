import json
import logging
import os
import re
from typing import Dict, List, Optional

from operator_api.graph import GraphChecker
from operator_api.llm import invoke_llm

from collections import deque
from concurrent.futures import ThreadPoolExecutor

#: 抽图 chunk 级并发的默认线程数。LLM 调用是纯 I/O，串行是主要瓶颈；
#: 可用算子 kwargs.maxWorkers 或环境变量 GRAPH_EXTRACT_MAX_WORKERS 覆盖（界 1..32）。
DEFAULT_MAX_WORKERS = 8


_DATE_MIDNIGHT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00:00$")


def _clean_entity_name(name):
    """把 LLM 常见的 ``YYYY-MM-DD 00:00:00`` 日期实体归一成 ``YYYY-MM-DD``。"""
    if not isinstance(name, str):
        return name
    match = _DATE_MIDNIGHT_RE.match(name.strip())
    return match.group(1) if match else name


DEFAULT_EXTRACTION_PROFILE = "general"

ATTRIBUTE_ADDENDUM = """

---ADDITIONAL REQUIREMENTS: ATTRIBUTES (profile general_attributes)---
In addition to the general entity/relationship extraction, extract semantic attributes as first-class entities and relationships:
- People: date_of_birth, date_of_death, place_of_birth, place_of_death, country_of_citizenship, occupation, spouse, father, mother, award_received.
- Films: director, performer, publication_date, country_of_origin, genre, award_received.
- Places: country, located_in.
- Countries ARE first-class entities. When the text states a nationality or citizenship (for example "Kenyan", "American", "Indian", "German"), create the country entity and a country_of_citizenship relationship for people, or country_of_origin for films. Normalize nationality adjectives to the country name: Kenyan -> Kenya, American -> United States, Indian -> India, German -> Germany. For places use country.
- Country examples:
  - "Aboud Omar is a Kenyan professional footballer." -> Aboud Omar --country_of_citizenship--> Kenya
  - "Alfons Zitterbacke is a 1966 East German film." -> Alfons Zitterbacke --country_of_origin--> East Germany
  - "The film was produced in France." -> the film --country_of_origin--> France
- Extract a country only when the text states a nationality/citizenship or a production country; do not guess it from a person's name.
- If the text explicitly gives another name for the same entity ("also known as", "born as", "real name", "stage name"), create an entity for the alias and an alias_of relationship from the alias to the canonical entity.
- Dates ARE valid entities when they are attribute values. Create a separate entity for each such date using ISO format YYYY-MM-DD with no time component when available, otherwise YYYY and a relationship from the subject entity. Do not omit dates and do not only put them inside descriptions.
- Only facts explicitly stated in the text. Keep the same JSON output format.
"""

PROMPT_ADDENDA = {"general_attributes": ATTRIBUTE_ADDENDUM}

#: 国家/国籍比较的确定性归一：历史政权、属地、常见别名归到同一组。
#: 只加 `country_group` 边，不改实体原名，避免破坏出处/展示。
COUNTRY_GROUP_ALIASES = {
    'east germany': 'Germany',
    'west germany': 'Germany',
    'german democratic republic': 'Germany',
    'federal republic of germany': 'Germany',
    'puerto rico': 'United States',
    'united states of america': 'United States',
    'usa': 'United States',
    'us': 'United States',
    'u.s.': 'United States',
    'united kingdom': 'United Kingdom',
    'great britain': 'United Kingdom',
    'britain': 'United Kingdom',
    'england': 'United Kingdom',
    'scotland': 'United Kingdom',
    'wales': 'United Kingdom',
    'northern ireland': 'United Kingdom',
    'soviet union': 'Russia',
    'ussr': 'Russia',
    'russian federation': 'Russia',
}


def _augment_country_groups(entities, edges, entity_name_map,
                            entity_id_counter, edge_id_counter, log_prefix_func):
    """给历史政权/属地/别名国家补 ``country_group`` 边（确定性，不调 LLM）。"""
    existing_edges = {
        (edge.get('source_id'), edge.get('target_id'),
         (edge.get('properties') or {}).get('relationship_keywords'))
        for edge in edges
    }
    for entity in list(entities):
        properties = entity.get('properties') or {}
        name = str(properties.get('entity_name') or '').strip()
        canonical = COUNTRY_GROUP_ALIASES.get(name.lower())
        if not canonical or canonical.lower() == name.lower():
            continue
        canonical_id = entity_name_map.get(canonical)
        if not canonical_id:
            canonical_id = f"Entity_{entity_id_counter}"
            entity_id_counter += 1
            entity_name_map[canonical] = canonical_id
            entities.append({
                "entity_type": "Entity",
                "entity_id": canonical_id,
                "properties": {
                    "entity_name": canonical,
                    "entity_description": (
                        f"{canonical} canonical country group for "
                        f"nationality/country comparison."),
                    "chunk_id": properties.get('chunk_id', ''),
                },
            })
        key = (entity.get('entity_id'), canonical_id, 'country_group')
        if key in existing_edges:
            continue
        edges.append({
            "edge_type": "Relation",
            "source_id": entity.get('entity_id'),
            "target_id": canonical_id,
            "edge_id": f"Relation_{edge_id_counter}",
            "properties": {
                "relationship_description": (
                    f"{name} is grouped under {canonical} for "
                    f"country/nationality comparison."),
                "relationship_keywords": "country_group",
            },
        })
        existing_edges.add(key)
        edge_id_counter += 1
    logging.info(log_prefix_func(
        f"Country groups: entities={len(entities)}, edges={len(edges)}"))
    return entity_id_counter, edge_id_counter


def _resolve_extraction_profile(kwargs):
    raw = str((kwargs or {}).get("extractionProfile") or DEFAULT_EXTRACTION_PROFILE).strip().lower()
    if raw not in PROMPT_ADDENDA and raw != DEFAULT_EXTRACTION_PROFILE:
        logging.warning(f"Unknown extractionProfile={raw!r}; falling back to {DEFAULT_EXTRACTION_PROFILE}")
        return DEFAULT_EXTRACTION_PROFILE
    return raw


def _resolve_workers(kwargs):
    raw = (kwargs or {}).get("maxWorkers")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = os.environ.get("GRAPH_EXTRACT_MAX_WORKERS", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_WORKERS
    return max(1, min(value, 32))


def _parallel_ordered(items, fn, workers):
    """有界并发 + 按输入顺序产出：在途不超过 2*workers，结果顺序与串行一致。"""
    pending = deque()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item in items:
            pending.append(pool.submit(fn, item))
            if len(pending) >= workers * 2:
                yield pending.popleft().result()
        while pending:
            yield pending.popleft().result()


message_dict = {
    "success": {
        "en": "Operator executed successfully",
        "zh": "算子执行成功"
    },
    "model_name_exception": {
        "en": "Missing required parameter 'llm' in kwargs",
        "zh": "缺少必需参数 'llm'"
    },
    "input_file_not_found_exception": {
        "en": "Input file not found",
        "zh": "输入文件未找到"
    },
    "graph_extraction_failed_exception": {
        "en": "Graph extraction failed",
        "zh": "图谱提取失败"
    },
    "save_json_exception": {
        "en": "Failed to save the result to jsonl",
        "zh": "结果存入jsonl失败"
    }
}

PROMPT_TEMPLATE = """
---Goal---
Given a text document that is potentially relevant to this activity and a list of entity types, identify all entities of those types from the text and all relationships among the identified entities.
Use the same language as the input text for all output content.

**CRITICAL LANGUAGE REQUIREMENT: 
- Use EXACTLY the same language as the input text for ALL output content
- If the input text is in Chinese, ALL entity descriptions, relationship descriptions, and keywords MUST be in Chinese
- If the input text is in English, ALL output MUST be in English
- Do NOT mix languages (e.g., do not use English descriptions for Chinese text)
- Do NOT use bilingual or mixed-language outputs**

---Steps---
1. Identify all entities. For each identified entity, extract the following information:

**IMPORTANT: Only extract entities that are semantically meaningful and contribute to knowledge graph construction.
Entity Quality Criteria:
- The entity must have semantic meaning and represent a real-world concept
- The entity should be able to participate in meaningful relationships
- The entity name should be a coherent noun phrase or proper noun
- Avoid extracting entities that are purely structural or formatting elements

DO NOT extract:
- Standalone dates, timestamps, or page numbers (e.g., "2024-01-01", "Page 5", "第3页")
- Pure numbers or numeric codes without semantic context (e.g., "123", "V1.0", "No. 001")
- Formatting markers or document structure markers (e.g., "Chapter 1", "Section A", "第1章")
- Version numbers or build numbers without product context (e.g., "V2.0", "Build 1234")
- Page numbers, line numbers, or document position markers (e.g., "Page 5", "Line 10", "第5页")**

- "entity_name": the exact name of the entity as it appears in the input text
- "entity_type": ALWAYS the literal string "Entity".
  **This operator deliberately does NOT classify entities into sub-types: the downstream
  code (see _process_entities) overwrites whatever you emit with the single schema type
  "Entity". Do not spend effort choosing a type, and do not invent type names.**
- "entity_description": **a comprehensive description of the entity's attributes and activities as mentioned in the text. MUST use the same language as the input text.**

Format each entity as:
{{"entity_name": "<entity_name>", "entity_type": "Entity", "entity_description": "<entity_description>"}}

2. From the entities identified in step 1, identify all pairs of (source_entity, target_entity) that are *clearly related* to each other.

**Relationship Quality Criteria:
- Only extract relationships between entities that have clear, explicit connections in the text
- The relationship should be meaningful and contribute to knowledge understanding
- Avoid extracting weak or inferred relationships**

For each such pair, extract the following information:
- "source_entity": the exact entity name from step 1
- "target_entity": the exact entity name from step 1
- "relationship_description": **a clear explanation of the relationship, grounded in the text. MUST use the same language as the input text.**
- "relationship_keywords": **one or more high-level keywords summarizing the thematic nature of the relationship. MUST use the same language as the input text. Format as a list of strings (e.g., ["affiliation", "development"])**

Format each relationship as:
{{"source_entity": "<source_entity>", "target_entity": "<target_entity>", "relationship_description": "<relationship_description>", "relationship_keywords": ["<keyword1>", "<keyword2>"]}}

3. Return a single JSON object with two top-level fields:
- "entities": an array of all entity objects from step 1
- "relationships": an array of all relationship objects from step 2

The entire output must be valid JSON and parsable by `json.loads()`.  
Do not include any additional text, formatting, comments, or delimiters.
**REMEMBER: All descriptions and keywords must use the same language as the input text.**

######################
---Examples---
######################
Example 1:

Entity_types: [Entity]
Text:
```
while Alex clenched his jaw, the buzz of frustration dull against the backdrop of Taylor's authoritarian certainty. It was this competitive undercurrent that kept him alert, the sense that his and Jordan's shared commitment to discovery was an unspoken rebellion against Cruz's narrowing vision of control and order.

Then Taylor did something unexpected. They paused beside Jordan and, for a moment, observed the device with something akin to reverence. "If this tech can be understood..." Taylor said, their voice quieter, "It could change the game for us. For all of us."

The underlying dismissal earlier seemed to falter, replaced by a glimpse of reluctant respect for the gravity of what lay in their hands. Jordan looked up, and for a fleeting heartbeat, their eyes locked with Taylor's, a wordless clash of wills softening into an uneasy truce.

It was a small transformation, barely perceptible, but one that Alex noted with an inward nod. They had all been brought here by different paths
```

Output:
{{
  "entities": [
    {{
      "entity_name": "Alex",
      "entity_type": "Entity",
      "entity_description": "Alex is a character who experiences frustration and is observant of the dynamics among other characters."
    }},
    {{
      "entity_name": "Taylor",
      "entity_type": "Entity",
      "entity_description": "Taylor is portrayed with authoritarian certainty and shows a moment of reverence towards a device, indicating a change in perspective."
    }},
    {{
      "entity_name": "Jordan",
      "entity_type": "Entity",
      "entity_description": "Jordan shares a commitment to discovery and has a significant interaction with Taylor regarding a device."
    }},
    {{
      "entity_name": "Cruz",
      "entity_type": "Entity",
      "entity_description": "Cruz is associated with a vision of control and order, influencing the dynamics among other characters."
    }},
    {{
      "entity_name": "The Device",
      "entity_type": "Entity",
      "entity_description": "The Device is central to the story, with potential game-changing implications, and is revered by Taylor."
    }}
  ],
  "relationships": [
    {{
      "source_entity": "Alex",
      "target_entity": "Taylor",
      "relationship_description": "Alex is affected by Taylor's authoritarian certainty and observes changes in Taylor's attitude towards the device.",
      "relationship_keywords": ["power dynamics", "perspective shift"]
    }},
    {{
      "source_entity": "Alex",
      "target_entity": "Jordan",
      "relationship_description": "Alex and Jordan share a commitment to discovery, which contrasts with Cruz's vision.",
      "relationship_keywords": ["shared goals", "rebellion"]
    }},
    {{
      "source_entity": "Taylor",
      "target_entity": "Jordan",
      "relationship_description": "Taylor and Jordan interact directly regarding the device, leading to a moment of mutual respect and an uneasy truce.",
      "relationship_keywords": ["conflict resolution", "mutual respect"]
    }},
    {{
      "source_entity": "Jordan",
      "target_entity": "Cruz",
      "relationship_description": "Jordan's commitment to discovery is in rebellion against Cruz's vision of control and order.",
      "relationship_keywords": ["ideological conflict", "rebellion"]
    }},
    {{
      "source_entity": "Taylor",
      "target_entity": "The Device",
      "relationship_description": "Taylor shows reverence towards the device, indicating its importance and potential impact.",
      "relationship_keywords": ["reverence", "technological significance"]
    }}
  ]
}}
#############################
Example 2:

Entity_types: [Entity]
Text:
```
Stock markets faced a sharp downturn today as tech giants saw significant declines, with the Global Tech Index dropping by 3.4% in midday trading. Analysts attribute the selloff to investor concerns over rising interest rates and regulatory uncertainty.

Among the hardest hit, Nexon Technologies saw its stock plummet by 7.8% after reporting lower-than-expected quarterly earnings. In contrast, Omega Energy posted a modest 2.1% gain, driven by rising oil prices.

Meanwhile, commodity markets reflected a mixed sentiment. Gold futures rose by 1.5%, reaching $2,080 per ounce, as investors sought safe-haven assets. Crude oil prices continued their rally, climbing to $87.60 per barrel, supported by supply constraints and strong demand.

Financial experts are closely watching the Federal Reserve's next move, as speculation grows over potential rate hikes. The upcoming policy announcement is expected to influence investor confidence and overall market stability.
```

Output:
{{
  "entities": [
    {{
      "entity_name": "Global Tech Index",
      "entity_type": "Entity",
      "entity_description": "The Global Tech Index tracks the performance of major technology stocks and experienced a 3.4% decline today."
    }},
    {{
      "entity_name": "Nexon Technologies",
      "entity_type": "Entity",
      "entity_description": "Nexon Technologies is a tech company that saw its stock decline by 7.8% after disappointing earnings."
    }},
    {{
      "entity_name": "Omega Energy",
      "entity_type": "Entity",
      "entity_description": "Omega Energy is an energy company that gained 2.1% in stock value due to rising oil prices."
    }},
    {{
      "entity_name": "Gold Futures",
      "entity_type": "Entity",
      "entity_description": "Gold futures rose by 1.5%, indicating increased investor interest in safe-haven assets."
    }},
    {{
      "entity_name": "Crude Oil",
      "entity_type": "Entity",
      "entity_description": "Crude oil prices rose to $87.60 per barrel due to supply constraints and strong demand."
    }},
    {{
      "entity_name": "Market Selloff",
      "entity_type": "Entity",
      "entity_description": "Market selloff refers to the significant decline in stock values due to investor concerns over interest rates and regulations."
    }},
    {{
      "entity_name": "Federal Reserve Policy Announcement",
      "entity_type": "Entity",
      "entity_description": "The Federal Reserve's upcoming policy announcement is expected to impact investor confidence and market stability."
    }}
  ],
  "relationships": [
    {{
      "source_entity": "Global Tech Index",
      "target_entity": "Market Selloff",
      "relationship_description": "The decline in the Global Tech Index is part of the broader market selloff driven by investor concerns.",
      "relationship_keywords": ["market performance", "investor sentiment"]
    }},
    {{
      "source_entity": "Nexon Technologies",
      "target_entity": "Global Tech Index",
      "relationship_description": "Nexon Technologies' stock decline contributed to the overall drop in the Global Tech Index.",
      "relationship_keywords": ["company impact", "index movement"]
    }},
    {{
      "source_entity": "Gold Futures",
      "target_entity": "Market Selloff",
      "relationship_description": "Gold prices rose as investors sought safe-haven assets during the market selloff.",
      "relationship_keywords": ["market reaction", "safe-haven investment"]
    }},
    {{
      "source_entity": "Federal Reserve Policy Announcement",
      "target_entity": "Market Selloff",
      "relationship_description": "Speculation over Federal Reserve policy changes contributed to market volatility and investor selloff.",
      "relationship_keywords": ["interest rate impact", "financial regulation"]
    }}
  ]
}}
#############################
Example 3:

Entity_types: [Entity]
Text:
```
At the World Athletics Championship in Tokyo, Noah Carter broke the 100m sprint record using cutting-edge carbon-fiber spikes.
```

Output:
{{
  "entities": [
    {{
      "entity_name": "World Athletics Championship",
      "entity_type": "Entity",
      "entity_description": "The World Athletics Championship is a global sports competition featuring top athletes in track and field."
    }},
    {{
      "entity_name": "Tokyo",
      "entity_type": "Entity",
      "entity_description": "Tokyo is the host city of the World Athletics Championship."
    }},
    {{
      "entity_name": "Noah Carter",
      "entity_type": "Entity",
      "entity_description": "Noah Carter is a sprinter who set a new record in the 100m sprint at the World Athletics Championship."
    }},
    {{
      "entity_name": "100m Sprint Record",
      "entity_type": "Entity",
      "entity_description": "The 100m sprint record is a benchmark in athletics, recently broken by Noah Carter."
    }},
    {{
      "entity_name": "Carbon-Fiber Spikes",
      "entity_type": "Entity",
      "entity_description": "Carbon-fiber spikes are advanced sprinting shoes that provide enhanced speed and traction."
    }},
    {{
      "entity_name": "World Athletics Federation",
      "entity_type": "Entity",
      "entity_description": "The World Athletics Federation is the governing body overseeing the World Athletics Championship and record validations."
    }}
  ],
  "relationships": [
    {{
      "source_entity": "World Athletics Championship",
      "target_entity": "Tokyo",
      "relationship_description": "The World Athletics Championship is being hosted in Tokyo.",
      "relationship_keywords": ["event location", "international competition"]
    }},
    {{
      "source_entity": "Noah Carter",
      "target_entity": "100m Sprint Record",
      "relationship_description": "Noah Carter set a new 100m sprint record at the championship.",
      "relationship_keywords": ["athlete achievement", "record-breaking"]
    }},
    {{
      "source_entity": "Noah Carter",
      "target_entity": "Carbon-Fiber Spikes",
      "relationship_description": "Noah Carter used carbon-fiber spikes to enhance performance during the race.",
      "relationship_keywords": ["athletic equipment", "performance boost"]
    }},
    {{
      "source_entity": "World Athletics Federation",
      "target_entity": "100m Sprint Record",
      "relationship_description": "The World Athletics Federation is responsible for validating and recognizing new sprint records.",
      "relationship_keywords": ["sports regulation", "record certification"]
    }}
  ]
}}
#############################

#############################
---Real Data---
######################
Entity_types: [Entity]
Text:
{content_expand}
######################
Output:
"""


def _get_message_by_lang(msg_code: str) -> dict:
    return message_dict.get(msg_code, {})


class GraphException(Exception):

    def __init__(self, code) -> None:
        self.code = code

    def get_code(self):
        return self.code


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


def graph_extract(file_path: str, lang: str, transaction_id: str = "", kwargs: Dict = None):
    """
    通用知识图谱抽取算子
    
    算子执行成功：返回示例:{"code": 0, "message": "xxx"}
    算子执行失败：返回示例：{"code":-1, "message": "xxx"}
    """
    # 注入 transaction_id 以便类内日志前缀可用
    if kwargs is None:
        kwargs = {}
    kwargs.setdefault("transaction_id", transaction_id)
    prefix = f"[{transaction_id}]>>" if transaction_id else ""
    p = (lambda m: f"{prefix}{m}") if prefix else (lambda m: m)
    
    logging.info(p(f'Start to extract graph, file_path={file_path}, lang={lang}, kwargs={_redact_llm_config(kwargs)}'))
    
    try:
        # 1. 参数校验
        if not kwargs.get('llm'):
            error_msg = "Missing required parameter 'llm' in kwargs"
            logging.error(p(error_msg))
            raise GraphException("model_name_exception")
        
        llm_model = kwargs['llm']
        llm_config = kwargs.get("llmConfig") or None
        
        # 2. 读取输入文件
        input_file_path = os.path.join(file_path, "output/document_chunk.jsonl")
        if not os.path.exists(input_file_path):
            error_msg = f"Input file not found: {input_file_path}"
            logging.error(p(error_msg))
            raise GraphException("input_file_not_found_exception")
        
        # 3. 使用提示词模板（profile 只追加属性段；默认 general 保持原 prompt）
        profile = _resolve_extraction_profile(kwargs)
        prompt_template = PROMPT_TEMPLATE + PROMPT_ADDENDA.get(profile, "")
        logging.info(p(f"Graph extraction profile: {profile}"))
        
        # 4. 初始化GraphChecker用于schema校验
        schema_data = _generate_schema()
        graph_checker = GraphChecker(schema_data)
        
        # 5. 初始化数据集合
        entity_name_map = {}  # {entity_name: entity_id}
        entities = []  # 实体列表
        edges = []  # 关系列表
        entity_id_counter = 1
        edge_id_counter = 1
        processed_chunks = 0
        error_count = 0
        
        # 5. 逐行处理输入文件
        #    LLM 调用是逐 chunk 的纯 I/O，串行是主要瓶颈（161 切片的 2MB PDF
        #    冷启动 >30 分钟）。改为**有界并发**：
        #    - 线程池里只放「LLM 调用 + 格式/schema 校验」（只读 checker）；
        #    - 实体/关系的去重与编号仍按**输入顺序**串行合并，结果与串行版一致；
        #    - 在途任务 ≤ 2*workers，避免大文档把所有响应压进内存。
        chunks = []
        with open(input_file_path, "r", encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk_data = json.loads(line)
                except json.JSONDecodeError as e:
                    logging.warning(p(f"Failed to parse line {line_num} into JSON: {e}"))
                    error_count += 1
                    continue
                chunk_id = chunk_data.get("id")
                content_expand = chunk_data.get("content_expand")
                if not chunk_id or not content_expand:
                    logging.warning(p(f"Missing required fields 'id' or 'content_expand' in line {line_num}"))
                    error_count += 1
                    continue
                chunks.append((line_num, chunk_id, content_expand))

        def _extract_one(item):
            line_num, chunk_id, content_expand = item
            try:
                extracted_data = _extract_with_llm(
                    prompt_template, content_expand, llm_model, p, transaction_id, chunk_id,
                    llm_config=llm_config
                )
                if not extracted_data:
                    return ("error", chunk_id, None)
                if not _validate_format(extracted_data, p, transaction_id, chunk_id):
                    return ("error", chunk_id, None)
                if not _validate_schema(extracted_data, graph_checker, p, transaction_id, chunk_id):
                    return ("error", chunk_id, None)
                return ("ok", chunk_id, extracted_data)
            except Exception as e:                                     # noqa: BLE001
                logging.exception(p(f"Error processing line {line_num}: {e}"))
                return ("error", chunk_id, None)

        workers = _resolve_workers(kwargs)
        logging.info(p(f"Graph extraction concurrency: {workers} worker(s) "
                       f"for {len(chunks)} chunk(s)"))

        for status, chunk_id, extracted_data in _parallel_ordered(
                chunks, _extract_one, workers):
            if status != "ok":
                error_count += 1
                continue
            entity_id_counter = _process_entities(
                extracted_data.get("entities", []),
                chunk_id,
                entity_name_map,
                entities,
                entity_id_counter,
                p
            )
            edge_id_counter = _process_relationships(
                extracted_data.get("relationships", []),
                entity_name_map,
                edges,
                edge_id_counter,
                p
            )
            processed_chunks += 1

        # 5.1 确定性国家分组（只对属性 profile）：East Germany/Puerto Rico
        # 等归到同一组，供“同一国家/国籍”类问题比较。
        if profile == "general_attributes":
            entity_id_counter, edge_id_counter = _augment_country_groups(
                entities, edges, entity_name_map,
                entity_id_counter, edge_id_counter, p)

        # 6. 使用GraphChecker校验处理后的实体和关系数据
        validation_errors = []
        for idx, entity in enumerate(entities):
            is_valid, error_msg = graph_checker.check_entity_data(entity)
            if not is_valid:
                validation_errors.append(f"Entity[{idx}] validation failed: {error_msg}")
                logging.warning(p(f"Entity validation failed: {error_msg}, entity_id={entity.get('entity_id')}"))
        
        for idx, edge in enumerate(edges):
            is_valid, error_msg = graph_checker.check_edge_data(edge)
            if not is_valid:
                validation_errors.append(f"Edge[{idx}] validation failed: {error_msg}")
                logging.warning(p(f"Edge validation failed: {error_msg}, edge_id={edge.get('edge_id')}"))
        
        if validation_errors:
            error_msg = f"Schema validation failed for processed data: {'; '.join(validation_errors[:5])}"
            logging.error(p(error_msg))
            # 可以选择继续输出或返回错误，这里选择继续输出但记录警告
            # return {"code": -1, "message": error_msg}
        
        # 7. 生成输出文件
        schema_data = _generate_schema()
        
        # 写入entities.jsonl
        entities_file_path = os.path.join(file_path, "entities.jsonl")
        _write_jsonl(entities_file_path, entities, p)
        
        # 写入edges.jsonl
        edges_file_path = os.path.join(file_path, "edges.jsonl")
        _write_jsonl(edges_file_path, edges, p)
        
        # 写入schema.json
        schema_file_path = os.path.join(file_path, "schema.json")
        _write_json_file(schema_file_path, schema_data, p)
        
        success_msg = f"Graph extraction completed. Processed {processed_chunks} chunks, " \
                     f"generated {len(entities)} entities, {len(edges)} edges. " \
                     f"Errors: {error_count}"
        logging.info(p(success_msg))
        
        success_message = _get_message_by_lang("success")
        return {"code": "0", "message": success_message}
        
    except GraphException as e:
        logging.exception(p(str(e)))
        exception_msg = _get_message_by_lang(e.get_code())
        return {"code": "-1", "message": exception_msg}

def _extract_with_llm(
    prompt_template: str,
    content_expand: str,
    llm_model: str,
    log_prefix_func,
    transaction_id: str,
    chunk_id: str,
    llm_config: Optional[dict] = None
) -> Optional[Dict]:
    """调用大模型抽取实体和关系"""
    try:
        # 构建提示词
        prompt = prompt_template.format(content_expand=content_expand)
        
        # 调用大模型
        messages = [{"role": "user", "content": prompt}]
        llm_response = invoke_llm(messages=messages, model=llm_model, temperature=0.1,
                                  endpoint=llm_config)
        
        if not llm_response:
            logging.warning(log_prefix_func(
                f"LLM returned empty response for chunk_id={chunk_id}"
            ))
            return None
        
        # 记录原始响应（用于调试）
        original_response = llm_response
        
        # 解析JSON响应
        # 尝试提取JSON部分（去除可能的markdown代码块标记和额外文本）
        llm_response = llm_response.strip()
        
        # 移除markdown代码块标记
        if llm_response.startswith("```json"):
            llm_response = llm_response[7:].strip()
        elif llm_response.startswith("```"):
            llm_response = llm_response[3:].strip()
        
        if llm_response.endswith("```"):
            llm_response = llm_response[:-3].strip()
        
        # 尝试查找JSON对象（可能前面有说明文字）
        # 查找第一个 { 和最后一个 } 的位置
        first_brace = llm_response.find('{')
        last_brace = llm_response.rfind('}')
        
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            llm_response = llm_response[first_brace:last_brace + 1]
        
        # 如果还是空的，尝试查找第一个 { 开始的内容
        if not llm_response.strip():
            # 可能响应中只有说明文字，尝试从 { 开始提取
            if '{' in original_response:
                first_brace = original_response.find('{')
                last_brace = original_response.rfind('}')
                if first_brace != -1 and last_brace != -1:
                    llm_response = original_response[first_brace:last_brace + 1]
        
        llm_response = llm_response.strip()
        
        if not llm_response:
            logging.warning(log_prefix_func(
                f"LLM response is empty after cleaning for chunk_id={chunk_id}"
            ))
            logging.debug(log_prefix_func(f"Original LLM response: {original_response[:500]}"))
            return None
        
        # 尝试解析JSON
        try:
            extracted_data = json.loads(llm_response)
        except json.JSONDecodeError as e:
            # 如果解析失败，尝试修复常见的JSON问题
            # 1. 移除末尾的逗号
            if llm_response.rstrip().endswith(','):
                llm_response = llm_response.rstrip().rstrip(',')
                try:
                    extracted_data = json.loads(llm_response)
                except json.JSONDecodeError:
                    pass
            
            # 如果还是失败，记录详细错误信息
            if 'extracted_data' not in locals():
                logging.warning(log_prefix_func(
                    f"Failed to parse LLM response as JSON for chunk_id={chunk_id}: {e}"
                ))
                logging.warning(log_prefix_func(
                    f"Cleaned LLM response (first 500 chars): {llm_response[:500]}"
                ))
                logging.debug(log_prefix_func(
                    f"Full LLM response: {original_response}"
                ))
                return None
        
        return extracted_data
        
    except Exception as e:
        logging.exception(log_prefix_func(
            f"LLM extraction failed for chunk_id={chunk_id}: {e}"
        ))
        if 'original_response' in locals():
            logging.debug(log_prefix_func(
                f"LLM response: {original_response[:500]}"
            ))
        return None


def _validate_format(extracted_data: Dict, log_prefix_func, transaction_id: str, chunk_id: str) -> bool:
    """校验输出格式是否符合提示词要求"""
    try:
        # 检查顶层字段
        if not isinstance(extracted_data, dict):
            logging.warning(log_prefix_func(
                f"Format validation failed: extracted_data is not a dict for chunk_id={chunk_id}"
            ))
            return False
        
        # 检查entities字段
        if "entities" not in extracted_data:
            logging.warning(log_prefix_func(
                f"Format validation failed: missing 'entities' field for chunk_id={chunk_id}"
            ))
            return False
        
        entities = extracted_data.get("entities", [])
        if not isinstance(entities, list):
            logging.warning(log_prefix_func(
                f"Format validation failed: 'entities' is not a list for chunk_id={chunk_id}"
            ))
            return False
        
        # 校验每个实体
        for idx, entity in enumerate(entities):
            if not isinstance(entity, dict):
                logging.warning(log_prefix_func(
                    f"Format validation failed: entity[{idx}] is not a dict for chunk_id={chunk_id}"
                ))
                return False
            
            required_fields = ["entity_name", "entity_type", "entity_description"]
            for field in required_fields:
                if field not in entity:
                    logging.warning(log_prefix_func(
                        f"Format validation failed: entity[{idx}] missing field '{field}' for chunk_id={chunk_id}"
                    ))
                    return False
                
                if not isinstance(entity[field], str):
                    logging.warning(log_prefix_func(
                        f"Format validation failed: entity[{idx}].{field} is not a string for chunk_id={chunk_id}"
                    ))
                    return False
        
        # 检查relationships字段
        if "relationships" not in extracted_data:
            logging.warning(log_prefix_func(
                f"Format validation failed: missing 'relationships' field for chunk_id={chunk_id}"
            ))
            return False
        
        relationships = extracted_data.get("relationships", [])
        if not isinstance(relationships, list):
            logging.warning(log_prefix_func(
                f"Format validation failed: 'relationships' is not a list for chunk_id={chunk_id}"
            ))
            return False
        
        # 校验每个关系
        for idx, relationship in enumerate(relationships):
            if not isinstance(relationship, dict):
                logging.warning(log_prefix_func(
                    f"Format validation failed: relationship[{idx}] is not a dict for chunk_id={chunk_id}"
                ))
                return False
            
            required_fields = ["source_entity", "target_entity", "relationship_description", "relationship_keywords"]
            for field in required_fields:
                if field not in relationship:
                    logging.warning(log_prefix_func(
                        f"Format validation failed: relationship[{idx}] missing field '{field}' for chunk_id={chunk_id}"
                    ))
                    return False
            
            # 检查字段类型
            if not isinstance(relationship["source_entity"], str):
                logging.warning(log_prefix_func(
                    f"Format validation failed: relationship[{idx}].source_entity is not a string for chunk_id={chunk_id}"
                ))
                return False
            
            if not isinstance(relationship["target_entity"], str):
                logging.warning(log_prefix_func(
                    f"Format validation failed: relationship[{idx}].target_entity is not a string for chunk_id={chunk_id}"
                ))
                return False
            
            if not isinstance(relationship["relationship_description"], str):
                logging.warning(log_prefix_func(
                    f"Format validation failed: relationship[{idx}].relationship_description is not a string for chunk_id={chunk_id}"
                ))
                return False
            
            # relationship_keywords可以是数组或字符串
            if not isinstance(relationship["relationship_keywords"], (list, str)):
                logging.warning(log_prefix_func(
                    f"Format validation failed: relationship[{idx}].relationship_keywords is not a list or string for chunk_id={chunk_id}"
                ))
                return False
        
        return True
        
    except Exception as e:
        logging.exception(log_prefix_func(
            f"Format validation exception for chunk_id={chunk_id}: {e}"
        ))
        return False


def _validate_schema(
    extracted_data: Dict,
    graph_checker: GraphChecker,
    log_prefix_func,
    transaction_id: str,
    chunk_id: str
) -> bool:
    """
    使用GraphChecker校验实体和关系是否符合schema设计
    
    将大模型返回的原始数据转换为符合schema的格式，然后使用GraphChecker进行校验
    """
    try:
        entities = extracted_data.get("entities", [])
        relationships = extracted_data.get("relationships", [])
        
        # 构建实体名称到临时entity_id的映射（用于关系校验）
        entity_name_to_temp_id = {}
        temp_entity_counter = 1
        
        # 校验每个实体
        for idx, entity in enumerate(entities):
            entity_name = entity.get("entity_name", "")
            entity_description = entity.get("entity_description", "")
            
            # 转换为符合schema的格式，用于GraphChecker校验
            temp_entity_id = f"Entity_{temp_entity_counter}"
            entity_name_to_temp_id[entity_name] = temp_entity_id
            temp_entity_counter += 1
            
            # 构建符合schema格式的实体数据
            entity_data = {
                "entity_type": "Entity",  # schema 中定义的实体类型固定为 "Entity"（不能叫 entity：与 EDGE/VERTEX 同属保留字，会被 schema 校验拒绝）
                "entity_id": temp_entity_id,
                "properties": {
                    "entity_name": entity_name,
                    "entity_description": entity_description,
                    "chunk_id": chunk_id
                }
            }
            
            # 使用GraphChecker校验实体数据
            is_valid, error_msg = graph_checker.check_entity_data(entity_data)
            if not is_valid:
                logging.warning(log_prefix_func(
                    f"Schema validation failed: entity[{idx}] validation error: {error_msg} "
                    f"for chunk_id={chunk_id}"
                ))
                return False
        
        # 校验每个关系
        temp_edge_counter = 1
        for idx, relationship in enumerate(relationships):
            source_entity_name = relationship.get("source_entity", "")
            target_entity_name = relationship.get("target_entity", "")
            relationship_description = relationship.get("relationship_description", "")
            relationship_keywords = relationship.get("relationship_keywords", "")
            
            # 处理relationship_keywords：如果是数组，转换为字符串
            if isinstance(relationship_keywords, list):
                relationship_keywords_str = ", ".join(str(kw) for kw in relationship_keywords)
            elif isinstance(relationship_keywords, str):
                relationship_keywords_str = relationship_keywords
            else:
                relationship_keywords_str = str(relationship_keywords) if relationship_keywords else ""
            
            # 获取source_id和target_id（如果不存在则跳过该关系）
            source_id = entity_name_to_temp_id.get(source_entity_name)
            target_id = entity_name_to_temp_id.get(target_entity_name)
            
            if not source_id or not target_id:
                # 如果source或target实体不存在，跳过该关系，不进行校验
                continue
            
            # 转换为符合schema的格式，用于GraphChecker校验
            temp_edge_id = f"Relation_{temp_edge_counter}"
            temp_edge_counter += 1
            
            # 构建符合schema格式的关系数据
            edge_data = {
                "edge_type": "Relation",  # schema 中定义的关系类型固定为 "Relation"（不能叫 edge：保留字）
                "edge_id": temp_edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "properties": {
                    "relationship_description": relationship_description,
                    "relationship_keywords": relationship_keywords_str
                }
            }
            
            # 使用GraphChecker校验关系数据
            is_valid, error_msg = graph_checker.check_edge_data(edge_data)
            if not is_valid:
                logging.warning(log_prefix_func(
                    f"Schema validation failed: relationship[{idx}] validation error: {error_msg} "
                    f"for chunk_id={chunk_id}"
                ))
                return False
        
        return True
        
    except Exception as e:
        logging.exception(log_prefix_func(
            f"Schema validation exception for chunk_id={chunk_id}: {e}"
        ))
        return False


def _process_entities(
    extracted_entities: List[Dict],
    chunk_id: str,
    entity_name_map: Dict[str, str],
    entities: List[Dict],
    entity_id_counter: int,
    log_prefix_func
) -> int:
    """处理实体：去重并添加到实体列表，返回更新后的entity_id_counter"""
    for entity in extracted_entities:
        entity_name = _clean_entity_name(entity.get("entity_name"))
        if not entity_name:
            continue
        
        # 检查实体名称是否已存在
        if entity_name in entity_name_map:
            # 实体已存在，更新chunk_id
            existing_entity_id = entity_name_map[entity_name]
            # 查找对应的实体对象
            for existing_entity in entities:
                if existing_entity.get("entity_id") == existing_entity_id:
                    existing_chunk_id = existing_entity.get("properties", {}).get("chunk_id", "")
                    if chunk_id not in existing_chunk_id:
                        # 追加新的chunk_id
                        if existing_chunk_id:
                            new_chunk_id = f"{existing_chunk_id},{chunk_id}"
                        else:
                            new_chunk_id = chunk_id
                        existing_entity["properties"]["chunk_id"] = new_chunk_id
                    break
        else:
            # 实体不存在，添加新实体
            entity_id = f"Entity_{entity_id_counter}"
            entity_name_map[entity_name] = entity_id
            
            new_entity = {
                "entity_type": "Entity",
                "entity_id": entity_id,
                "properties": {
                    "entity_name": entity_name,
                    "entity_description": entity.get("entity_description", ""),
                    "chunk_id": chunk_id
                }
            }
            entities.append(new_entity)
            entity_id_counter += 1
    
    return entity_id_counter


def _process_relationships(
    extracted_relationships: List[Dict],
    entity_name_map: Dict[str, str],
    edges: List[Dict],
    edge_id_counter: int,
    log_prefix_func
) -> int:
    """处理关系：生成edge_id并关联entity_id，返回更新后的edge_id_counter"""
    for relationship in extracted_relationships:
        source_entity_name = _clean_entity_name(relationship.get("source_entity"))
        target_entity_name = _clean_entity_name(relationship.get("target_entity"))
        
        if not source_entity_name or not target_entity_name:
            continue
        
        # 查找source_entity和target_entity的entity_id
        source_id = entity_name_map.get(source_entity_name)
        target_id = entity_name_map.get(target_entity_name)
        
        if not source_id or not target_id:
            # 实体不存在（可能已被去重丢弃），跳过该关系
            logging.debug(log_prefix_func(
                f"Skipping relationship: source_entity='{source_entity_name}' or "
                f"target_entity='{target_entity_name}' not found in entity_name_map"
            ))
            continue
        
        # 处理relationship_keywords：如果是数组，转换为字符串
        relationship_keywords = relationship.get("relationship_keywords", "")
        if isinstance(relationship_keywords, list):
            relationship_keywords = ", ".join(str(kw) for kw in relationship_keywords)
        elif not isinstance(relationship_keywords, str):
            relationship_keywords = str(relationship_keywords)
        
        # 生成edge_id并构建关系对象
        edge_id = f"Relation_{edge_id_counter}"
        new_edge = {
            "edge_type": "Relation",
            "source_id": source_id,
            "target_id": target_id,
            "edge_id": edge_id,
            "properties": {
                "relationship_description": relationship.get("relationship_description", ""),
                "relationship_keywords": relationship_keywords
            }
        }
        edges.append(new_edge)
        edge_id_counter += 1
    
    return edge_id_counter


def _generate_schema() -> Dict:
    """生成schema.json文件内容"""
    return {
        "schema_id": "General_Schema",
        "schema_name": "General_Schema",
        "schema_desc": "General_Schema",
        "entities": [
            {
                "entity_type": "Entity",
                "properties": [
                    {
                        "name": "entity_name",
                        "type": "STRING",
                        "desc": "实体名称，用于向量化和检索",
                        "is_embedding": True,
                        "is_primary": True
                    },
                    {
                        "name": "entity_description",
                        "type": "STRING",
                        "desc": "实体描述",
                        "is_embedding": False,
                        "is_primary": False
                    },
                    {
                        "name": "chunk_id",
                        "type": "STRING",
                        "desc": "实体关联的chunk_id",
                        "is_embedding": False,
                        "is_primary": False
                    }
                ]
            }
        ],
        "edges": [
            {
                "edge_type": "Relation",
				"source_entity": "Entity",
				"target_entity": "Entity",
                "properties": [
                    {
                        "name": "relationship_description",
                        "type": "STRING",
                        "desc": "关系描述信息",
                        "is_embedding": True
                    },
                    {
                        "name": "relationship_keywords",
                        "type": "STRING",
                        "desc": "关系关键词",
                        "is_embedding": True
                    }
                ]
            }
        ]
    }


def _write_jsonl(file_path: str, data_list: List[Dict], log_prefix_func):
    """写入JSONL文件"""
    try:
        with open(file_path, "w", encoding='utf-8') as f:
            for item in data_list:
                json_line = json.dumps(item, ensure_ascii=False)
                f.write(json_line + "\n")
        logging.info(log_prefix_func(f"Successfully wrote {len(data_list)} items to {file_path}"))
    except Exception as e:
        logging.exception(log_prefix_func(f"Failed to write JSONL file {file_path}: {e}"))
        raise GraphException("save_json_exception")


def _write_json_file(file_path: str, data: Dict, log_prefix_func):
    """写入JSON文件"""
    try:
        with open(file_path, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(log_prefix_func(f"Successfully wrote JSON file {file_path}"))
    except Exception as e:
        logging.exception(log_prefix_func(f"Failed to write JSON file {file_path}: {e}"))
        raise GraphException("save_json_exception")