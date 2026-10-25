import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { PhotoCredit } from '../lib/photos';
import { useI18n } from '../i18n';

/** Small mono credit: factual title, photographer and licence, linking to the Credits page. */
export function PhotoCreditLine({
  photo,
  variant = 'overlay',
  text,
  omitTitle = false,
}: {
  photo: PhotoCredit;
  variant?: 'overlay' | 'below';
  /** Override the generated line (used for the home hero's approved wording). */
  text?: string;
  /** Leave the title out when a caption next to the photo already gives it. */
  omitTitle?: boolean;
}) {
  const { t } = useI18n();
  const line = text ?? [omitTitle ? '' : photo.title, t('photo.by', { author: photo.author }), photo.license].filter(Boolean).join(' · ');
  return (
    <small className={`ns-credit${variant === 'below' ? ' ns-credit--below' : ''}`}>
      <Link to="/credits" lang={text ? undefined : 'en'}>
        {line}
      </Link>
    </small>
  );
}

/**
 * A credited photograph. Uses <picture> so phones fetch the small rendition.
 * The credit sits on the image (overlay) or under it (below).
 */
export default function Photo({
  photo,
  className = '',
  eager = false,
  credit = 'overlay',
  caption,
  sizesHint,
}: {
  photo: PhotoCredit;
  className?: string;
  eager?: boolean;
  credit?: 'overlay' | 'below' | 'none';
  caption?: ReactNode;
  /** Viewport width below which the small rendition is used. */
  sizesHint?: number;
}) {
  const { lang } = useI18n();
  const useHindiAlt = (lang === 'hi' || lang === 'ne') && Boolean(photo.alt_hi);
  const alt = useHindiAlt ? (photo.alt_hi as string) : photo.alt_en;
  return (
    <figure className={`ns-pic ${className}`.trim()}>
      <div className="ns-pic__frame">
        <picture>
          {photo.web.small && <source media={`(max-width: ${sizesHint ?? 760}px)`} srcSet={photo.web.small} />}
          <img
            src={photo.web.large}
            alt={alt}
            lang={useHindiAlt ? 'hi' : 'en'}
            loading={eager ? 'eager' : 'lazy'}
            decoding="async"
            fetchPriority={eager ? 'high' : 'auto'}
          />
        </picture>
        {credit === 'overlay' && <PhotoCreditLine photo={photo} />}
      </div>
      {(caption || credit === 'below') && (
        <figcaption>
          {caption}
          {credit === 'below' && <PhotoCreditLine photo={photo} variant="below" omitTitle={Boolean(caption)} />}
        </figcaption>
      )}
    </figure>
  );
}
