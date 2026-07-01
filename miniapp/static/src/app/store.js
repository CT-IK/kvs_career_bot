const FAVORITES_KEY = 'kvs-job:favorites';
const ONBOARDING_KEY = 'kvs-job:onboarding-seen';
const ADMIN_EMAIL = '253103@edu.fa.ru';
const ADMIN_DEVELOPERS_KEY = 'kvs-job:admin-developers';
const ADMIN_PLACES_KEY = 'kvs-job:admin-places';

function readList(key) {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function readFavorites() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(FAVORITES_KEY) || '["sber-data-intern"]');
    return new Set(Array.isArray(parsed) ? parsed : ['sber-data-intern']);
  } catch {
    return new Set(['sber-data-intern']);
  }
}

export const store = {
  route: null,
  filters: {
    vacancyQuery: '',
    vacancyCategory: 'Все',
    eventCategory: 'Все',
  },
  profileTab: 'resume',
  profileLoginMode: 'button',
  profileEmail: '',
  profileEmailError: '',
  adminMode: 'panel',
  adminDevelopers: readList(ADMIN_DEVELOPERS_KEY),
  adminPlaces: readList(ADMIN_PLACES_KEY),
  adminFormError: '',
  favorites: readFavorites(),
  onboardingSeen: window.localStorage.getItem(ONBOARDING_KEY) === '1',
};

export function isProfileAuthenticated() {
  return Boolean(store.profileEmail);
}

export function isAdminProfile() {
  return store.profileEmail === ADMIN_EMAIL;
}

export function startProfileLogin() {
  store.profileLoginMode = 'email';
  store.profileEmailError = '';
}

export function submitProfileEmail(email) {
  const normalized = String(email || '').trim().toLowerCase();
  if (!/^[a-z0-9._%+-]+@edu\.fa\.ru$/i.test(normalized)) {
    store.profileEmailError = 'Почта должна заканчиваться на @edu.fa.ru';
    return false;
  }
  store.profileEmail = normalized;
  store.profileEmailError = '';
  store.profileLoginMode = 'button';
  store.adminMode = normalized === ADMIN_EMAIL ? 'panel' : 'profile';
  return true;
}

export function logoutProfile() {
  store.profileEmail = '';
  store.profileLoginMode = 'button';
  store.profileEmailError = '';
  store.adminMode = 'panel';
  store.adminFormError = '';
}

export function setAdminMode(mode) {
  store.adminMode = mode === 'profile' ? 'profile' : 'panel';
  store.adminFormError = '';
}

export function addAdminDeveloper({ name, email }) {
  const n = String(name || '').trim();
  const e = String(email || '').trim().toLowerCase();
  if (!n || !/^[a-z0-9._%+-]+@edu\.fa\.ru$/i.test(e)) {
    store.adminFormError = 'Укажи имя и почту разработчика в домене edu.fa.ru';
    return false;
  }
  store.adminDevelopers = [
    { id: window.crypto?.randomUUID?.() || `${Date.now()}`, name: n, email: e },
    ...store.adminDevelopers,
  ];
  store.adminFormError = '';
  window.localStorage.setItem(ADMIN_DEVELOPERS_KEY, JSON.stringify(store.adminDevelopers));
  return true;
}

export function addAdminPlace({ title, address }) {
  const t = String(title || '').trim();
  const addr = String(address || '').trim();
  if (!t || !addr) {
    store.adminFormError = 'Укажи название и адрес места';
    return false;
  }
  store.adminPlaces = [
    { id: window.crypto?.randomUUID?.() || `${Date.now()}`, title: t, address: addr },
    ...store.adminPlaces,
  ];
  store.adminFormError = '';
  window.localStorage.setItem(ADMIN_PLACES_KEY, JSON.stringify(store.adminPlaces));
  return true;
}

export function saveFavorites() {
  window.localStorage.setItem(FAVORITES_KEY, JSON.stringify([...store.favorites]));
}

export function toggleFavorite(id) {
  if (store.favorites.has(id)) {
    store.favorites.delete(id);
  } else {
    store.favorites.add(id);
  }
  saveFavorites();
}

export function markOnboardingSeen() {
  store.onboardingSeen = true;
  window.localStorage.setItem(ONBOARDING_KEY, '1');
}