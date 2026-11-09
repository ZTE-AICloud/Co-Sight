import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';

import conversationShot from '../assets/guide/conversation.png';
import expertsShot from '../assets/guide/experts.png';
import harnessShot from '../assets/guide/harness-build.png';
import knowledgeShot from '../assets/guide/knowledge.png';
import observabilityShot from '../assets/guide/observability.png';
import { Button } from '../components/ui/Button';
import { Icon, type IconName } from '../components/ui/Icon';
import { cn } from '../lib/cn';
import { useI18n } from '../i18n/useI18n';
import type { MessageKey } from '../i18n/types';
import { useUiStore } from '../stores/ui';
import styles from './GuidePage.module.css';

/**
 * 使用说明页（`/guide`，侧栏底部的问号入口）。
 *
 * 这页不是 README 的搬运：它按**第一次使用的顺序**组织（模型 → 工作区 → 对话），
 * 每一步都给一个能直接执行的动作。用户看完第一步就可以点「去配置模型」，
 * 不需要在"文档"和"设置"之间来回找。
 *
 * 内容以仓库根目录的 QUICKSTART.md 与产品实际交互为准。功能地图配了各入口的
 * 截图（取自内部使用说明页），因为"这个按钮长什么样"是新手最缺的信息；
 * 截图会随改版过期，所以每张都写清 alt，界面对不上时也好知道该换哪张。
 *
 * 页面是宿主自己的内容，不走 ModuleHost：帮助文档不该依赖运行期扫描出来的模块清单，
 * 模块没接入时也不能变成"尚未接入"。
 */

type GuideKey = Extract<MessageKey, `guide.${string}`>;
type TocKey = Extract<MessageKey, `guide.toc.${string}`>;

interface TocItem {
  id: string;
  labelKey: TocKey;
}

interface Step {
  /** 步骤标识用语义图标，而不是再排一套 01/02/03。 */
  icon: IconName;
  titleKey: GuideKey;
  bodyKey: GuideKey;
  actionKey: GuideKey;
  onAction: () => void;
}

interface ModuleCard {
  icon: IconName;
  /** 入口截图。打包时由 Vite 生成带哈希的地址。 */
  image: string;
  titleKey: GuideKey;
  bodyKey: GuideKey;
  altKey: GuideKey;
}

/** 页内大图预览。点任意一张截图进入，再点一下或按 Esc 关闭。 */
interface PreviewImage {
  src: string;
  alt: string;
}

interface FaqItem {
  questionKey: GuideKey;
  answerKey: GuideKey;
}

/*
 * 元组而不是数组：第一节是"页面顶部的默认章节"，代码里会直接取 `TOC[0]`。
 * 标成非空元组后，这个默认值在类型上就是确定的，不用在渲染时再做一次判空。
 */
const TOC = [
  { id: 'quickstart', labelKey: 'guide.toc.quickstart' },
  { id: 'model', labelKey: 'guide.toc.model' },
  { id: 'workspace', labelKey: 'guide.toc.workspace' },
  { id: 'modules', labelKey: 'guide.toc.modules' },
  { id: 'faq', labelKey: 'guide.toc.faq' },
] as const satisfies readonly [TocItem, ...TocItem[]];

const MODULE_CARDS: readonly ModuleCard[] = [
  {
    icon: 'newChat',
    image: conversationShot,
    titleKey: 'guide.modules.conversationTitle',
    bodyKey: 'guide.modules.conversationBody',
    altKey: 'guide.modules.conversationAlt',
  },
  {
    icon: 'experts',
    image: expertsShot,
    titleKey: 'guide.modules.expertsTitle',
    bodyKey: 'guide.modules.expertsBody',
    altKey: 'guide.modules.expertsAlt',
  },
  {
    icon: 'agentDev',
    image: harnessShot,
    titleKey: 'guide.modules.agentDevTitle',
    bodyKey: 'guide.modules.agentDevBody',
    altKey: 'guide.modules.agentDevAlt',
  },
  {
    icon: 'knowledge',
    image: knowledgeShot,
    titleKey: 'guide.modules.knowledgeTitle',
    bodyKey: 'guide.modules.knowledgeBody',
    altKey: 'guide.modules.knowledgeAlt',
  },
  {
    icon: 'observability',
    image: observabilityShot,
    titleKey: 'guide.modules.observabilityTitle',
    bodyKey: 'guide.modules.observabilityBody',
    altKey: 'guide.modules.observabilityAlt',
  },
];

