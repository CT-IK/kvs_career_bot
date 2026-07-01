import { markOnboardingSeen } from '../app/store.js';
import { icons } from '../components/icons.js';
import { appShell, button } from '../components/ui.js';

export function renderOnboarding() {
  return appShell(
    `
    <header class="brand-row">
      <span class="brand-mark">${icons.briefcase}</span>
      <strong>ФинКарьера</strong>
    </header>

    <section class="welcome-card">
      <img src="/assets/images/fin-career-hero.jpg" alt="" loading="eager" />
      <div class="welcome-overlay"></div>
      <div class="welcome-copy">
        <h1>Найди свою первую работу</h1>
        <p>Стажировки и вакансии от партнёров Финансового университета</p>
      </div>
    </section>

    <section class="benefits" aria-label="Возможности приложения">
      <article>
        ${icons.briefcase}
        <div>
          <strong>Вакансии от партнёров вуза</strong>
          <span>Только проверенные компании</span>
        </div>
      </article>
      <article>
        ${icons.sparkle}
        <div>
          <strong>Конструктор резюме</strong>
          <span>Готовое резюме за 5 минут</span>
        </div>
      </article>
      <article>
        ${icons.calendar}
        <div>
          <strong>Карьерные события</strong>
          <span>Хакатоны, дни карьеры, воркшопы</span>
        </div>
      </article>
    </section>

    <footer class="onboarding-actions">
      ${button('Начать', { action: 'start-onboarding' })}
      <button class="text-action" type="button" data-action="start-onboarding">У меня уже есть аккаунт</button>
    </footer>
    `,
    { className: 'onboarding-screen' },
  );
}

export function startOnboarding(navigate) {
  markOnboardingSeen();
  navigate('/vacancies');
}