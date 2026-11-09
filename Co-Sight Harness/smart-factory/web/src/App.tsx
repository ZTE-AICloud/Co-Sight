import { useEffect } from 'react';
import { BrowserRouter, Navigate, NavLink, Route, Routes } from 'react-router-dom';
import { AgentCreatePage } from './features/agent-create/AgentCreatePage';
import { AgentListPage } from './features/agent-list/AgentListPage';
import { HomePage } from './features/home/HomePage';
import { WorkshopPage } from './features/skill-workshop/WorkshopPage';
import { useI18n } from './i18n/useI18n';
import { LanguageSwitch } from './shared/components/LanguageSwitch';
import { isEmbedded } from './shared/embed';

/**
 * 应用外壳：左侧导航 + 路由出口。
 *
 * 外壳**只在独立访问时**才带左侧导航：被框架嵌在 iframe 里时导航归宿主页面，模块自己
 * 再挂一条就是两个导航打架（判据与调试开关见 `shared/embed.ts`）。收掉侧边栏不需要动
 * 样式 —— `.app-shell` 是 flex、`.app-main` 是 `flex: 1`，aside 一没了它自然占满。
 *
 * 路由按资源命名，一个资源一个命名空间：
 *   /                       → features/home         → 模块落地页：一句话登记一个专家
 *   /agents                 → features/agent-list   → 专家列表（server modules/agent）
 *   /agents?tab=skills      → 同一个页面切到技能库 tab（features/skill-library）
 *   /skills                 → 重定向到 `/agents?tab=skills`（首页快捷卡与文档里的旧落点）
 *   /workshop               → features/skill-workshop → 技能线的工作台（目录会话，cwd = 技能库根）
 *                             `?target=&name=` 从技能卡「优化」进来；`?session=` 恢复一场
 *   /agents/:agentId/design → features/agent-create → 某个专家的设计页（development 阶段那场会话）
 *                             `?stage=preview|evaluation` 进来直接停在那个阶段
 *                             （卡底「评估」的落点，见 `AgentCreatePage` 的 `readStageParam`）
 *
 * 落地页就是 `/`，不再套一层 `/home`：宿主 iframe 的入口本来就是模块根地址（模块清单的
 * `entry`），多一次重定向只会多一闪，也不会让地址栏多一些信息。
 *
 * `/agents/:agentId/design` 是**围着某一个专家转**的页，只在路径里带 agentId 时才存在
 * （顶栏身份、工作目录、会话上下文都从它来）。路由段仍叫 `design`：这个专家已经建出来了，
 * 这一页在做的是「设计」；卡底那颗动作按钮 2026-10-30 起改叫「构建」，只在文案上跟
 * 「Harness工程构建」对齐，路由与键名不动。所以：
 *   - 侧边栏没有它的入口，入口只有专家卡底的「构建」
 *   - 卡片 / 详情弹窗上的「使用」**不落在本模块**：它是整页跳去框架首页（会话页），
 *     见 `features/agent-list/AgentListPage.tsx` 的 `useExpertInFramework`
 *
 * 旧地址一律不做兼容跳转：项目还没发布，没有需要养着的老书签；留着只会让路由表里多出
 * 没有页面的入口，读代码时还得先分辨哪条是正主。
 *
 * ⚠️ 正确路径是 `/agents/:agentId/design`。写成 `/agent-create/:id`、`/agent/:id/design`
 * 这类前缀**不会报错**：它会落进下面的 `*` 兜底，被静默送回 `/`。首页登记完专家跳设计页
 * 曾经就这么错过一次 —— 智能体建出来了，页面却像什么都没发生（静默失败，最难查的一种）。
 *
 * 导航的文案与路由的段名**不是一回事**：文案是给人看的（「Harness工程构建」/「专家·技能」），
 * 段名是接口路径的投影（`/agents` 对 `GET /agents`；技能库没有自己的资源段，
 * 它是这个页面上的一个 tab）。
 */
export function App() {
  const { t } = useI18n();
  // 嵌态不挂左侧导航。每渲染一次判一次：`?embed=` 是读地址的，地址变了得跟着变
  const embedded = isEmbedded();

  // 标签页标题跟着语言走：index.html 里的静态标题只对首帧负责
  useEffect(() => {
    document.title = t('app.title');
  }, [t]);

  return (
    <BrowserRouter>
      <div className="app-shell">
        {!embedded && (
          <aside className="app-sidebar">
            <div className="app-brand">
              <span className="app-brand__name">{t('app.brandName')}</span>
              <span className="app-brand__sub">{t('app.brandSub')}</span>
            </div>
            <nav className="app-nav">
              <NavLink to="/agents" className="app-nav__link">
                {t('app.nav.expertsAndSkills')}
              </NavLink>
              {/* `end`：没有它，`/` 会匹配所有地址，两个入口会同时高亮 */}
              <NavLink to="/" end className="app-nav__link">
                {t('app.nav.createAgent')}
              </NavLink>
            </nav>
            <div className="app-sidebar__footer">
              <LanguageSwitch />
            </div>
          </aside>
        )}

        <main className="app-main">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/agents" element={<AgentListPage />} />
            {/*
              技能库与专家列表同页，tab 由 `?tab=` 决定。保留 `/skills` 这条短地址并
              重定向过去：首页快捷卡、`capability-routing.md` 与外部记录里写的都是它，
              前端自己改口没有意义（重定向只多一跳，不会落在 `*` 兜底里）。
            */}
            <Route path="/skills" element={<Navigate to="/agents?tab=skills" replace />} />
            {/*
              工坊没有侧栏入口：它从首页的能力 / 技能卡「优化 / 历史」进来。
              cwd 由页面自己从 `GET /skills` 拿（前端不拼 `{COSIGHT_HOME}`）。
            */}
            <Route path="/workshop" element={<WorkshopPage />} />
            <Route path="/agents/:agentId/design" element={<AgentCreatePage />} />
            {/* 兜底：任何没命中的地址回落地页（模块内部没有 404 页） */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
