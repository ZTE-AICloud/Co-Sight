/**
 * 默认使用的环境配置，如本地开发
 */
export const environment = {
    production: false,
    baseApiUrl: "/api/openans-support-chatbot/v1",
    baseDeepSearchApiUrl: "/api/nae-deep-research/v1",
    // 获取csrftoken，在创建ws链接时使用
    csrfToken: () => undefined,
    // 用于设置rest请求的header中的 Forgerydefense 字段值
    forgeryDefense: () => undefined,
    hideHumanMentions: true,
    isAIS: true
};
