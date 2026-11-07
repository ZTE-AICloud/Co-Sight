# 基站备电运维本体知识（完整属性版）

## 实体

站点 ent_site_001：英文名 West Lake No.1 Site，实体类型 site，维度 dimension。
描述：杭州西湖一号站，属于基站备电监测的核心站点。
别名 JSON 数组：["西湖一号站","WL1 站"]。
属性定义 JSON：[{"name":"vendor","type":"string","note":"设备厂家"},{"name":"backup_hours","type":"float","note":"当前备电小时数"}]。
属性注解 JSON：{"vendor":"华为/企业","backup_hours":"断电后可维持供电的小时数"}。

行政区 ent_district_001：英文名 West Lake District，实体类型 district，维度 dimension。
描述：杭州市西湖区，是站点所属的行政区。
别名 JSON 数组：["西湖区"]。
属性定义 JSON：[{"name":"city","type":"string","note":"所属城市"}]。
属性注解 JSON：{"city":"地级市名称"}。

运维圈 ent_circle_001：英文名 Hangzhou O&M Circle，实体类型 circle，维度 dimension。
描述：杭州运维圈，负责杭州区域内基站的日常运维。
别名 JSON 数组：["杭州运维圈"]。
属性定义 JSON：[{"name":"manager","type":"string","note":"运维负责人"}]。
属性注解 JSON：{"manager":"值班经理工号"}。

网元 ent_me_001：英文名 West Lake No.1 ME，实体类型 me，维度 dimension。
描述：西湖一号主网元，归属站点 ent_site_001。
别名 JSON 数组：["西湖一号主设备"]。
属性定义 JSON：[{"name":"model","type":"string","note":"设备型号"}]。
属性注解 JSON：{"model":"厂家型号编码"}。

小区 ent_cell_001：英文名 West Lake No.1 Cell，实体类型 cell，维度 dimension。
描述：西湖一号第一小区，归属网元 ent_me_001。
别名 JSON 数组：["西湖一号第一小区"]。
属性定义 JSON：[{"name":"pci","type":"string","note":"物理小区标识"}]。
属性注解 JSON：{"pci":"PCI 编号"}。

备电事实 ent_battery_backup_001：英文名 West Lake No.1 Backup Fact，实体类型 battery_backup，维度 fact。
描述：西湖一号站 2026-10-01 的备电观测事实，备电时长 1.5 小时，电池健康度 78%。
别名 JSON 数组：["西湖一号备电记录"]。
属性定义 JSON：[{"name":"backup_hours","type":"float","note":"备电时长(小时)"},{"name":"health","type":"float","note":"电池健康度(%)"}]。
属性注解 JSON：{"backup_hours":"断电后可维持供电时长","health":"电池健康度百分比"}。

## 指标

指标定义 ent_metric_backup_duration：指标名称 backup_duration，展示名「备电时长」，单位小时，关联实体类型 battery_backup，聚合方式 AVG，数据来源 ent_battery_backup_001，锚定事实实体 ent_battery_backup_001，引用维度 ent_site_001，统计口径按站点取平均值，描述：衡量站点断电后维持供电能力的指标。

## 规则

业务规则 ent_rule_backup_low：规则名称「备电不足告警规则」，规则类型 eca，描述：当站点备电时长低于 2 小时时触发备电不足事件，逻辑表达式 backup_hours < 2，事件类型 backup_low，条件表达式 ent_site_001.backup_hours < 2，涉及实体类型 ["site"]。

## 动作

动作 ent_action_query_backup：动作名称「查询站点备电时长」，类型 query，描述：按站点查询备电时长与健康度，实现引用 endpoint:/api/backup/query，绑定映射 ent_mapping_backup_api，入参 JSON Schema {"type":"object","properties":{"site_id":{"type":"string","x-entity":"site"}}}，写回规格 {"target_entity":"battery_backup"}，消费实体类型 ["site"]，产出实体类型 ["battery_backup"]。

## 场景

场景 ent_scene_root：场景名称「运维分析」，场景层级 0，分类 analysis，描述：运维分析的根场景，示例问句「帮我做运维分析」，扩展问句 ["运维分析怎么做"]，必需实体类型 []，可选实体类型 []。

场景 ent_scene_backup_alarm：场景名称「备电告警分析」，场景层级 1，父场景 ent_scene_root，分类 alarm，描述：分析站点备电不足告警，必需实体类型 ["site"]，可选实体类型 ["battery_backup"]，示例问句「西湖一号站备电时长是多少」，扩展问句 ["哪些站点备电不足"]。

## 流程

流程 ent_process_backup_check：流程名称「备电巡检流程」，描述：备电巡检的标准流程，动作序列 ["ent_action_query_backup"]，步骤明细 [{"step_order":1,"action_id":"ent_action_query_backup","params":{"site_id":"ent_site_001"}}]。

## 数据映射

数据映射 ent_mapping_backup_api：映射名称「站点备电取数映射」，目标实体 ID ent_battery_backup_001，映射种类 api，映射源类型 l2_to_l3_rest，执行器 text2api，API 引用 capability:getSiteBackup，设计文档引用 doc://backup-api，请求槽位映射 [{"attr":"site_id","target_slot":"siteId"}]，查询参数映射 [{"name":"date","from":"current_date"}]，响应投影 {"rows_path":"data.rows","fields":["backupHours","health"]}。
