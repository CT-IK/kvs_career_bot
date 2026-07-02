import { isAdminProfile, isProfileAuthenticated, store } from '../app/store.js';
import { vacancies } from '../mock/data.js';
import { vacancyCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, badge, button, emptyState, errorState, escapeHtml, skeletonList, topTitle } from '../components/ui.js';
import { getProfile } from '../services/api.js';

function tabs() {
  const count = store.favorites.size;
  return `
    <div class="profile-tabs" role="tablist">
      <button class="${store.profileTab === 'resume' ? 'is-active' : ''}" type="button" role="tab" aria-selected="${store.profileTab === 'resume'}" data-action="profile-tab" data-value="resume">Резюме</button>
      <button class="${store.profileTab === 'favorites' ? 'is-active' : ''}" type="button" role="tab" aria-selected="${store.profileTab === 'favorites'}" data-action="profile-tab" data-value="favorites">
        Избранное <span data-favorites-count ${count > 0 ? '' : 'hidden'}>${count}</span>
      </button>
    </div>`;
}

export function renderProfileLoading() {
  if (!isProfileAuthenticated()) {
    return appShell(loginGateView(), { nav: true, className: 'profile-login-screen' });
  }
  if (isAdminProfile() && store.adminMode === 'panel') {
    return appShell(adminPanelView(), { nav: true, className: 'admin-profile-screen' });
  }
  return appShell(`${topTitle('Мой профиль')}${tabs()}${skeletonList(2)}`, { nav: true });
}

function loginGateView() {
  if (store.profileLoginMode === 'email') {
    return `
      <section class="profile-login-only">
        <div class="login-card">
          <span class="login-icon">${icons.user}</span>
          <h2>Вход в профиль</h2>
          <p>Введи корпоративную почту Финансового университета</p>
          <div class="profile-email-form">
            <label class="sr-only" for="profileEmail">Корпоративная почта</label>
            <input id="profileEmail" type="email" inputmode="email" autocomplete="email" placeholder="student@edu.fa.ru" value="${escapeHtml(store.profileEmail)}" aria-invalid="${Boolean(store.profileEmailError)}" ${store.profileEmailError ? 'aria-describedby="profileEmailError"' : ''} />
            ${store.profileEmailError ? `<p class="form-error" id="profileEmailError" role="alert">${escapeHtml(store.profileEmailError)}</p>` : ''}
            ${button('Войти', { variant: 'primary', action: 'submit-profile-email', icon: icons.arrowRight })}
          </div>
        </div>
      </section>`;
  }

  return `
    <section class="profile-login-only">
      <div class="login-card">
        <span class="login-icon">${icons.user}</span>
        <h2>Мой профиль</h2>
        <p>Войди с корпоративной почтой, чтобы видеть резюме и избранные вакансии</p>
        ${button('Войти в профиль', { variant: 'primary', action: 'start-profile-login', icon: icons.arrowRight })}
      </div>
    </section>`;
}

