/**
 * 语言切换器（只在独立访问时出现）。
 *
 * 被宿主嵌在 iframe 里时，语言由宿主设置里的语言决定并通过 `?locale=` 下发；
 * 模块自己再摆一个切换器，就会出现「模块切了、宿主没切」的两个真相。
 * 语言名称一律用该语言本身书写（中文用户找 English，英文用户找 简体中文）。
 */

import { LOCALE_LABELS, SUPPORTED_LOCALES } from '../../i18n/locale';
import { useI18n } from '../../i18n/useI18n';
import './LanguageSwitch.css';

export function LanguageSwitch() {
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="language-switch" role="group" aria-label={t('app.language')}>
      {SUPPORTED_LOCALES.map((value) => (
        <button
          key={value}
          type="button"
          className={`language-switch__option${
            value === locale ? ' language-switch__option--on' : ''
          }`}
          aria-pressed={value === locale}
          onClick={() => {
            setLocale(value);
          }}
        >
          {LOCALE_LABELS[value]}
        </button>
      ))}
    </div>
  );
}
