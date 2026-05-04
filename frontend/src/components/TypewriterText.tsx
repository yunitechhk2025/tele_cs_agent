import { useEffect, useRef, useState } from 'react';

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

  return <>{shown}</>;
}

export default TypewriterText;