function resumeView(profile) {
  return `
    ${isAdminProfile() ? `<section class="admin-entry">${button('Панель разработчика', { variant: 'primary', action: 'admin-mode', route: 'panel', icon: icons.sparkle })}</section>` : ''}

    <section class="profile-head">
      <span class="avatar">${icons.user}</span>
      <div>
        <h2>${escapeHtml(profile.name)}</h2>
        <p>${escapeHtml(profile.headline)}</p>
        <p class="muted-line">${icons.mapPin}${escapeHtml(profile.location)} · ${escapeHtml(profile.relocation)}</p>
      </div>
    </section>

    <section class="resume-summary">
      <div class="tag-cloud">
        ${badge(profile.status, 'red-soft')}
        ${badge(profile.target)}
        ${badge(profile.salary)}
      </div>
      <p class="contact">${icons.mail}${escapeHtml(profile.email)}</p>
      <p class="contact">${icons.phone}${escapeHtml(profile.phone)}</p>
    </section>

    <section class="content-section"><h3>О себе</h3><p>${escapeHtml(profile.about)}</p></section>

    <section class="content-section icon-section">
      <span class="soft-icon">${icons.graduation}</span>
      <div>
        <h3>${escapeHtml(profile.education.university)}</h3>
        <p>${escapeHtml(profile.education.program)}<br />${escapeHtml(profile.education.period)}</p>
      </div>
    </section>

    <section class="content-section">
      <h3>Навыки</h3>
      <div class="tag-cloud">${profile.skills.map((s) => badge(s)).join('')}</div>
    </section>

    <section class="content-section">
      <h3>Опыт работы</h3>
      ${profile.experience.map((item) => `
        <article class="timeline-item">
          <span>${icons.briefcase}</span>
          <div>
            <h4>${escapeHtml(item.title)}</h4>
            <p>${escapeHtml(item.company)}<br />${escapeHtml(item.period)}</p>
            <ul>${item.bullets.map((b) => `<li>${escapeHtml(b)}</li>`).join('')}</ul>
          </div>
        </article>`).join('')}
    </section>

    <section class="progress-callout">
      ${icons.star}
      <div>
        <strong>Резюме заполнено на 100%</strong>
        <span></span>
        <p>Резюме с заполненным профилем просматривают в 3× чаще</p>
      </div>
    </section>

    <section class="profile-actions">
      ${button('Редактировать профиль', { variant: 'dark', action: 'navigate', route: '/profile/edit', icon: icons.pencil })}
      ${button('Выйти', { variant: 'ghost', action: 'logout-profile', icon: icons.logout })}
      ${button('Скачать резюме как PDF', { variant: 'ghost', disabled: true, icon: icons.download })}
    </section>`;
}

function listRows(items, emptyText, renderItem) {
  return items.length ? items.map(renderItem).join('') : `<p class="admin-empty">${escapeHtml(emptyText)}</p>`;
}

function adminPanelView() {
  return `
    ${topTitle('Панель разработчика')}
    <section class="admin-window">
      <div class="admin-window-head">
        <div>
          <span>Админ-доступ</span>
          <strong>${escapeHtml(store.profileEmail)}</strong>
        </div>
        ${button('Обычный профиль', { variant: 'ghost', action: 'admin-mode', route: 'profile', icon: icons.user })}
      </div>

      ${store.adminFormError ? `<p class="admin-error" role="alert">${escapeHtml(store.adminFormError)}</p>` : ''}

      <section class="admin-form">
        <h2>Добавить разработчика</h2>
        <label class="sr-only" for="adminDeveloperName">Имя разработчика</label>
        <input id="adminDeveloperName" type="text" autocomplete="name" placeholder="Имя разработчика" />
        <label class="sr-only" for="adminDeveloperEmail">Почта разработчика</label>
        <input id="adminDeveloperEmail" type="email" inputmode="email" autocomplete="email" placeholder="developer@edu.fa.ru" />
        ${button('Добавить разработчика', { variant: 'primary', action: 'add-admin-developer', icon: '' })}
      </section>

      <section class="admin-form">
        <h2>Добавить место</h2>
        <label class="sr-only" for="adminPlaceTitle">Название места</label>
        <input id="adminPlaceTitle" type="text" placeholder="Название места" />
        <label class="sr-only" for="adminPlaceAddress">Адрес или описание</label>
        <input id="adminPlaceAddress" type="text" placeholder="Адрес или описание" />
        ${button('Добавить место', { variant: 'primary', action: 'add-admin-place', icon: '' })}
      </section>
    </section>

    <section class="admin-list">
      <h2>Разработчики</h2>
      ${listRows(store.adminDevelopers, 'Разработчики пока не добавлены.', (item) => `<article><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.email)}</span></article>`)}
    </section>

    <section class="admin-list">
      <h2>Места</h2>
      ${listRows(store.adminPlaces, 'Места пока не добавлены.', (item) => `<article><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.address)}</span></article>`)}
    </section>

    <section class="profile-actions">
      ${button('Выйти из профиля', { variant: 'ghost', action: 'logout-profile', icon: icons.logout })}
    </section>`;
}

