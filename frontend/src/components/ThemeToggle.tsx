import { useEffect } from 'react';
import { Moon, Sun } from 'lucide-react';
import { useThemeStore, watchSystemTheme } from '../lib/theme';
import { useI18n } from '../i18n';

/** Switches between light and dark. The button's name says what it will do. */
export default function ThemeToggle({ className = 'ns-nav__btn ns-nav__icon', withLabel = false }: { className?: string; withLabel?: boolean }) {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const { t } = useI18n();

  useEffect(() => watchSystemTheme(), []);

  const label = theme === 'dark' ? t('theme.toLight') : t('theme.toDark');
  const Icon = theme === 'dark' ? Sun : Moon;
  return (
    <button type="button" className={className} onClick={toggle} aria-label={withLabel ? undefined : label} title={label} data-theme-now={theme}>
      <Icon className="w-4 h-4" aria-hidden="true" />
      {withLabel && <span>{label}</span>}
    </button>
  );
}
