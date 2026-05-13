import { useMemo } from 'react';

const RICH_TOKEN_RE = /\[([^\[\]\n`]+?)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>()"']+)/g;

type Segment =
  | { kind: 'text'; value: string }
  | { kind: 'link'; label: string; href: string };

function parseRichSegments(text: string): Segment[] {
  if (!text) return [];
  const segments: Segment[] = [];
  let lastIdx = 0;
  RICH_TOKEN_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = RICH_TOKEN_RE.exec(text)) !== null) {
    if (match.index > lastIdx) {
      segments.push({ kind: 'text', value: text.slice(lastIdx, match.index) });
    }
    if (match[1] && match[2]) {
      segments.push({ kind: 'link', label: match[1], href: match[2] });
    } else if (match[3]) {
      let href = match[3];
      while (/[).,;!?，。；！？)】]$/.test(href)) {
        href = href.slice(0, -1);
      }
      segments.push({ kind: 'link', label: href, href });
      const consumed = match[3].length - href.length;
      if (consumed > 0) {
        RICH_TOKEN_RE.lastIndex -= consumed;
      }
    }
    lastIdx = RICH_TOKEN_RE.lastIndex;
  }
  if (lastIdx < text.length) {
    segments.push({ kind: 'text', value: text.slice(lastIdx) });
  }
  return segments;
}

export function RichText({ text, linkColor = '#5ca5db' }: { text: string; linkColor?: string }) {
  const segments = useMemo(() => parseRichSegments(text), [text]);
  if (segments.length === 0) return null;
  if (segments.length === 1 && segments[0].kind === 'text') {
    return <>{segments[0].value}</>;
  }
  return (
    <>
      {segments.map((segment, index) =>
        segment.kind === 'link' ? (
          <a
            key={index}
            href={segment.href}
            target="_blank"
            rel="noreferrer"
            style={{ color: linkColor, textDecoration: 'underline', wordBreak: 'break-all' }}
          >
            {segment.label}
          </a>
        ) : (
          <span key={index}>{segment.value}</span>
        ),
      )}
    </>
  );
}
