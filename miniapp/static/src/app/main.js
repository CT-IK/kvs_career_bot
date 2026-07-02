import { navigate, parseRoute, setRoute } from './router.js';
import {
  addAdminDeveloper,
  addAdminPlace,
  logoutProfile,
  setAdminMode,
  startCreateEvent,
  startEditEvent,
  startProfileLogin,
  store,
  submitProfileEmail,
  toggleFavorite,
} from './store.js';
import { icons } from '../components/icons.js';
import { renderEvents, renderEventsLoading } from '../features/events.js';
import { renderJobs, renderJobsLoading } from '../features/jobs.js';
import { renderOnboarding, startOnboarding } from '../features/onboarding.js';
import { renderProfile, renderProfileLoading } from '../features/profile.js';
import { renderVacancyDetail, renderVacancyDetailLoading } from '../features/vacancyDetails.js';
import { createEvent, deleteEvent, updateEvent } from '../services/api.js';

const app = document.querySelector('#app');
const tg = window.Telegram?.WebApp;
// Outside the real Telegram client the SDK still injects a stub WebApp object
// whose colorScheme is hardcoded to 'light', so `initData` is the only reliable
// signal that we're actually embedded and should trust tg.colorScheme.
const isEmbedded = Boolean(tg?.initData);

tg?.ready();
tg?.expand();
tg?.disableVerticalSwipes?.();

const THEME_COLORS = {
  light: { header: '#ffffff', bg: '#f2f2f2' },
  dark: { header: '#1c1c1e', bg: '#121214' },
};

function applyTheme(scheme) {
  const theme = scheme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme].header);
  tg?.setHeaderColor?.(THEME_COLORS[theme].header);
  tg?.setBackgroundColor?.(THEME_COLORS[theme].bg);
}

function resolveScheme() {
  if (isEmbedded) return tg.colorScheme === 'dark' ? 'dark' : 'light';
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

applyTheme(resolveScheme());
if (isEmbedded) {
  tg.onEvent?.('themeChanged', () => applyTheme(resolveScheme()));
} else {
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(resolveScheme()));
}

function haptic(type = 'light') {
  tg?.HapticFeedback?.impactOccurred(type);
}

/* ─── Navigation direction & view transitions ─────────────────── */
// Route "depth": deeper routes slide in (push), shallower slide out (pop),
// same-level tab switches slide sideways following the tab order.
const ROUTE_LEVELS = { onboarding: 0, vacancies: 1, events: 1, profile: 1, 'profile-edit': 2, 'vacancy-detail': 2 };
const TAB_ORDER = { vacancies: 0, events: 1, profile: 2 };
const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
const scrollMemory = new Map();
let prevRoute = null;

function routeKey(route) {
  const query = route.params.toString();
  return query ? `${route.path}?${query}` : route.path;
}

function directionFor(prev, next) {
  if (!prev) return 'fade';
  const from = ROUTE_LEVELS[prev.name] ?? 1;
  const to = ROUTE_LEVELS[next.name] ?? 1;
  if (to > from) return 'push';
  if (to < from) return 'pop';
  const a = TAB_ORDER[prev.name];
  const b = TAB_ORDER[next.name];
  if (a !== undefined && b !== undefined && a !== b) return b > a ? 'tab-forward' : 'tab-back';
  return 'fade';
}

// Never let a caller wait on a promise indefinitely — transition.finished can
// reject (transition interrupted by another navigation) or, in rare browser
// edge cases, simply never settle. Capping the wait keeps render() from
// hanging forever if that happens.
function withTimeout(promise, ms) {
  return Promise.race([
    Promise.resolve(promise).catch(() => {}),
    new Promise((resolve) => window.setTimeout(resolve, ms)),
  ]);
}

