import { useEffect, useState } from 'react';
import { modelsApi } from './models';
import type { ModelSummary } from './models';
import { msg } from '../../i18n/useI18n';
import { ApiError } from './client';

/**
 * 拉一次模型清单，给「选一个模型」的控件用。
 *
 * 首页和创建页都要在 Composer 右下角显示模型选择，逻辑一样 —— 抽这里，
 * 页面只管把结果喂给 <Composer model={...} />，Composer 自己不碰网络。
 *
 * 模型由框架维护，清单是「选一个」的枚举而不是分页浏览的数据：没有分页参数，
 * 一次拿全。`activeId` 是框架的「当前生效模型」，页面用它做默认选中 ——
 * 与列表同一次响应返回，不存在两次调用之间的竞态。
 */
export interface UseModelsResult {
    models: ModelSummary[];
    /** 框架当前生效的模型 id；没有生效模型时为 null */
    activeId: string | null;
    loading: boolean;
    /** 加载失败时的人话；成功为 null */
    error: string | null;
}

export function useModels(): UseModelsResult {
    const [models, setModels] = useState<ModelSummary[]>([]);
    const [activeId, setActiveId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);

        modelsApi
            .list()
            .then((result) => {
                if (cancelled) return;
                setModels(result.items);
                setActiveId(result.activeId);
            })
            .catch((err: unknown) => {
                if (cancelled) return;
                setError(describeModelsError(err));
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, []);

    return { models, activeId, loading, error };
}

/**
 * 「现在能不能发起动作」的唯一判据：必须确认有一个可用模型。
 *
 * 加载中、拉失败、清单为空**都挡** —— 三者的共同点是「此刻无法确认有可用模型」，
 * 放行只会在创建完智能体 / 发出消息之后才失败。返回 null 才可放行。
 *
 * `action` 只影响文案（「创建智能体」/「发起会话」），判定本身两处一致 ——
 * 分开写迟早会有一处只判 `length === 0`，把加载态放过去。
 */
export function modelBlockReason(
    state: Pick<UseModelsResult, 'models' | 'loading' | 'error'>,
    action: string,
): string | null {
    if (state.loading) return msg('api.modelsLoading');
    if (state.error !== null) return msg('api.modelsLoadFailedAction', { action });
    if (state.models.length === 0) return msg('api.noModelsAction', { action });
    return null;
}

/**
 * 会话自己的 `modelId` 是否还活着：清单里没有它 = 模型在框架侧被删了。
 *
 * **只在清单确认可用时下判断**：加载中 / 拉失败一律返回 null（这两种情况
 * `modelBlockReason` 已经先挡了），否则一次网络抖动就会变成「你必须重选模型」。
 * 空 id 也不在这里判 —— 那是 `session_no_model` 的事，服务端有明确说法。
 *
 * 这是发送前的预检，不是权威校验：清单可能过期、删除可能发生在发送那一瞬间，
 * 服务端那条 `session_model_missing` 兜底必须保留。
 */
export function sessionModelBlockReason(
    state: Pick<UseModelsResult, 'models' | 'loading' | 'error'>,
    sessionModelId: string | null | undefined,
): string | null {
    if (state.loading || state.error !== null) return null;
    if (sessionModelId === undefined || sessionModelId === null || sessionModelId === '') return null;
    return state.models.some((item) => item.id === sessionModelId) ? null : msg('api.modelGoneAction');
}

/**
 * 与列表页 `describeLoadError`、首页 `describeCreateError` 同源。
 *
 * 模型清单失败会让下拉不可用，含糊的报错会让人以为模型管理坏了：
 * - 请求压根没发出去（fetch 自身的 TypeError）→ 是本仓 dev server / 后端没起；
 * - ApiError → 服务端已经把「框架没起 / 令牌不对 / 被 403」翻译成人话了，直接用。
 */
function describeModelsError(err: unknown): string {
    if (err instanceof DOMException && err.name === 'AbortError') {
        return msg('api.loadTimeout');
    }
    if (err instanceof TypeError) {
        return msg('api.cannotConnect');
    }
    if (err instanceof ApiError) {
        return err.message;
    }
    return err instanceof Error ? err.message : msg('api.modelsLoadFailed');
}
