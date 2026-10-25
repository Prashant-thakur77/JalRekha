import { API_BASE } from '../store';
import { getStoredPin } from '../api';

/** In the cloud deployment every non-public write needs the operator PIN. The original
 *  pages call fetch() directly, so attach the session's PIN (if one was entered) to
 *  their write requests. Public submissions do not need it but it does no harm. */
export function installPinFetch(): void {
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const pin = getStoredPin();
    if (pin && method !== 'GET' && url.startsWith(API_BASE)) {
      const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
      if (!headers.has('X-Operator-Pin')) headers.set('X-Operator-Pin', pin);
      return original(input, { ...init, headers });
    }
    return original(input, init);
  };
}
