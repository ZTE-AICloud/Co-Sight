<template>
  <div class="knowledge-illustration" role="img" :aria-label="$t('modules.auth.login.illustration.aria')">
    <div class="illustration-orbit orbit-outer" />
    <div class="illustration-orbit orbit-inner" />
    <div class="illustration-caption"><span /> KNOWLEDGE, IN SYNC</div>

    <svg class="knowledge-connections" viewBox="0 0 560 340" fill="none" aria-hidden="true">
      <path d="M150 95H191Q211 95 211 115V150Q211 170 231 170H280" />
      <path d="M137 170H280" />
      <path d="M150 245H191Q211 245 211 225V190Q211 170 231 170H280" />
      <path class="connection-output" d="M320 170H370Q390 170 390 190V257" />
      <circle cx="211" cy="170" r="4" />
      <circle cx="390" cy="196" r="4" />
    </svg>

    <div class="knowledge-source source-docs"><span class="source-symbol blue"><Document /></span><span><b>{{ $t('modules.auth.login.illustration.docsTitle') }}</b><small>{{ $t('modules.auth.login.illustration.docsDesc') }}</small></span><span class="source-dot" /></div>
    <div class="knowledge-source source-graph"><span class="source-symbol purple"><Share /></span><span><b>{{ $t('modules.auth.login.illustration.graphTitle') }}</b><small>{{ $t('modules.auth.login.illustration.graphDesc') }}</small></span><span class="source-dot" /></div>
    <div class="knowledge-source source-data"><span class="source-symbol cyan"><Coin /></span><span><b>{{ $t('modules.auth.login.illustration.dataTitle') }}</b><small>{{ $t('modules.auth.login.illustration.dataDesc') }}</small></span><span class="source-dot" /></div>

    <div class="knowledge-hub"><div class="hub-mark"><BrandMark /></div><span>{{ $t('modules.auth.login.illustration.hubTitle') }}</span><small>Retrieve · Connect · Generate</small></div>
    <div class="answer-preview">
      <div class="answer-heading"><span class="answer-spark"><SparkleIcon /></span><b>{{ $t('modules.auth.login.illustration.answerTitle') }}</b><span class="answer-ready"><Check /> {{ $t('modules.auth.login.illustration.answerReady') }}</span></div>
      <p>{{ $t('modules.auth.login.illustration.answerLine1') }}<br />{{ $t('modules.auth.login.illustration.answerLine2') }}</p>
      <div class="answer-citations"><span><Document /> {{ $t('modules.auth.login.illustration.citationDocs') }}</span><span><Share /> {{ $t('modules.auth.login.illustration.citationGraph') }}</span><span class="citation-count">{{ $t('modules.auth.login.illustration.citationCount') }} <Right /></span></div>
    </div>
    <div class="illustration-note"><span /> {{ $t('modules.auth.login.illustration.note') }}</div>
  </div>
</template>

<script setup>
import { Document, Share, Coin, Check, Right } from '@/shared/lib/icons'
import BrandMark from '@/shared/ui/BrandMark.vue'
import { SparkleIcon } from '@/shared/ui/icons'
</script>

