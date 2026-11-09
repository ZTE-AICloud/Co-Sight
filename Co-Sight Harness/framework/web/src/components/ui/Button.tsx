import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '../../lib/cn';
import { Icon, type IconName } from './Icon';
import styles from './Button.module.css';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger';
export type ButtonSize = 'sm' | 'md';

interface BaseButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 文字左侧的图标。图标是装饰性的，语义由文字承担。 */
  icon?: IconName;
  className?: string;
}

export interface ButtonProps extends BaseButtonProps {
  children: ReactNode;
}

/**
 * 转发 ref。删除确认框需要把初始焦点放到「取消」上（见 ConfirmDialog），
 * 而 React 18 里函数组件不转发 ref 就没法拿到那个 DOM 节点。
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, className, children, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      /*
       * 默认 type="button"。
       *
       * HTML 里 <button> 的默认 type 是 "submit"，只在表单里才有意义，
       * 但副作用是：同一个组件放进 <form> 会突然变成提交按钮。工作台里到处都是
       * 按钮、迟早会有表单把它们包起来，所以这里显式定死，需要提交时由调用方传 type="submit"。
       */
      type={type}
      className={cn(styles.button, styles[variant], styles[size], className)}
      {...rest}
    >
      {icon === undefined ? null : <Icon name={icon} />}
      {children}
    </button>
  );
});

export interface IconButtonProps extends Omit<BaseButtonProps, 'icon' | 'children'> {
  /** 必填：只有图标的按钮对读屏软件和自动化测试都无字可读。 */
  label: string;
  icon: IconName;
  /** 图标放大用。默认跟随尺寸（24 → 16px 图标）。 */
  iconSize?: number;
}

/** 只有图标的按钮（侧栏折叠、设置关闭、搜索清空、加载失败重试）。 */
export function IconButton({
  label,
  icon,
  iconSize,
  variant = 'ghost',
  size = 'sm',
  className,
  type = 'button',
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cn(styles.button, styles[variant], styles[size], styles.iconOnly, className)}
      {...rest}
    >
      <Icon name={icon} {...(iconSize === undefined ? {} : { size: iconSize })} />
    </button>
  );
}
