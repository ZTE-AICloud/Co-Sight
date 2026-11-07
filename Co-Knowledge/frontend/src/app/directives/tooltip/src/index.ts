// v-tooltip.ts
import { createVNode, render, Directive, DirectiveBinding, nextTick } from 'vue';
import { ElTooltip, type ElTooltipProps } from 'element-plus';
// import { configureCompat } from 'vue';

export type TableOverflowTooltipOptions = Partial<
  Pick<
    ElTooltipProps,
    | 'appendTo'
    | 'effect'
    | 'enterable'
    | 'hideAfter'
    | 'offset'
    | 'placement'
    | 'popperClass'
    | 'popperOptions'
    | 'showAfter'
    | 'showArrow'
    | 'transition'
  >
>

interface TooltipBinding {
  text: string;
  props: TableOverflowTooltipOptions
}

interface ExtendedHTMLElement extends HTMLElement {
  __tooltipContent?: string;
  __tooltipVisible?: boolean;
  __removeTooltip?: () => void;
  __showTooltip?: (() => void) | null;
  __hideTooltip?: (() => void) | null;
  __resizeListener: (() => void) | null;
}

type RemovePopperFn = (() => void) & {
  trigger?: HTMLElement
}

let removeTooltip: RemovePopperFn | null = null
export const vTooltip: Directive<ExtendedHTMLElement, TooltipBinding> = {
  beforeMount (el: ExtendedHTMLElement, binding: DirectiveBinding<TooltipBinding>) {
    // 使用 extend HTMLElement interface 来添加属性
    extendHTMLElement(el, binding);
  },
  updated (el: ExtendedHTMLElement, binding: DirectiveBinding<TooltipBinding>) {
    extendHTMLElement(el, binding);
  },
  mounted (el: ExtendedHTMLElement, binding: DirectiveBinding<TooltipBinding>) {
    const showTooltip: RemovePopperFn = () => {
      if (isOver(el)) {
        if (removeTooltip?.trigger === el) {
          return
        }
        removeTooltip?.()
        el.__tooltipVisible = true;
        const popperOptions = {
          strategy: 'fixed',
          ...binding.value.props?.popperOptions,
        }
        const popperClass = `ai-v-tooltip ${binding.value.props?.popperClass || ''}`
        const vm = createVNode(ElTooltip, {
          content: el.__tooltipContent,
          virtualTriggering: true,
          virtualRef: getEle(el, 'div'),
          appendTo: getEle(el, 'body') || getEle(el, 'div'),
          placement: 'top',
          transition: 'none',
          offset: 12,
          hideAfter: 200,
          effect: 'light',
          ...binding.value.props,
          popperOptions,
          popperClass,
          onHide: () => {
            removeTooltip?.()
          }
        });
        const container = document.createElement('div');
        nextTick(() => {
          render(vm, container);
          vm.component!.exposed!.onOpen();
        })
        removeTooltip = () => {
          render(null, container);
          removeTooltip = null;
        };
        removeTooltip.trigger = el;
      } else {
        el.__tooltipVisible = false;
        removeTooltip?.();
      }
    };

    const hideTooltip: RemovePopperFn = () => {
      el.__tooltipVisible = false;
      removeTooltip?.();
    };
    if (!el.__showTooltip) {
      el.__showTooltip = showTooltip;
      el.addEventListener('mouseenter', el.__showTooltip, true);
    }

    el.__removeTooltip = () => {
      if (el.__showTooltip) {
        el.removeEventListener('mouseenter', el.__showTooltip);
        el.__showTooltip = null;
      }
      hideTooltip();
    };
  },
  beforeUnmount (el: ExtendedHTMLElement) {
    el.__removeTooltip?.();
  }
};

function extendHTMLElement (el: ExtendedHTMLElement, binding: DirectiveBinding<TooltipBinding>) {
  el.__tooltipContent = binding.value?.text as any;
  if (!el.__tooltipVisible) {
    el.__tooltipVisible = false;
  }
}

function isOver (el: ExtendedHTMLElement) {
  const range = document.createRange()
  range.setStart(el, 0)
  range.setEnd(el, el.childNodes.length)
  const { width: rangeWidth, height: rangeHeight } =
      range.getBoundingClientRect()
  const { width: cellChildWidth, height: cellChildHeight } =
    el.getBoundingClientRect()

  const { top, left, right, bottom } = getPadding(el)
  const horizontalPadding = left + right
  const verticalPadding = top + bottom
  return (isGreaterThan(rangeWidth + horizontalPadding, cellChildWidth) ||
    isGreaterThan(rangeHeight + verticalPadding, cellChildHeight))
  // ||
  // isGreaterThan(el.scrollWidth, cellChildWidth)
}

const getPadding = (el: HTMLElement) => {
  const style = window.getComputedStyle(el, null)
  const paddingLeft = Number.parseInt(style.paddingLeft, 10) || 0
  const paddingRight = Number.parseInt(style.paddingRight, 10) || 0
  const paddingTop = Number.parseInt(style.paddingTop, 10) || 0
  const paddingBottom = Number.parseInt(style.paddingBottom, 10) || 0
  return {
    left: paddingLeft,
    right: paddingRight,
    top: paddingTop,
    bottom: paddingBottom
  }
}
const EPSILON = 0.03
function isGreaterThan (a: number, b: number, epsilon = EPSILON) {
  return a - b > epsilon
}

function getEle (el: HTMLElement, tagName: string) {
  return el?.closest(tagName)
};
