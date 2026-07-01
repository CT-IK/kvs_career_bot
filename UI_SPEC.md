# UI Spec: KVS Job Mini App

## Палитра

- `--color-bg`: `#F2F2F2` - фон контентных списков.
- `--color-surface`: `#FFFFFF` - карточки, верхние области, формы.
- `--color-surface-muted`: `#EDEDED` - чипы, поля ввода, нижние фоны.
- `--color-text`: `#292927` - основной текст.
- `--color-muted`: `#777586` - вторичный текст.
- `--color-soft`: `#AFAFAF` - disabled/secondary icons.
- `--color-primary`: `#C40016` - основной красный CTA/active.
- `--color-primary-soft`: `#FCEBEE` - светло-красные бейджи.
- `--color-success`: `#1EA342` - company mark/positive state.
- `--color-blue`: `#246BFE` - verified/blue format chip.
- `--color-divider`: `#DFDFDF` - разделители.

## Типографика

- Основной стек: `Inter`, `SF Pro Display`, `Segoe UI`, `Arial`, sans-serif.
- H1 screen title: 36-40 px, 800/900, line-height 1.05.
- Card title: 21-24 px, 800/900, line-height 1.14.
- Body: 16-19 px, 400/500, line-height 1.45.
- Caption/meta: 13-15 px, 500/700.
- Letter spacing: 0.

## Сетка и отступы

- Целевая ширина: 360-430 px, max app width 430 px.
- Safe area: `env(safe-area-inset-*)`, нижний контент учитывает fixed BottomNav/CTA.
- Горизонтальные поля экрана: 16 px на 360-375, 20 px на 390-430.
- Вертикальный ритм: 12/16/20/24 px.
- Карточки списка: full-width внутри content area, gap 12-16 px.
- Scroll chips: горизонтальный rail без hover-only поведения.

## Радиусы

- Большие карточки: 20-24 px.
- CTA кнопки: 16-20 px.
- Чипы: 999 px.
- Логотипы компаний: 16-20 px.
- Поля ввода: 18-20 px.

## Тени

- Карточки: `0 2px 8px rgba(0,0,0,.08)` + тонкий border.
- Hero/detail logo: `0 8px 18px rgba(0,0,0,.18)`.
- Bottom nav: верхний border, без тяжелой тени.

## Кнопки

- Primary: красный фон, белый текст, min-height 56 px, bold, tap scale до `0.98`.
- Dark secondary: `#252522`, белый текст.
- Ghost/text: прозрачный фон, muted text.
- Disabled: серый текст и фон, `aria-disabled`, без pointer feedback.

## Карточки

- VacancyCard: logo 56 px, company + verified, title, salary, meta chips, short description, footer with experience and CTA.
- EventCard: image top, overlay format/category badges, red lead line, title, date/location, deadline chip, dark CTA.
- Detail: cover band, floating company logo, centered title, chips, sections and sticky bottom CTA.

## Инпуты

- Search input: 56 px height, light gray background, left search icon, no border in normal state.
- Profile form fields: rounded gray filled fields, labels above, touch-friendly.
- Focus: visible red/blue outline without layout shift.

## Навигация

- BottomNav fixed, 3 пункта: `Вакансии`, `События`, `Профиль`.
- Active state: red icon/text.
- Inactive state: `#AFAFAF`.
- BottomNav hidden on onboarding and vacancy detail; detail uses sticky CTA.

## Адаптив

- 360 px: сохранять один столбец, чипы уходят в горизонтальный скролл.
- 375/390/414/430 px: фиксированные touch targets >= 44 px, без горизонтального скролла документа.
- Длинные названия обрезаются line-clamp на карточках; в detail раскрываются.
- Sticky CTA/BottomNav не перекрывают контент: `padding-bottom` учитывает safe area.

## Анимации

- Переходы между route: fade + translateY 8-12 px, 180-240 ms.
- Карточки: мягкое появление с задержкой 35 ms на item.
- Tap feedback: scale `0.98`, 120-160 ms.
- Skeleton shimmer: 1.1-1.3 s.
- `prefers-reduced-motion: reduce` отключает анимации и smooth scroll.
