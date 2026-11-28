import { demoTables } from './text2sql.js'

// Additional metadata is for scale testing only; executable examples still use the original three tables.
const domains = [
  ['交易', ['order_item:订单明细', 'order_payment:支付流水', 'order_refund:退款记录', 'order_delivery:配送记录', 'order_address:订单地址', 'order_invoice:订单发票', 'order_status_log:订单状态日志', 'order_discount:订单优惠']],
  ['客户', ['customer_profile:客户档案', 'customer_contact:客户联系方式', 'customer_address:客户地址', 'customer_tag:客户标签', 'customer_segment:客户分群', 'customer_level:会员等级', 'customer_points:积分流水', 'customer_visit:客户访问']],
  ['商品库存', ['product_info:商品档案', 'product_sku:商品规格', 'product_category:商品分类', 'product_brand:品牌信息', 'inventory_stock:库存台账', 'inventory_change:库存变动', 'warehouse_info:仓库信息', 'supplier_info:供应商信息']],
  ['营销', ['campaign_info:营销活动', 'campaign_channel:活动渠道', 'coupon_info:优惠券', 'coupon_usage:优惠券使用', 'promotion_rule:促销规则', 'advertising_plan:广告计划', 'advertising_cost:广告费用', 'channel_conversion:渠道转化']],
  ['财务', ['finance_account:财务账户', 'finance_settlement:结算记录', 'finance_reconciliation:对账明细', 'finance_receivable:应收账款', 'finance_payable:应付账款', 'finance_invoice:财务发票', 'finance_expense:费用记录', 'finance_budget:预算记录']],
  ['运营', ['operation_event:运营事件', 'operation_task:运营任务', 'service_ticket:服务工单', 'service_feedback:客户反馈', 'system_user:系统用户', 'system_role:系统角色', 'audit_log:操作审计']]
]
let index = 0
export const scaleTables = [
  ...demoTables.map(table => ({ ...table, group: table.name === 'order_info' ? '交易' : table.name === 'user_info' ? '客户' : '基础资料' })),
  ...domains.flatMap(([group, entries]) => entries.map(entry => {
    const [name, label] = entry.split(':'); const missing = index++ % 4 === 0
    return { name, label, group, description: missing ? '' : label, rows: 0, metadataOnly: true,
      columns: [{ name: 'id', type: 'bigint', description: '记录唯一标识', primaryKey: true }, { name: 'business_no', type: 'varchar(64)', description: '业务编号' }, { name: 'status', type: 'smallint', description: '业务状态' }, { name: 'created_at', type: 'timestamp', description: '记录创建时间' }] }
  }))
]
export const sourceTables = source => (source?.catalog === 'commerce50' ? scaleTables : demoTables)
export const sourceTableNames = source => sourceTables(source).map(table => table.name)
export const tableLabel = table => table.description || table.label || table.name
export const tableDescription = (table, descriptions = {}) => (Object.hasOwn(descriptions, table.name) ? descriptions[table.name] : table.description || '')

export function updateTableSelection (current, names, checked) {
  const next = new Set(current)
  for (const name of names) {
    if (checked) {
      next.add(name);
    } else {
      next.delete(name)
    }
  }
  return [...next]
}
