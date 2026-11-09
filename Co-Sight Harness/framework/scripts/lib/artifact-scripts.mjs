/**
 * 产物里的脚本与配置模板：清单、行尾/编码规整、以及那几条"只在别人机器上炸"的校验。
 *
 * 为什么这些放在 lib 而不是 package.mjs 里：它们需要被测试直接调用。
 * package.mjs 一 import 就会开始打包，没法在单测里引；而这些规则
 * （`.cmd` 必须纯 ASCII + CRLF、`.sh` 必须 LF、可执行脚本首行必须是 shebang）
 * 恰恰是**只能靠断言守住**的那一类——它们错了不会当场报错，
 * 而是变成"用户双击 install.cmd 闪一下就没了"。
 *
 * 真源是 `framework/scripts/artifact/`：产物里放的是那些文件的拷贝，
 * 不存在"打包时另写一版脚本"的分叉。
 */

import fs from 'node:fs';
import path from 'node:path';

import { ARTIFACT_LAYOUT } from './project.mjs';

/**
 * 归档顶层要放的脚本与配置模板。
 *
 * `lineEndings` 是在这里**统一改写**的，不依赖 git 的 checkout 策略：无论打包机的
 * 工作区是 LF 还是 CRLF（本仓库没有 .gitattributes），归档字节都一样。
 *   - `.sh` 强制 LF：`#!/bin/sh\r` 在 Linux 上报 "bad interpreter: /bin/sh^M"；
 *   - `.cmd` 强制 CRLF：cmd.exe 对 LF-only 的批处理容错很差（`goto`/标签尤其）。
 */
export const ARTIFACT_SCRIPTS = [
  { name: ARTIFACT_LAYOUT.installSh, mode: 0o755, lineEndings: 'lf' },
  { name: ARTIFACT_LAYOUT.uninstallSh, mode: 0o755, lineEndings: 'lf' },
  { name: ARTIFACT_LAYOUT.startSh, mode: 0o755, lineEndings: 'lf' },
  { name: ARTIFACT_LAYOUT.installCmd, mode: 0o644, lineEndings: 'crlf', asciiOnly: true },
  { name: ARTIFACT_LAYOUT.uninstallCmd, mode: 0o644, lineEndings: 'crlf', asciiOnly: true },
  { name: ARTIFACT_LAYOUT.startCmd, mode: 0o644, lineEndings: 'crlf', asciiOnly: true },
  { name: ARTIFACT_LAYOUT.envExample, mode: 0o644, lineEndings: 'lf' },
];

/** 解压后要能直接运行（`./install.sh`、`./uninstall.sh`）的条目。 */
export const EXECUTABLE_ENTRIES = [
  ARTIFACT_LAYOUT.entryFile,
  ARTIFACT_LAYOUT.installSh,
  ARTIFACT_LAYOUT.uninstallSh,
  ARTIFACT_LAYOUT.startSh,
];

/**
 * 纯 ASCII 校验。
 *
 * cmd.exe 按 ANSI（简体中文系统上是 GBK）读脚本字节，UTF-8 中文注释会变成乱码，
 * 而且 `chcp 65001` **救不了**——解析器在代码页切换之前就已经读过那一行了。
 * 所以 `.cmd` 里只留英文，中文说明一律放 README.md。
 */
export function assertAsciiOnly(name, text) {
  if (text.startsWith('\uFEFF')) {
    throw new Error(
      `${name} 开头有 UTF-8 BOM（cmd.exe 会把它当成命令的一部分，第一行直接报错）。请存成"UTF-8 无 BOM"。`,
    );
  }

  for (const [index, line] of text.split('\n').entries()) {
    const badIndex = [...line].findIndex((character) => (character.codePointAt(0) ?? 0) > 0x7f);
    if (badIndex !== -1) {
      throw new Error(
        `${name} 第 ${index + 1} 行第 ${badIndex + 1} 列有非 ASCII 字符：${line.trim()}\n` +
          '  cmd.exe 按 ANSI 读脚本，UTF-8 中文在 GBK 控制台上是乱码（chcp 65001 也救不了）。\n' +
          '  中文说明请放进 README.md，脚本里只留英文。',
      );
    }
  }
}

/** 行尾统一成指定的那一种（对已经是目标形态的输入是幂等的）。 */
export function normalizeLineEndings(text, lineEndings) {
  const lf = text.replace(/\r\n/g, '\n');
  return lineEndings === 'crlf' ? lf.replace(/\n/g, '\r\n') : lf;
}

/**
 * 读一个脚本源文件并做完整规整，返回归档条目的三要素
 * （`mode` / `size` / `read`）。缺文件、编码不对、行尾不对、可执行脚本缺 shebang
 * 都在这里**报错退出**：产出一个"能解压但双击没反应"的包，比打包失败难排查得多。
 */
export function loadArtifactScript(spec, sourceDir) {
  const source = path.join(sourceDir, spec.name);
  if (!fs.existsSync(source)) {
    throw new Error(`缺少产物脚本 ${source}——它必须与打包脚本一起提交。`);
  }

  const raw = fs.readFileSync(source, 'utf8');
  if (spec.asciiOnly === true) {
    assertAsciiOnly(spec.name, raw);
  }

  const text = normalizeLineEndings(raw, spec.lineEndings);

  if ((spec.mode & 0o111) !== 0 && !text.startsWith('#!')) {
    throw new Error(`${spec.name} 要带可执行位，但第一行不是 #! 开头的解释器声明（解压后无法直接运行）。`);
  }

  return {
    mode: spec.mode,
    size: Buffer.byteLength(text, 'utf8'),
    read: () => Buffer.from(text, 'utf8'),
  };
}
