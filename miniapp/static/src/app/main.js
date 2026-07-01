import { navigate, parseRoute, setRoute } from './router.js';
import {
  addAdminDeveloper,
  addAdminPlace,
  logoutProfile,
  setAdminMode,
  startProfileLogin,
  store,
  submitProfileEmail,
  toggleFavorite,
} from './store.js';
import { renderEvents, renderEventsLoading } from '../features/events.js';
import { renderJobs, renderJobsLoading } from '../features/jobs.js';
import { renderOnboarding, startOnboarding } from '../features/onboarding.js';
import { renderProfile, renderProfileLoading } from '../features/profile.js';
import { renderVacancyDetail, renderVacancyDetailLoading } from '../features/vacancyDetails.js';

const app = document.querySelector('#app');
const tg = window.Telegram?.WebApp;

tg?.ready();
tg?.expand();
tg?.setHeaderColor?.('#ffffff');
tg?.setBackgroundColor?.('#f2f2f2');

function haptic(type = 'light') {
  tg?.HapticFeedback?.impactOccurred(type);
}

function loadingFor(route) {
  if (route.name === 'events') return renderEventsLoading();
  if (route.name === 'profile' || route.name === 'profile-edit') return renderProfileLoading();
  if (route.name === 'vacancy-detail') return renderVacancyDetailLoading();
  if (route.name === 'onboarding') return renderOnboarding();
  return renderJobsLoading();
}

async function viewFor(route) {
  if (route.name === 'events') return renderEvents();
  if (route.name === 'profile' || route.name === 'profile-edit') return renderProfile(route);
  if (route.name === 'vacancy-detail') return renderVacancyDetail(route.id);
  if (route.name === 'onboarding') return renderOnboarding();
  return renderJobs();
}

async function render() {
  const route = parseRoute();
  setRoute(route);
  app.innerHTML = loadingFor(route);
  window.scrollTo({ top: 0, behavior: 'instant' });
  const html = await viewFor(route);
  if (store.route === route) {
    app.innerHTML = html;
    bindInputs();
  }
}

function bindInputs() {
  const search = document.querySelector('#vacancySearch');
  if (search) {
    search.addEventListener('input', (e) => {
      store.filters.vacancyQuery = e.target.value;
      window.clearTimeout(search._timer);
      search._timer = window.setTimeout(render, 220);
    });
  }
}

function openExternal(url) {
  if (!url) return;
  haptic('medium');
  if (tg?.openLink) {
    tg.openLink(url);
  } else {
    window.open(url, '_blank', 'noopener');
  }
}

document.addEventListener('click', (e) => {
  const target = e.target.closest('[data-action]');
  if (!target) return;

  const action = target.dataset.action;
  haptic();

  if (action === 'navigate') navigate(target.dataset.route);
  if (action === 'back') window.history.length > 1 ? window.history.back() : navigate('/vacancies');
  if (action === 'start-onboarding') startOnboarding(navigate);
  if (action === 'open-link' || action === 'apply') openExternal(target.dataset.url);
  if (action === 'notify-placeholder') tg?.showAlert?.('Уведомления появятся после подключения backend.');
  if (action === 'save-profile-step') tg?.showAlert?.('Шаг сохранён. Продолжай заполнять резюме!');

  if (action === 'start-profile-login') {
    startProfileLogin();
    render();
  }

  if (action === 'submit-profile-email') {
    const email = document.querySelector('#profileEmail')?.value;
    if (!submitProfileEmail(email)) {
      tg?.HapticFeedback?.notificationOccurred?.('error');
    }
    render();
  }

  if (action === 'logout-profile') {
    logoutProfile();
    render();
  }

  if (action === 'admin-mode') {
    setAdminMode(target.dataset.route);
    render();
  }

  if (action === 'add-admin-developer') {
    const ok = addAdminDeveloper({
      name: document.querySelector('#adminDeveloperName')?.value,
      email: document.querySelector('#adminDeveloperEmail')?.value,
    });
    if (!ok) tg?.HapticFeedback?.notificationOccurred?.('error');
    render();
  }

  if (action === 'add-admin-place') {
    const ok = addAdminPlace({
      title: document.querySelector('#adminPlaceTitle')?.value,
      address: document.querySelector('#adminPlaceAddress')?.value,
    });
    if (!ok) tg?.HapticFeedback?.notificationOccurred?.('error');
    render();
  }

  if (action === 'set-vacancy-category') {
    store.filters.vacancyCategory = target.dataset.value;
    render();
  }

  if (action === 'set-event-category') {
    store.filters.eventCategory = target.dataset.value;
    render();
  }

  if (action === 'toggle-favorite') {
    e.preventDefault();
    e.stopPropagation();
    toggleFavorite(target.dataset.id);
    haptic('medium');
    render();
  }

  if (action === 'profile-tab') {
    store.profileTab = target.dataset.value;
    navigate(`/profile?tab=${store.profileTab}`);
  }
});

window.addEventListener('hashchange', render);
render();