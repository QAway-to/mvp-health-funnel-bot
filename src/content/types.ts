/** Структура контента лендинга. Оба лендинга (А и Б) описываются одной схемой. */

export interface NavLink {
  readonly label: string;
  readonly href: string;
}

export interface Meta {
  readonly title: string;
  readonly description: string;
  /** Путь к OG-картинке относительно `public/`. */
  readonly ogImage: string;
}

export interface Hero {
  readonly kicker: string;
  readonly title: string;
  readonly lead: string;
  readonly image: string;
  /** Затемнение фонового фото, если в макете задан filter: brightness(). */
  readonly imageBrightness?: number;
  readonly trust: readonly string[];
}

export interface MirrorCard {
  readonly label: string;
  readonly title: string;
  readonly text: string;
}

export interface Mirror {
  readonly kicker: string;
  readonly title: string;
  readonly cards: readonly MirrorCard[];
  readonly closer: string;
}

export interface ReasonCard {
  readonly num: string;
  readonly title: string;
  readonly text: string;
  readonly solution: string;
}

export interface Reasons {
  readonly kicker: string;
  readonly title: string;
  readonly cards: readonly ReasonCard[];
}

export interface TitledText {
  readonly title: string;
  readonly text: string;
}

export interface Mechanism {
  readonly kicker: string;
  readonly title: string;
  readonly items: readonly TitledText[];
  readonly note: string;
  readonly image: string;
  readonly imageAlt: string;
}

export interface Effects {
  readonly kicker: string;
  readonly title: string;
  readonly items: readonly TitledText[];
}

export interface ProgramBlock extends TitledText {
  readonly label: string;
}

export interface Program {
  readonly kicker: string;
  readonly title: string;
  readonly blocks: readonly ProgramBlock[];
  readonly extras: readonly TitledText[];
}

export interface PlanItem extends TitledText {
  readonly label: string;
  /** Подстрочник через border-top — только у варианта `weeks` (лендинг Б). */
  readonly note?: string;
}

export interface Plan {
  readonly kicker: string;
  readonly title: string;
  /** `days` — карточки-линии (А), `weeks` — карточки с фоном (Б). */
  readonly variant: 'days' | 'weeks';
  readonly items: readonly PlanItem[];
  readonly closer: string;
}

export interface Metric {
  readonly value: string;
  readonly label: string;
}

export interface Author {
  readonly kicker: string;
  readonly title: string;
  readonly text: string;
  readonly image: string;
  readonly imageAlt: string;
  /** Сторона, с которой стоит фото: А — слева, Б — справа. */
  readonly imageSide: 'left' | 'right';
  readonly metrics: readonly Metric[];
}

export interface PricingPlan {
  readonly label: string;
  readonly price: string;
  readonly text: string;
  readonly features: readonly string[];
  readonly ctaLabel: string;
  readonly href: string;
}

export interface Pricing {
  readonly kicker: string;
  readonly title: string;
  readonly base: PricingPlan;
  readonly premium: PricingPlan;
  readonly badge: string;
  readonly guarantee: string;
  readonly payment: string;
}

export interface FaqItem {
  readonly question: string;
  readonly answer: string;
}

export interface Faq {
  readonly kicker: string;
  readonly title: string;
  readonly items: readonly FaqItem[];
}

export interface FinalCta {
  readonly title: string;
  readonly lead: string;
  readonly ctaLabel: string;
  readonly href: string;
  readonly note: string;
  readonly image: string;
  readonly imageBrightness: number;
}

export interface LandingContent {
  readonly slug: string;
  readonly brand: string;
  readonly meta: Meta;
  readonly nav: readonly NavLink[];
  readonly hero: Hero;
  readonly mirror: Mirror;
  readonly reasons: Reasons;
  readonly mechanism: Mechanism;
  /** Секция «Шесть эффектов» есть только на лендинге Б. */
  readonly effects?: Effects;
  readonly program: Program;
  readonly plan: Plan;
  readonly author: Author;
  readonly pricing: Pricing;
  readonly faq: Faq;
  readonly finalCta: FinalCta;
}
