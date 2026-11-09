/**
 * 密钥 / 令牌的草稿状态（D26：只写不读）。
 *
 * 读侧永远拿不到明文，只有 `hasApiKey` / `hasToken` 这种布尔。于是"编辑一个已经
 * 配好密钥的条目"在界面上必然表现为**空输入框**，而空输入框在提交时的含义必须由
 * 一个额外的状态补全，否则同一个"空"会同时表示三件不同的事：
 *
 * - 新建时留空   → 不设置（`null`）
 * - 编辑时留空   → 保持原密钥（`undefined`，JSON 序列化时这个键会消失）
 * - 点过「清除」 → 删除已存的密钥（`null`）
 *
 * 这就是 `clearing` 存在的唯一理由。它是**待保存的意图**，不是立即生效的动作：
 * 用户点「清除密钥」的真实动机常常只是"想改个名字时顺手点错了"，而密钥一旦删掉
 * 服务端也读不回来（明文本来就不回显），只能重新去供应商那里生成。所以清除要等到
 * 按「保存」才落库，并且在按钮上明说这一步还没有发生。
 */

export interface SecretDraft {
  /** 输入框里的内容；**永远是空串或用户刚敲进去的东西**，绝不回显已存的密钥。 */
  value: string;
  /** 「清除」的待保存意图。 */
  clearing: boolean;
}

/** 初值：空输入框 + 不打算清除。共享同一个对象是安全的——下面是纯函数，没有人改它。 */
export const EMPTY_SECRET: SecretDraft = { value: '', clearing: false };

/**
 * 敲进新密钥。
 *
 * 不需要旧的草稿：结果只取决于刚敲进去的值。这也顺带**撤销**"将清除"——两个意图
 * 同时成立时没有确定的行为，而"用户刚敲的字符被忽略、提交时却把密钥删了"
 * 是其中最坏的一种。
 *
 * **不做 trim**：密钥是粘贴进来的原样内容，尾部的空格可能是它的一部分；
 * 而名称、地址那类字段的 trim 由服务端 schema 负责，这里不必抢着做。
 */
export function typeSecret(value: string): SecretDraft {
  return { value, clearing: false };
}

/** 点「清除密钥」/「将清除（点此撤销）」。 */
export function toggleClear(draft: SecretDraft): SecretDraft {
  return { ...draft, clearing: !draft.clearing };
}

export type SecretMode = 'create' | 'edit';

/*
 * 两个重载把"新建时不可能出现 `undefined`"这件事写进类型里：创建接口的
 * `apiKey: string | null`（带 default）本就不接受缺省，若只有一个联合返回类型，
 * 调用点就得自己断言或退让成 `?? null`——而后者会把将来某次真正的"漏传"掩盖掉。
 */
export function resolveSecret(draft: SecretDraft, mode: 'create'): string | null;
export function resolveSecret(draft: SecretDraft, mode: 'edit'): string | null | undefined;

/**
 * 草稿 → 请求体里的密钥字段。
 *
 * 返回值直接对应契约的三态。**绝不能**把留空映射成空串：服务端对密钥是
 * `min(1)`，空串会被判成 422，用户看到的是"请求参数校验未通过"——
 * 一句既不指向字段、也不指向原因的话。
 *
 * 编辑态里 `clearing` 优先于输入框内容：按钮上写着"将清除"，此时用户又敲了新值
 * 的话 `typeSecret` 已经把 `clearing` 撤掉了，所以两者同时为真只可能来自直接构造的
 * 数据，按"清除"处理至少与按钮显示的那句话一致。
 */
export function resolveSecret(draft: SecretDraft, mode: SecretMode): string | null | undefined {
  if (mode === 'create') {
    // 新建时没有"原值"可保持，`clearing` 也就无从谈起（界面上不会出现那个按钮）。
    return draft.value === '' ? null : draft.value;
  }
  if (draft.clearing) {
    return null;
  }
  return draft.value === '' ? undefined : draft.value;
}
