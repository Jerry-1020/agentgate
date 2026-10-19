import { pinia } from '../stores';
import { useAuthStore, type PlatformIdentity } from '../stores/modules/auth';

const identityKeys = ['token', 'teamId', 'teamName', 'userId', 'userName'] as const;

function startupContext(): { embedded: boolean; identity: PlatformIdentity | null } {
  if (typeof window === 'undefined') return { embedded: false, identity: null };
  const url = new URL(window.location.href);
  const hash = url.hash.slice(1);
  const separator = hash.indexOf('?');
  const path = separator < 0 ? hash : hash.slice(0, separator);
  const hashParams = new URLSearchParams(separator < 0 ? '' : hash.slice(separator + 1));
  const embedded = window.parent !== window &&
    (url.searchParams.get('embedded') === '1' || hashParams.get('embedded') === '1');
  if (!embedded) return { embedded: false, identity: null };

  // The host owns identity validation. Missing values remain empty; they do not
  // determine the entry mode. Main-query values take precedence over hash values.
  const identity = {} as PlatformIdentity;
  for (const key of identityKeys) {
    identity[key] = url.searchParams.get(key) ?? hashParams.get(key) ?? '';
    url.searchParams.delete(key);
    hashParams.delete(key);
  }
  url.searchParams.set('embedded', '1');
  const query = hashParams.toString();
  url.hash = path + (query ? `?${query}` : '');
  window.history.replaceState(window.history.state, '', url.href);
  return { embedded: true, identity };
}

// Capture before the router can replace the initial URL. Browser-only boundary.
const startup = startupContext();
export const embeddedMode = startup.embedded;

export function initializeUrlIdentity(): void {
  if (!embeddedMode || !startup.identity) return;
  useAuthStore(pinia).initializePlatform(startup.identity);
  startup.identity = null;
}
