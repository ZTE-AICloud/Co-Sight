#!/usr/bin/env node
/**
 * verify-apply.mjs — runs the real plugin apply() against a minimal fake cordis
 * ctx, asserting the wiring actually registers, without needing a live dsh.
 * Exit 0 = pass.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { apply } from '../src/index.mjs'

const DRIVE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

let failures = 0
function check(label, ok, detail) {
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures += 1
}

const listeners = {}
const mountedSkills = new Map()
const registeredTools = new Map()

const fakeCtx = {
  get: (key) => {
    if (key === 'skills') {
      return { register: (s) => mountedSkills.set(s.name, s) }
    }
    if (key === 'tools') {
      return { register: (def) => registeredTools.set(def.name, def) }
    }
    return undefined
  },
  on: (event, fn) => { listeners[event] = fn },
  logger: { info: () => {}, warn: (...a) => console.warn('  [warn]', ...a) },
}

console.log('\ndrive-compat apply() verification')
console.log(`  driveRoot=${DRIVE_ROOT}\n`)

const disposed = await apply(fakeCtx, { driveRoot: DRIVE_ROOT, hooks: true, hitl: true, skills: true, shims: true })

// 1) skills mounted — every directory with SKILL.md
const skillDirs = fs.readdirSync(path.join(DRIVE_ROOT, 'skills'), { withFileTypes: true })
  .filter((e) => e.isDirectory() && !e.name.startsWith('.'))
  .filter((e) => fs.existsSync(path.join(DRIVE_ROOT, 'skills', e.name, 'SKILL.md')))
check('all drive skills mounted', mountedSkills.size === skillDirs.length,
  `${mountedSkills.size}/${skillDirs.length}`)

// 2) ${CLAUDE_SKILL_DIR} expanded — sample the drive skill body
{
  const drive = mountedSkills.get('drive')
  check('drive skill mounted', !!drive)
  if (drive) {
    check('CLAUDE_SKILL_DIR expanded', !drive.content.includes('${CLAUDE_SKILL_DIR}'),
      drive.content.includes('${CLAUDE_SKILL_DIR}') ? 'still literal' : 'absolute path injected')
    check('references drive scripts path', drive.content.includes('/skills/drive/scripts'),
      'scripts path reachable')
  }
}

// 3) shim tools registered
check('Agent shim registered', registeredTools.has('Agent'))
check('TodoWrite shim registered', registeredTools.has('TodoWrite'))
check('AskUserQuestion shim registered', registeredTools.has('AskUserQuestion'))

// 4) pre-execute listener registered
const pre = listeners['tools/pre-execute']
check('tools/pre-execute listener registered', typeof pre === 'function')

// 5) pre-execute actually decides: drive a deny through it
if (typeof pre === 'function') {
  const evilDir = path.join(DRIVE_ROOT, 'verify-apply-tmp')
  fs.mkdirSync(path.join(evilDir, '.drive', 'plan-verify-apply'), { recursive: true })
  fs.writeFileSync(path.join(evilDir, '.drive', '.current-plan'), 'plan-verify-apply')
  fs.writeFileSync(path.join(evilDir, '.drive', 'plan-verify-apply', 'executeState.json'),
    JSON.stringify({ active_stage: 'execute', status: 'executing' }))
  const exec = {
    name: 'write',
    arguments: { file_path: path.join(evilDir, '.drive', 'plan-verify-apply', 'nope.txt'), content: 'x' },
    agent: undefined,
    callId: 'v1',
  }
  let delegated = false
  const decision = await pre(exec, () => { delegated = true; return { kind: 'allow' } })
  check('pre-execute denies out-of-whitelist write', decision && decision.kind === 'deny',
    decision ? decision.kind : 'none')
  fs.rmSync(evilDir, { recursive: true, force: true })
}

console.log(`\n${failures === 0 ? 'APPLY VERIFICATION PASSED' : `${failures} CHECK(S) FAILED`}\n`)
process.exit(failures === 0 ? 0 : 1)
