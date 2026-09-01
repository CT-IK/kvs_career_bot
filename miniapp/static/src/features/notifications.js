import { store } from '../app/store.js';
import { eventCard } from '../components/cards.js';
import { icons } from '../components/icons.js';
import { appShell, emptyState, errorState, iconButton, skeletonList, topTitle } from '../components/ui.js';
import { getMyEvents } from '../services/api.js';

function header() {
  return topTitle('Мои события', iconButton('Назад', icons.back, { action: 'back', className: 'notifications-back' }));
}

export function registeredEventsList(items) {
  return items.length
    ? `<section class="list-stack">${items.map((item, index) => eventCard(item, index, { registeredView: true })).join('')}</section>`
    : emptyState(
      'Нет добавленных событий',
      'Добавь мероприятие на вкладке «События», и оно появится здесь.',
      icons.bell,
    );
}

export function renderNotificationsLoading() {
  return appShell(`${header()}${skeletonList(2)}`, { className: 'notifications-screen' });
}

export async function renderNotifications() {
  try {
    const data = await getMyEvents();
    store.myEvents = data.items || [];
    store.notificationsCount = Number(data.total || store.myEvents.length);
    return appShell(`${header()}${registeredEventsList(store.myEvents)}`, { className: 'notifications-screen' });
  } catch {
    return appShell(`${header()}${errorState('Не удалось загрузить добавленные мероприятия.')}`, { className: 'notifications-screen' });
  }
}
