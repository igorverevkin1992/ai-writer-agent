'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { BibleManager } from '@/components/BibleManager';
import { AgentSidebar } from '@/components/AgentSidebar';
import { WriterEditor } from '@/components/WriterEditor';
import { ProjectHub } from '@/components/ProjectHub';
import { StoryMap } from '@/components/StoryMap';
import { supabase } from '@/lib/supabase';
import { generateFullOutline } from './actions';
import { 
  Bible, Chapter, Act, StoryCircle, AgentStatus, 
  ContinuityError, AgentType, ProjectMeta, CodexItem 
} from '@/types/types';

import { 
  generateBeatSheet, generateSceneProse, checkContinuity,
  runArchitectAgent, saveChapterAction, runChroniclerAgent
} from './actions';

// --- ХЕЛПЕРЫ ---
const createEmptyCircle = (): StoryCircle => ({
  step1_you: "", step2_need: "", step3_go: "", step4_search: "",
  step5_find: "", step6_take: "", step7_return: "", step8_change: ""
});

export default function MainApp() {
  // --- СОСТОЯНИЕ СПИСКА ПРОЕКТОВ ---
  const [projectList, setProjectList] = useState<ProjectMeta[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);

  // --- СОСТОЯНИЕ ТЕКУЩЕГО ПРОЕКТА ---
  const [bibleMeta, setBibleMeta] = useState<Partial<Bible>>({});
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [codexItems, setCodexItems] = useState<CodexItem[]>([]);
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null);

  // --- UI СОСТОЯНИЯ ---
  const [isLoaded, setIsLoaded] = useState(false);
  const [isMapOpen, setIsMapOpen] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatus>({ isWorking: false });
  const [continuityErrors, setContinuityErrors] = useState<ContinuityError[]>([]);
  const [chronicleSuggestions, setChronicleSuggestions] = useState<any[]>([]);
  const [toast, setToast] = useState<{message: string, type: 'error'|'success'} | null>(null);

  // --- 1. ИНИЦИАЛИЗАЦИЯ (AUTH + PROJECTS) ---
  useEffect(() => {
    const init = async () => {
      let { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        const { data } = await supabase.auth.signInAnonymously();
        user = data.user;
      }
      
      const { data } = await supabase.from('projects').select('*').order('last_modified', { ascending: false });
      if (data) setProjectList(data as any);
      setIsLoaded(true);
    };
    init();
  }, []);

  // --- 2. ЗАГРУЗКА ДАННЫХ ПРОЕКТА ---
  useEffect(() => {
    if (!currentProjectId) return;

    const loadProject = async () => {
      const [projRes, chapRes, codexRes] = await Promise.all([
        supabase.from('projects').select('*').eq('id', currentProjectId).single(),
        supabase.from('chapters').select('*').eq('project_id', currentProjectId).order('order_index', { ascending: true }),
        supabase.from('codex_items').select('*').eq('project_id', currentProjectId)
      ]);

      if (projRes.data) {
        setBibleMeta({
          conflicts: projRes.data.conflicts || { philosophical: "", emotional: "", physical: "" },
          globalCircle: projRes.data.global_circle || createEmptyCircle(),
          characterArc: projRes.data.character_arc || "",
          summary: projRes.data.name
        });
      }

      if (chapRes.data) {
        setChapters(chapRes.data as any);
        if (chapRes.data.length > 0) setActiveChapterId(chapRes.data[0].id);
      }
      
      if (codexRes.data) setCodexItems(codexRes.data as any);
    };

    loadProject();
  }, [currentProjectId]);

  // --- 3. АВТО-СКРЫТИЕ TOAST ---
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  // --- 4. СБОРКА ВИРТУАЛЬНОЙ БИБЛИИ ДЛЯ UI ---
  const bibleForUI: Bible = useMemo(() => {
    const acts: Act[] = [];
    for (let i = 1; i <= 4; i++) {
      const actChapters = chapters.filter(c => c.order_index > (i - 1) * 4 && c.order_index <= i * 4);
      acts.push({
        id: `act-${i}`,
        order: i,
        title: `Act ${i}`,
        circle: (bibleMeta as any)?.actCircles?.[i-1] || createEmptyCircle(),
        chapters: actChapters as any
      });
    }
    return {
      summary: bibleMeta.summary || "",
      conflicts: bibleMeta.conflicts || { philosophical: "", emotional: "", physical: "" },
      globalCircle: bibleMeta.globalCircle || createEmptyCircle(),
      characterArc: bibleMeta.characterArc || "",
      acts,
      characters: codexItems.filter(i => i.type === 'character') as any,
      locations: codexItems.filter(i => i.type === 'location') as any
    };
  }, [bibleMeta, chapters, codexItems]);

  const activeChapter = chapters.find(c => c.id === activeChapterId);

  // --- 5. ОБНОВЛЕНИЕ ГЛАВЫ (STATE + DB) ---
  const updateActiveChapter = useCallback(async (updates: Partial<Chapter>) => {
    if (!activeChapterId) return;
    setChapters(prev => prev.map(c => c.id === activeChapterId ? { ...c, ...updates } : c));
    await saveChapterAction(activeChapterId, updates);
  }, [activeChapterId]);

  // --- 6. СОЗДАНИЕ ПРОЕКТА ---
  const handleCreateProject = async (name: string) => {
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Auth failed");

      const { data: proj, error: projError } = await supabase.from('projects').insert({ 
        name, user_id: user.id, conflicts: {}, global_circle: createEmptyCircle() 
      }).select().single();

      if (projError) throw projError;

      const newChapters = Array.from({ length: 16 }, (_, i) => ({
        project_id: proj.id, order_index: i + 1, title: `Chapter ${i + 1}`,
        circle: createEmptyCircle(), content: "", beat_sheet: ""
      }));
      
      await supabase.from('chapters').insert(newChapters);
      setProjectList(prev => [proj as any, ...prev]);
      setCurrentProjectId(proj.id);
      setToast({ message: "Project Initialized in Cloud", type: 'success' });
    } catch (error: any) {
      setToast({ message: error.message, type: 'error' });
    }
  };

  // --- 7. ЛОГИКА АРХИТЕКТОРА (КРУГИ ИСТОРИИ) ---
  const handleArchitectAction = async (level: string, actIndex?: number) => {
    // 1. Установка статуса
    setAgentStatus({ isWorking: true, currentTask: 'architect', agentName: 'ARCHITECT' });
    
    // Техническое сопоставление твоих шагов
    const isCore = level === 'core';       // Шаг 1
    const isGlobal = level === 'global';   // Шаг 2
    const isAct = level === 'act';         // Шаг 3
    const isOutline = level === 'outline'; // Шаг 4
    const isChapter = level === 'chapter'; // Шаг 5 (генерация круга внутри выбранной главы)

    try {
      // Сбор контекста: ИИ должен знать всё, что было решено на предыдущих шагах
      const context = JSON.stringify({ 
        bibleMeta, 
        currentActNum: isAct ? (actIndex !== undefined ? actIndex + 1 : 1) : null,
        activeChapter: isChapter ? { 
          id: activeChapterId, 
          order: activeChapter?.order_index,
          title: activeChapter?.title, 
          circle: activeChapter?.circle 
        } : null
      });

      // 2. ВЫЗОВ АГЕНТА
      const res = isOutline 
        ? await generateFullOutline(context) 
        : await runArchitectAgent(level, context, `Generate structural data for ${level}`);
      
      // 3. ОБРАБОТКА УСПЕХА
      if (res.success && res.data) {
        
        // --- ШАГ 1: CORE ---
        if (isCore) {
          setBibleMeta(prev => ({ 
            ...prev, 
            conflicts: res.data.conflicts || prev.conflicts,
            characterArc: res.data.characterArc || prev.characterArc
          }));
          await supabase.from('projects').update({ 
            conflicts: res.data.conflicts, 
            character_arc: res.data.characterArc 
          }).eq('id', currentProjectId);
        }

        // --- ШАГ 2: GLOBAL ---
        else if (isGlobal) {
          setBibleMeta(prev => ({ ...prev, globalCircle: { ...res.data } }));
          await supabase.from('projects').update({ global_circle: res.data }).eq('id', currentProjectId);
        } 
        
        // --- ШАГ 3: ACTS ---
        else if (isAct && actIndex !== undefined) {
          const currentActCircles = (bibleMeta as any).actCircles || [{}, {}, {}, {}];
          const newActCircles = [...currentActCircles];
          newActCircles[actIndex] = res.data;
          
          setBibleMeta(prev => ({ ...prev, actCircles: newActCircles }));
          await supabase.from('projects').update({ act_circles: newActCircles }).eq('id', currentProjectId);
        } 
        
        // --- ШАГ 4: GENERATE FULL OUTLINE (Массовое обновление 16 глав) ---
        else if (isOutline) {
          const updatedChapters = chapters.map((ch) => {
            const aiData = res.data.find((d: any) => d.order === ch.order_index);
            // Записываем название и ставим цель главы в Step 1 круга главы
            return aiData ? { 
              ...ch, 
              title: aiData.title, 
              circle: { ...ch.circle, step1_you: aiData.goal } 
            } : ch;
          });
          
          // Обновляем интерфейс мгновенно
          setChapters(updatedChapters);

          // Профессиональное сохранение в Supabase: UPSERT (обновляем всё одним запросом)
          const chaptersToUpsert = updatedChapters.map(ch => ({
            id: ch.id,
            project_id: currentProjectId,
            order_index: ch.order_index,
            title: ch.title,
            circle: ch.circle,
            content: ch.content, // сохраняем текущий текст, чтобы не затереть
            beat_sheet: ch.beat_sheet
          }));

          const { error: upsertError } = await supabase.from('chapters').upsert(chaptersToUpsert);
          if (upsertError) throw upsertError;
        } 

        // --- ШАГ 5: SELECT CHAPTER & GENERATE CIRCLE ---
        else if (isChapter) {
          await updateActiveChapter({ circle: { ...res.data } });
        }

        setToast({ message: `Success! Step ${level.toUpperCase()} updated.`, type: 'success' });

      } 
      // 4. ОБРАБОТКА ОШИБОК (429 и другие)
      else {
        const isQuota = res.error === "QUOTA_EXCEEDED" || res.message?.includes('429');
        setToast({ 
          message: isQuota ? "Google API Limit. Please wait 1 minute." : (res.message || "AI Error"), 
          type: 'error' 
        });
      }

    } catch (error: any) {
      console.error("Architect Logic Error:", error);
      setToast({ message: "System Error. Please try again.", type: 'error' });
    } finally {
      // Всегда разблокируем интерфейс
      setAgentStatus({ isWorking: false });
    }
  };

  // --- 8. ЛОГИКА АГЕНТОВ (WRITE / PLAN / CONTI) ---
  const handleAgentAction = async (type: AgentType, input?: string) => {
    setAgentStatus({ isWorking: true, currentTask: type, agentName: type.toUpperCase() });
    const context = `
      CONFLICTS: ${JSON.stringify(bibleMeta.conflicts)}
      GLOBAL: ${JSON.stringify(bibleMeta.globalCircle)}
      CHAPTER_CIRCLE: ${JSON.stringify(activeChapter?.circle)}
      CODEX: ${JSON.stringify(codexItems)}
    `;

    try {
      if (type === 'planner') {
        const res = await generateBeatSheet(context, input || "Plan chapter");
        if (res.success) updateActiveChapter({ beatSheet: res.data });
      } 
      else if (type === 'writer') {
        const res = await generateSceneProse(context, activeChapter?.beatSheet || "");
        if (res.success) {
          updateActiveChapter({ content: res.data });
          
          // Авто-Хронист
          setAgentStatus({ isWorking: true, currentTask: 'writer', agentName: 'CHRONICLER' });
          const chronRes = await runChroniclerAgent(res.data, JSON.stringify(codexItems));
          if (chronRes.success) setChronicleSuggestions(chronRes.data);

          // Авто-Континьюити
          setAgentStatus({ isWorking: true, currentTask: 'continuity', agentName: 'SCANNING...' });
          const contRes = await checkContinuity(context, res.data);
          if (contRes.success) setContinuityErrors(JSON.parse(contRes.data).errors || []);
        }
      }
      else if (type === 'continuity') {
        const res = await checkContinuity(context, activeChapter?.content || "");
        if (res.success) setContinuityErrors(JSON.parse(res.data).errors || []);
      }
    } finally {
      setAgentStatus({ isWorking: false });
    }
  };

  // --- 9. ХРОНИСТ: ПРИМЕНЕНИЕ ПРАВОК ---
  const handleApplySuggestion = async (suggestion: any) => {
    const existing = codexItems.find(i => i.name.toLowerCase() === suggestion.name.toLowerCase());
    const newItem = {
      id: existing?.id || crypto.randomUUID(),
      project_id: currentProjectId!,
      type: suggestion.type,
      name: suggestion.name,
      description: existing ? `${existing.description}\n[Update]: ${suggestion.suggestion}` : suggestion.suggestion,
      metadata: {}
    };

    const { data } = await supabase.from('codex_items').upsert(newItem).select().single();
    if (data) {
      setCodexItems(prev => [...prev.filter(i => i.id !== data.id), data as CodexItem]);
      setChronicleSuggestions(prev => prev.filter(s => s !== suggestion));
      setToast({ message: "Codex Updated", type: 'success' });
    }
  };

  // --- РЕНДЕР ---
  if (!isLoaded) return null;

  if (!currentProjectId) {
    return <ProjectHub projects={projectList} onSelect={setCurrentProjectId} onCreate={handleCreateProject} onDelete={() => {}} />;
  }

  return (
    <main className="flex h-screen w-screen overflow-hidden bg-[#050505] text-gray-100 relative">
      {/* Кнопки управления (Top Left) */}
      <div className="fixed top-4 left-4 z-50 flex gap-2">
        <button onClick={() => setCurrentProjectId(null)} className="p-2.5 bg-gray-900/80 hover:bg-blue-600 rounded-full border border-gray-800 transition-all shadow-2xl">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
        </button>
        <button onClick={() => setIsMapOpen(true)} className="flex items-center gap-2 px-4 py-2 bg-gray-900/80 hover:bg-blue-600 text-[10px] font-black uppercase tracking-widest text-white border border-gray-800 rounded-full transition-all shadow-2xl">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/></svg>
          Story Map
        </button>
      </div>

      <BibleManager 
        bible={bibleForUI} 
        onUpdate={(u) => { /* твой код обновления */ }}
        onArchitectAction={handleArchitectAction}
        isWorking={agentStatus.isWorking && agentStatus.currentTask === 'architect'}
        onReset={() => {}} 
        hasApiKey={true}
        activeChapterId={activeChapterId}
        onSelectChapter={setActiveChapterId}
      />

      <div className="flex-1 flex flex-col min-w-0 border-l border-gray-900">
        <WriterEditor 
          content={activeChapter?.content || ""} 
          onChange={(val) => updateActiveChapter({ content: val })}
          title={activeChapter?.title || ""}
          onTitleChange={(val) => updateActiveChapter({ title: val })}
          scenes={chapters as any}
          activeSceneId={activeChapterId || ""}
          onSelectScene={setActiveChapterId}
          onAddScene={() => {}} 
          onDeleteScene={() => {}} 
          hasApiKey={true}
        />
      </div>

      <AgentSidebar 
        status={agentStatus}
        continuityErrors={continuityErrors}
        onAction={handleAgentAction}
        plan={activeChapter?.beatSheet || ""}
        setPlan={(val) => updateActiveChapter({ beatSheet: val })}
        suggestions={chronicleSuggestions}
        onApplySuggestion={handleApplySuggestion}
      />

      {isMapOpen && <StoryMap bible={bibleForUI} onSelectChapter={setActiveChapterId} onClose={() => setIsMapOpen(false)} />}

      {toast && (
        <div className={`fixed bottom-12 right-8 px-6 py-4 rounded-xl shadow-2xl text-white font-bold z-[200] flex items-center gap-3 animate-in slide-in-from-bottom-5 duration-300 ${toast.type === 'error' ? 'bg-red-600' : 'bg-blue-600'}`}>
          <span>{toast.message}</span>
          <button onClick={() => setToast(null)} className="bg-white/20 hover:bg-white/40 w-6 h-6 rounded-full flex items-center justify-center">×</button>
        </div>
      )}
    </main>
  );
}