'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { BibleManager } from '@/components/BibleManager';
import { AgentSidebar } from '@/components/AgentSidebar';
import { WriterEditor } from '@/components/WriterEditor';
import { ProjectHub } from '@/components/ProjectHub';
import { supabase } from '@/lib/supabase';
import { 
  Bible, 
  Chapter, 
  Act, 
  StoryCircle, 
  AgentStatus, 
  ContinuityError, 
  AgentType, 
  ProjectMeta, 
  ProjectData 
} from '@/types/types';

import { 
  generateBeatSheet, 
  generateSceneProse, 
  checkContinuity,
  runArchitectAgent
} from './actions';

// --- ИНИЦИАЛИЗАЦИЯ ФРАКТАЛЬНОЙ СТРУКТУРЫ ---

const createEmptyCircle = (): StoryCircle => ({
  step1_you: "", step2_need: "", step3_go: "", step4_search: "",
  step5_find: "", step6_take: "", step7_return: "", step8_change: ""
});

const createInitialStructure = (): Act[] => {
  const acts: Act[] = [];
  let chapterCounter = 1;
  for (let a = 1; a <= 4; a++) {
    const chapters: Chapter[] = [];
    for (let c = 1; c <= 4; c++) {
      chapters.push({
        id: `ch-${chapterCounter}`,
        order: chapterCounter,
        title: `Chapter ${chapterCounter}`,
        circle: createEmptyCircle(),
        beatSheet: "",
        content: "",
        lastAgent: null
      });
      chapterCounter++;
    }
    acts.push({ id: `act-${a}`, order: a, title: `Act ${a}`, circle: createEmptyCircle(), chapters });
  }
  return acts;
};

const DEFAULT_BIBLE: Bible = {
  summary: "",
  conflicts: { philosophical: "", emotional: "", physical: "" },
  characterArc: "",
  globalCircle: createEmptyCircle(),
  acts: createInitialStructure(),
  characters: [],
  locations: []
};

