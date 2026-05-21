import { useEffect, useMemo, useRef, useState } from 'react';

// 全局缓存：记录每个 id 最近一次"已经完整呈现"的文本。
// 这样消息列表滚动 / 父组件 re-render 时不会让旧气泡反复重放打字效果，
// 只有第一次拿到目标文本的气泡才会逐字输出。
const animatedCache: Map<string, string> = new Map();

interface TypewriterTextProps {
  /** 用于缓存命中、避免重复重放的稳定标识。 */
  id: string;
  /** 目标文本。 */
  text: string;
  /** 每个字符之间的延迟（毫秒）。 */
  speed?: number;
  /** 关闭打字机效果时直接显示完整文本。 */
  enabled?: boolean;
}

// Markdown 链接 [text](url) 与裸 URL 的联合匹配；
// 使用全局正则按顺序切片，把命中片段渲染成 <a>，其余保持纯文本。
// - 链接文本不含换行 / 反引号 / 方括号；
// - URL 部分允许常见的 URL 字符，禁止空白和右括号闭合 token；
// - 裸 URL 仅匹配 http(s)://，避免误伤普通文本里的 ":" 等。
const RICH_TOKEN_RE = /\[([^\[\]\n`]+?)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>()"']+)/g;

type Segment =
  | { kind: 'text'; value: string }
  | { kind: 'link'; label: string; href: string };

function parseRichSegments(text: string): Segment[] {
  if (!text) return [];
  const segments: Segment[] = [];
  let lastIdx = 0;
  // 重置 lastIndex 以防全局正则状态泄漏。
  RICH_TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = RICH_TOKEN_RE.exec(text)) !== null) {
    if (m.index > lastIdx) {
      segments.push({ kind: 'text', value: text.slice(lastIdx, m.index) });
    }
    if (m[1] && m[2]) {
      // markdown link
      segments.push({ kind: 'link', label: m[1], href: m[2] });
    } else if (m[3]) {
      // 裸 URL，去掉常见的尾部标点
      let href = m[3];
      const trailing = /[).,;!?，。；！？)】]$/;
      while (trailing.test(href)) {
        href = href.slice(0, -1);
      }
      segments.push({ kind: 'link', label: href, href });
      // 把剥离掉的尾部标点补回为后续文本，避免吞字符。
      const consumed = m[3].length - href.length;
      if (consumed > 0) {
        // 把被吞掉的部分塞回索引，下一轮匹配从这里继续。
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

export function RichText({ text }: { text: string }) {
  const segments = useMemo(() => parseRichSegments(text), [text]);
  if (segments.length === 0) return null;
  // 仅有纯文本时直接返回字符串，避免多余的 span 包裹影响 white-space: pre-wrap。
  if (segments.length === 1 && segments[0].kind === 'text') {
    return <>{segments[0].value}</>;
  }
  return (
    <>
      {segments.map((seg, i) =>
        seg.kind === 'link' ? (
          <a
            key={i}
            href={seg.href}
            target="_blank"
            rel="noreferrer"
            style={{ color: '#5ca5db', textDecoration: 'underline', wordBreak: 'break-all' }}
          >
            {seg.label}
          </a>
        ) : (
          <span key={i}>{seg.value}</span>
        ),
      )}
    </>
  );
}

export function TypewriterText({ id, text, speed = 18, enabled = true }: TypewriterTextProps) {
  const initial = !enabled || animatedCache.get(id) === text ? text : '';
  const [shown, setShown] = useState<string>(initial);
  const targetRef = useRef<string>(text);

  useEffect(() => {
    targetRef.current = text;

    if (!enabled) {
      setShown(text);
      animatedCache.set(id, text);
      return;
    }

    if (animatedCache.get(id) === text) {
      setShown(text);
      return;
    }

    let i = 0;
    setShown('');
    const timer = window.setInterval(() => {
      i += 1;
      const cur = targetRef.current;
      setShown(cur.slice(0, i));
      if (i >= cur.length) {
        window.clearInterval(timer);
        animatedCache.set(id, cur);
      }
    }, Math.max(4, speed));

    return () => {
      window.clearInterval(timer);
      animatedCache.set(id, targetRef.current);
    };
  }, [id, text, enabled, speed]);

  // 打字完成后切到富文本渲染：把 [text](url) 与裸 URL 转成可点击超链接。
  // 动画过程中链接 token 还没成型，仍渲染纯字符，避免出现"半个 a 标签"。
  const finished = shown === text;
  if (finished) {
    return <RichText text={text} />;
  }
  return <>{shown}</>;
}

export default TypewriterText;
