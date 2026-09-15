#!/usr/bin/env node
/**
 * Behaviour checks for the dashboard Markdown parser
 * (flowkit/dashboard/src/lib/markdown.ts).
 *
 * The dashboard has no test runner, and adding one means another throttled
 * `npm install`. The parser is deliberately free of React and DOM references so
 * it can be exercised directly in Node instead.
 *
 * Self-contained: transpiles the TypeScript on the fly with the dashboard's own
 * `typescript` package, so there is no build step to remember.
 *
 *   node tools/check_markdown.js
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const DASHBOARD = path.join(__dirname, '..', 'flowkit', 'dashboard')
const SOURCE = path.join(DASHBOARD, 'src', 'lib', 'markdown.ts')

function loadParser() {
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

const { parseMarkdown, parseInline, safeHref } = loadParser()

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

// --- blocks ---------------------------------------------------------------

check('paragraph', () => {
  assert.deepEqual(parseMarkdown('hello world'), [{ kind: 'paragraph', text: 'hello world' }])
})

check('consecutive lines join into one paragraph', () => {
  const b = parseMarkdown('one\ntwo')
  assert.equal(b.length, 1)
  assert.equal(b[0].text, 'one two')
})

check('blank lines separate paragraphs', () => {
  assert.equal(parseMarkdown('one\n\ntwo').length, 2)
})

check('heading levels', () => {
  const b = parseMarkdown('# A\n## B\n###### F')
  assert.deepEqual(b.map(x => x.level), [1, 2, 6])
  assert.equal(b[0].text, 'A')
})

check('seven hashes is not a heading', () => {
  assert.equal(parseMarkdown('####### nope')[0].kind, 'paragraph')
})

check('fenced code keeps its language and body verbatim', () => {
  const b = parseMarkdown('```json\n{"a": 1}\n```')
  assert.equal(b.length, 1)
  assert.equal(b[0].kind, 'code')
  assert.equal(b[0].lang, 'json')
  assert.equal(b[0].code, '{"a": 1}')
})

check('an unterminated fence still renders as code (mid-stream)', () => {
  const b = parseMarkdown('```json\n{"a":')
  assert.equal(b[0].kind, 'code')
  assert.equal(b[0].lang, 'json')
  assert.equal(b[0].code, '{"a":')
})

check('code body is not parsed for emphasis', () => {
  assert.equal(parseMarkdown('```\n**not bold**\n```')[0].code, '**not bold**')
})

check('tilde fences work', () => {
  const b = parseMarkdown('~~~py\nx = 1\n~~~')
  assert.equal(b[0].kind, 'code')
  assert.equal(b[0].lang, 'py')
})

check('unordered list', () => {
  const b = parseMarkdown('- one\n- two\n* three')
  assert.equal(b.length, 1)
  assert.equal(b[0].kind, 'list')
  assert.equal(b[0].ordered, false)
  assert.deepEqual(b[0].items, ['one', 'two', 'three'])
})

check('ordered list', () => {
  const b = parseMarkdown('1. one\n2. two')
  assert.equal(b[0].ordered, true)
  assert.deepEqual(b[0].items, ['one', 'two'])
})

check('switching from bullets to numbers ends the list', () => {
  const b = parseMarkdown('- a\n1. b')
  assert.equal(b.length, 2)
  assert.equal(b[0].ordered, false)
  assert.equal(b[1].ordered, true)
})

check('blockquote', () => {
  const b = parseMarkdown('> line one\n> line two')
  assert.equal(b[0].kind, 'quote')
  assert.equal(b[0].text, 'line one\nline two')
})

check('horizontal rule', () => {
  assert.equal(parseMarkdown('---')[0].kind, 'rule')
  assert.equal(parseMarkdown('***')[0].kind, 'rule')
})

check('a manifest block after prose parses as its own code block', () => {
  const src = [
    'Here is the episode.',
    '',
    '```json',
    '{"project_name": "Ep 2", "scenes": [{"duration": 6.0}]}',
    '```',
  ].join('\n')
  const b = parseMarkdown(src)
  assert.equal(b.length, 2)
  assert.equal(b[0].kind, 'paragraph')
  assert.equal(b[1].kind, 'code')
  assert.equal(JSON.parse(b[1].code).project_name, 'Ep 2')
})

// --- inline ---------------------------------------------------------------

check('plain text', () => {
  assert.deepEqual(parseInline('abc'), [{ kind: 'text', text: 'abc' }])
})

check('bold', () => {
  assert.deepEqual(parseInline('a **b** c'), [
    { kind: 'text', text: 'a ' },
    { kind: 'bold', text: 'b' },
    { kind: 'text', text: ' c' },
  ])
})

check('italic', () => {
  const p = parseInline('a *b* c')
  assert.equal(p[1].kind, 'italic')
  assert.equal(p[1].text, 'b')
})

check('strikethrough', () => {
  assert.equal(parseInline('~~gone~~')[0].kind, 'strike')
})

check('inline code', () => {
  assert.deepEqual(parseInline('use `npm ci` now'), [
    { kind: 'text', text: 'use ' },
    { kind: 'code', text: 'npm ci' },
    { kind: 'text', text: ' now' },
  ])
})

check('inline code protects asterisks', () => {
  const p = parseInline('`a ** b`')
  assert.equal(p.length, 1)
  assert.equal(p[0].kind, 'code')
  assert.equal(p[0].text, 'a ** b')
})

check('link', () => {
  const p = parseInline('see [docs](https://example.com/x)')
  assert.equal(p[1].kind, 'link')
  assert.equal(p[1].text, 'docs')
  assert.equal(p[1].href, 'https://example.com/x')
})

check('an unclosed bold marker stays literal', () => {
  const p = parseInline('**unfinished')
  assert.equal(p.length, 1)
  assert.equal(p[0].kind, 'text')
  assert.equal(p[0].text, '**unfinished')
})

check('snake_case is not italicised', () => {
  const p = parseInline('call read_file_now please')
  assert.equal(p.length, 1)
  assert.equal(p[0].kind, 'text')
})

check('_emphasis_ at a boundary still works', () => {
  assert.equal(parseInline('_yes_')[0].kind, 'italic')
})

// --- link safety ----------------------------------------------------------

check('safeHref allows http, https, mailto and relative', () => {
  assert.equal(safeHref('https://a.b'), 'https://a.b')
  assert.equal(safeHref('http://a.b'), 'http://a.b')
  assert.equal(safeHref('mailto:a@b.c'), 'mailto:a@b.c')
  assert.equal(safeHref('/docs/x'), '/docs/x')
  assert.equal(safeHref('#anchor'), '#anchor')
})

check('safeHref rejects script-bearing schemes', () => {
  assert.equal(safeHref('javascript:alert(1)'), null)
  assert.equal(safeHref('JavaScript:alert(1)'), null)
  assert.equal(safeHref('data:text/html,<script>'), null)
  assert.equal(safeHref('vbscript:x'), null)
  assert.equal(safeHref(''), null)
})

// --- streaming robustness -------------------------------------------------

check('partial stream prefixes never throw', () => {
  const src = '# Title\n\nIntro **bo\n\n```json\n{"scenes": [\n'
  for (let n = 0; n <= src.length; n++) {
    parseMarkdown(src.slice(0, n))
  }
})

check('pathological input does not hang or throw', () => {
  for (const src of ['', '\n\n\n', '```', '>>>', '---', '***', '#', '[', '`', '**']) {
    parseMarkdown(src)
  }
})

// --- report ---------------------------------------------------------------

if (failures.length) {
  console.log(`FAILED ${failures.length} of ${passed + failures.length}`)
  for (const f of failures) console.log(`  x ${f}`)
  process.exit(1)
}
console.log(`all ${passed} markdown checks passed`)
