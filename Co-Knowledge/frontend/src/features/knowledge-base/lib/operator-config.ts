/**
 * 切分配置里「操作符数据」的整理纯函数：按后缀裁剪多余项 / 序列化前去掉运行时列表 /
 * 生成表单校验字段路径。
 *
 * 注意：这三个都是**就地修改传进来的对象/数组的参数**（不是严格意义上的无副作用函数，
 * 但只碰实参、不读组件状态）；单测里要按「就地改」来断言。
 *
 * 零 Vue 依赖：不读组件状态 / i18n，可在 Node 里直接单测。
 */

/** `addOperatorValidateFields` 的最小入参：只管 `args` 数组的算子数据。 */
export interface OperatorArgsLike {
  /** 算子参数列表（缺省按空列表处理） */
  args?: unknown[] | null
}

/** `cleanOperatorList` 的最小入参：值对象允许带（也只有它需要处理）`operatorList`。 */
export interface OperatorListHolder {
  /** 算子列表 Map：只存在于内存（表单下拉用），序列化进上传 metadata 前要删掉 */
  operatorList?: unknown
}

// 移除多余的操作符数据
export function removeExcessOperatorData(fileSuffixList: string[], data: Record<string, unknown>): void {
  Object.keys(data).forEach(suffix => {
    if (!fileSuffixList.includes(suffix)) {
      delete data[suffix];
    }
  });
}

// 添加操作符验证字段
export function addOperatorValidateFields(
  validateFields: string[],
  operatorData: OperatorArgsLike | null | undefined,
  propPrefix: string
): void {
  if (operatorData) {
    validateFields.push(`${propPrefix}.operatorId`);
    const args = operatorData.args || [];
    args.forEach((arg: any, index: number) => {
      validateFields.push(`${propPrefix}.args.${index}.defaultValue`);
    });
  }
}

// 清理操作符中的列表数据
export function cleanOperatorList(operator: Record<string, OperatorListHolder>): void {
  Object.keys(operator).forEach(key => {
    delete operator[key].operatorList;
  });
}
