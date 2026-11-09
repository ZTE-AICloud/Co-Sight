import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { applyHtmlLang } from './i18n/store';
import './styles/global.css';

// 首帧之前就把 <html lang> 摆对：index.html 里写死的是中文，
// 英文用户不该等到 React 挂载后才被读屏器按中文朗读。
applyHtmlLang();

const container = document.getElementById('root');
if (!container) {
  throw new Error('未找到挂载节点 #root，请检查 index.html');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
