import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgent } from './helpers/agents.js';
import { startWorkspaceStub } from './helpers/workspace-stub.js';

const env = prepareTestEnv('artifact-text');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');
const { artifactService } = await import('../src/modules/artifact/artifact.service.js');

after(async () => {
  await stub.close();
  await prisma.$disconnect();
});

test('artifactService.file：剥掉 UTF-8 BOM，正文原样返回', async () => {
  await seedAgent('bom-file');
  const dir = join(agentRootIn(env.workspaceDir, 'bom-file'), 'development');
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'note.txt'), '﻿你好\n');

  const file = await artifactService.file({ stage: 'development', agentId: 'bom-file', path: 'note.txt' });

  assert.equal(file.content, '你好\n');
});
