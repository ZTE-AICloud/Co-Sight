// 定义一个Map，用于将布尔值映射到发布状态的字符串
export const publishMap: Map<boolean, string> = new Map([
  [true, window.aipVueInstance.$t('prompt.published')], // 如果知识库已发布，则显示'已发布'
  [false, window.aipVueInstance.$t('prompt.unPublished')] // 如果知识库未发布，则显示'未发布'
]);

// 定义一个Map，用于将可见范围的字符串映射到对应的字符串
export const visibleRangeMap: Map<'public' | 'private', string> = new Map([
  ['public', window.aipVueInstance.$t('modules.extendedManagement.public')], // 如果可见范围是公开的，则显示'公开'
  ['private', window.aipVueInstance.$t('modules.extendedManagement.private')] // 如果可见范围是私有的，则显示'私有'
]);
