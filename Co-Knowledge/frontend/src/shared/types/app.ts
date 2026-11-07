// 共享类型：ComponentTheme、InputVariable。

export interface InputVariable {
  'key': string;
  'label': string;
  'sourceNode': string;
};

export interface ComponentTheme {
  theme?: 'primary' | 'orange' | 'purple' | 'purple1' | 'green' | 'pink' | 'pink1' | 'lightyellow' | 'script' | '';
  icon?: any;
  iconGray?: any;
}
