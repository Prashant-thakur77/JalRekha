import { ExternalLink } from 'lucide-react';
import { useI18n } from '../i18n';
import { usePhotos } from '../lib/photos';
import Photo from '../components/Photo';
import { PageHeader, StateNotice } from '../components/ui';

interface Notice {
  name: string;
  what: string;
  licence: string;
  href?: string;
  licenceHref?: string;
}

/** Licence attribution for the photographs and data the app uses. */
export default function Credits() {
  const { t } = useI18n();
  const { photos, error } = usePhotos();

  const notices: Notice[] = [
    {
      name: t('credits.usgsName'),
      what: t('credits.usgs'),
      licence: t('credits.usgsLicence'),
      href: 'https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits',
    },
    {
      name: t('credits.meteoName'),
      what: t('credits.meteo'),
      licence: 'CC BY 4.0',
      href: 'https://open-meteo.com/',
      licenceHref: 'https://creativecommons.org/licenses/by/4.0/',
    },
    {
      name: t('credits.opencvName'),
      what: t('credits.opencv'),
      licence: 'Apache-2.0',
      href: 'https://opencv.org/license/',
      licenceHref: 'https://www.apache.org/licenses/LICENSE-2.0',
    },
    {
      name: t('credits.modelsName'),
      what: t('credits.models'),
      licence: t('credits.modelsLicence'),
    },
  ];

  return (
    <div className="ns-page">
      <PageHeader title={t('credits.title')} subtitle={t('credits.subtitle')} />

      <section className="ns-stack" aria-labelledby="credits-photos-h">
        <h2 id="credits-photos-h" className="ns-eyebrow">
          {t('credits.photos')}
        </h2>
        {photos === null && <StateNotice kind="loading" message={t('common.loading')} />}
        {photos && photos.length === 0 && (
          <StateNotice kind={error ? 'error' : 'empty'} message={error ? t('credits.photosError') : t('credits.photosEmpty')} />
        )}
        {photos && photos.length > 0 && (
          <ul className="ns-credits-grid">
            {photos.map((p) => (
              <li key={p.id} className="ns-credit-card">
                <Photo photo={p} credit="none" sizesHint={4000} />
                <div className="ns-credit-card__body">
                  <h3 className="ns-credit-card__title" lang="en">
                    {p.title || p.id}
                  </h3>
                  {p.place && (
                    <p className="ns-hint" lang="en">
                      {p.place}
                    </p>
                  )}
                  <p>{t('photo.by', { author: p.author })}</p>
                  <p>
                    {t('credits.licence')}:{' '}
                    {p.license_url ? (
                      <a className="ns-link" href={p.license_url} target="_blank" rel="noreferrer license">
                        {p.license || p.license_url}
                      </a>
                    ) : (
                      <span>{p.license || '–'}</span>
                    )}
                  </p>
                  {p.source_url && (
                    <p>
                      <a className="ns-link" href={p.source_url} target="_blank" rel="noreferrer">
                        {t('credits.original')} <ExternalLink className="w-4 h-4" aria-hidden="true" />
                      </a>
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="ns-stack" aria-labelledby="credits-data-h">
        <h2 id="credits-data-h" className="ns-eyebrow">
          {t('credits.data')}
        </h2>
        <div className="ns-dtable-card">
          <table className="ns-dtable">
            <thead>
              <tr>
                <th scope="col">{t('credits.colSource')}</th>
                <th scope="col">{t('credits.colUse')}</th>
                <th scope="col" className="ns-num">{t('credits.licence')}</th>
              </tr>
            </thead>
            <tbody>
              {notices.map((n) => (
                <tr key={n.name}>
                  <th scope="row">
                    {n.href ? (
                      <a className="ns-link" href={n.href} target="_blank" rel="noreferrer">
                        {n.name}
                      </a>
                    ) : (
                      n.name
                    )}
                  </th>
                  <td>{n.what}</td>
                  <td className="ns-num">
                    {n.licenceHref ? (
                      <a href={n.licenceHref} target="_blank" rel="noreferrer license" className="ns-link">
                        {n.licence}
                      </a>
                    ) : (
                      n.licence
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
