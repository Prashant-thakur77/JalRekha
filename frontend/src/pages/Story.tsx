import { Fragment } from 'react';
import { Link } from 'react-router-dom';
import { chapters, context, isPlaceholder, isVerified, principles, storyMeta, type RichText } from '../content/story';
import { chaptersHi, contextHi, principlesHi, storyMetaHi } from '../content/story.hi';
import { chaptersNe, contextNe, principlesNe, storyMetaNe } from '../content/story.ne';
import { useI18n } from '../i18n';
import { orderPhotos, pickPhotos, usePhotos, type PhotoCredit } from '../lib/photos';
import Photo, { PhotoCreditLine } from '../components/Photo';
import ScrollStatement from '../components/ScrollStatement';

const CONTENT = {
  en: { storyMeta, context, chapters, principles },
  hi: { storyMeta: storyMetaHi, context: contextHi, chapters: chaptersHi, principles: principlesHi },
  ne: { storyMeta: storyMetaNe, context: contextNe, chapters: chaptersNe, principles: principlesNe },
};

/** Chapters (by index) followed by a full-bleed photograph, and the preferred photo for each. */
const PLATE_AFTER = [1, 3, 5];
const PLATE_IDS = ['nepal-triyuga-2019', 'prayagraj-ganga-bench-2011', 'bihar-ndrf-rescue-2008'];
const STORY_HERO_ID = 'koshi-barrage-2018';

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
  const { photos } = usePhotos();
  const ordered = photos ? orderPhotos(photos) : [];
  const hero: PhotoCredit | null = pickPhotos(photos, [STORY_HERO_ID])[0] ?? ordered[0] ?? null;
  const preferred = pickPhotos(photos, PLATE_IDS);
  const plates = preferred.length === PLATE_IDS.length ? preferred : ordered.filter((p) => p !== hero);
  const [keyRule, ...otherRules] = principles;

  return (
    <article className="ns-story">
      <header className="ns-hero ns-hero--story">
        {hero ? (
          <div className="ns-hero__media">
            <Photo photo={hero} eager credit="none" />
          </div>
        ) : (
          <div className="ns-hero__fallback" aria-hidden="true" />
        )}
        <div className="ns-hero__inner">
          <p className="ns-eyebrow ns-eyebrow--light">{t('story.kicker')}</p>
          <h1 className="ns-display ns-display--story" lang={cl}>
            {storyMeta.title}
          </h1>
          <p className="ns-hero__lede" lang={cl}>
            <Rich parts={storyMeta.lede} />
          </p>
          <div className="ns-actions-row">
            <Link to="/live" className="ns-btn ns-btn--primary">
              {t('story.cta')}
            </Link>
          </div>
          <p className="ns-hero__note" lang={cl}>
            {storyMeta.scenarioNote}
          </p>
        </div>
        {hero && <PhotoCreditLine photo={hero} />}
      </header>

      <div className="ns-story__body">
        <section className="ns-story__col" aria-labelledby="story-context-h">
          <p className="ns-eyebrow">{t('story.factsTitle')}</p>
          <h2 id="story-context-h" className="sr-only">
            {t('story.factsTitle')}
          </h2>
          <div className="ns-story__context" lang={cl}>
            {context.body.map((p, i) => (
              <p key={i}>
                <Rich parts={p} />
              </p>
            ))}
          </div>
        </section>

        <section aria-labelledby="story-night-h">
          <div className="ns-story__col">
            <h2 id="story-night-h" className="ns-h2 ns-h2--left">
              {t('story.timeline')}
            </h2>
          </div>
          <ol className="ns-chapters" lang={cl}>
            {chapters.map((ch, i) => {
              const plateIdx = PLATE_AFTER.indexOf(i);
              const plate = plateIdx >= 0 ? plates[plateIdx] : undefined;
              return (
                <Fragment key={ch.id}>
                  <li className="ns-chapter">
                    <div className="ns-chapter__meta">
                      <span className="ns-eyebrow">{ch.time}</span>
                      <span className="ns-chapter__place">{ch.place}</span>
                      <span className="ns-badge" title={td(`country.${ch.country}`, ch.country)}>
                        {ch.country}
                      </span>
                    </div>
                    <div className="ns-chapter__text">
                      <h3 className="ns-chapter__heading">{ch.heading}</h3>
                      {ch.body.map((p, j) => (
                        <p key={j}>
                          <Rich parts={p} />
                        </p>
                      ))}
                    </div>
                  </li>
                  {plate && (
                    <li className="ns-plate" aria-hidden="false">
                      <Photo
                        photo={plate}
                        credit="below"
                        caption={
                          plate.title ? (
                            <span lang="en" className="ns-plate__title">
                              {plate.title}
                              {plate.place ? `, ${plate.place}` : ''}
                            </span>
                          ) : null
                        }
                      />
                    </li>
                  )}
                </Fragment>
              );
            })}
          </ol>
        </section>
      </div>

      {keyRule && (
        <ScrollStatement text={keyRule} lang={cl}>
          <p className="ns-statement__source">{t('story.keyEyebrow')}</p>
        </ScrollStatement>
      )}

      <div className="ns-story__body">
        <section aria-labelledby="story-how-h">
          <header className="ns-section__head">
            <p className="ns-kicker">{t('story.howTitle')}</p>
            <h2 id="story-how-h" className="sr-only">
              {t('story.howTitle')}
            </h2>
          </header>
          <ul className="ns-crossgrid ns-rules" lang={cl}>
            {otherRules.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>

        <p className="ns-story__persona" lang={cl}>
          {storyMeta.personaNote}
        </p>

        <div className="ns-story__cta">
          <p className="ns-lead" lang={cl}>
            {t('story.ctaHint')}
          </p>
          <Link to="/live" className="ns-btn ns-btn--primary">
            {t('story.cta')}
          </Link>
        </div>
      </div>
    </article>
  );
}
