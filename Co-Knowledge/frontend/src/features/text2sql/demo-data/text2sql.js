// Entirely local fixtures. No database, model service or SQL engine is contacted.
export const demoDate = '2026-11-03'
export const demoDatasource = {
  id: 'text2sql-demo', name: '电商业务演示库', type: 'PostgreSQL', host: 'localhost', port: 5432,
  database: 'commerce_demo', schema: 'public', username: 'demo_readonly', passwordConfigured: true,
  status: 'indexed', scannedAt: '2026-11-03 10:00', indexedAt: '2026-11-03 10:01'
}

const column = (name, type, description, extra = {}) => ({ name, type, description, nullable: false, defaultValue: null, ...extra })
export const demoTables = [
  { name: 'order_info', description: '订单主表', rows: 12, columns: [
    column('order_id', 'bigint', '订单唯一标识', { primaryKey: true }),
    column('user_id', 'bigint', '下单用户', { foreignKey: true }),
    column('pay_amount', 'numeric(12,2)', '订单实际支付金额，单位元'),
    column('status', 'smallint', '订单状态：1 未支付 / 2 已支付 / 3 已退款', { defaultValue: '1' }),
    column('create_time', 'timestamp', '订单创建时间', { defaultValue: 'CURRENT_TIMESTAMP' })
  ] },
  { name: 'user_info', description: '用户信息表', rows: 6, columns: [
    column('user_id', 'bigint', '用户唯一标识', { primaryKey: true }),
    column('user_name', 'varchar(100)', '用户姓名'),
    column('city_id', 'integer', '用户所属城市', { foreignKey: true })
  ] },
  { name: 'region_info', description: '城市地区表', rows: 3, columns: [
    column('city_id', 'integer', '城市唯一标识', { primaryKey: true }),
    column('city_name', 'varchar(100)', '城市名称，例如西安市、咸阳市、宝鸡市')
  ] }
]

export const demoRelations = [
  { from_table: 'order_info', from_column: 'user_id', to_table: 'user_info', to_column: 'user_id' },
  { from_table: 'user_info', from_column: 'city_id', to_table: 'region_info', to_column: 'city_id' }
]
export const demoValues = [
  { table: 'region_info', column: 'city_name', value: '西安市', label: '西安', score: 0.98 },
  { table: 'region_info', column: 'city_name', value: '咸阳市', label: '咸阳', score: 0.86 },
  { table: 'region_info', column: 'city_name', value: '宝鸡市', label: '宝鸡', score: 0.84 },
  { table: 'order_info', column: 'status', value: 1, label: '未支付', score: 0.72 },
  { table: 'order_info', column: 'status', value: 2, label: '已支付', score: 0.96 },
  { table: 'order_info', column: 'status', value: 3, label: '已退款', score: 0.71 }
]

export const exampleQuestions = [
  { id: 'total', title: '支付订单总额', question: '查询最近30天支付订单总金额。', hint: '单表聚合' },
  { id: 'xian', title: '西安支付金额', question: '查询西安最近30天支付订单金额。', hint: '值匹配 · 关系补全' },
  { id: 'cities', title: '各城市支付金额', question: '查询最近30天每个城市支付订单金额。', hint: '多表关联 · 分组' },
  { id: 'top', title: '支付金额最高的城市', question: '哪个城市最近30天支付金额最高？', hint: '分组 · 排序' },
  { id: 'users', title: '最近30天付费用户', question: '最近30天有多少付费用户？', hint: '去重计数' },
  { id: 'monthly', title: '西安每月付费用户', question: '统计西安每个月的付费用户数。', hint: '按月聚合' }
]

export const demoScenarios = [
  { id: 'auto', label: '跟随问题', description: '六个示例问题与删除指令演示' },
  { id: 'unsafe', label: '写入 SQL 拦截', description: '模拟 SQL_UNSAFE' },
  { id: 'multiple', label: '多语句拦截', description: '模拟多 Statement 拒绝' },
  { id: 'column', label: '未知字段', description: '模拟 SQL_UNKNOWN_COLUMN' },
  { id: 'cost', label: '执行计划成本过高', description: '模拟 SQL_COST_TOO_HIGH' },
  { id: 'empty', label: '未召回 Schema', description: '模拟 SCHEMA_RETRIEVAL_EMPTY' },
  { id: 'model', label: '模型生成失败', description: '模拟 LLM_GENERATE_FAILED' }
]

export const pipelineStages = [
  { id: 'tables', label: 'Table Retrieval', name: '表检索', ms: 18 },
  { id: 'columns', label: 'Column Retrieval', name: '字段检索', ms: 23 },
  { id: 'values', label: 'Value Retrieval', name: '值匹配', ms: 15 },
  { id: 'relations', label: 'Relation Expansion', name: '关系补全', ms: 2 },
  { id: 'llm', label: 'SQL Generation', name: 'SQL 生成', ms: 1250 },
  { id: 'validation', label: 'SQL Validation', name: '安全校验', ms: 5 },
  { id: 'explain', label: 'EXPLAIN', name: '执行计划', ms: 8 },
  { id: 'execute', label: 'Execute', name: '只读查询', ms: 20 }
]

// The results below are computed from these fake rows, keeping all six cases consistent.
export const demoRegions = [
  { city_id: 1, city_name: '西安市' }, { city_id: 2, city_name: '咸阳市' }, { city_id: 3, city_name: '宝鸡市' }
]
export const demoUsers = [
  { user_id: 1, user_name: '陈晨', city_id: 1 }, { user_id: 2, user_name: '林悦', city_id: 1 },
  { user_id: 3, user_name: '王宁', city_id: 2 }, { user_id: 4, user_name: '李青', city_id: 2 },
  { user_id: 5, user_name: '周然', city_id: 3 }, { user_id: 6, user_name: '赵欣', city_id: 3 }
]
export const demoOrders = [
  { order_id: 1, user_id: 1, pay_amount: 52000, status: 2, create_time: '2026-10-05' },
  { order_id: 2, user_id: 1, pay_amount: 41220, status: 2, create_time: '2026-10-18' },
  { order_id: 3, user_id: 2, pay_amount: 60000, status: 2, create_time: '2026-11-02' },
  { order_id: 4, user_id: 3, pay_amount: 50000, status: 2, create_time: '2026-10-12' },
  { order_id: 5, user_id: 4, pay_amount: 32320, status: 2, create_time: '2026-11-01' },
  { order_id: 6, user_id: 5, pay_amount: 45600, status: 2, create_time: '2026-10-20' },
  { order_id: 7, user_id: 6, pay_amount: 18800, status: 2, create_time: '2026-10-29' },
  { order_id: 8, user_id: 1, pay_amount: 12000, status: 2, create_time: '2026-09-10' },
  { order_id: 9, user_id: 2, pay_amount: 9000, status: 2, create_time: '2026-09-22' },
  { order_id: 10, user_id: 2, pay_amount: 8000, status: 1, create_time: '2026-10-10' },
  { order_id: 11, user_id: 3, pay_amount: 4500, status: 3, create_time: '2026-10-15' },
  { order_id: 12, user_id: 6, pay_amount: 6600, status: 1, create_time: '2026-11-02' }
]
