import { companyLogo } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, badge, escapeHtml, errorState, iconButton, skeletonList } from '../components/ui.js';
import { getVacancy } from '../services/api.js';

export function renderVacancyDetailLoading() {
  return appShell(skeletonList(1), { className: 'detail-screen' });
}

export async function renderVacancyDetail(id) {
  try {
    const item = await getVacancy(id);
    const formatClass = item.format === 'Гибрид' ? 'blue' : item.format === 'Офис' ? 'green' : 'yellow';

    return appShell(
      `
      <section class="detail-cover" style="--brand:${escapeHtml(item.company.brandColor)}">
        ${iconButton('Назад', icons.back, { action: 'back', className: 'back-floating' })}
      </section>
      <article class="detail-content">
        <div class="detail-logo-wrap">${companyLogo(item.company, 'large')}</div>
        <p class="detail-company">${escapeHtml(item.company.name)}</p>
        <h1>${escapeHtml(item.title)}</h1>
        <div class="detail-badges">
          ${badge(item.format, formatClass)}
          ${badge(item.kind, item.kind === 'Стажировка' ? 'red-soft' : '')}
          ${badge(item.category)}
        </div>

        <section class="content-section">
          <h2>О вакансии</h2>
          <p>${escapeHtml(item.fullDescription || item.description)}</p>
        </section>

        <section class="content-section">
          <h2>Требования</h2>
          <ul class="red-list">${item.requirements.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ul>
        </section>

        <section class="offer-panel">
          <h2>Что предлагают</h2>
          <ul class="red-list">${item.offer.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ul>
        </section>

        <section class="detail-meta-row">
          ${badge(item.experience)}
          <span class="metro" style="--metro:${escapeHtml(item.metroColor)}">${escapeHtml(item.metro)}</span>
          <strong class="detail-salary">${escapeHtml(item.salary)}</strong>
        </section>
      </article>

      <footer class="sticky-cta">
        <button class="btn btn-primary" type="button" data-action="apply" data-url="${escapeHtml(item.applyUrl)}">
          <span>Откликнуться</span>${icons.arrowUpRight}
        </button>
      </footer>
      `,
      { className: 'detail-screen' },
    );
  } catch {
    return appShell(
      `${iconButton('Назад', icons.back, { action: 'back', className: 'plain-back' })}${errorState('Вакансия не найдена или временно недоступна.')}`,
      { className: 'detail-screen' },
    );
  }
}