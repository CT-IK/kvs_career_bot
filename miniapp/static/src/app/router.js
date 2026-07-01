import { store } from './store.js';

export function navigate(path) {
  window.location.hash = path;
}

export function parseRoute() {
  const raw = window.location.hash.replace(/^#/, '') || (store.onboardingSeen ? '/vacancies' : '/onboarding');
  const [path, queryString = ''] = raw.split('?');
  const params = new URLSearchParams(queryString);

  if (path.startsWith('/vacancies/')) {
    return { name: 'vacancy-detail', path, id: path.split('/').pop(), params };
  }
  if (path === '/events') return { name: 'events', path, params };
  if (path === '/profile/edit') return { name: 'profile-edit', path, params };
  if (path === '/profile') return { name: 'profile', path, params };
  if (path === '/onboarding') return { name: 'onboarding', path, params };
  return { name: 'vacancies', path: '/vacancies', params };
}

export function setRoute(route) {
  store.route = route;
  if (route.name === 'profile') {
    store.profileTab = route.params.get('tab') || store.profileTab || 'resume';
  }
}