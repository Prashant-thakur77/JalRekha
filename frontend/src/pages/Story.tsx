import { Link } from 'react-router-dom';
import { ArrowRight, Info, MapPin, ShieldCheck } from 'lucide-react';
import { chapters, context, isPlaceholder, isVerified, principles, storyMeta, type RichText } from '../content/story';
import { chaptersHi, contextHi, principlesHi, storyMetaHi } from '../content/story.hi';
import { chaptersNe, contextNe, principlesNe, storyMetaNe } from '../content/story.ne';

const CONTENT = {
  en: { storyMeta, context, chapters, principles },
  hi: { storyMeta: storyMetaHi, context: contextHi, chapters: chaptersHi, principles: principlesHi },
  ne: { storyMeta: storyMetaNe, context: contextNe, chapters: chaptersNe, principles: principlesNe },
};
import { useI18n } from '../i18n';

function Rich({ parts }: { parts: RichText }) {
  const { t, lang } = useI18n();
  return (
    <>
      {parts.map((part, i) => {
        if (typeof part === 'string') return <span key={i}>{part}</span>;
        if (isPlaceholder(part)) {
          return (
            <span key={i} lang={lang} className="ns-fact-pending" data-fact={part.placeholder} title={t('story.sourcePendingHint')}>
              [{t('story.sourcePending')}]
            </span>
          );
        }
        if (isVerified(part)) {
          return (
            <span key={i} className="ns-fact" title={part.source}>
              {part.value}
              {part.url && (
                <a className="ns-fact__src" href={part.url} target="_blank" rel="noreferrer" aria-label={`${t('story.source')}: ${part.source}`}>
                  <sup>[{t('story.source')}]</sup>
                </a>
              )}
            </span>
          );
        }
        return null;
      })}
    </>
  );
}

export default function Story() {
  const { t, td, lang } = useI18n();
  const cl = (lang === 'hi' || lang === 'ne' ? lang : 'en') as keyof typeof CONTENT;
  const { storyMeta, context, chapters, principles } = CONTENT[cl];
  return (
    <article className="ns-story">
      <header className="ns-story__hero">
        <p className="ns-story__kicker">{t('story.kicker')}</p>
        <h2 className="ns-story__title" lang={cl}>{storyMeta.title}</h2>
        <p className="ns-story__lede" lang={cl}>
          <Rich parts={storyMeta.lede} />
        </p>
        <Link to="/live" className="ns-btn ns-btn--primary ns-btn--lg">
          {t('story.cta')} <ArrowRight className="w-5 h-5" aria-hidden="true" />
        </Link>
        <p className="ns-story__note" lang={cl}>
          <Info className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {storyMeta.scenarioNote}
        </p>
      </header>

      <section aria-labelledby="story-context-h" className="ns-card ns-stack">
        <h3 id="story-context-h" className="ns-h3">{t('story.factsTitle')}</h3>
        {context.body.map((p, i) => (
          <p key={i} lang={cl}>
            <Rich parts={p} />
          </p>
        ))}
      </section>

      <section aria-labelledby="story-night-h" className="ns-stack">
        <h3 id="story-night-h" className="ns-h3">{t('story.timeline')}</h3>
        <ol className="ns-story__timeline" lang={cl}>
          {chapters.map((ch) => (
            <li key={ch.id} className={`ns-story__chapter ns-story__chapter--${ch.country.toLowerCase()}`}>
              <div className="ns-story__when">
                <span className="ns-story__time">{ch.time}</span>
                <span className="ns-story__place">
                  <MapPin className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {ch.place},{' '}
                  {td(`country.${ch.country}`, ch.country)}
                </span>
              </div>
              <h4 className="ns-story__heading">{ch.heading}</h4>
              {ch.body.map((p, i) => (
                <p key={i}>
                  <Rich parts={p} />
                </p>
              ))}
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="story-how-h" className="ns-card ns-stack">
        <h3 id="story-how-h" className="ns-h3">{t('story.howTitle')}</h3>
        <ul className="ns-principles" lang={cl}>
          {principles.map((p) => (
            <li key={p}>
              <ShieldCheck className="w-5 h-5 shrink-0" aria-hidden="true" />
              <span>{p}</span>
            </li>
          ))}
        </ul>
      </section>

      <p className="ns-story__note" lang={cl}>
        <Info className="w-4 h-4 ns-inline-icon" aria-hidden="true" /> {storyMeta.personaNote}
      </p>

      <div className="ns-story__cta">
        <p>{t('story.ctaHint')}</p>
        <Link to="/live" className="ns-btn ns-btn--primary ns-btn--lg">
          {t('story.cta')} <ArrowRight className="w-5 h-5" aria-hidden="true" />
        </Link>
      </div>
    </article>
  );
}
