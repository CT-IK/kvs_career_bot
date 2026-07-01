import { store } from '../app/store.js';
import { vacancyCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, chips, emptyState, errorState, escapeHtml, iconButton, skeletonList, topTitle } from '../components/ui.js';
import { getVacancies } from '../services/api.js';

export function renderJobsLoading() {
  return appShell(
    `
    ${topTitle('Вакансии', iconButton('Уведомления', icons.bell, { action: 'notify-placeholder' }))}
    <label class="search-field">${icons.search}<input type="search" placeholder="Поиск стажировок и вакансий" disabled /></label>
    ${chips(['Все', 'Финансы', 'IT', 'Маркетинг', 'Аналитика'], 'Все', 'set-vacancy-category')}
    ${skeletonList(3)}
    `,
    { nav: true },
  );
}

export async function renderJobs() {
  try {
    const data = await getVacancies({
      query: store.filters.vacancyQuery,
      category: store.filters.vacancyCategory,
    });

    const list = data.items.length
      ? `<section class="list-stack">${data.items.map((item, i) => vacancyCard(item, { index: i })).join('')}</section>`
      : emptyState('Вакансий не найдено', 'Попробуй изменить поиск или выбрать другую категорию.', icons.search);

    return appShell(
      `
      ${topTitle('Вакансии', iconButton('Уведомления', icons.bell, { action: 'notify-placeholder' }))}
      <label class="search-field">${icons.search}<input id="vacancySearch" type="search" value="${escapeHtml(store.filters.vacancyQuery)}" placeholder="Поиск стажировок и вакансий" autocomplete="off" /></label>
      ${chips(data.categories, store.filters.vacancyCategory, 'set-vacancy-category')}
      ${list}
      `,
      { nav: true },
    );
  } catch {
    return appShell(
      `
      ${topTitle('Вакансии', iconButton('Уведомления', icons.bell, { action: 'notify-placeholder' }))}
      ${errorState('Не удалось загрузить вакансии. Проверь подключение и попробуй ещё раз.')}
      `,
      { nav: true },
    );
  }
}