function favoritesView() {
  const favorites = vacancies.filter((v) => store.favorites.has(v.id));
  return favorites.length
    ? `<section class="list-stack">${favorites.map((v, i) => vacancyCard(v, { compact: true, index: i })).join('')}</section>`
    : emptyState('В избранном пусто', 'Добавляй подходящие вакансии — нажми сердечко на любой карточке.', icons.heartOutline);
}

const STEP_LABELS = ['Образование', 'Цель и зарплата', 'Контакты', 'Навыки', 'Опыт'];

function editView(profile) {
  const step = profile.draft;
  const pct = ((step.step - 1) / step.totalSteps) * 100;

  return `
    <section class="edit-profile-head">
      <span class="avatar">${icons.user}</span>
      <div>
        <h2>${escapeHtml(profile.name)}</h2>
        <p>${escapeHtml(profile.username)} · ${escapeHtml(profile.universityShort)}</p>
      </div>
    </section>

    <section class="step-summary">
      <p>Шаг <strong>${step.step} из ${step.totalSteps}</strong> — ${escapeHtml(STEP_LABELS[step.step - 1] || '')}</p>
      <div class="step-bar"><span style="width:${pct}%"></span></div>
      <div class="step-dots">
        ${Array.from({ length: step.totalSteps }, (_, i) => `<span class="${i + 1 === step.step ? 'is-active' : i + 1 < step.step ? 'is-done' : ''}" aria-label="Шаг ${i + 1}">${i + 1 < step.step ? icons.check : i + 1}</span>`).join('')}
      </div>
    </section>

    <section class="form-card">
      <h2>Образование</h2>
      <p>Вуз, курс и специальность</p>
      <label>Университет<input value="${escapeHtml(profile.draft.university)}" placeholder="Название университета" /></label>
      <div class="form-grid">
        <label>Курс<input value="${escapeHtml(profile.draft.course)}" placeholder="4" inputmode="numeric" /></label>
        <label>Специальность<input value="${escapeHtml(profile.draft.specialty)}" placeholder="Финансы" /></label>
      </div>
    </section>

    <section class="profile-actions">
      ${button('Сохранить шаг', { variant: 'dark', action: 'save-profile-step', icon: icons.check })}
      ${button('Сгенерировать резюме', { variant: 'ghost', disabled: true, icon: icons.sparkle })}
      ${button('Выйти', { variant: 'ghost', action: 'logout-profile', icon: icons.logout })}
    </section>`;
}

export async function renderProfile(route) {
  if (!isProfileAuthenticated()) {
    return appShell(loginGateView(), { nav: true, className: 'profile-login-screen' });
  }

  if (isAdminProfile() && store.adminMode === 'panel') {
    return appShell(adminPanelView(), { nav: true, className: 'admin-profile-screen' });
  }

  try {
    const loadedProfile = await getProfile();
    const profile = loadedProfile ? { ...loadedProfile, email: store.profileEmail } : null;

    if (!profile) {
      return appShell(
        `${topTitle('Мой профиль')}${emptyState('Профиль не найден', 'Заполни резюме, чтобы получать более точные рекомендации.')}`,
        { nav: true },
      );
    }

    if (route.name === 'profile-edit') {
      return appShell(`${topTitle('Редактирование')}${editView(profile)}`, { nav: true, className: 'profile-edit-screen' });
    }

    return appShell(
      `${topTitle('Мой профиль')}${tabs()}${store.profileTab === 'favorites' ? favoritesView() : resumeView(profile)}`,
      { nav: true },
    );
  } catch {
    return appShell(`${topTitle('Мой профиль')}${errorState('Не удалось загрузить профиль.')}`, { nav: true });
  }
}