// Returns a promise that resolves once it's safe to mutate the DOM again —
// once the slide animation has finished (or ANIMATION_MAX_WAIT_MS elapses,
// whichever first), not just once the callback ran. render() awaits this
// before swapping the loading skeleton for real content: replacing innerHTML
// mid-animation (which happens whenever data arrives faster than the ~300ms
// transition) changed the live page's height under the still-playing
// transition and looked like the whole screen jerking/scrolling.
const ANIMATION_MAX_WAIT_MS = 400;

function swapView(html, direction, scrollTop = null) {
  const apply = () => {
    app.innerHTML = html;
    bindInputs();
    if (scrollTop !== null) window.scrollTo({ top: scrollTop, behavior: 'instant' });
  };

  if (reduceMotion?.matches || !document.startViewTransition) {
    apply();
    return Promise.resolve();
  }

  document.documentElement.dataset.nav = direction;
  const transition = document.startViewTransition(apply);
  const cleanup = () => {
    if (document.documentElement.dataset.nav === direction) delete document.documentElement.dataset.nav;
  };
  transition.finished.finally(cleanup);
  return withTimeout(transition.finished, ANIMATION_MAX_WAIT_MS);
}

/* ─── Telegram native back button on nested screens ───────────── */
function goBack() {
  if (window.history.length > 1) {
    window.history.back();
  } else {
    navigate('/vacancies');
  }
}

if (isEmbedded && tg.BackButton) tg.BackButton.onClick(goBack);

function syncBackButton(route) {
  if (!isEmbedded || !tg.BackButton) return;
  if ((ROUTE_LEVELS[route.name] ?? 1) > 1) {
    tg.BackButton.show();
  } else {
    tg.BackButton.hide();
  }
}

/* ─── Toast ───────────────────────────────────────────────────── */
let toastTimer = 0;

function showToast(message, icon = '') {
  document.querySelector('.toast')?.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.innerHTML = `${icon}<span></span>`;
  el.querySelector('span').textContent = message;
  document.body.append(el);
  requestAnimationFrame(() => el.classList.add('is-visible'));
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    el.classList.remove('is-visible');
    window.setTimeout(() => el.remove(), 320);
  }, 2100);
}

