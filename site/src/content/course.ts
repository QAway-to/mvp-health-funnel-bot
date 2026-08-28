import { landingA } from './landing-a';

/**
 * Состав продукта — единый источник для страницы /kurs/ и для блока
 * «что именно получаешь» на всех остальных страницах.
 *
 * Блоки берутся из существующего описания гайда (landing-a), а не дублируются:
 * так формулировки не разъедутся при правках.
 *
 * Названия уроков сюда должен дать заказчик. Пока `lessons` пуст, страница
 * показывает явную заглушку вместо выдуманного списка.
 */

export interface Lesson {
  readonly title: string;
  /** Длительность, например «6 мин». Пусто — не отрисовывается. */
  readonly duration?: string;
}

export interface CourseBlock {
  readonly label: string;
  readonly title: string;
  readonly text: string;
  readonly lessons: readonly Lesson[];
}

/** Осязаемые характеристики продукта: то, чего не хватало для сравнения тарифов. */
export interface CourseFacts {
  readonly lessonsCount: string;
  readonly dailyTime: string;
  readonly access: string;
  readonly devices: string;
  readonly feedback: string;
  readonly equipment: string;
}

export const courseBlocks: readonly CourseBlock[] = landingA.program.blocks.map((block) => ({
  label: block.label,
  title: block.title,
  text: block.text,
  lessons: [],
}));

export const courseFacts: CourseFacts = {
  lessonsCount: 'Четыре блока с уроками по 5–10 минут',
  dailyTime: '5–10 минут в день',
  access: 'Доступ — пока активна подписка',
  devices: 'Телефон, планшет, компьютер — браузер, без установки',
  feedback: 'Разбор вопросов в чате поддержки',
  equipment: 'Без зала и снаряжения',
};

/** Дополнения к основным блокам — тоже из существующего контента. */
export const courseExtras = landingA.program.extras;

/** Есть ли у заказчика названия уроков. Пока нет — не выдумываем. */
export const hasLessonList = courseBlocks.some((block) => block.lessons.length > 0);
