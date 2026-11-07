import { QUERY_BASE } from '@/shared/api/endpoints'
import { streamPost } from '@/shared/api/stream'

// 对话测试（/chat）：流式问答。上游 = 编排运行时的 `POST <prefix>/query`。
//
// **不走 axios**：见 `shared/api/stream` 的说明（XHR 拿不到增量）。
//
// 失败有两种形状，调用方都要接：
//   ① 没进入流式 —— 服务端在出第一字节前失败（未发布的工作流、参数不合法…），
//      返回真实 HTTP 状态 + `application/problem+json`；
//      nginx 层失败（502/504）连 problem 都没有，只能按状态码兜底。
//   ② 流中途失败 —— 服务端发终态 `event: error`（problem 字段同形），fetch 也可能抛错。
export function chatQueryStream (params, handlers) {
  return streamPost(`${QUERY_BASE}/query`, params, handlers)
}
