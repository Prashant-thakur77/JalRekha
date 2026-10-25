import { Outlet, Link, useLocation } from 'react-router-dom';
import { useAppStore, API_BASE } from '../store';
import { CheckCircle2, Menu, Siren, Wifi, WifiOff, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { LANGS, useI18n, type Lang } from '../i18n';
import Toasts from './Toasts';
import PinDialogHost from './PinDialog';
import Logo from './Logo';
import ThemeToggle from './ThemeToggle';

interface NavItem {
	path: string;
	label: string;
	/** Also active for nested routes (e.g. /traces/:id). */
	prefix?: boolean;
}

/** Routes whose first section runs edge to edge under the floating nav. */
const BLEED_ROUTES = new Set(['/', '/story', '/live']);

function isActive(pathname: string, item: NavItem) {
	return pathname === item.path || Boolean(item.prefix && pathname.startsWith(`${item.path}/`));
}

export default function Layout() {
	const { isOnline, queueCount, checkConnectivity, setOnline } = useAppStore();
	const location = useLocation();
	const { t, lang, setLang } = useI18n();
	const wasOffline = useRef(false);
	const prevQueue = useRef(queueCount);
	const [flashSynced, setFlashSynced] = useState(false);
	const [sheetOpen, setSheetOpen] = useState(false);
	const [moreOpen, setMoreOpen] = useState(false);
	const sheetBtn = useRef<HTMLButtonElement>(null);
	const sheetRef = useRef<HTMLDivElement>(null);
	const moreBtn = useRef<HTMLButtonElement>(null);
	const moreWrap = useRef<HTMLDivElement>(null);
	const ids = useId();

	const primary: NavItem[] = [
		{ path: '/', label: t('nav.home') },
		{ path: '/live', label: t('nav.live') },
		{ path: '/approvals', label: t('nav.approvals') },
		{ path: '/traces', label: t('nav.traces'), prefix: true },
		{ path: '/rivers', label: t('nav.rivers') },
		{ path: '/relief', label: t('nav.relief') },
		{ path: '/story', label: t('nav.story') },
	];
	const legacy: NavItem[] = [
		{ path: '/dashboard', label: t('nav.command') },
		{ path: '/report', label: t('nav.reports') },
		{ path: '/queue', label: t('nav.queue', { n: queueCount }) },
		{ path: '/settings', label: t('nav.runtime') },
	];
	const about: NavItem[] = [{ path: '/credits', label: t('nav.credits') }];

	useEffect(() => {
		if (!isOnline) {
			wasOffline.current = true;
		} else if (wasOffline.current && queueCount === 0 && prevQueue.current > 0) {
			setFlashSynced(true);
			const timer = setTimeout(() => setFlashSynced(false), 2500);
			wasOffline.current = false;
			return () => clearTimeout(timer);
		}
		prevQueue.current = queueCount;
	}, [isOnline, queueCount]);

	useEffect(() => {
		checkConnectivity();
		const interval = setInterval(() => {
			checkConnectivity();
		}, 10000);
		return () => clearInterval(interval);
	}, [checkConnectivity]);

	// Desktop "More" popover: close on outside click or Escape.
	useEffect(() => {
		if (!moreOpen) return;
		const onDown = (e: MouseEvent) => {
			if (moreWrap.current && !moreWrap.current.contains(e.target as Node)) setMoreOpen(false);
		};
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				setMoreOpen(false);
				moreBtn.current?.focus();
			}
		};
		document.addEventListener('mousedown', onDown);
		document.addEventListener('keydown', onKey);
		return () => {
			document.removeEventListener('mousedown', onDown);
			document.removeEventListener('keydown', onKey);
		};
	}, [moreOpen]);

	// Full-screen menu: Escape closes it, focus moves in and returns to the button, the page does not scroll behind it.
	useEffect(() => {
		if (!sheetOpen) return;
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				setSheetOpen(false);
				sheetBtn.current?.focus();
			}
		};
		document.addEventListener('keydown', onKey);
		const prevOverflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		sheetRef.current?.querySelector<HTMLElement>('a, button')?.focus();
		return () => {
			document.removeEventListener('keydown', onKey);
			document.body.style.overflow = prevOverflow;
		};
	}, [sheetOpen]);

	const toggleOffline = async () => {
		const nextStatus = !isOnline;
		try {
			await fetch(`${API_BASE}/settings/connectivity`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ is_online: nextStatus }),
			});
		} catch (error) {
			console.error('Could not toggle backend offline status', error);
		}
		setOnline(nextStatus);
	};

	const closeAll = () => {
		setSheetOpen(false);
		setMoreOpen(false);
	};

	const connectivityButton = (className: string) => (
		<button
			type="button"
			className={className}
			onClick={() => void toggleOffline()}
			aria-pressed={!isOnline}
			title={t('status.toggleHint')}
		>
			{isOnline ? <WifiOff className="w-4 h-4" aria-hidden="true" /> : <Wifi className="w-4 h-4" aria-hidden="true" />}
			<span>{isOnline ? t('nav.simulateOffline') : t('nav.simulateOnline')}</span>
		</button>
	);

	const langSelect = (id: string, className: string) => (
		<>
			<label htmlFor={id} className="sr-only">
				{t('lang.label')}
			</label>
			<select id={id} className={className} value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
				{LANGS.map((l) => (
					<option key={l.code} value={l.code} lang={l.code}>
						{l.native}
					</option>
				))}
			</select>
		</>
	);

	const bleed = BLEED_ROUTES.has(location.pathname);

	return (
		<div className="ns-app">
			<a href="#main" className="ns-skip">
				{t('skip.main')}
			</a>
			<header className="ns-nav-wrap">
				<div className="ns-nav">
					<Link to="/" className="ns-brand" aria-label={t('nav.home.aria')} onClick={closeAll}>
						<Logo />
						<span className="ns-brand__name">NadiSaathi</span>
					</Link>

					<nav className="ns-nav__links" aria-label={t('nav.main')}>
						<ul>
							{primary.map((item) => (
								<li key={item.path}>
									<Link to={item.path} aria-current={isActive(location.pathname, item) ? 'page' : undefined}>
										{item.label}
									</Link>
								</li>
							))}
						</ul>
					</nav>

					<div className="ns-nav__tools">
						<span
							className={`ns-nav__status${isOnline ? '' : ' ns-nav__status--off'}`}
							title={isOnline ? t('status.online') : t('status.offline')}
						>
							<span className="sr-only">{isOnline ? t('status.online') : t('status.offline')}</span>
						</span>
						<Link to="/live" className="ns-nav__cta" onClick={closeAll}>
							{t('home.ctaLive')}
						</Link>
						<span className="ns-nav__desk">{langSelect('ui-lang', 'ns-nav__btn ns-nav__lang')}</span>
						<span className="ns-nav__desk">
							<ThemeToggle className="ns-nav__btn ns-nav__icon" />
						</span>
						<div className="ns-more ns-nav__desk" ref={moreWrap}>
							<button
								ref={moreBtn}
								type="button"
								className="ns-nav__btn ns-nav__more"
								aria-expanded={moreOpen}
								aria-controls={`${ids}-more`}
								onClick={() => setMoreOpen((o) => !o)}
							>
								{t('nav.more')}
								<span className="sr-only"> {t('nav.pages')}</span>
							</button>
							{moreOpen && (
								<div id={`${ids}-more`} className="ns-menu ns-dark">
									<p className="ns-menu__title">{t('nav.legacy')}</p>
									<ul className="ns-menu__list">
										{legacy.map((item) => (
											<li key={item.path}>
												<Link
													to={item.path}
													className="ns-menu__item"
													aria-current={isActive(location.pathname, item) ? 'page' : undefined}
													onClick={closeAll}
												>
													{item.label}
												</Link>
											</li>
										))}
									</ul>
									<p className="ns-menu__title">{t('footer.about')}</p>
									<ul className="ns-menu__list">
										{about.map((item) => (
											<li key={item.path}>
												<Link to={item.path} className="ns-menu__item" onClick={closeAll}>
													{item.label}
												</Link>
											</li>
										))}
										<li>{connectivityButton('ns-menu__item')}</li>
									</ul>
								</div>
							)}
						</div>
						<button
							ref={sheetBtn}
							type="button"
							className="ns-nav__btn ns-nav__menu"
							aria-expanded={sheetOpen}
							aria-controls={`${ids}-sheet`}
							onClick={() => setSheetOpen((o) => !o)}
						>
							{sheetOpen ? <X className="w-5 h-5" aria-hidden="true" /> : <Menu className="w-5 h-5" aria-hidden="true" />}
							<span className="sr-only">{t('nav.menu')}</span>
						</button>
					</div>
				</div>
			</header>

			{sheetOpen && (
				<div id={`${ids}-sheet`} ref={sheetRef} className="ns-sheet ns-dark" role="dialog" aria-modal="true" aria-label={t('nav.menu')}>
					<nav aria-label={t('nav.main')}>
						<ul className="ns-sheet__primary">
							{primary.map((item) => (
								<li key={item.path}>
									<Link to={item.path} aria-current={isActive(location.pathname, item) ? 'page' : undefined} onClick={closeAll}>
										{item.label}
									</Link>
								</li>
							))}
						</ul>
					</nav>
					<div className="ns-sheet__cols">
						<div>
							<p className="ns-menu__title">{t('nav.legacy')}</p>
							<ul className="ns-sheet__secondary">
								{legacy.map((item) => (
									<li key={item.path}>
										<Link to={item.path} onClick={closeAll}>
											{item.label}
										</Link>
									</li>
								))}
							</ul>
						</div>
						<div>
							<p className="ns-menu__title">{t('footer.about')}</p>
							<ul className="ns-sheet__secondary">
								{about.map((item) => (
									<li key={item.path}>
										<Link to={item.path} onClick={closeAll}>
											{item.label}
										</Link>
									</li>
								))}
							</ul>
						</div>
					</div>
					<div className="ns-sheet__tools">
						{langSelect('ui-lang-sheet', 'ns-input ns-sheet__lang')}
						<ThemeToggle className="ns-btn ns-btn--secondary ns-sheet__theme" withLabel />
						{connectivityButton('ns-btn ns-btn--tertiary')}
					</div>
				</div>
			)}

			{!isOnline && (
				<div className="ns-banner ns-banner--off" role="status">
					<Siren className="w-4 h-4" aria-hidden="true" />
					{t('banner.offline', { n: queueCount })}
				</div>
			)}
			{flashSynced && (
				<div className="ns-banner ns-banner--ok" role="status">
					<CheckCircle2 className="w-4 h-4" aria-hidden="true" /> {t('banner.synced')}
				</div>
			)}

			<main id="main" tabIndex={-1} className={`ns-main${bleed ? ' ns-main--bleed' : ''}`}>
				<Outlet />
			</main>

			<footer className="ns-footer ns-dark">
				<div className="ns-footer__inner">
					<div className="ns-footer__brand">
						<p className="ns-footer__name">
							<Logo className="ns-footer__mark" />
							NadiSaathi <span lang="ne">नदी साथी</span>
						</p>
						<p>{t('footer.tagline')}</p>
					</div>
					<div className="ns-footer__cols">
						<div>
							<h2 className="ns-footer__title">{t('footer.app')}</h2>
							<ul className="ns-footer__list">
								{primary.map((item) => (
									<li key={item.path}>
										<Link to={item.path}>{item.label}</Link>
									</li>
								))}
							</ul>
						</div>
						<div>
							<h2 className="ns-footer__title">{t('nav.legacy')}</h2>
							<ul className="ns-footer__list">
								{legacy.map((item) => (
									<li key={item.path}>
										<Link to={item.path}>{item.label}</Link>
									</li>
								))}
							</ul>
						</div>
						<div>
							<h2 className="ns-footer__title">{t('footer.about')}</h2>
							<ul className="ns-footer__list">
								{about.map((item) => (
									<li key={item.path}>
										<Link to={item.path}>{item.label}</Link>
									</li>
								))}
							</ul>
						</div>
					</div>
				</div>
				<div className="ns-footer__base">
					<p>{t('footer.notOfficial')}</p>
					<p>
						{t('footer.note')} <Link to="/credits">{t('nav.credits')}</Link>
					</p>
				</div>
			</footer>

			<Toasts />
			<PinDialogHost />
		</div>
	);
}
