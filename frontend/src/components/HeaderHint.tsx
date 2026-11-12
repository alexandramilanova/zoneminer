import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

/** Hover/focus help stays outside the scrolling table and never expands a row. */
export default function HeaderHint({ label, text }: { label: string; text: string }) {
  const id = useId();
  const icon = useRef<HTMLSpanElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number; width: number } | null>(null);
  const show = () => {
    const box = icon.current?.getBoundingClientRect();
    if (!box) return;
    const width = Math.min(280, window.innerWidth - 24);
    setPosition({ left: Math.max(12, Math.min(box.right - width, window.innerWidth - width - 12)),
      top: box.bottom + 120 < window.innerHeight ? box.bottom + 8 : Math.max(12, box.top - 120), width });
  };
  useEffect(() => {
    if (!position) return;
    const hide = () => setPosition(null);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => { window.removeEventListener("scroll", hide, true); window.removeEventListener("resize", hide); };
  }, [position]);
  return <>
    <span ref={icon} className="table-header-info" tabIndex={0} role="img" aria-label={`About ${label}`}
      aria-describedby={position ? id : undefined} onMouseEnter={show} onMouseLeave={() => setPosition(null)}
      onFocus={show} onBlur={() => setPosition(null)} onKeyDown={event => { if (event.key === "Escape") setPosition(null); }}>ⓘ</span>
    {position && createPortal(<span id={id} role="tooltip" className="table-header-tooltip" style={position}>{text}</span>, document.body)}
  </>;
}