export default function MainApp() {
  // --- СОСТОЯНИЕ ---
  const [projectList, setProjectList] = useState<ProjectMeta[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [bible, setBible] = useState<Bible>(DEFAULT_BIBLE);
  const [activeChapterId, setActiveChapterId] = useState<string>("ch-1");
  const [isLoaded, setIsLoaded] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AgentStatus>({ isWorking: false });
  const [continuityErrors, setContinuityErrors] = useState<ContinuityError[]>([]);

  // --- ОБЛАЧНОЕ И ЛОКАЛЬНОЕ ХРАНЕНИЕ ---

  // 1. Загрузка списка проектов (из Supabase с фолбеком на LocalStorage)
  useEffect(() => {
    const initLoad = async () => {
      // --- ДОБАВЬТЕ ЭТОТ БЛОК ДЛЯ АВТО-ВХОДА ---
      let { data: { user } } = await supabase.auth.getUser();
      
      if (!user) {
        // Если пользователя нет, входим анонимно
        const { data: signInData } = await supabase.auth.signInAnonymously();
        user = signInData.user;
        console.log("Anonymous session started:", user?.id);
      }
      const { data: cloudProjects } = await supabase.from('projects').select('id, name, last_modified, summary_snippet');
      const localList = localStorage.getItem('vwr_projects_index');
      
      if (cloudProjects && cloudProjects.length > 0) {
        setProjectList(cloudProjects as any);
      } else if (localList) {
        setProjectList(JSON.parse(localList));
      }
      setIsLoaded(true);
    };
    initLoad();
  }, []);

  // 2. Загрузка данных конкретного проекта
  useEffect(() => {
    if (!currentProjectId) return;
    const loadProjectData = async () => {
      // Сначала пробуем облако
      const { data: cloudData } = await supabase.from('projects').select('data').eq('id', currentProjectId).single();
      
      let finalBible = DEFAULT_BIBLE;

      if (cloudData) {
        finalBible = cloudData.data.bible;
      } else {
        // Если нет в облаке, смотрим локально
        const localData = localStorage.getItem(`vwr_p_${currentProjectId}`);
        if (localData) finalBible = JSON.parse(localData).bible;
      }

      setBible({
        ...DEFAULT_BIBLE,
        ...finalBible,
        acts: finalBible.acts || DEFAULT_BIBLE.acts
      });
      
      if (finalBible.acts?.[0]?.chapters?.[0]) {
        setActiveChapterId(finalBible.acts[0].chapters[0].id);
      }
    };
    loadProjectData();
  }, [currentProjectId]);

  // 3. Автосохранение (Облако + Локал)
  useEffect(() => {
    if (!isLoaded || !currentProjectId) return;

    const syncData = async () => {
      const projectData = { bible };
      // Локально
      localStorage.setItem(`vwr_p_${currentProjectId}`, JSON.stringify(projectData));
      
      // В облако (Supabase)
      await supabase.from('projects').upsert({
        id: currentProjectId,
        name: projectList.find(p => p.id === currentProjectId)?.name || "Untitled",
        data: projectData,
        last_modified: new Date().toISOString(),
        summary_snippet: bible.summary.slice(0, 100)
      });
    };

    const timer = setTimeout(syncData, 2000); // Дебаунс сохранения
    return () => clearTimeout(timer);
  }, [bible, currentProjectId, isLoaded, projectList]);

  // --- НАВИГАЦИЯ ---
  const allChapters = (bible.acts || []).flatMap(act => act.chapters || []);
  const activeChapter = allChapters.find(c => c.id === activeChapterId) || allChapters[0];

  const updateActiveChapter = useCallback((updates: Partial<Chapter>) => {
    setBible(prev => ({
      ...prev,
      acts: prev.acts.map(act => ({
        ...act,
        chapters: act.chapters.map(ch => ch.id === activeChapterId ? { ...ch, ...updates } : ch)
      }))
    }));
  }, [activeChapterId]);

  // --- ЛОГИКА ПРОЕКТОВ ---
  const handleCreateProject = async (name: string) => {
    const newId = crypto.randomUUID();
    const newMeta: ProjectMeta = { id: newId, name, lastModified: Date.now(), summarySnippet: "New story..." };
    
    setProjectList(prev => [newMeta, ...prev]);
    setBible(DEFAULT_BIBLE);
    setCurrentProjectId(newId);

    await supabase.from('projects').insert({
      id: newId,
      name,
      data: { bible: DEFAULT_BIBLE },
      user_id: (await supabase.auth.getUser()).data.user?.id
    });
  };

  // --- ЛОГИКА ИИ-АГЕНТОВ ---

  const handleArchitectAction = async (level: 'global' | 'act' | 'chapter') => {
    setAgentStatus({ isWorking: true, currentTask: 'architect', agentName: 'ARCHITECT' });
    const currentAct = bible.acts.find(a => a.chapters.some(c => c.id === activeChapterId));
    
    const context = `
      LEVEL: ${level}
      CORE CONFLICTS: ${JSON.stringify(bible.conflicts)}
      GLOBAL CIRCLE: ${JSON.stringify(bible.globalCircle)}
      ACT CIRCLE: ${JSON.stringify(currentAct?.circle)}
    `;

    try {
      const res = await runArchitectAgent(level, context, "Generate fractal 8-step story circle");
      if (res.success) {
        if (level === 'global') setBible(prev => ({ ...prev, globalCircle: res.data }));
        else if (level === 'act' && currentAct) {
          setBible(prev => ({
            ...prev, acts: prev.acts.map(a => a.id === currentAct.id ? { ...a, circle: res.data } : a)
          }));
        } else if (level === 'chapter') {
          updateActiveChapter({ circle: res.data });
        }
      }
    } finally { setAgentStatus({ isWorking: false }); }
  };

  const handleAgentAction = async (type: AgentType, input?: string) => {
    setAgentStatus({ isWorking: true, currentTask: type, agentName: type.toUpperCase() });
    const currentAct = bible.acts.find(a => a.chapters.some(c => c.id === activeChapterId));
    
    const context = `
      CONFLICTS: ${JSON.stringify(bible.conflicts)}
      GLOBAL: ${JSON.stringify(bible.globalCircle)}
      ACT: ${JSON.stringify(currentAct?.circle)}
      CHAPTER_CIRCLE: ${JSON.stringify(activeChapter.circle)}
    `;

    try {
      if (type === 'planner') {
        const res = await generateBeatSheet(context, input || "Plan this chapter");
        if (res.success) updateActiveChapter({ beatSheet: res.data });
      } 
      else if (type === 'writer') {
        const res = await generateSceneProse(context, activeChapter.beatSheet);
        if (res.success) {
          updateActiveChapter({ content: res.data });
          const contRes = await checkContinuity(context, res.data);
          if (contRes.success) setContinuityErrors(JSON.parse(contRes.data).errors || []);
        }
      }
      else if (type === 'continuity') {
        const res = await checkContinuity(context, activeChapter.content);
        if (res.success) setContinuityErrors(JSON.parse(res.data).errors || []);
      }
    } finally { setAgentStatus({ isWorking: false }); }
  };

  // --- РЕНДЕР ---

  if (!isLoaded) return null;

  if (!currentProjectId) {
    return <ProjectHub projects={projectList} onSelect={setCurrentProjectId} onCreate={handleCreateProject} onDelete={() => {}} />;
  }

  return (
    <main className="flex h-screen w-screen overflow-hidden bg-[#050505] text-gray-100 relative">
      <button 
        onClick={() => setCurrentProjectId(null)}
        className="fixed top-4 left-4 z-50 p-2.5 bg-gray-900/80 hover:bg-blue-600 rounded-full border border-gray-800 transition-all shadow-2xl"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
      </button>

      <BibleManager 
        bible={bible} 
        onUpdate={setBible} 
        onArchitectAction={handleArchitectAction}
        isWorking={agentStatus.isWorking && agentStatus.currentTask === 'architect'}
        onReset={() => {}} 
        hasApiKey={true}
      />

      <div className="flex-1 flex flex-col min-w-0 border-l border-gray-900">
        <WriterEditor 
          content={activeChapter.content} 
          onChange={(val) => updateActiveChapter({ content: val })}
          title={activeChapter.title}
          onTitleChange={(val) => updateActiveChapter({ title: val })}
          scenes={allChapters as any}
          activeSceneId={activeChapterId}
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
        plan={activeChapter.beatSheet}
        setPlan={(val) => updateActiveChapter({ beatSheet: val })}
      />
    </main>
  );
}