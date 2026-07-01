import { store } from '../app/store.js';
import { eventCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, chips, emptyState, errorState, skeletonList, topTitle } from '../components/ui.js';
import { getEvents } from '../services/api.js';

export function renderEventsLoading() {
  return appShell(
    `
    ${topTitle('Мероприятия')}
    ${chips(['Все', 'Хакатоны', 'Воркшопы', 'Дни карьеры'], store.filters.eventCategory, 'set-event-category')}
    ${skeletonList(3)}
    `,
    { nav: true },
  );
}

export async function renderEvents() {
  try {
    const data = await getEvents({ category: store.filters.eventCategory });

    const list = data.items.length
      ? `<section class="list-stack">${data.items.map((item, i) => eventCard(item, i)).join('')}</section>`
      : emptyState('Мероприятий пока нет', 'Когда появятся новые события, они будут здесь.', icons.calendar);

    return appShell(
      `
      ${topTitle('Мероприятия')}
      ${chips(data.categories, store.filters.eventCategory, 'set-event-category')}
      ${list}
      `,
      { nav: true },
    );
  } catch {
    return appShell(`${topTitle('Мероприятия')}${errorState('Не удалось загрузить мероприятия.')}`, { nav: true });
  }
}