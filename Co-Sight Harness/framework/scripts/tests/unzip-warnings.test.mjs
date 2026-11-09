/**
 * Info-ZIP 告警放行的边界。
 *
 * 这条判定决定"退出码 1 到底算不算失败"。放得太宽，一次真的解压失败会被当成
 * 偶发告警吞掉，冒烟变假通过；放得太窄，Windows 上每次解压都硬失败。
 * 两边的样本都钉在这里。
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { countMetadataOnlyUnzipWarnings } from '../lib/archive/unzip-warnings.mjs';

/** 只有元数据告警：两条，各自带一条缩进原因。 */
const METADATA_ONLY = [
  'warning:  cannot set permissions for   cosight-harness-1/tmp/',
  '          No such file or directory',
  'warning:  cannot set modif./access times for   cosight-harness-1/tmp/',
  '          No such file or directory',
  '',
].join('\n');

describe('unzip 告警判定', () => {
  it('只有元数据告警时返回条数', () => {
    assert.equal(countMetadataOnlyUnzipWarnings(METADATA_ONLY), 2);
  });

  it('没有任何输出时不放行', () => {
    // 退出码 1 但 stderr 空着是说不通的：没有可核对的理由就不能当成告警。
    assert.equal(countMetadataOnlyUnzipWarnings(''), 0);
    assert.equal(countMetadataOnlyUnzipWarnings('\n  \n'), 0);
  });

  it('顶格的失败行一律不放行', () => {
    assert.equal(
      countMetadataOnlyUnzipWarnings(`${METADATA_ONLY}error:  invalid compressed data to inflate\n`),
      0,
    );
    assert.equal(countMetadataOnlyUnzipWarnings('bad CRC 0x12345678  (should be 0x87654321)\n'), 0);
  });

  it('缩进的失败行也不放行', () => {
    // Info-ZIP 会把真正的失败缩进打印；只认"以空白开头"会把它一起吞掉。
    const skipped = `${METADATA_ONLY}  skipping:  some/file.js  need PK compat. v5.1 (can do v4.6)\n`;
    assert.equal(countMetadataOnlyUnzipWarnings(skipped), 0);
  });

  it('不认识的告警措辞按失败处理', () => {
    // 宁可把一次偶发告警判成失败（人一看就知道），也不要放宽成什么都放行。
    assert.equal(countMetadataOnlyUnzipWarnings('warning:  something new happened\n'), 0);
  });
});