<style scoped>
.knowledge-illustration{position:relative;width:560px;height:390px;isolation:isolate;flex-shrink:0}
.illustration-orbit{position:absolute;border:1px solid var(--rs-primary-border);border-radius:50%;opacity:.25;z-index:-1;pointer-events:none}
.orbit-outer{width:430px;height:430px;left:87px;top:-55px}
.orbit-inner{width:310px;height:310px;left:147px;top:5px}
.illustration-caption{position:absolute;top:5px;left:27px;display:flex;align-items:center;gap:9px;font-size:9px;font-weight:600;letter-spacing:2px;color:var(--rs-text-3)}
.illustration-caption>span{width:5px;height:5px;background:var(--rs-primary);border-radius:50%}
.knowledge-connections{position:absolute;inset:0;width:560px;height:340px;overflow:visible}
.knowledge-connections path{stroke:var(--rs-primary-border);stroke-width:1.5;stroke-dasharray:4 4}
.knowledge-connections .connection-output{stroke:var(--rs-primary);stroke-dasharray:none;opacity:.6}
.knowledge-connections circle{fill:var(--rs-bg-card);stroke:var(--rs-primary);stroke-width:1.5}
.knowledge-source{position:absolute;left:8px;display:flex;align-items:center;gap:12px;width:180px;min-height:66px;padding:12px;background:var(--rs-bg-card);border:1px solid var(--rs-border);border-radius:10px;box-shadow:0 4px 12px #193d7e04}
.source-docs{top:62px;left:18px;transform:rotate(-3deg)}
.source-graph{top:137px;left:0}
.source-data{top:212px;left:18px;transform:rotate(3deg)}
.source-symbol{display:grid;place-items:center;width:35px;height:38px;flex-shrink:0;border-radius:8px;color:var(--tone);background:var(--tint)}
.source-symbol svg{width:20px;height:20px}
.knowledge-source b{display:block;font-size:12px;font-weight:600;color:var(--rs-text)}
/* 英文描述比中文长得多（如 Turn experience into knowledge）：允许在卡片内换行，
   不能 nowrap，否则会溢出 180px 的卡片压到连线。两行在 66px 卡片内仍放得下。 */
.knowledge-source small{display:block;font-size:9px;color:var(--rs-text-3);margin-top:5px;line-height:1.3}
/* 状态点脱离文档流：英文标题（Knowledge graph）需要完整的一行宽度，
   点占 17px 会把标题挤成两行。定位值与原 flex 位置一致。 */
.source-dot{position:absolute;top:12px;right:10px;width:5px;height:5px;background:var(--rs-tone-green);border-radius:50%}
.knowledge-hub{position:absolute;top:104px;left:252px;display:flex;align-items:center;flex-direction:column;width:138px}
.hub-mark{display:grid;place-items:center;width:86px;height:86px;border:1px solid var(--rs-primary-border);outline:7px solid color-mix(in srgb,var(--rs-bg-card) 60%,transparent);border-radius:22px;background:linear-gradient(145deg,var(--rs-bg-card),var(--rs-bg-selected));box-shadow:0 12px 30px #1677ff12}
.hub-mark .brand-mark{width:52px;height:52px}
.knowledge-hub>span{font-size:12px;font-weight:600;margin-top:17px;color:var(--rs-text-2)}
.knowledge-hub>small{font-size:7px;letter-spacing:.4px;color:var(--rs-text-3);margin-top:6px}
.answer-preview{position:absolute;left:211px;top:257px;width:337px;padding:18px 18px 14px;background:var(--rs-bg-card);border:1px solid var(--rs-border);border-radius:12px;box-shadow:0 12px 36px #193d7e0a;transform:rotate(-2deg)}
.answer-heading{display:flex;align-items:center;gap:8px}
.answer-spark{color:var(--rs-primary);display:flex}
.answer-spark svg{width:17px;height:17px}
.answer-heading b{font-size:11px;font-weight:600}
.answer-ready{margin-left:auto;color:var(--rs-tone-green);font-size:8px;display:flex;align-items:center;gap:3px;white-space:nowrap}
.answer-ready svg{width:11px;height:11px}
.answer-preview p{color:var(--rs-text-2);font-size:10px;line-height:1.9;margin:12px 0 14px}
.answer-citations{display:flex;align-items:center;gap:6px;border-top:1px solid var(--rs-border-soft);padding-top:11px}
.answer-citations>span{display:flex;align-items:center;gap:4px;font-size:8px;padding:4px 5px;border-radius:4px;background:var(--rs-bg-soft);color:var(--rs-text-2)}
.answer-citations svg{width:10px;height:10px}
.answer-citations .citation-count{margin-left:auto;background:transparent;padding-right:0;color:var(--rs-text-3)}
.illustration-note{position:absolute;left:22px;top:321px;font-size:9px;color:var(--rs-text-3);display:flex;align-items:center;gap:7px}
.illustration-note>span{width:5px;height:5px;border-radius:50%;background:var(--rs-tone-green);box-shadow:0 0 0 3px var(--rs-tint-green)}
</style>
