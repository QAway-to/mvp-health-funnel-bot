/**
 * Английские страницы направлений — адаптация, а не перевод.
 *
 * ЧЕМ АДАПТАЦИЯ ОТЛИЧАЕТСЯ ЗДЕСЬ. Русская страница объясняет, что холод и бег
 * полезны, потому что читатель приходит с этим вопросом. Англоязычный не
 * приходит: cold exposure у него уже названо, оформлено и продано как
 * интенсивная практика — ice bath, breathwork, challenge. Объяснять пользу
 * значит повторять то, что он слышал.
 *
 * Поэтому каждая страница начинается с различия: не «холод полезен», а «вот
 * чем ежедневная доза отличается от подвига раз в неделю». Это единственный
 * поворот, ради которого стоило переводить.
 *
 * Шаги перечислены настоящие — те же, что в `prompts/steps/`. Придумывать
 * состав для другого языка нельзя: человек заплатит и получит другое.
 */

export interface EnDirectionPage {
  /** Слаг русской страницы: адреса совпадают, меняется только префикс. */
  readonly slug: string;
  readonly title: string;
  /** Обещание в одну строку — что человек получит. */
  readonly promise: string;
  /** С чего страница начинается: различие, а не польза. */
  readonly angle: string;
  readonly body: readonly string[];
  /** Настоящие шаги курса, коротко. */
  readonly steps: readonly string[];
  /** Кому не подходит. Стоит на странице, а не в примечании. */
  readonly notFor: string;
}

export const enDirections: readonly EnDirectionPage[] = [
  {
    slug: 'zakalivanie',
    title: 'Cold exposure',
    promise: 'From a cool shower to snow — in order, with the contraindications named.',
    angle: 'You have probably seen the ice bath version: two minutes, a timer, a video. This is the other one — the daily dose, small enough that you keep doing it in November.',
    body: [
      'Ten steps, and the first one is not about water. It is about the fear, because that is what stops people, not the temperature.',
      'The order matters more than the intensity. Warm up before, not after. Get out before you stop feeling cold, not when you are numb. If you did not warm back up within twenty minutes, the dose was wrong — and there is a step about exactly that.',
      'Contraindications are step two, not a disclaimer. Some people should not do this at all, and it is better to find that out on day one.',
    ],
    steps: [
      'Fear, not water — what actually stops people',
      'Check your health first: who should not do this',
      'Ten reasons this works, so you know what you are after',
      'The first pour: how much, how long, what to do after',
      'If you did not warm back up',
      'Where cold sits in the morning order',
      'Dew and bare ground',
      'Snow — and how long it takes to get there',
      'How much and how often',
      'Summer counts too',
    ],
    notFor: 'Anyone with acute inflammation, a fever, heart or kidney conditions, or who is pregnant — see a doctor first. This is not a challenge and there is no benefit in pushing through.',
  },
  {
    slug: 'beg',
    title: 'Running',
    promise: 'Run without the heaviness the next morning — through technique, not mileage.',
    angle: 'No pace targets, no heart-rate zones, no half marathon. The distance here is one to two kilometres, and the whole point is that you can do it tomorrow as well.',
    body: [
      'Fourteen steps. Three of them are technique, and none of them is about speed: filling with oxygen through the breath, loading the muscles, and the charge-and-release pattern.',
      'Preparation takes twice as long as the run itself — that is a step, not a complaint. Route, surface, footwear, and the first time barefoot.',
      'The last step is about not quitting, and it is the one people need most: the threshold is not the run, it is the door.',
    ],
    steps: [
      'Why do this at all',
      'What is actually in your way',
      'Preparation takes twice as long as the run',
      'Who should not run',
      'The first time out',
      'Technique one: filling with oxygen',
      'Technique two: loading the muscles',
      'Technique three: charge and release',
      'The route',
      'Barefoot, the first time',
      'Surfaces: grass, sand, gravel, water',
      'Snow',
      'Cold after the run',
      'How not to quit',
    ],
    notFor: 'If running is contraindicated for you, the course says so in step four and tells you what replaces it. It does not work around a diagnosis.',
  },
  {
    slug: 'son',
    title: 'Sleep',
    promise: 'Fall asleep on time and wake up rested — the evening as a descent, not a switch.',
    angle: 'Nothing here is a supplement or a tracker. Seven steps, each one an ordinary thing you do in the two hours before bed.',
    body: [
      'Falling asleep is not a switch you flip. It is assembled from simple things: light, temperature, quiet, dinner, and getting your head empty.',
      'The last step is the one that surprises people: the morning holds the evening. A fixed wake-up time does more for falling asleep than anything you do at night.',
    ],
    steps: [
      'The room: light, temperature, air',
      'The phone, half an hour before',
      'Dinner and caffeine',
      'Emptying your head onto paper',
      'Already in bed',
      'The daytime nap',
      'The morning holds the evening',
    ],
    notFor: 'Persistent insomnia is a medical question, not a habit one. This course covers the habits around sleep, not the disorder.',
  },
  {
    slug: 'vrednye-privychki',
    title: 'Habits',
    promise: 'Sugar, bread, coffee, alcohol: what they cover for you, and what replaces it.',
    angle: 'Not willpower. Fourteen steps built on one idea — a habit is a loop of cue, action and reward, and the part you change is the reward.',
    body: [
      'It starts with picking one habit. Not twelve. Twelve at once is a guaranteed relapse, and that is step one.',
      'Step three is the uncomfortable one: write down ten honest things the habit gives you. Nobody keeps a habit that gives them nothing, and until that list exists there is nothing to replace.',
      'The exit plan is measured in months, not in "starting tomorrow, never again". A month, six months, a year — with what changes at each.',
      'The last step is arithmetic: what it cost you per month and per year, in your own numbers.',
    ],
    steps: [
      'Pick one',
      'Where you are now, on a scale',
      'What it gives you — ten honest lines',
      'The loop: cue, action, reward',
      'Your triggers, named specifically',
      'Remove the traces',
      'What replaces it',
      'The exit plan in stages',
      'Coffee, tea and sugar',
      'Sweets, bread and flour',
      'Meat, fast food and processed',
      'Laziness — as a signal, not a character flaw',
      'Resentment and envy',
      'What it cost you',
    ],
    notFor: 'Dependency that needs medical treatment. This is about habits you can still choose to change, and it says so rather than pretending otherwise.',
  },
  {
    slug: 'zaryadka',
    title: 'Morning',
    promise: 'The morning in order: from waking to the first meal, without rushing.',
    angle: 'Eleven steps, and the first one says the order matters more than the exercises. Most morning routines are a list of movements; this is a sequence with reasons for the sequence.',
    body: [
      'Wake, run, breathe, warm up, self-massage, ground yourself, settle, cold water, and only then eat. Food comes last in the morning, not first.',
      'Warm-up goes before cold water, never after. That order is not preference — it is the difference between a routine and an injury.',
      'The last step is honest about what is missing: there is no exercise list with sets and repetitions yet, and rather than invent one, the course says so.',
    ],
    steps: [
      'Order matters more than exercises',
      'What time to get up',
      'Running',
      'Filling with oxygen',
      'Warm-up — before the cold, always',
      'Self-massage on a warm body',
      'Standing on the ground barefoot',
      'A minute of settling before the water',
      'Cold water',
      'The first meal, last',
      'What this course does not yet cover',
    ],
    notFor: 'Anyone looking for a strength programme. There are no sets and repetitions here, and the course says so in its own last step.',
  },
  {
    slug: 'massazh',
    title: 'Massage and self-massage',
    promise: 'Release tension with your own hands — and know who to go to when hands are not enough.',
    angle: 'Half of this is not technique at all: it is how to choose a practitioner and what to ask before you book. That half is missing from almost everything written on the subject.',
    body: [
      'Four techniques hold up both a professional session and what you do yourself: stroking, rubbing, kneading, vibration. The difference is whose hands, not what they do.',
      'They go in order. Starting with kneading is like running without warming up.',
      'The minimum version is five evening minutes on the neck and shoulders — which does more than one long session a week, and that is the thing worth taking from the whole course.',
      'The last step names what is not covered: the mechanics of pressure, the neck technique, the order of zones. The neck is where a made-up instruction costs the most, so it is not made up.',
    ],
    steps: [
      'Who should not do this',
      'The four techniques',
      'The order, not the set',
      'Five minutes in the evening',
      'Through the feet',
      'How long, and on what',
      'The short one at your desk',
      'Seven kinds of massage, and what each does',
      'Choosing yours: task first, name second',
      'Four questions before you book',
      'The session: before, during, after',
      'What this course does not yet cover',
    ],
    notFor: 'Acute inflammation, skin or blood conditions, tumours, swollen lymph nodes — step one lists them. Spinal work is a doctor’s job, not a self-massage one.',
  },
];

