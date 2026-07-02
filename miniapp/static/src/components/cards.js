import { isAdminProfile, store } from '../app/store.js';
import { icons } from './icons.js';
import { badge, escapeHtml, verifiedIcon } from './ui.js';

export function companyLogo(company, size = '') {
  if (company.logoUrl) {
    // Explicit width/height (not just CSS) stop the browser from ever laying the
    // <img> out at its native intrinsic size — or the ~300x150 broken-image
    // placeholder size — for the instant before/if the real asset loads.
    const box = size === 'large' ? 76 : 56;
    return `<span class="company-logo company-logo-image ${size}"><img src="${escapeHtml(company.logoUrl)}" width="${box}" height="${box}" alt="" loading="lazy" /></span>`;
  }
  return `<span class="company-logo ${size}" style="--brand:${escapeHtml(company.brandColor)}">${escapeHtml(company.initial)}</span>`;
}

export function vacancyCard(vacancy, { compact = false, index = 0 } = {}) {
  const isFavorite = store.favorites.has(vacancy.id);
  const formatClass = vacancy.format === 'Гибрид' ? 'blue' : vacancy.format === 'Офис' ? 'green' : 'yellow';

  return `
    <article class="vacancy-card ${compact ? 'is-compact' : ''}" style="--i:${index}" aria-label="${escapeHtml(vacancy.title)} · ${escapeHtml(vacancy.company.name)}">
      <div class="vacancy-main">
        ${companyLogo(vacancy.company)}
        <div class="vacancy-info">
          <p class="company-line">${escapeHtml(vacancy.company.name)}${vacancy.company.verified ? verifiedIcon() : ''}</p>
          <h2>${escapeHtml(vacancy.title)}</h2>
          <strong>${escapeHtml(vacancy.salary)}</strong>
        </div>
        <button class="heart-btn ${isFavorite ? 'is-active' : ''}" type="button" data-action="toggle-favorite" data-id="${escapeHtml(vacancy.id)}" aria-label="${isFavorite ? 'Убрать из избранного' : 'Добавить в избранное'}">
          ${isFavorite ? icons.heart : icons.heartOutline}
        </button>
      </div>
      <div class="meta-row">
        <span class="metro" style="--metro:${escapeHtml(vacancy.metroColor)}">${escapeHtml(vacancy.metro)}</span>
        ${badge(vacancy.format, formatClass)}
        ${badge(vacancy.kind, vacancy.kind === 'Стажировка' ? 'red-soft' : '')}
      </div>
      ${compact ? '' : `<p class="card-copy">${escapeHtml(vacancy.description)}</p>`}
      <div class="card-footer">
        ${badge(vacancy.experience)}
        <button class="btn btn-primary btn-small" type="button" data-action="apply" data-url="${escapeHtml(vacancy.applyUrl)}">Откликнуться</button>
      </div>
      <button class="card-hit" type="button" data-action="navigate" data-route="/vacancies/${escapeHtml(vacancy.id)}" aria-label="Открыть вакансию: ${escapeHtml(vacancy.title)}, ${escapeHtml(vacancy.company.name)}"></button>
    </article>`;
}

export function eventCard(event, index = 0) {
  const formatClass = event.format === 'Онлайн' ? 'green' : event.format === 'Гибрид' ? 'blue-solid' : 'red';

  // Same manage controls as the admin panel's own event list — shown right on
  // the public card so an admin browsing this tab doesn't have to separately
  // remember to go to Профиль → Панель разработчика to edit/delete something
  // they're looking at right now.
  const adminControls = isAdminProfile()
    ? `
    <div class="event-admin-actions">
      <button class="btn btn-ghost btn-small" type="button" data-action="edit-admin-event" data-id="${escapeHtml(event.id)}">${icons.pencil}<span>Редактировать</span></button>
      <button class="btn btn-ghost btn-small" type="button" data-action="delete-admin-event" data-id="${escapeHtml(event.id)}">${icons.trash}<span>Удалить</span></button>
    </div>`
    : '';

  return `
    <article class="event-card" style="--i:${index}">
      <div class="event-image" style="background-image:url('${escapeHtml(event.image)}')">
        <span class="event-format ${formatClass}">${escapeHtml(event.format)}</span>
        <span class="event-kind">${escapeHtml(event.category)}</span>
      </div>
      <div class="event-body">
        <p class="event-lead">${escapeHtml(event.lead)}</p>
        <h2>${escapeHtml(event.title)}</h2>
        <p class="event-meta">${icons.calendar}${escapeHtml(event.date)}</p>
        <p class="event-meta">${icons.mapPin}${escapeHtml(event.place)}</p>
        <p class="card-copy">${escapeHtml(event.description)}</p>
        ${adminControls}
        <div class="event-actions">
          ${badge(event.deadline, 'red-soft deadline')}
          <button class="btn btn-dark btn-small" type="button" data-action="open-link" data-url="${escapeHtml(event.url)}">Подробнее ${icons.arrowUpRight}</button>
        </div>
      </div>
    </article>`;
}