import { useId, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { msg, useI18n } from '../../../i18n/useI18n';
import { filesApi } from '../../../shared/api/files';
import { ApiError } from '../../../shared/api/client';
import { AgentAvatar } from '../../../shared/components/AgentAvatar';
import { Icon } from '../../../shared/components/Icon';

interface CoverFieldProps {
  /** 当前地址。空串 = 没有封面 */
  value: string;
  /** 名称，给预览的首字兜底用 —— 用户一边改名字，预览里的字也跟着变 */
  name: string;
  onChange: (value: string) => void;
  /** 输入框获得焦点？新建弹窗让名称先聚焦，这里默认不抢 */
  autoFocus?: boolean;
}

/** 与后端 `Agent.icon` 的上限一致（契约 5.01：它是一条地址，比 name / description 宽得多）。 */
const ICON_MAX = 512;

/**
 * 可选的图片类型。**与后端 Content-Type 映射表里那几项对齐**
 * （`server/src/modules/files/files.service.ts` 的 `CONTENT_TYPES`）：
 * 其它图片（HEIC / TIFF 等）会被后端按 `application/octet-stream` + `nosniff` 回，
 * `<img>` 根本解不出来，最后只会退回名称首字 —— 与其让用户上传完才发现，
 * 不如在选择器里就收窄。扩展名兜底是给「浏览器没填 MIME」的文件留的路。
 */
const IMAGE_ACCEPT =
  'image/png,image/jpeg,image/gif,image/webp,image/svg+xml,image/x-icon,image/bmp,image/avif';
const IMAGE_TYPES = new Set(IMAGE_ACCEPT.split(','));
const IMAGE_EXTENSIONS = /\.(png|jpe?g|gif|webp|svg|ico|bmp|avif)$/i;

/**
 * 封面图那一格：左边一个**活的预览**，中间是地址，右边是「上传图片」。
 *
 * 2026-10-18 起从「只能手贴 URL」改成**以选本地图片为主**：
 * 选图 → `POST /files`（multipart，字段名 `file`）→ 把响应里的 `url` 写回 `icon`
 * （接口与机制见 `server/docs/05-openapi/5.02-file-openapi.yaml`、
 * `server/docs/03-architecture/09-file.md`）。
 *
 * 三处是刻意这么做的：
 *
 * - **上传是立即的，不等「保存」**。上传与保存是两件事：上传只产生一个文件、拿到 URL；
 *   写回智能体仍由底部的「保存」负责。好处是选完就能看到真实图片，不用等表单提交；
 *   代价是取消编辑会留下一个孤儿文件 —— 后端明确接受（无删除端点，见 09-file.md §6）。
 * - **地址输入框保留为并行方式**。上传接口没做类型白名单，手贴 URL 仍有它的用处
 *   （内网图床、已有的地址）。两种方式写的是同一个 `icon`。
 * - **前端只拦「不是图片」**，不拦大小。上限由服务端 `FILES_MAX_FILE_BYTES` 决定，
 *   写死 10MB 会在部署改大改小时误杀；413 让后端说，这里只负责把它翻译成人话。
 *
 * 预览放在输入框旁边而不是等保存后回列表看：地址敲错了在列表上只会显示成首字兜底，
 * 看不出「是没填还是填错了」。当场看见图（或者看见它退回首字），才是能立刻改正的反馈。
 */
export function CoverField({ value, name, onChange, autoFocus }: CoverFieldProps) {
  const { t } = useI18n();
  const empty = value.trim() === '';
  const urlId = useId();
  const fileRef = useRef<HTMLInputElement>(null);

  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /**
   * 本地预览的 object URL。上传期间用它先显示选中的那张图；
   * 成功后等服务器地址接上再清掉（见下面 setTimeout 那段），失败则立刻退回原封面。
   */
  const [localPreview, setLocalPreview] = useState<string | null>(null);

  const preview = localPreview ?? value;

  async function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // 清空 value：否则连续选同一个文件不会再触发 change
    event.target.value = '';
    if (file === undefined) return;

    // 后端不做类型白名单（09-file.md §6），所以图片这件事在前端收口
    if (!IMAGE_TYPES.has(file.type) && !IMAGE_EXTENSIONS.test(file.name)) {
      setError(t('agentList.cover.badType'));
      return;
    }

    setError(null);
    setUploading(true);

    const objectUrl = URL.createObjectURL(file);
    setLocalPreview(objectUrl);

    try {
      const uploaded = await filesApi.upload(file);
      onChange(uploaded.url);

      // 先别 revoke：服务器地址那张图可能还没解码完，立刻切过去会闪一下首字兜底。
      // 留 1.2s 让本地图顶着；期间又选了新图的话，`current === objectUrl` 会把这次清理跳过。
      window.setTimeout(() => {
        URL.revokeObjectURL(objectUrl);
        setLocalPreview((current) => (current === objectUrl ? null : current));
      }, 1200);
    } catch (err) {
      URL.revokeObjectURL(objectUrl);
      setLocalPreview(null);
      setError(describeUploadError(err));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="al-field">
      <label className="al-field-label" htmlFor={urlId}>
        {t('agentList.cover.label')}
      </label>

      <div className="al-cover">
        <AgentAvatar icon={preview} name={name} size={36} />

        <input
          id={urlId}
          className="al-input"
          value={value}
          onChange={(event) => {
            setError(null);
            onChange(event.target.value);
          }}
          maxLength={ICON_MAX}
          placeholder={t('agentList.cover.urlPlaceholder')}
          autoFocus={autoFocus}
          disabled={uploading}
        />

        <button
          type="button"
          className="al-btn al-btn--sm al-cover-upload"
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
        >
          <Icon name="arrowUp" size={12} />
          {uploading ? t('agentList.cover.uploading') : t('agentList.cover.upload')}
        </button>

        {!empty && !uploading && (
          <button
            type="button"
            className="al-cover-clear"
            onClick={() => {
              setError(null);
              onChange('');
            }}
            aria-label={t('agentList.cover.remove')}
            title={t('agentList.cover.remove')}
          >
            <Icon name="close" size={12} />
          </button>
        )}
      </div>

      {/* 隐藏的文件选择器：按钮只是它的触发器 */}
      <input
        ref={fileRef}
        type="file"
        accept={IMAGE_ACCEPT}
        hidden
        onChange={(event) => void onFileChange(event)}
      />

      {/* 与别的字段同一版式：左边说事、右边计数（没填时没有数可数）。
          上传失败时把左边那句换成红字，和标签/名称的校验提示同一个位置。 */}
      <span className="al-field-hint">
        <span>
          {error !== null ? (
            <span className="al-field-problem">{error}</span>
          ) : empty ? (
            t('agentList.cover.emptyHint')
          ) : (
            t('agentList.cover.filledHint')
          )}
        </span>
        {!empty && (
          <span>
            {value.length}/{ICON_MAX}
          </span>
        )}
      </span>
    </div>
  );
}

/**
 * 上传失败翻译成人话。
 *
 * 413 是「文件超过服务端上限」——后端消息里带着具体 MB 数，但它可能被部署改过，
 * 所以这里不写死数字，只给下一步动作。`BAD_RESPONSE` 是 vite 代理连不上后端时的长相
 * （响应根本不是 JSON），跟「后端说不行」是两回事。
 */
function describeUploadError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 413) return msg('agentList.cover.tooLarge');
    if (err.code === 'BAD_RESPONSE') return msg('agentList.cover.noBackend');
    return msg('agentList.cover.failedDetail', { error: err.message });
  }
  if (err instanceof TypeError) return msg('agentList.cover.failedNetwork');
  return msg('agentList.cover.failedRetry');
}
