/**
 * 产物里的四个脚本 + 配置模板：编码、行尾、可执行位。
 *
 * 这些断言针对的是**一类只在别人机器上发作**的错：
 *   · `.cmd` 里出现中文 → GBK 控制台上乱码，而 `chcp 65001` 救不了（解析器已读过那一行）；
 *   · `.cmd` 是 LF 行尾 → cmd.exe 对 LF-only 批处理的容错很差；
 *   · `.sh` 是 CRLF → Linux 上报 `bad interpreter: /bin/sh^M`；
 *   · 可执行脚本没有 shebang → 解压后 `./start.sh` 直接失败。
 *
 * 前三条在 Linux 开发机上**看不到任何异常**（文件本身完全合法），
 * 所以只有断言能守住。这里既测规整函数，也直接测仓库里那几个真文件——
 * 后者才是"手滑写了个中文注释"能被 CI 拦住的唯一原因。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';

import {
  ARTIFACT_SCRIPTS,
  assertAsciiOnly,
  loadArtifactScript,
  normalizeLineEndings,
} from '../lib/artifact-scripts.mjs';
import { ARTIFACT_LAYOUT, MODULE_ROOT } from '../lib/project.mjs';

const sourceDir = path.join(MODULE_ROOT, ARTIFACT_LAYOUT.scriptSourceDir);

describe('纯 ASCII 校验', () => {
  it('放过合法的 ASCII 批处理', () => {
    assert.doesNotThrow(() => assertAsciiOnly('probe.cmd', '@echo off\r\nrem ok\r\nexit /b 0\r\n'));
  });

  it('中文注释被拦住，并指出行号列号', () => {
    assert.throws(() => assertAsciiOnly('probe.cmd', '@echo off\necho 你好\n'), /第 2 行第 6 列/);
  });

  it('UTF-8 BOM 被单独认出来（它的报错更具体）', () => {
    assert.throws(() => assertAsciiOnly('probe.cmd', '﻿@echo off\n'), /BOM/);
  });

  it('全角标点同样拦住（中文输入法下最容易按出来的东西）', () => {
    assert.throws(() => assertAsciiOnly('probe.cmd', 'echo （test）\n'), /非 ASCII/);
  });
});

describe('行尾规整', () => {
  it('两种目标都幂等：CRLF 工作区与 LF 工作区产出同一串字节', () => {
    assert.equal(normalizeLineEndings('a\r\nb\nc', 'crlf'), 'a\r\nb\r\nc');
    assert.equal(normalizeLineEndings('a\r\nb\r\nc', 'crlf'), 'a\r\nb\r\nc');
    assert.equal(normalizeLineEndings('a\r\nb\nc', 'lf'), 'a\nb\nc');
    assert.equal(normalizeLineEndings('a\nb\nc', 'lf'), 'a\nb\nc');
  });
});

describe('搬运真实脚本文件', () => {
  for (const spec of ARTIFACT_SCRIPTS) {
    it(`${spec.name}：能读出来且符合规则`, () => {
      const entry = loadArtifactScript(spec, sourceDir);
      const text = entry.read().toString('utf8');

      assert.equal(entry.mode, spec.mode);
      assert.equal(entry.size, Buffer.byteLength(text, 'utf8'));

      if (spec.lineEndings === 'crlf') {
        assert.ok(text.includes('\r\n'), `${spec.name} 必须是 CRLF 行尾`);
        // 不能出现"孤立的 LF"：那意味着有的行没被规整到。
        assert.equal(/(?<!\r)\n/.test(text), false, `${spec.name} 里有未规整的 LF`);
      } else {
        assert.equal(text.includes('\r'), false, `${spec.name} 不能有 CR`);
      }

      if (spec.asciiOnly === true) {
        assert.doesNotThrow(() => assertAsciiOnly(spec.name, text));
      }
      if ((spec.mode & 0o111) !== 0) {
        assert.ok(text.startsWith('#!'), `${spec.name} 要以 shebang 开头`);
      }
    });
  }

  it('缺文件时报错，而不是安静地把包打出来', () => {
    assert.throws(
      () => loadArtifactScript({ name: 'nope.sh', mode: 0o755, lineEndings: 'lf' }, sourceDir),
      /缺少产物脚本/,
    );
  });

  it('要可执行却没有 shebang 时报错', () => {
    const scratch = fs.mkdtempSync(path.join(process.env.TMPDIR ?? '/tmp', 'artifact-scripts-'));
    try {
      fs.writeFileSync(path.join(scratch, 'bad.sh'), 'echo hi\n');
      assert.throws(
        () => loadArtifactScript({ name: 'bad.sh', mode: 0o755, lineEndings: 'lf' }, scratch),
        /#! 开头的解释器声明/,
      );
    } finally {
      fs.rmSync(scratch, { recursive: true, force: true });
    }
  });
});

describe('两个平台的脚本内容约定', () => {
  // 中文不能出现在 .cmd 里（上面那条 ASCII 规则），但用户看到的窗口全是英文，
  // 所以每个 .cmd 都必须把"中文说明在哪"写出来——否则中文用户找不到文档。
  it('三个 .cmd 都把中文说明指向 README.md（窗口里读不到中文）', () => {
    for (const name of [
      ARTIFACT_LAYOUT.installCmd,
      ARTIFACT_LAYOUT.uninstallCmd,
      ARTIFACT_LAYOUT.startCmd,
    ]) {
      const text = fs.readFileSync(path.join(sourceDir, name), 'utf8');
      assert.equal(text.includes('README'), true, `${name} 应当把中文说明指向 README.md`);
    }
  });

  it('install.sh 与 install.cmd 都把真正的活交给 start.mjs --install', () => {
    const sh = fs.readFileSync(path.join(sourceDir, ARTIFACT_LAYOUT.installSh), 'utf8');
    const cmd = fs.readFileSync(path.join(sourceDir, ARTIFACT_LAYOUT.installCmd), 'utf8');
    for (const [name, text] of [
      ['install.sh', sh],
      ['install.cmd', cmd],
    ]) {
      // `--install` 在 `--init` 之上多装五个插件：安装入口必须走它，
      // 否则用户装完能启动、专家页却是空的。
      assert.ok(
        /start\.mjs --install/.test(text),
        `${name} 应当调用 start.mjs --install（安装逻辑只写一份）`,
      );
    }
  });

  it('uninstall.sh 与 uninstall.cmd 都把真正的活交给 start.mjs --uninstall', () => {
    const sh = fs.readFileSync(path.join(sourceDir, ARTIFACT_LAYOUT.uninstallSh), 'utf8');
    const cmd = fs.readFileSync(path.join(sourceDir, ARTIFACT_LAYOUT.uninstallCmd), 'utf8');
    for (const [name, text] of [
      ['uninstall.sh', sh],
      ['uninstall.cmd', cmd],
    ]) {
      /*
       * 卸载要按顺序做四件事（卸插件、摘市场、清载荷副本、按需删数据目录），
       * 写两遍 sh/cmd 一定会在某次改动后分叉，而且只在另一个平台上暴露。
       */
      assert.ok(
        /start\.mjs --uninstall/.test(text),
        `${name} 应当调用 start.mjs --uninstall（卸载逻辑只写一份）`,
      );
    }
  });

  it('卸载脚本不静默删数据目录：--purge-data 必须同时要 --yes', () => {
    // 这条断言守的是文档口径：脚本里提示的"连数据一起删"必须带两个开关，
    // 否则有人照抄一句 --purge-data 就把会话和密钥删了。
    for (const name of [ARTIFACT_LAYOUT.uninstallSh, ARTIFACT_LAYOUT.uninstallCmd]) {
      const text = fs.readFileSync(path.join(sourceDir, name), 'utf8');
      assert.match(text, /--purge-data --yes/, `${name} 里的删除示例必须同时给出 --yes`);
    }
  });
});
