import { categories, eventCategories, events, profile, vacancies } from '../mock/data.js';

const API_BASE = window.KVS_API_BASE ?? '/api/v1';
const MOCK_DELAY = 200;

const wait = (ms = MOCK_DELAY) => new Promise((resolve) => window.setTimeout(resolve, ms));

function getMode() {
  return new URLSearchParams(window.location.search).get('mockState') || 'normal';
}

function canUseMockFallback() {
  const params = new URLSearchParams(window.location.search);
  return params.has('mockState') || window.KVS_USE_MOCK === true;
}

async function request(path) {
  if (!API_BASE) return null;
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function normalize(value) {
  return String(value || '').trim().toLowerCase();
}

function matchesCategory(item, category) {
  return !category || category === 'Все' || item.category === category;
}

function matchesQuery(item, query) {
  const q = normalize(query);
  if (!q) return true;
  return [item.title, item.company?.name, item.salary, item.metro, item.format, item.kind, item.category, item.description].some((v) =>
    normalize(v).includes(q),
  );
}

async function withMockState(factory) {
  await wait();
  const mode = getMode();
  if (mode === 'error') throw new Error('Mock error');
  if (mode === 'empty') return factory(true);
  return factory(false);
}

export async function getVacancies({ query = '', category = 'Все' } = {}) {
  try {
    const real = await request(`/vacancies?q=${encodeURIComponent(query)}&category=${encodeURIComponent(category)}`);
    if (real) return real;
  } catch (error) {
    if (!canUseMockFallback()) throw error;
  }

  return withMockState((forceEmpty) => ({
    categories,
    items: forceEmpty ? [] : vacancies.filter((v) => matchesCategory(v, category) && matchesQuery(v, query)),
  }));
}

export async function getVacancy(id) {
  try {
    const real = await request(`/vacancies/${encodeURIComponent(id)}`);
    if (real) return real;
  } catch (error) {
    if (!canUseMockFallback()) throw error;
  }

  await wait(140);
  const item = vacancies.find((v) => v.id === id);
  if (!item) throw new Error('Not found');
  return item;
}

export async function getEvents({ category = 'Все' } = {}) {
  const real = await request(`/events?category=${encodeURIComponent(category)}`).catch(() => null);
  if (real) return real;

  return withMockState((forceEmpty) => ({
    categories: eventCategories,
    items: forceEmpty ? [] : events.filter((e) => matchesCategory(e, category)),
  }));
}

export async function getProfile() {
  const real = await request('/profile').catch(() => null);
  if (real) return real;

  return withMockState((forceEmpty) => (forceEmpty ? null : profile));
}