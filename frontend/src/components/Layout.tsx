import { Outlet, Link, useLocation } from "react-router-dom";
import { useAppStore, API_BASE } from "../store";
import {
	Activity,
	BookOpen,
	CheckCircle2,
	ClipboardCheck,
	FileText,
	GitBranch,
	LifeBuoy,
	Radio,
	Settings,
	Siren,
	UploadCloud,
	Waves,
	Wifi,
	WifiOff,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { LANGS, useI18n, type Lang, type MsgKey } from "../i18n";
import Toasts from "./Toasts";
import PinDialogHost from "./PinDialog";

interface NavItem {
	path: string;
	label: string;
	icon: ReactNode;
	primary?: boolean;
	legacy?: boolean;
	/** Also active for nested routes (e.g. /traces/:id). */
	prefix?: boolean;
}

export default function Layout() {
	const { isOnline, queueCount, checkConnectivity, setOnline } =
		useAppStore();
	const location = useLocation();
	const { t, lang, setLang } = useI18n();
	const wasOffline = useRef(false);
	const prevQueue = useRef(queueCount);
	const [flashSynced, setFlashSynced] = useState(false);

	useEffect(() => {
		if (!isOnline) {
			wasOffline.current = true;
		} else if (
			wasOffline.current &&
			queueCount === 0 &&
			prevQueue.current > 0
		) {
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

	const toggleOffline = async () => {
		const nextStatus = !isOnline;
		try {
			await fetch(`${API_BASE}/settings/connectivity`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ is_online: nextStatus }),
			});
		} catch (error) {
			console.error("Could not toggle backend offline status", error);
		}
		setOnline(nextStatus);
	};

	const icon = (Icon: typeof Activity) => (
		<Icon className="w-5 h-5" aria-hidden="true" />
	);
	const label = (key: MsgKey, vars?: Record<string, number>) => t(key, vars);

	const navItems: NavItem[] = [
		{ path: "/live", label: label("nav.live"), icon: icon(Radio) },
		{ path: "/approvals", label: label("nav.approvals"), icon: icon(ClipboardCheck) },
		{ path: "/traces", label: label("nav.traces"), icon: icon(GitBranch), prefix: true },
		{ path: "/rivers", label: label("nav.rivers"), icon: icon(Waves) },
		{ path: "/relief", label: label("nav.relief"), icon: icon(LifeBuoy) },
		{ path: "/story", label: label("nav.story"), icon: icon(BookOpen) },
		{ path: "/dashboard", label: label("nav.command"), icon: icon(Activity), legacy: true },
		{ path: "/report", label: label("nav.reports"), icon: icon(FileText), legacy: true },
		{ path: "/queue", label: label("nav.queue", { n: queueCount }), icon: icon(UploadCloud), legacy: true },
		{ path: "/settings", label: label("nav.runtime"), icon: icon(Settings), legacy: true },
	];

	const isActive = (item: NavItem) =>
		location.pathname === item.path ||
		(item.prefix && location.pathname.startsWith(`${item.path}/`));

	return (
		<div className="min-h-screen bg-gray-50 text-gray-900 flex flex-col font-sans">
			<a href="#main" className="ns-skip">
				{t("skip.main")}
			</a>
			<header className="ns-header">
				<div className="ns-brand">
					<Activity className="w-6 h-6" aria-hidden="true" />
					<div className="min-w-0">
						<h1 className="ns-brand__name">
							NadiSaathi{" "}
							<span lang="ne" className="ns-brand__native">
								नदी साथी
							</span>
						</h1>
						<p className="ns-brand__tagline">{t("app.tagline")}</p>
					</div>
				</div>

				<div className="ns-header__tools">
					<label htmlFor="ui-lang" className="sr-only">
						{t("lang.label")}
					</label>
					<select
						id="ui-lang"
						className="ns-lang"
						value={lang}
						onChange={(e) => setLang(e.target.value as Lang)}
					>
						{LANGS.map((l) => (
							<option key={l.code} value={l.code} lang={l.code}>
								{l.native}
							</option>
						))}
					</select>
					<button
						type="button"
						onClick={toggleOffline}
						title={t("status.toggleHint")}
						aria-pressed={!isOnline}
						className={`ns-conn ${isOnline ? "ns-conn--on" : "ns-conn--off"}`}
					>
						{isOnline ? (
							<>
								<Wifi className="w-4 h-4" aria-hidden="true" />{" "}
								{t("status.online")}
							</>
						) : (
							<>
								<WifiOff className="w-4 h-4" aria-hidden="true" />{" "}
								{t("status.offline")}
							</>
						)}
					</button>
				</div>
			</header>

			<nav className="ns-nav" aria-label={t("nav.main")}>
				<ul className="ns-nav__list">
					{navItems.map((item) => {
						const active = isActive(item);
						return (
							<li key={item.path}>
								<Link
									to={item.path}
									aria-current={active ? "page" : undefined}
									className={`ns-nav__link${item.primary ? " ns-nav__link--primary" : ""}${item.legacy ? " ns-nav__link--legacy" : ""}${
										active ? " ns-nav__link--active" : ""
									}`}
								>
									{item.icon}
									<span>{item.label}</span>
								</Link>
							</li>
						);
					})}
				</ul>
			</nav>

			{!isOnline && (
				<div className="bg-red-700 text-white px-4 py-2 text-sm font-semibold flex items-center justify-center gap-2 animate-pulse">
					<Siren className="w-4 h-4" aria-hidden="true" />
					{t("banner.offline", { n: queueCount })}
				</div>
			)}
			{flashSynced && (
				<div className="bg-green-700 text-white px-4 py-2 text-sm font-semibold flex items-center justify-center gap-2">
					<CheckCircle2 className="w-4 h-4" aria-hidden="true" />{" "}
					{t("banner.synced")}
				</div>
			)}
			<main id="main" tabIndex={-1} className="ns-main flex-1 p-4 max-w-5xl mx-auto w-full">
				<Outlet />
			</main>

			<Toasts />
			<PinDialogHost />
		</div>
	);
}
