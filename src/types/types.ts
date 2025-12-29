// --- 1. СТРУКТУРА КРУГА ИСТОРИИ (8 ШАГОВ) ---
export interface StoryCircle {
  step1_you: string;          // Герой в зоне комфорта
  step2_need: string;         // Но есть потребность/желание
  step3_go: string;           // Переход в незнакомую ситуацию
  step4_search: string;       // Адаптация и поиск
  step5_find: string;         // Нахождение того, что искал
  step6_take: string;         // Тяжелая цена за это
  step7_return: string;       // Возврат в знакомую ситуацию
  step8_change: string;       // Изменение героя (финал)
}

// --- 2. ГЛАВА (CHAPTER) ---
export interface Chapter {
  id: string;
  order: number;              // 1-16
  title: string;
  circle: StoryCircle;        // Круг истории конкретной главы
  beatSheet: string;          // Бит-шит главы (Шаг 6)
  content: string;            // Финальный текст (Шаг 7)
  imageUrl?: string;
  lastAgent: string | null;
}

// --- 3. АКТ (ACT) ---
export interface Act {
  id: string;
  order: number;              // 1, 2, 3, 4
  title: string;
  circle: StoryCircle;        // Круг истории всего акта
  chapters: Chapter[];        // 4 главы внутри акта
}

// --- 4. КОНФЛИКТЫ (ШАГ 0) ---
export interface CoreConflicts {
  philosophical: string;      // Философский (Идея vs Контридея)
  emotional: string;          // Эмоциональный (Внутренний)
  physical: string;           // Физический (Внешний антагонист)
}

// --- 5. ГЛОБАЛЬНАЯ БИБЛИЯ ПРОЕКТА ---
export interface Bible {
  summary: string;
  conflicts: CoreConflicts;   // Шаг 0
  characterArc: string;       // Шаг 0
  globalCircle: StoryCircle;  // Шаг 1 (Круг всей истории)
  
  acts: Act[];                // Шаги 2-5 (Структура 4х4)
  
  characters: Character[];    // Справочник персонажей
  locations: Location[];      // Справочник локаций
}

// --- ДОПОЛНИТЕЛЬНЫЕ ТИПЫ ДЛЯ UI ---

export interface Character {
  id: string;
  name: string;
  description: string;
  traits: string[];
  arcStatus: string;
}

export interface Location {
  id: string;
  name: string;
  description: string;
}

export type AgentType = 'planner' | 'writer' | 'continuity' | 'editor' | 'visualizer' | 'architect';

export interface AgentStatus {
  isWorking: boolean;
  currentTask?: AgentType;
  agentName?: string;
}

export interface ContinuityError {
  type: string;
  description: string;
}

export interface ProjectMeta {
  id: string;
  name: string;
  lastModified: number;
  summarySnippet: string;
}

export interface ProjectData {
  bible: Bible;
}