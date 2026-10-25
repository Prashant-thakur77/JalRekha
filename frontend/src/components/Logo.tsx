/** NadiSaathi mark: a gauge staff standing in a water line. Uses currentColor; the name always sits next to it. */
export default function Logo({ className = 'ns-brand__mark' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M15 2.5v13M15 4.5h3.5M15 8h2.5M15 11.5h3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" fill="none" />
      <path d="M2.5 17.5h4l2-2.5 2 2.5h4l2-2.5 2 2.5h3" stroke="currentColor" strokeWidth="2" strokeLinejoin="miter" fill="none" />
      <path d="M2.5 21.5h19" stroke="currentColor" strokeWidth="2" fill="none" opacity="0.55" />
    </svg>
  );
}
