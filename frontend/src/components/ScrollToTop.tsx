import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/** New page, new view: scroll to the top unless the URL points at an anchor (e.g. #step-3). */
export default function ScrollToTop() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (hash) return;
    try {
      window.scrollTo(0, 0);
    } catch {
      // jsdom and some embedded browsers do not implement scrollTo
    }
  }, [pathname, hash]);
  return null;
}
