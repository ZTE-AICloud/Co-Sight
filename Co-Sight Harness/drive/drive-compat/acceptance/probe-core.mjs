#!/usr/bin/env node
/**
 * probe-core.mjs — acceptance probes for drive-compat's pre-execute wiring.
 *
 * Drives `decide()` directly with a fake cordis ctx/exec, against a freshly
 * created throwaway plan directory, asserting three contracts:
 *   1. write outside the drive whitelist  -> {kind:'deny'}
 *   2. bash call appends to run-log.jsonl -> marker present
 *   3. confirm-style bash                 -> {kind:'ask'}
 *
 * Usage (run from the workspace that holds .drive/):
 *   node drive-compat/acceptance/probe-core.mjs [--drive-root <drive>]
 * Exit 0 = all pass.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { decide } from '../src/guards.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DRIVE_ROOT = process.argv.includes('--drive-root')
  ? process.argv[process.argv.indexOf('--drive-root') + 1]
  : path.resolve(HERE, '..', '..')
const WORKSPACE = process.cwd()
const DRIVE_DIR = path.join(WORKSPACE, '.drive')

const FAKE_CTX = {
  get: () => undefined,
  logger: { warn: (...a) => console.warn('  [warn]', ...a), info: () => {} },
}

let failures = 0
function check(label, ok, detail) {
  const mark = ok ? 'PASS' : 'FAIL'
  if (!ok) failures += 1
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`)
}

function makeExec(name, arguments_) {
  return { name, arguments: arguments_, agent: undefined, callId: `probe-${name}-${Date.now()}` }
}

// ---- fresh throwaway plan (so we never touch a real drive run) ----
const planName = `plan-probe-compat-${Date.now()}`
const planDir = path.join(DRIVE_DIR, planName)
fs.mkdirSync(path.join(planDir, 'runtime'), { recursive: true })
fs.writeFileSync(path.join(planDir, 'executeState.json'),
  JSON.stringify({ active_stage: 'execute', status: 'executing', revision: 1, confirmed_stages: [] }, null, 2))
if (!fs.existsSync(path.join(DRIVE_DIR, '.current-plan'))) {
  fs.writeFileSync(path.join(DRIVE_DIR, '.current-plan'), planName)
} else {
  const prev = fs.readFileSync(path.join(DRIVE_DIR, '.current-plan'), 'utf8')
  fs.writeFileSync(path.join(DRIVE_DIR, '.current-plan'), planName)
  fs.writeFileSync(path.join(DRIVE_DIR, `.current-plan.bak`), prev)
}
const runLog = path.join(planDir, 'run-log.jsonl')

console.log(`\ndrive-compat acceptance probes`)
console.log(`  driveRoot=${DRIVE_ROOT}`)
console.log(`  workspace=${WORKSPACE}`)
console.log(`  probe plan=${planName}\n`)

// ---- 1) write guard ----
{
  const evil = path.join(planDir, 'evil-not-whitelisted.txt')
  const d = await decide(FAKE_CTX, makeExec('write', { file_path: evil, content: 'x' }),
    { driveRoot: DRIVE_ROOT, hooks: true, hitl: false }, FAKE_CTX.logger)
  check('write outside whitelist is denied', d && d.kind === 'deny',
    d ? `kind=${d.kind} reason=${String(d.reason ?? '').slice(0, 60)}` : 'no decision')
}

// ---- 2) audit ----
{
  if (fs.existsSync(runLog)) fs.rmSync(runLog)
  const marker = `probe-audit-marker-${Date.now()}`
  const d = await decide(FAKE_CTX, makeExec('bash', { command: `echo ${marker}` }),
    { driveRoot: DRIVE_ROOT, hooks: true, hitl: false }, FAKE_CTX.logger)
  let appended = false
  if (fs.existsSync(runLog)) {
    appended = fs.readFileSync(runLog, 'utf8').includes(marker)
  }
  check('bash call was audited into run-log', appended,
    d ? `decision=${d.kind}` : 'no decision')
}

// ---- 3) hitl ----
{
  const d = await decide(FAKE_CTX,
    makeExec('bash', { command: `python3 drive-compat/../../hooks/confirm_stage.py --stage execute --note x` }),
    { driveRoot: DRIVE_ROOT, hooks: false, hitl: true }, FAKE_CTX.logger)
  check('confirm-style command asks the human', d && d.kind === 'ask',
    d ? `kind=${d.kind}` : 'no decision')
}

// ---- cleanup ----
fs.rmSync(planDir, { recursive: true, force: true })
if (fs.existsSync(path.join(DRIVE_DIR, '.current-plan.bak'))) {
  fs.renameSync(path.join(DRIVE_DIR, '.current-plan.bak'), path.join(DRIVE_DIR, '.current-plan'))
}

console.log(`\n${failures === 0 ? 'ALL PROBES PASSED' : `${failures} PROBE(S) FAILED`}\n`)
process.exit(failures === 0 ? 0 : 1)
