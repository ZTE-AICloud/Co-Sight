import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

prepareTestEnv('files-api');

const { config } = await import('../src/config/index.js');

let api: TestApi;

before(async () => {
  api = await startTestApi();
});

after(async () => {
  await api.close();
});

/** multipart 上传不走 helpers 的 JSON call：直接 fetch + FormData。 */
async function upload(fileName: string, bytes: Uint8Array, contentType = 'image/png'): Promise<{ status: number; body: any }> {
  const form = new FormData();
  form.append('file', new Blob([bytes], { type: contentType }), fileName);
  const response = await fetch(`${api.base}${API}/files`, { method: 'POST', body: form });
  return { status: response.status, body: await response.json().catch(() => null) };
}

const PNG_BYTES = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x01, 0x02, 0x03, 0x04]);

test('上传文件落盘并返回可访问 URL：POST /files', async () => {
  const { status, body } = await upload('cover.png', PNG_BYTES);
  assert.equal(status, 200);
  assert.match(body.name, /^fil_[0-9a-f-]{36}\.png$/);
  assert.equal(body.url, `${API}/files/${body.name}`);
  assert.equal(body.size, PNG_BYTES.length);

  const stored = await readFile(join(config.home, 'files', body.name));
  assert.deepEqual(new Uint8Array(stored), PNG_BYTES);
});

test('按存储名读回文件：GET /files/{name}，Content-Type 按扩展名', async () => {
  const uploaded = await upload('cover.png', PNG_BYTES);
  const response = await fetch(`${api.base}${uploaded.body.url}`);
  assert.equal(response.status, 200);
  assert.ok(response.headers.get('content-type')?.startsWith('image/png'));
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  const bytes = new Uint8Array(await response.arrayBuffer());
  assert.deepEqual(bytes, PNG_BYTES);
});

test('扩展名消毒：大小写归一、只留字母数字', async () => {
  const { body } = await upload('Cover.PNG', PNG_BYTES);
  assert.match(body.name, /^fil_[0-9a-f-]{36}\.png$/);
});

test('存储名形态非法（含路径穿越段）：400', async () => {
  const response = await fetch(`${api.base}${API}/files/fil_..%2f..%2fetc%2fpasswd`);
  assert.equal(response.status, 400);
  const body = await response.json();
  assert.equal(body.error, 'BAD_REQUEST');
});

test('存储名形态合法但文件不存在：404', async () => {
  const response = await fetch(`${api.base}${API}/files/fil_00000000-0000-4000-8000-000000000000.png`);
  assert.equal(response.status, 404);
  const body = await response.json();
  assert.equal(body.error, 'NOT_FOUND');
});

test('没带 file 字段：400', async () => {
  const form = new FormData();
  form.append('other', 'x');
  const response = await fetch(`${api.base}${API}/files`, { method: 'POST', body: form });
  assert.equal(response.status, 400);
  const body = await response.json();
  assert.equal(body.error, 'BAD_REQUEST');
});

test('单文件超过 10MB 上限：413', async () => {
  const big = new Uint8Array(10 * 1024 * 1024 + 1);
  const { status, body } = await upload('big.png', big);
  assert.equal(status, 413);
  assert.equal(body.error, 'PAYLOAD_TOO_LARGE');
});
