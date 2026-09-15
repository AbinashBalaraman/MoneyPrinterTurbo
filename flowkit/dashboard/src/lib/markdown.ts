/**
 * A small Markdown parser for the Agent Studio transcript.
 *
 * Why not a library
 * -----------------
 * The transcript is model output, so it is untrusted text. Rendering it through
 * a general-purpose Markdown library means trusting that library's sanitiser.
 * This parser instead produces a *data structure* which the renderer turns into
 * React elements — React escapes text nodes itself, so there is no
 * `dangerouslySetInnerHTML` anywhere and no HTML injection surface at all.
 *
 * It also means no new dependency, which matters here: the sandbox throttles
 * `npm install` badly enough that one already took over half an hour.
 *
 * Scope
 * -----
 * Deliberately the subset an assistant actually emits: headings, fenced code,
 * lists, blockquotes, rules, and inline code/bold/italic/strikethrough/links.
 * Tables and HTML passthrough are not supported — HTML is shown as text rather
 * than interpreted, which is the safe default.
 *
 * Streaming
 * ---------
 * The parser is written to tolerate partial input, because during a stream the
 * text is frequently mid-construct: an unterminated code fence renders as a
 * code block, an unclosed `**` stays literal, and a half-written link is left
 * as text. Nothing throws.
 */

export type Block =
  | { kind: 'paragraph'; text: string }
  | { kind: 'heading'; level: 1 | 2 | 3 | 4 | 5 | 6; text: string }
  | { kind: 'code'; lang: string | null; code: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'quote'; text: string }
  | { kind: 'rule' }

export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'bold'; text: string }
  | { kind: 'italic'; text: string }
  | { kind: 'strike'; text: string }
  | { kind: 'link'; text: string; href: string }

const FENCE = /^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/
const HEADING = /^(#{1,6})\s+(.*)$/
const RULE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/
const QUOTE = /^\s*>\s?/
const LIST_ITEM = /^\s*([-*+]|\d+[.)])\s+(.*)$/

/** True when a line begins a construct other than a paragraph. */
function startsBlock(line: string): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    QUOTE.test(line) ||
    LIST_ITEM.test(line)
  )
}

/**
 * Split Markdown source into block-level nodes.
 *
 * Never throws: malformed input degrades to paragraphs rather than failing a
 * render, because a half-received stream is the normal case while streaming.
 */
export function parseMarkdown(src: string): Block[] {
  const lines = (src ?? '').replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    if (!line.trim()) {
      i++
      continue
    }

    const fence = FENCE.exec(line)
    if (fence) {
      const marker = fence[1][0]
      const lang = fence[2] || null
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith(marker.repeat(3))) {
        body.push(lines[i])
        i++
      }
      // Consume the closing fence if there is one. An unclosed fence is normal
      // mid-stream, so the block is emitted either way.
      if (i < lines.length) i++
      blocks.push({ kind: 'code', lang, code: body.join('\n') })
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      blocks.push({
        kind: 'heading',
        level: heading[1].length as 1 | 2 | 3 | 4 | 5 | 6,
        text: heading[2].trim(),
      })
      i++
      continue
    }

    if (RULE.test(line)) {
      blocks.push({ kind: 'rule' })
      i++
      continue
    }

    if (QUOTE.test(line)) {
      const body: string[] = []
      while (i < lines.length && QUOTE.test(lines[i])) {
        body.push(lines[i].replace(QUOTE, ''))
        i++
      }
      blocks.push({ kind: 'quote', text: body.join('\n') })
      continue
    }

    const item = LIST_ITEM.exec(line)
    if (item) {
      const ordered = /\d/.test(item[1])
      const items: string[] = []
      while (i < lines.length) {
        const next = LIST_ITEM.exec(lines[i])
        // A switch between bullet and numbered ends the list rather than
        // silently merging two different lists into one.
        if (!next || /\d/.test(next[1]) !== ordered) break
        items.push(next[2])
        i++
      }
      blocks.push({ kind: 'list', ordered, items })
      continue
    }

    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i])) {
      para.push(lines[i].trim())
      i++
    }
    if (para.length) {
      blocks.push({ kind: 'paragraph', text: para.join(' ') })
    } else {
      // Unreachable in practice, but guarantees progress so a parser bug can
      // never spin forever on a live stream.
      i++
    }
  }

  return blocks
}

/**
 * Split a line of text into inline nodes.
 *
 * Inline code is matched before emphasis so that `` `a ** b` `` keeps its
 * asterisks, which is the usual reason to reach for code formatting.
 */
export function parseInline(src: string): Inline[] {
  const out: Inline[] = []
  const text = src ?? ''
  let buffer = ''
  let i = 0

  const flush = () => {
    if (buffer) {
      out.push({ kind: 'text', text: buffer })
      buffer = ''
    }
  }

  while (i < text.length) {
    const c = text[i]

    if (c === '`') {
      const end = text.indexOf('`', i + 1)
      if (end > i + 1) {
        flush()
        out.push({ kind: 'code', text: text.slice(i + 1, end) })
        i = end + 1
        continue
      }
    }

    if (c === '[') {
      const close = text.indexOf(']', i + 1)
      if (close !== -1 && text[close + 1] === '(') {
        const paren = text.indexOf(')', close + 2)
        if (paren !== -1) {
          flush()
          out.push({
            kind: 'link',
            text: text.slice(i + 1, close),
            href: text.slice(close + 2, paren),
          })
          i = paren + 1
          continue
        }
      }
    }

    if (c === '*' && text[i + 1] === '*') {
      const end = text.indexOf('**', i + 2)
      if (end > i + 2) {
        flush()
        out.push({ kind: 'bold', text: text.slice(i + 2, end) })
        i = end + 2
        continue
      }
    }

    if (c === '~' && text[i + 1] === '~') {
      const end = text.indexOf('~~', i + 2)
      if (end > i + 2) {
        flush()
        out.push({ kind: 'strike', text: text.slice(i + 2, end) })
        i = end + 2
        continue
      }
    }

    if (c === '*' && text[i + 1] !== '*') {
      const end = text.indexOf('*', i + 1)
      if (end > i + 1 && text[end + 1] !== '*') {
        flush()
        out.push({ kind: 'italic', text: text.slice(i + 1, end) })
        i = end + 1
        continue
      }
    }

    if (c === '_') {
      // Require a boundary before the underscore so snake_case identifiers are
      // not mangled into emphasis.
      const prev = text[i - 1]
      const atBoundary = i === 0 || /[\s([{"'\-]/.test(prev)
      const end = text.indexOf('_', i + 1)
      if (atBoundary && end > i + 1) {
        flush()
        out.push({ kind: 'italic', text: text.slice(i + 1, end) })
        i = end + 1
        continue
      }
    }

    buffer += c
    i++
  }

  flush()
  return out
}

/**
 * Allow only link targets that cannot execute.
 *
 * Returns `null` for anything else — including `javascript:` and `data:` —
 * so the renderer can show the label as plain text instead of a live link.
 */
export function safeHref(href: string): string | null {
  const trimmed = (href ?? '').trim()
  if (!trimmed) return null
  if (/^(https?:|mailto:)/i.test(trimmed)) return trimmed
  if (/^[/#]/.test(trimmed)) return trimmed
  return null
}
