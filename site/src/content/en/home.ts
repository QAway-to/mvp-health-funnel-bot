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
 *
 * ЧТО ИЗМЕНИЛОСЬ 03.09.2026. Раньше здесь лежала своя копия списка
 * направлений — шесть карточек с числом шагов, переписанных руками. Копия
 * начала расходиться с курсом в тот же день, когда в курсе появился шаг.
 * Теперь состав берётся из `en/directions.ts`, а число шагов считается по
 * настоящему списку шагов: разойтись им больше негде.
 */

import type { Faq, FinalCta } from '../types';

export const enHome = {
  brand: 'Federation of Health',

  meta: {
    title: 'Federation of Health — the order and the dose for an ordinary day',
    description:
      'Six directions and 68 steps: running, sleep, cold exposure, habits, the morning routine and massage. A step is a short clip and the dose in text. Delivered in Telegram.',
    ogImage: '/img/silhouettes.jpg',
  },

  hero: {
    eyebrow: 'Federation of Health',
    heading: 'Health is built from habits, not from courses',
    lede: 'Sleep pulls the morning, the morning pulls the load, the load pulls recovery. That is why there are ten directions and one subscription: take them one at a time, but there is no sense buying them apart.',
    note: 'Delivered in Telegram, step by step. A step is a short clip and the dose in text.',
    /** Вторая кнопка ведёт к списку направлений, а не в кассу. */
    secondary: 'See the directions',
  },

  method: {
    heading: 'What makes this different from an ice bath challenge',
    paragraphs: [
      'Cold exposure and breathwork are well covered in English — mostly as an intense practice you brace yourself for. This is the other half: the order and the dose for an ordinary day.',
      'Each step is one action. The clip shows the movement, the text gives the measure — how much, in what sequence, and what not to do. Sixty-eight steps across the six directions that are open.',
      'Nothing here promises a cure or a result. Some practices have contraindications, and they are named inside the steps rather than in a disclaimer at the bottom.',
    ],
  },

  directions: {
    kicker: 'Directions',
    /** Числа подставляются из реестра: обещать шесть, когда открыто пять, нельзя. */
    heading: (open: number, total: number) => `${open} of ${total} open`,
    cardAction: 'Read on',
    stepsLabel: (count: number) => `${count} steps`,
  },

  soon: {
    kicker: 'In the works',
    heading: (count: number) =>
      count === 1 ? 'One more direction in the works' : `${count} more directions in the works`,
    lede: 'They are part of the Federation plan and open to subscribers at no extra cost. Which one comes first depends on what people ask for — the bot is where to say so.',
  },

  testimonials: {
    kicker: 'How it goes for other people',
    /**
     * Подпись обязательна. Отзывы настоящие, но написаны они не по-английски:
     * человек читает перевод, и знать об этом он должен от нас, а не догадаться.
     */
    title: 'Before — after',
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
   * на первом шаге. То же предупреждение стоит вторым экземпляром прямо в
   * блоке цены (`subscription.warning`) — там, где человек достаёт карту.
   */
  language: {
    heading: 'A note on language',
    text: 'The material is in Russian: all 68 steps, the clips and the bot itself. This page is in English because the method travels further than the language — if you teach cold exposure, breathing or barefoot running and want to talk, write to me. An English version of the course is not promised on a date, and I would rather say so than imply one.',
    cta: 'Write about collaboration',
  },
} as const;

/**
 * Вопросы англоязычного читателя, а не перевод русских.
 *
 * Русский человек спрашивает, не вредно ли это для коленей. Англоязычный
 * приходит с другим набором: на каком языке материал, подписка это или
 * покупка, чем это отличается от того, что он уже видел на YouTube. Первым
 * стоит язык — это первое, что он должен узнать, и последнее, о чём мы стали
 * бы молчать.
 */
export const enFaq: Faq = {
  kicker: 'Questions',
  title: 'Before you decide',
  items: [
    {
      question: 'What language is the course in?',
      answer:
        'Russian. All 68 steps, the clips and the bot speak Russian; only this site is in English. There is no English version yet and no date promised for one — if that is a blocker, it is a blocker, and better to know now.',
    },
    {
      question: 'What exactly is a step?',
      answer:
        'One action, not one lesson. A short clip that shows it and a few lines of text with the measure: how much, in what order, and what not to do. A direction is seven to fourteen of them.',
    },
    {
      question: 'Is this a subscription or a purchase?',
      answer:
        'A subscription, monthly, cancel any time. Every direction is open on every level from the first day — the levels differ in how closely the author works with you, not in how much material you get.',
    },
    {
      question: 'How is it different from what is on YouTube?',
      answer:
        'YouTube has the intense version: the ice bath, the timer, the challenge. This is the daily dose and the order between practices — cold after the warm-up, food last in the morning, the run before the cold. The sequence is the product.',
    },
    {
      question: 'Do I need equipment or a gym?',
      answer:
        'No. Cold water, ordinary ground, your own hands and a pair of shoes you already own. There is no strength programme here, and the morning course says so in its own last step.',
    },
    {
      question: 'Is it safe?',
      answer:
        'Some of it is not, for some people. Contraindications are named inside the steps — step two of cold exposure, step four of running, step one of massage — and not hidden in a footer. Nothing here treats a diagnosis or replaces a doctor.',
    },
    {
      question: 'How do I pay from outside Russia?',
      answer:
        'Two ways, both work internationally: an ordinary card payment through LavaTop, or Telegram Stars inside the chat if you would rather not enter a card at all.',
    },
  ],
};

/** Последний экран английской главной. */
export const enFinalCta: FinalCta = {
  title: 'One step is enough to start',
  lead: 'Pick a direction, take the first step free, and decide after you have done it once.',
  note: 'The first step costs nothing and asks for nothing.',
  image: '/img/mountain.jpg',
  imageBrightness: 0.55,
};