export const enDirectionBySlug = (slug: string): EnDirectionPage | undefined =>
  enDirections.find((direction) => direction.slug === slug);

/**
 * Направления, которых по-английски ещё нет — как и по-русски.
 *
 * Русская главная говорит «направлений десять», английская молчала о четырёх
 * из них и обещала шесть. Это не сокращение, а другое предложение: человек
 * платит за подписку, в которую новые темы входят без доплаты, и должен
 * видеть, какие именно темы имеются в виду.
 *
 * Слаги те же, что в русском реестре: список сверяется с ним на сборке
 * (`src/i18n/content.ts`), поэтому переименовать направление и забыть про
 * английскую версию нельзя.
 */
export interface EnSoonDirection {
  readonly slug: string;
  readonly title: string;
  readonly promise: string;
}

export const enSoonDirections: readonly EnSoonDirection[] = [
  {
    slug: 'eda',
    title: 'Food',
    promise: 'What to eat and when, so the day does not run out of you.',
  },
  {
    slug: 'trenirovki',
    title: 'Training',
    promise: 'Strength without a gym: a load an ordinary week can carry.',
  },
  {
    slug: 'golodanie',
    /**
     * Обещание узкое сознательно, как и в русском реестре: материала о том,
     * кому входить нельзя, у нас нет, и «detox» здесь не обещается ни на
     * каком языке. По-английски соблазн сильнее — слово продано рынком.
     */
    title: 'Fasting',
    promise: 'Pauses from food: how to enter, how to come out, and why coming out matters more.',
  },
  {
    slug: 'pohudenie',
    title: 'Weight',
    promise: 'Weight as a consequence of habits, not a three-week diet.',
  },
];