const FAQ_ITEMS: readonly FaqItem[] = [
  {
    questionKey: 'guide.faq.knowledgeQ',
    answerKey: 'guide.faq.knowledgeA',
  },
  {
    questionKey: 'guide.faq.modelQ',
    answerKey: 'guide.faq.modelA',
  },
  {
    questionKey: 'guide.faq.languageQ',
    answerKey: 'guide.faq.languageA',
  },
  {
    questionKey: 'guide.faq.addressQ',
    answerKey: 'guide.faq.addressA',
  },
];

export function GuidePage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const openSettings = useUiStore((state) => state.openSettings);
  const openWorkspace = useUiStore((state) => state.openWorkspace);

  /** 滚动容器。目录高亮要监听它的 scroll，而不是 window。 */
  const pageRef = useRef<HTMLDivElement>(null);
  const [activeId, setActiveId] = useState<string>(TOC[0].id);
  const [preview, setPreview] = useState<PreviewImage | null>(null);

  /*
   * 目录高亮：取"已经滚过阅读线"的最后一个章节。
   * 不挂 IntersectionObserver——章节高度差得太多，阈值很难同时适配短章节和长章节；
   * 直接读每节标题相对滚动容器的位置，结果稳定也更符合"当前读到哪"的直觉。
   */
  useEffect(() => {
    const scroller = pageRef.current;
    if (scroller === null) {
      return;
    }

    const READING_LINE = 140;
    const update = () => {
      // 回到顶部时固定第一节，避免第一条还没滚进阅读线就没有高亮。
      if (scroller.scrollTop <= 0) {
        setActiveId(TOC[0].id);
        return;
      }

      const line = scroller.getBoundingClientRect().top + READING_LINE;
      let current: string = TOC[0].id;
      for (const item of TOC) {
        const section = document.getElementById(item.id);
        if (section !== null && section.getBoundingClientRect().top <= line) {
          current = item.id;
        }
      }
      setActiveId(current);
    };

    update();
    scroller.addEventListener('scroll', update, { passive: true });
    return () => {
      scroller.removeEventListener('scroll', update);
    };
  }, []);

  /* Esc 关闭预览；打开时监听一次，关闭后摘掉，不给全局留监听。 */
  useEffect(() => {
    if (preview === null) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPreview(null);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [preview]);

  const steps: readonly Step[] = [
    {
      icon: 'settings',
      titleKey: 'guide.quickstart.model.title',
      bodyKey: 'guide.quickstart.model.body',
      actionKey: 'guide.quickstart.model.action',
      onAction: () => {
        openSettings('model');
      },
    },
    {
      icon: 'workspace',
      titleKey: 'guide.quickstart.workspace.title',
      bodyKey: 'guide.quickstart.workspace.body',
      actionKey: 'guide.quickstart.workspace.action',
      onAction: openWorkspace,
    },
    {
      icon: 'newChat',
      titleKey: 'guide.quickstart.chat.title',
      bodyKey: 'guide.quickstart.chat.body',
      actionKey: 'guide.quickstart.chat.action',
      onAction: () => {
        void navigate('/');
      },
    },
  ];

  return (
    <div ref={pageRef} className={styles.page}>
      <div className={styles.inner}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}>{t('guide.eyebrow')}</span>
          <h1 className={styles.title}>{t('guide.title')}</h1>
          <p className={styles.lead}>{t('guide.lead')}</p>
          <div className={styles.heroActions}>
            <Button
              variant="primary"
              icon="newChat"
              onClick={() => {
                void navigate('/');
              }}
            >
              {t('guide.startChat')}
            </Button>
            <Button
              icon="settings"
              onClick={() => {
                openSettings('model');
              }}
            >
              {t('guide.configureModel')}
            </Button>
          </div>
        </header>

        <div className={styles.body}>
          {/*
           * 目录是页内锚点而不是路由：说明页只有一个地址，分享时指过来就能看到全貌；
           * 章节切换不该产生新的历史记录，否则浏览器"后退"要按很多次才能离开。
           */}
          <nav className={styles.toc} aria-label={t('guide.tocLabel')}>
            <span className={styles.tocHeading} aria-hidden="true">
              {t('guide.tocLabel')}
            </span>
            {TOC.map((item, index) => {
              const isActive = item.id === activeId;
              return (
                <a
                  key={item.id}
                  className={cn(styles.tocLink, isActive && styles.tocLinkActive)}
                  href={`#${item.id}`}
                  aria-current={isActive ? 'location' : undefined}
                >
                  {/* 序号与右侧章节的 01–05 对齐，目录本身也读得出一条进度。 */}
                  <span className={styles.tocIndex} aria-hidden="true">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span>{t(item.labelKey)}</span>
                </a>
              );
            })}
          </nav>

          <article className={styles.content}>
            <section id="quickstart" className={styles.section} aria-labelledby="guide-quickstart">
              <header className={styles.sectionHead}>
                <span className={styles.sectionIndex} aria-hidden="true">
                  01
                </span>
                <h2 id="guide-quickstart" className={styles.sectionTitle}>
                  {t('guide.quickstart.title')}
                </h2>
              </header>
              <p className={styles.sectionLead}>{t('guide.quickstart.lead')}</p>

              <ol className={styles.steps}>
                {steps.map((step) => (
                  <li key={step.titleKey} className={styles.step}>
                    <span className={styles.stepIcon} aria-hidden="true">
                      <Icon name={step.icon} size={18} />
                    </span>
                    <div className={styles.stepText}>
                      <h3 className={styles.stepTitle}>{t(step.titleKey)}</h3>
                      <p className={styles.stepBody}>{t(step.bodyKey)}</p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className={cn(styles.stepAction)}
                      onClick={step.onAction}
                    >
                      {t(step.actionKey)}
                      <Icon
                        name="chevronRight"
                        size={14}
                        className={cn(styles.stepArrow)}
                      />
                    </Button>
                  </li>
                ))}
              </ol>
            </section>

            <section id="model" className={styles.section} aria-labelledby="guide-model">
              <header className={styles.sectionHead}>
                <span className={styles.sectionIndex} aria-hidden="true">
                  02
                </span>
                <h2 id="guide-model" className={styles.sectionTitle}>
                  {t('guide.model.title')}
                </h2>
              </header>
              <p className={styles.sectionLead}>{t('guide.model.lead')}</p>

              <h3 className={styles.subTitle}>{t('guide.model.fieldsTitle')}</h3>
              <ul className={styles.list}>
                <li>{t('guide.model.fieldSupplier')}</li>
                <li>{t('guide.model.fieldName')}</li>
                <li>{t('guide.model.fieldId')}</li>
                <li>{t('guide.model.fieldGateway')}</li>
                <li>{t('guide.model.fieldKey')}</li>
              </ul>

              <div className={styles.noteGrid}>
                <div className={styles.note}>
                  <h3 className={styles.noteTitle}>{t('guide.model.currentTitle')}</h3>
                  <p className={styles.noteBody}>{t('guide.model.currentBody')}</p>
                </div>
                <div className={styles.note}>
                  <h3 className={styles.noteTitle}>{t('guide.model.paramsTitle')}</h3>
                  <p className={styles.noteBody}>{t('guide.model.paramsBody')}</p>
                </div>
              </div>
            </section>

            <section id="workspace" className={styles.section} aria-labelledby="guide-workspace">
              <header className={styles.sectionHead}>
                <span className={styles.sectionIndex} aria-hidden="true">
                  03
                </span>
                <h2 id="guide-workspace" className={styles.sectionTitle}>
                  {t('guide.workspace.title')}
                </h2>
              </header>
              <p className={styles.sectionLead}>{t('guide.workspace.lead')}</p>

              <ul className={styles.list}>
                <li>{t('guide.workspace.itemName')}</li>
                <li>{t('guide.workspace.itemDir')}</li>
                <li>{t('guide.workspace.itemModel')}</li>
                <li>{t('guide.workspace.itemProxy')}</li>
              </ul>
              <p className={styles.tip}>{t('guide.workspace.tip')}</p>
            </section>

            <section id="modules" className={styles.section} aria-labelledby="guide-modules">
              <header className={styles.sectionHead}>
                <span className={styles.sectionIndex} aria-hidden="true">
                  04
                </span>
                <h2 id="guide-modules" className={styles.sectionTitle}>
                  {t('guide.modules.title')}
                </h2>
              </header>
              <p className={styles.sectionLead}>{t('guide.modules.lead')}</p>

              <div className={styles.moduleGrid}>
                {MODULE_CARDS.map((card) => {
                  const alt = t(card.altKey);
                  return (
                    <article key={card.titleKey} className={styles.moduleCard}>
                      {/*
                       * 截图会随界面改版过期，但"入口长什么样"是新手最缺的信息。
                       * 点击在当前页放大，不跳新标签页——说明页读一半被带走很打断。
                       */}
                      <button
                        type="button"
                        className={styles.shotButton}
                        onClick={() => {
                          setPreview({ src: card.image, alt });
                        }}
                        aria-label={alt}
                      >
                        <img className={styles.shot} src={card.image} alt={alt} loading="lazy" />
                      </button>
                      <div className={styles.moduleText}>
                        <span className={styles.cardIcon}>
                          <Icon name={card.icon} size={16} />
                        </span>
                        <h3 className={styles.cardTitle}>{t(card.titleKey)}</h3>
                        <p className={styles.cardBody}>{t(card.bodyKey)}</p>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>

            <section id="faq" className={styles.section} aria-labelledby="guide-faq">
              <header className={styles.sectionHead}>
                <span className={styles.sectionIndex} aria-hidden="true">
                  05
                </span>
                <h2 id="guide-faq" className={styles.sectionTitle}>
                  {t('guide.faq.title')}
                </h2>
              </header>

              <div className={styles.faqList}>
                {FAQ_ITEMS.map((item) => (
                  <details key={item.questionKey} className={styles.faqItem}>
                    <summary className={styles.faqSummary}>
                      <span>{t(item.questionKey)}</span>
                      <Icon name="chevronDown" size={16} className={styles.faqChevron} />
                    </summary>
                    <p className={styles.faqAnswer}>{t(item.answerKey)}</p>
                  </details>
                ))}
              </div>
            </section>

            <p className={styles.footerHint}>{t('guide.footerHint')}</p>
          </article>
        </div>
      </div>

      {/*
       * 大图预览：铺满整个页面（fixed），点任意位置——包括图片本身——关闭，
       * 所以不拦冒泡。Esc 是给键盘用户的等价出口。
       */}
      {preview === null ? null : (
        <div
          className={styles.preview}
          role="dialog"
          aria-modal="true"
          aria-label={preview.alt}
          onClick={() => {
            setPreview(null);
          }}
        >
          <button
            type="button"
            className={styles.previewClose}
            aria-label={t('guide.previewClose')}
            onClick={() => {
              setPreview(null);
            }}
            autoFocus
          >
            <Icon name="close" size={18} />
          </button>
          <img className={styles.previewImage} src={preview.src} alt={preview.alt} />
        </div>
      )}
    </div>
  );
}
