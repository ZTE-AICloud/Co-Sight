import { useNavigate } from 'react-router';

import { useI18n } from '../i18n/useI18n';
import { Button } from '../components/ui/Button';
import { StatusPanel } from '../components/ui/StatusPanel';

/**
 * 宿主路由没匹配上。
 *
 * 与 ModuleHost 的"模块尚未接入"刻意分开：那个是**路由对了但内容没来**，
 * 这个是**地址本身不存在**。两者的下一步动作完全不同（去找模块 vs 回首页），
 * 合成一个页面会让用户不知道该改什么。
 */
export function NotFoundPage() {
  const { t } = useI18n();
  const navigate = useNavigate();

  return (
    <StatusPanel
      icon="empty"
      title={t('error.notFound.title')}
      hint={t('error.notFound.hint')}
      action={
        <Button
          variant="primary"
          onClick={() => {
            void navigate('/');
          }}
        >
          {t('error.notFound.back')}
        </Button>
      }
    />
  );
}
