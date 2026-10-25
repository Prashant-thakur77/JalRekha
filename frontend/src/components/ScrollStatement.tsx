import { useEffect, useRef, useState, type ReactNode } from 'react';

function reducedMotion(): boolean {
  try {
    return typeof window === 'undefined' || !window.matchMedia || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return true;
  }
}

/**
 * A large statement on a dark band whose words brighten from 30 % to full
 * opacity as the section scrolls through the viewport. Words stay lit once
 * lit. With reduced motion (or no matchMedia) the whole sentence is shown at once.
 */
export default function ScrollStatement({ text, lang, children }: { text: string; lang?: string; children?: ReactNode }) {
  const words = text.split(/\s+/).filter(Boolean);
  const ref = useRef<HTMLParagraphElement>(null);
  const [lit, setLit] = useState(() => (reducedMotion() ? words.length : Math.ceil(words.length * 0.4)));

  useEffect(() => {
    if (reducedMotion()) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const vh = window.innerHeight || 800;
      const progress = Math.min(1, Math.max(0, (vh * 0.85 - rect.top) / (rect.height + vh * 0.35)));
      const target = Math.ceil(words.length * (0.4 + 0.6 * progress));
      setLit((prev) => (target > prev ? target : prev));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [words.length]);

  return (
    <section className="ns-statement ns-dark">
      <p ref={ref} className="ns-statement__text" lang={lang}>
        {words.map((w, i) => (
          <span key={i} className={i < lit ? 'is-lit' : undefined}>
            {w}{' '}
          </span>
        ))}
      </p>
      {children}
    </section>
  );
}
