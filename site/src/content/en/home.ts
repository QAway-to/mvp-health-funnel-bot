/**
 * Английская главная и вход.
 *
 * Не перевод русской страницы слово в слово, а её английская версия: у
 * англоязычного читателя нет ни Порфирия Иванова в культурном фоне, ни
 * привычки к «загартовуванню». Зато есть Wim Hof и cold exposure — на этом
 * языке тема уже названа, и опираться надо на неё.
 *
 * Отсюда главное отличие текста: по-русски мы объясняем, что холод и бег
 * полезны. По-английски объяснять это не нужно — нужно объяснить, чем наш
 * порядок отличается от интенсивной практики, к которой они привыкли.
 */

export interface EnDirection {
  readonly title: string;
  readonly promise: string;
  readonly steps: number;
}

export const enHome = {
  brand: 'Federation of Health',

  hero: {
    eyebrow: 'Federation of Health',
    heading: 'Health is built from habits, not from courses',
    lede: 'Sleep pulls the morning, the morning pulls the load, the load pulls recovery. That is why there are six directions and one subscription: take them one at a time, but there is no sense buying them apart.',
    note: 'Delivered in Telegram, step by step. A step is a short clip and the dose in text.',
  },

  method: {
    heading: 'What makes this different from an ice bath challenge',
    paragraphs: [
      'Cold exposure and breathwork are well covered in English — mostly as an intense practice you brace yourself for. This is the other half: the order and the dose for an ordinary day.',
      'Each step is one action. The clip shows the movement, the text gives the measure — how much, in what sequence, and what not to do. Sixty-eight steps across six directions.',
      'Nothing here promises a cure or a result. Some practices have contraindications, and they are named inside the steps rather than in a disclaimer at the bottom.',
    ],
  },

  directions: [
    { title: 'Running', promise: 'Run without the heaviness the next morning — through technique, not mileage.', steps: 14 },
    { title: 'Sleep', promise: 'Fall asleep on time and wake up rested — ten evening habits.', steps: 7 },
    { title: 'Cold exposure', promise: 'From a cool shower to snow, in order and with the contraindications.', steps: 10 },
    { title: 'Habits', promise: 'Sugar, bread, coffee, alcohol: what they cover for you and what replaces it.', steps: 14 },
    { title: 'Morning', promise: 'The morning in order: from waking to the first meal, without rushing.', steps: 11 },
    { title: 'Massage and self-massage', promise: 'Release tension with your own hands — and know who to go to when hands are not enough.', steps: 12 },
  ] as readonly EnDirection[],

  access: {
    heading: 'One subscription, three levels',
    lede: 'The material is the same on all three. What differs is how closely I am there.',
    note: 'New directions open to subscribers at no extra cost. Cancel any time.',
  },

  start: {
    heading: 'Start with one step',
    lede: 'Open the bot, pick a direction, and get the first step — the clip and the dose. No payment, no form.',
    button: 'Open in Telegram',
  },

  /**
   * Сказано прямо и на видном месте, а не сноской внизу.
   *
   * Продукт русскоязычный: 68 шагов, ролики и ответы бота — всё на русском.
   * Продать англоязычному человеку русский курс и умолчать об этом — тот же
   * обман, что выдуманный отзыв, только дороже: он платит и обнаруживает это
   * на первом шаге.
   */
  language: {
    heading: 'A note on language',
    text: 'The material is in Russian: all 68 steps, the clips and the bot itself. This page is in English because the method travels further than the language — if you teach cold exposure, breathing or barefoot running and want to talk, write to me. An English version of the course is not promised on a date, and I would rather say so than imply one.',
    cta: 'Write about collaboration',
  },
} as const;
