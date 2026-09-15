#!/usr/bin/env node
/**
 * Behaviour checks for the OpenCode client helpers
 * (flowkit/dashboard/src/api/opencode.ts).
 *
 * The dashboard still has no test runner, and adding one means another
 * throttled `npm install`. The functions checked here are pure — no React, no
 * DOM, no network — so they run directly in Node. Self-contained: the
 * TypeScript is transpiled on the fly with the dashboard's own `typescript`.
 *
 * The error payloads below are not invented. They were captured verbatim from
 * https://opencode.ai/zen/v1 while smoke-testing the streaming endpoint, which
 * is the only way to be sure the parser matches what the provider really sends.
 *
 *   node tools/check_opencode_api.js
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const DASHBOARD = path.join(__dirname, '..', 'flowkit', 'dashboard')
const SOURCE = path.join(DASHBOARD, 'src', 'api', 'opencode.ts')

function loadModule() {
  const ts = require(path.join(DASHBOARD, 'node_modules', 'typescript'))
  const source = fs.readFileSync(SOURCE, 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  })
  const mod = { exports: {} }
  // eslint-disable-next-line no-new-func
  new Function('exports', 'require', 'module', outputText)(mod.exports, require, mod)
  return mod.exports
}

const { explainUpstreamError, findModel } = loadModule()

let passed = 0
const failures = []

function check(name, fn) {
  try {
    fn()
    passed++
  } catch (err) {
    failures.push(`${name}\n    ${err.message.split('\n')[0]}`)
  }
}

// --- payloads captured from the live provider ------------------------------

const CREDITS_ERROR =
  '{"type":"error","error":{"type":"CreditsError","message":"No payment method. ' +
  'Add a payment method to continue using this model."}}'

// The `message` field here is itself a JSON string — the double-encoded shape.
const MODEL_UNAVAILABLE =
  '{"error":{"type":"server_error","message":"Error from provider (Console): ' +
  'Upstream request failed: Model is unavailable."}}'

const FREE_LIMIT =
  '{"type":"error","error":{"type":"FreeUsageLimitError","message":"Error from ' +
  'provider (Console): Free usage limit reached."}}'

// --- recognised failures ---------------------------------------------------

check('CreditsError is explained and points at free models', () => {
  const out = explainUpstreamError(CREDITS_ERROR)
  assert.ok(out, 'expected an explanation')
  assert.match(out.title, /paid account/i)
  assert.match(out.hint, /-free/)
  assert.equal(out.switchModel, true)
})

check('a model that is offline upstream is explained', () => {
  const out = explainUpstreamError(MODEL_UNAVAILABLE)
  assert.ok(out, 'expected an explanation')
  assert.match(out.title, /offline/i)
  assert.equal(out.switchModel, true)
})

check('an exhausted free quota is explained', () => {
  const out = explainUpstreamError(FREE_LIMIT)
  assert.ok(out, 'expected an explanation')
  assert.match(out.title, /quota/i)
  assert.equal(out.switchModel, true)
})

check('a rejected key is explained and does NOT suggest switching model', () => {
  const out = explainUpstreamError(
    '{"error":{"type":"authentication_error","message":"Invalid API key provided."}}'
  )
  assert.ok(out, 'expected an explanation')
  assert.match(out.title, /key was rejected/i)
  // Switching model cannot fix an auth problem; offering it would mislead.
  assert.equal(out.switchModel, false)
})

check('rate limiting is explained', () => {
  const out = explainUpstreamError(
    '{"error":{"type":"rate_limit_error","message":"Rate limit exceeded, retry later."}}'
  )
  assert.ok(out, 'expected an explanation')
  assert.match(out.title, /rate limited/i)
})

check('credits are detected from the message even without the type', () => {
  const out = explainUpstreamError('{"message":"No payment method on file."}')
  assert.ok(out, 'expected a message-only match')
  assert.match(out.title, /paid account/i)
})

check('the flat {type,message} shape is understood', () => {
  const out = explainUpstreamError('{"type":"CreditsError","message":"nope"}')
  assert.ok(out, 'expected the flat shape to be read')
  assert.match(out.title, /paid account/i)
})

// --- refusals to guess -----------------------------------------------------

check('an unrecognised envelope returns null rather than a made-up cause', () => {
  assert.equal(explainUpstreamError('{"error":{"type":"weird_new_thing","message":"???"}}'), null)
})

check('plain text returns null', () => {
  assert.equal(explainUpstreamError('Failed to fetch'), null)
})

check('malformed JSON returns null instead of throwing', () => {
  assert.equal(explainUpstreamError('{"error": {"type": "CreditsError"'), null)
})

check('an empty string returns null', () => {
  assert.equal(explainUpstreamError(''), null)
})

check('an empty JSON object returns null', () => {
  assert.equal(explainUpstreamError('{}'), null)
})

check('a JSON array returns null', () => {
  assert.equal(explainUpstreamError('[]'), null)
})

check('null-ish input does not throw', () => {
  assert.equal(explainUpstreamError('null'), null)
})

// --- model lookup ----------------------------------------------------------

check('findModel matches on id', () => {
  const models = [
    { id: 'a', endpoint_type: 'chat-completions' },
    { id: 'b', endpoint_type: 'responses' },
  ]
  assert.equal(findModel(models, 'b').endpoint_type, 'responses')
})

check('findModel returns undefined for an unknown id', () => {
  assert.equal(findModel([{ id: 'a' }], 'zzz'), undefined)
})

// --- report ----------------------------------------------------------------

if (failures.length) {
  console.error(`\n${failures.length} check(s) failed:\n`)
  for (const f of failures) console.error(`  ✗ ${f}\n`)
  console.error(`all ${passed + failures.length} checks: ${passed} passed, ${failures.length} failed`)
  process.exit(1)
}

console.log(`all ${passed} opencode client checks passed`)
