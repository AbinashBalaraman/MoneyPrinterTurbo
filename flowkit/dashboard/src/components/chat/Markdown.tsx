import { useMemo, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import {
  parseInline,
  parseMarkdown,
  safeHref,
  type Block,
  type Inline,
} from '../../lib/markdown'

/**
 * Render assistant output as Markdown.
 *
 * Everything here becomes React elements. There is no `dangerouslySetInnerHTML`
 * and no HTML passthrough, so model output cannot inject markup — React escapes
 * text nodes itself. Link targets are additionally filtered by `safeHref`.
 */

function Inlines({ text }: { text: string }) {
  const parts = useMemo(() => parseInline(text), [text])
  return (
    <>
      {parts.map((part, i) => (
        <InlineNode key={i} part={part} />
      ))}
    </>
  )
}

function InlineNode({ part }: { part: Inline }) {
  switch (part.kind) {
    case 'code':
      return (
        <code
          className="px-1 py-0.5 rounded text-[0.92em] font-mono"
          style={{
            background: 'var(--bg)',
            border: '1px solid var(--border)',
            color: 'var(--accent)',
          }}
        >
          {part.text}
        </code>
      )
    case 'bold':
      return (
        <strong style={{ fontWeight: 650 }}>
          <Inlines text={part.text} />
        </strong>
      )
    case 'italic':
      return (
        <em>
          <Inlines text={part.text} />
        </em>
      )
    case 'strike':
      return (
        <s style={{ opacity: 0.65 }}>
          <Inlines text={part.text} />
        </s>
      )
    case 'link': {
      const href = safeHref(part.href)
      // An unsafe scheme renders as plain text, not a live link, so a
      // javascript: target from the model cannot become clickable.
      if (!href) return <span title={part.href}>{part.text}</span>
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2"
          style={{ color: 'var(--accent)' }}
        >
          {part.text}
        </a>
      )
    }
    default:
      return <>{part.text}</>
  }
}

function CodeBlock({ lang, code }: { lang: string | null; code: string }) {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  // NOTE: syntax highlighting is deliberately deferred, not missing.
  // Per docs/CHAT_UI_REVIEW.md §2 ("would need a highlighter dependency;
  // the copy button covers the common need") and §4 ("Needs a dependency"),
  // the decision is to adopt nothing and keep this dependency-free.
  // Revisit only with a ground-up UI redesign; do not add a highlighter here.

  return (
    <div
      className="rounded-md overflow-hidden my-1"
      style={{ border: '1px solid var(--border)', background: 'var(--bg)' }}
    >
      <div
        className="flex items-center justify-between px-2.5 py-1 text-[10px] font-mono"
        style={{ borderBottom: '1px solid var(--border)', color: 'var(--muted)' }}
      >
        <span>{lang || 'text'}</span>
        <button
          onClick={copy}
          aria-label={copied ? 'Code copied' : `Copy ${lang || 'text'} code to clipboard`}
          className="flex items-center gap-1 hover:opacity-80"
        >
          {copied ? (
            <>
              <Check size={10} aria-hidden="true" /> Copied
            </>
          ) : (
            <>
              <Copy size={10} aria-hidden="true" /> Copy
            </>
          )}
        </button>
      </div>
      <pre className="px-2.5 py-2 overflow-x-auto text-[11px] leading-relaxed" style={{ margin: 0 }}>
        <code
          style={{
            fontFamily: 'var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
            color: 'var(--text)',
          }}
        >
          {code}
        </code>
      </pre>
    </div>
  )
}

const HEADING_SIZE: Record<number, string> = {
  1: '1.3em',
  2: '1.18em',
  3: '1.06em',
  4: '1em',
  5: '0.95em',
  6: '0.92em',
}

function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case 'heading': {
      // Semantic headings (not styled divs): screen-reader users navigate by
      // heading level, and a chat transcript without h1-h6 is a flat wall.
      const Tag = (`h${Math.min(Math.max(block.level, 1), 6)}` as unknown) as 'h1'
      return (
        <Tag
          style={{
            fontSize: HEADING_SIZE[block.level],
            fontWeight: 650,
            color: 'var(--text)',
            marginTop: '0.4em',
            marginBottom: '0.15em',
            lineHeight: 1.3,
          }}
        >
          <Inlines text={block.text} />
        </Tag>
      )
    }
    case 'code':
      return <CodeBlock lang={block.lang} code={block.code} />
    case 'list':
      return block.ordered ? (
        <ol className="list-decimal pl-5 space-y-0.5">
          {block.items.map((item, i) => (
            <li key={i}>
              <Inlines text={item} />
            </li>
          ))}
        </ol>
      ) : (
        <ul className="list-disc pl-5 space-y-0.5">
          {block.items.map((item, i) => (
            <li key={i}>
              <Inlines text={item} />
            </li>
          ))}
        </ul>
      )
    case 'quote':
      return (
        <blockquote
          className="pl-3 italic"
          style={{ borderLeft: '3px solid var(--border)', color: 'var(--muted)' }}
        >
          <Inlines text={block.text.replace(/\n/g, ' ')} />
        </blockquote>
      )
    case 'rule':
      return <hr style={{ border: 0, borderTop: '1px solid var(--border)' }} />
    default:
      return (
        <p>
          <Inlines text={block.text} />
        </p>
      )
  }
}

export default function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdown(text), [text])
  return (
    <div className="space-y-2">
      {blocks.map((block, i) => (
        <BlockView key={i} block={block} />
      ))}
    </div>
  )
}