function updateFavoriteCounters() {
  const count = store.favorites.size;
  document.querySelectorAll('[data-favorites-count]').forEach((el) => {
    el.textContent = count;
    el.hidden = count === 0;
  });
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

async function render({ silent = false, transition = null } = {}) {
  const route = parseRoute();
  const key = routeKey(route);
  const prev = prevRoute;
  const direction = transition ?? directionFor(prev, route);
  setRoute(route);
  prevRoute = { name: route.name, key };
  syncBackButton(route);

  const focused = document.activeElement;
  const focusedId = focused?.id;
  const selStart = focused?.selectionStart;
  const selEnd = focused?.selectionEnd;

  let scrollTarget = 0;
  let transitionDone = Promise.resolve();
  if (!silent) {
    if (prev && prev.key !== key) scrollMemory.set(prev.key, window.scrollY);
    scrollTarget = direction === 'pop' ? scrollMemory.get(key) ?? 0 : 0;
    transitionDone = swapView(loadingFor(route), direction, scrollTarget);
  }

  const [html] = await Promise.all([viewFor(route), transitionDone]);
  if (store.route !== route) return;

  app.innerHTML = html;
  bindInputs();
  if (!silent) window.scrollTo({ top: scrollTarget, behavior: 'instant' });

  if (silent && focusedId) {
    const el = document.getElementById(focusedId);
    if (el) {
      el.focus({ preventScroll: true });
      if (typeof selStart === 'number' && el.setSelectionRange) {
        try {
          el.setSelectionRange(selStart, selEnd);
        } catch {
          /* not a text-selectable input, ignore */
        }
      }
    }
  }
}

function bindInputs() {
  const search = document.querySelector('#vacancySearch');
  if (search) {
    search.addEventListener('input', (e) => {
      store.filters.vacancyQuery = e.target.value;
      window.clearTimeout(search._timer);
      search._timer = window.setTimeout(() => render({ silent: true }), 220);
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

function shareVacancy(url) {
  if (!url) return;
  const title = document.querySelector('.detail-content h1')?.textContent?.trim() || 'Вакансия';
  const text = `${title} — нашёл в KVS Job`;

  if (isEmbedded && tg.openTelegramLink) {
    tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`);
  } else if (navigator.share) {
    navigator.share({ title, text, url }).catch(() => {});
  } else if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(url).then(() => showToast('Ссылка скопирована', icons.link)).catch(() => {});
  }
}

document.addEventListener('click', (e) => {
  const target = e.target.closest('[data-action]');
  if (!target) return;

  const action = target.dataset.action;
  haptic();

  if (action === 'navigate') navigate(target.dataset.route);
  if (action === 'back') goBack();
  if (action === 'start-onboarding') startOnboarding(navigate);
  if (action === 'open-link' || action === 'apply') openExternal(target.dataset.url);
  if (action === 'share-vacancy') shareVacancy(target.dataset.url);
  if (action === 'notify-placeholder') tg?.showAlert?.('Уведомления появятся после подключения backend.');
  if (action === 'save-profile-step') tg?.showAlert?.('Шаг сохранён. Продолжай заполнять резюме!');

  if (action === 'start-profile-login') {
    startProfileLogin();
    render();
  }

  if (action === 'submit-profile-email') {
    const email = document.querySelector('#profileEmail')?.value;
    const ok = submitProfileEmail(email);
    if (!ok) tg?.HapticFeedback?.notificationOccurred?.('error');
    render().then(() => { if (!ok) document.querySelector('#profileEmail')?.focus(); });
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
    render().then(() => { if (!ok) document.querySelector('#adminDeveloperName')?.focus(); });
  }

  if (action === 'add-admin-place') {
    const ok = addAdminPlace({
      title: document.querySelector('#adminPlaceTitle')?.value,
      address: document.querySelector('#adminPlaceAddress')?.value,
    });
    if (!ok) tg?.HapticFeedback?.notificationOccurred?.('error');
    render().then(() => { if (!ok) document.querySelector('#adminPlaceTitle')?.focus(); });
  }

  if (action === 'submit-admin-event') {
    const title = document.querySelector('#adminEventTitle')?.value?.trim() || '';
    if (!title) {
      store.adminEventError = 'Укажи название мероприятия';
      tg?.HapticFeedback?.notificationOccurred?.('error');
      render().then(() => document.querySelector('#adminEventTitle')?.focus());
    } else {
      const payload = {
        title,
        category: document.querySelector('#adminEventCategory')?.value?.trim() || '',
        format: document.querySelector('#adminEventFormat')?.value?.trim() || '',
        lead: document.querySelector('#adminEventLead')?.value?.trim() || '',
        date: document.querySelector('#adminEventDate')?.value?.trim() || '',
        place: document.querySelector('#adminEventPlace')?.value?.trim() || '',
        description: document.querySelector('#adminEventDescription')?.value?.trim() || '',
        deadline: document.querySelector('#adminEventDeadline')?.value?.trim() || '',
        image: document.querySelector('#adminEventImage')?.value?.trim() || '',
        url: document.querySelector('#adminEventUrl')?.value?.trim() || '',
        isActive: document.querySelector('#adminEventActive')?.checked ?? true,
      };
      const editingId = store.adminEventEditingId;
      (editingId ? updateEvent(editingId, payload) : createEvent(payload))
        .then(() => {
          store.adminEventError = '';
          startCreateEvent();
          tg?.HapticFeedback?.notificationOccurred?.('success');
          showToast(editingId ? 'Мероприятие обновлено' : 'Мероприятие добавлено', icons.check);
          render();
        })
        .catch((error) => {
          store.adminEventError = error.message || 'Не удалось сохранить мероприятие';
          tg?.HapticFeedback?.notificationOccurred?.('error');
          render();
        });
    }
  }

  if (action === 'edit-admin-event') {
    const eventToEdit = store.adminEvents.find((item) => item.id === target.dataset.id);
    if (eventToEdit) {
      startEditEvent(eventToEdit);
      store.adminMode = 'panel';
      // This button also lives on public event cards (Мероприятия tab) now —
      // the edit *form* only exists in the admin panel, so jump there when
      // clicked from anywhere else instead of re-rendering in place.
      if (parseRoute().name === 'profile') {
        render();
        window.scrollTo({ top: 0, behavior: 'instant' });
      } else {
        navigate('/profile');
      }
    } else {
      // store.adminEvents is only stale if the list fetch failed or hasn't
      // resolved yet — surface that instead of silently doing nothing.
      tg?.HapticFeedback?.notificationOccurred?.('error');
      showToast('Не удалось открыть мероприятие для редактирования', icons.link);
    }
  }

  if (action === 'cancel-admin-event') {
    startCreateEvent();
    render();
  }

  if (action === 'delete-admin-event') {
    const eventId = target.dataset.id;
    const runDelete = () => {
      deleteEvent(eventId)
        .then(() => {
          if (store.adminEventEditingId === eventId) startCreateEvent();
          tg?.HapticFeedback?.notificationOccurred?.('success');
          showToast('Мероприятие удалено', icons.trash);
          render();
        })
        .catch((error) => {
          const message = error.message || 'Не удалось удалить мероприятие';
          store.adminEventError = message;
          tg?.HapticFeedback?.notificationOccurred?.('error');
          // The admin panel's own error banner isn't visible from other
          // screens (e.g. this button also lives on public event cards now),
          // so show a toast too rather than failing silently there.
          showToast(message, icons.link);
          render();
        });
    };
    // tg.showConfirm() is gated on the client negotiating a recent enough Bot
    // API version — on a client that doesn't support it, it can silently do
    // nothing (no error, no callback), which looked exactly like "delete is
    // broken". window.confirm() is a plain browser API and works reliably
    // inside Telegram's WebView regardless of client/Bot-API version.
    if (window.confirm('Удалить это мероприятие?')) {
      runDelete();
    }
  }

  if (action === 'set-vacancy-category') {
    store.filters.vacancyCategory = target.dataset.value;
    render();
  }

  if (action === 'set-event-category') {
    store.filters.eventCategory = target.dataset.value;
    render();
  }

  if (action === 'reset-vacancy-filters') {
    store.filters.vacancyQuery = '';
    store.filters.vacancyCategory = 'Все';
    render();
  }

  if (action === 'toggle-favorite') {
    e.preventDefault();
    e.stopPropagation();
    const id = target.dataset.id;
    toggleFavorite(id);
    const active = store.favorites.has(id);
    tg?.HapticFeedback?.notificationOccurred?.(active ? 'success' : 'warning');

    // Update hearts in place so the pop animation plays instead of a full re-render.
    document.querySelectorAll('.heart-btn').forEach((btn) => {
      if (btn.dataset.id !== id) return;
      btn.classList.toggle('is-active', active);
      btn.innerHTML = active ? icons.heart : icons.heartOutline;
      btn.setAttribute('aria-label', active ? 'Убрать из избранного' : 'Добавить в избранное');
      btn.classList.remove('heart-pop');
      void btn.offsetWidth;
      btn.classList.add('heart-pop');
    });
    updateFavoriteCounters();
    showToast(active ? 'Добавлено в избранное' : 'Убрано из избранного', active ? icons.heart : icons.heartOutline);

    if (store.route?.name === 'profile' && store.profileTab === 'favorites') render({ silent: true });
  }

  if (action === 'profile-tab') {
    store.profileTab = target.dataset.value;
    navigate(`/profile?tab=${store.profileTab}`);
  }
});

window.addEventListener('hashchange', () => render());
render();