import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';

interface DialogProps {
  /**
   * 按 Esc 时调用。不传即「关不掉」—— 提交中就该传 undefined，
   * 否则用户按 Esc 关掉弹窗、操作却在后台落地了。
   */
  onDismiss?: () => void;
  /**
   * 点弹窗外的遮罩也关掉。默认**不关**：编辑弹窗里有没提交的输入，误点一下就没了。
   * 只给内边距为 0、内容自铺满的弹窗用（详情就是）—— 否则内边距那圈也算「空白」。
   */
  dismissOnBackdrop?: boolean;
  /** 附加类名，用来区分宽窄（如确认框要窄一些） */
  className?: string;
  children: ReactNode;
}

/**
 * 模态壳，用原生 `<dialog>` + `showModal()`。
 *
 * 不用手搓 overlay：全仓没有任何 backdrop / focus-trap 代码，手搓要自己写遮罩、Esc、
 * 焦点陷阱和 `role="dialog"`；原生 dialog 白送这四样，CSS 只要一条 `::backdrop`。
 *
 * 调用方**按需挂载**（`{open && <Dialog/>}`），所以「挂载即打开」。
 */
export function Dialog({ onDismiss, dismissOnBackdrop = false, className, children }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const node = ref.current;
    // StrictMode 下 effect 会跑两遍：已经 open 了再 showModal() 会抛 InvalidStateError
    if (node && !node.open) node.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      className={`al-dialog${className ? ` ${className}` : ''}`}
      // 只接 onCancel（Esc）。别改成 <form method="dialog"> 或用 onClose 复用这个语义：
      // 「提交成功」和「取消」都会触发 close，混在一起会分不清，甚至点确定反手把操作取消掉。
      onCancel={(event) => {
        event.preventDefault();
        onDismiss?.();
      }}
      // 用 pointerdown 而不是 click：遮罩上的 click，目标是按下/抬起两点的共同祖先 ——
      // 在内容里拖选文字、手滑松开到遮罩上也会命中，那一下不该被当成「点空白」。
      onPointerDown={(event) => {
        if (!dismissOnBackdrop) return;
        // 遮罩上的事件 target 就是 dialog 自己，内容区里则是子节点
        if (event.target === ref.current) onDismiss?.();
      }}
    >
      {children}
    </dialog>
  );
}
