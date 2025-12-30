'use client';

import React, { useState } from 'react';
import { Bible, StoryCircle, CoreConflicts, CodexItem } from '../types/types';
import { 
  Dna, Disc, Layers, BookOpen, Zap, Loader2, 
  Trash2, Plus, Users, MapPin, Sparkles, Settings, ChevronDown 
} from 'lucide-react';

interface BibleManagerProps {
  bible: Bible;
  onUpdate: (bible: Bible) => void;
  onArchitectAction: (level: string, index?: number) => void;
  isWorking: boolean;
  onReset: () => void;
  hasApiKey: boolean;
  activeChapterId: string | null;
  onSelectChapter: (id: string) => void;
}

type ArchitectStep = 'step0_core' | 'step1_global' | 'step2_acts' | 'step4_chapters';

export const BibleManager: React.FC<BibleManagerProps> = ({ 
  bible, onUpdate, onArchitectAction, isWorking, onReset, hasApiKey, activeChapterId, onSelectChapter
}) => {
  // --- СОСТОЯНИЕ ---
  const [mainTab, setMainTab] = useState<'architect' | 'codex'>('architect');
  const [archStep, setArchStep] = useState<ArchitectStep>('step0_core');
  const [activeCircleStep, setActiveCircleStep] = useState(0);
  const [selectedActIndex, setSelectedActIndex] = useState(0);
  const [codexTab, setCodexTab] = useState<'chars' | 'locs'>('chars');
  

  // --- ХЕЛПЕРЫ ОБНОВЛЕНИЯ ---
  const updateCircle = (circle: StoryCircle, stepKey: keyof StoryCircle, val: string): StoryCircle => ({
    ...circle, [stepKey]: val
  });

  const circleKeys: (keyof StoryCircle)[] = [
    'step1_you', 'step2_need', 'step3_go', 'step4_search', 
    'step5_find', 'step6_take', 'step7_return', 'step8_change'
  ];

  const circleLabels = ['YOU', 'NEED', 'GO', 'SEARCH', 'FIND', 'TAKE', 'RETURN', 'CHANGE'];
  const circleDescs = [
    'Zone of Comfort', 'But they want something', 'Enter unfamiliar situation', 
    'Adapt to it', 'Get what they wanted', 'Pay a heavy price', 
    'To familiar situation', 'Having changed'
  ];

  // --- УНИВЕРСАЛЬНЫЙ КОМПОНЕНТ СЛАЙДЕРА (ДЛЯ ВСЕХ ШАГОВ АРХИТЕКТОРА) ---
  const renderStepEditor = (
    title: string,
    desc: string,
    value: string,
    onChange: (val: string) => void,
    stepsCount: number,
    levelLabel: string
  ) => (
    <div className="flex flex-col h-full overflow-hidden animate-in fade-in duration-500">
      {/* Кнопка AI Генерации */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <button 
          onClick={() => {const index = archStep === 'step2_acts' ? selectedActIndex : undefined; onArchitectAction(levelLabel, index);}}
          disabled={isWorking}
          className="w-full flex items-center justify-center gap-2 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-[10px] font-black text-white uppercase rounded-xl transition-all shadow-lg shadow-blue-900/20"
        >
          {isWorking ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
          AI Generate Full {levelLabel}
        </button>
      </div>

      {/* Навигатор 1-8 или 1-4 */}
      <div className="flex justify-between gap-1 mb-4 shrink-0">
        {Array.from({ length: stepsCount }).map((_, idx) => (
          <button
            key={idx}
            onClick={() => setActiveCircleStep(idx)}
            className={`flex-1 py-2 rounded-lg text-[10px] font-black border transition-all ${
              activeCircleStep === idx ? 'bg-blue-600 border-blue-500 text-white shadow-md' : 'bg-gray-950 border-gray-900 text-gray-600'
            }`}
          >
            {idx + 1}
          </button>
        ))}
      </div>

      {/* ГИГАНТСКОЕ ПОЛЕ ВВОДА */}
      <div className="flex-1 flex flex-col min-h-0 bg-gray-950 border border-gray-800 rounded-3xl p-6 shadow-inner group focus-within:border-blue-500/50 transition-all">
        <div className="flex justify-between items-center mb-4 shrink-0">
          <h3 className="text-lg font-black text-white uppercase tracking-tighter">{title}</h3>
          <span className="text-[10px] font-bold text-gray-600 uppercase italic">{desc}</span>
        </div>
        <textarea
          className="flex-1 w-full bg-transparent text-gray-200 text-sm leading-relaxed outline-none resize-none custom-scrollbar placeholder:text-gray-800"
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={`Describe ${title.toLowerCase()}...`}
        />
        <div className="flex justify-between mt-4 shrink-0">
           <button onClick={() => setActiveCircleStep(Math.max(0, activeCircleStep - 1))} className="text-[10px] font-black text-gray-700 hover:text-blue-400 uppercase tracking-widest transition-colors">← Prev</button>
           <button onClick={() => setActiveCircleStep(Math.min(stepsCount - 1, activeCircleStep + 1))} className="text-[10px] font-black text-gray-700 hover:text-blue-400 uppercase tracking-widest transition-colors">Next →</button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="w-80 bg-[#0a0a0a] border-r border-gray-900 flex flex-col h-full shadow-2xl relative">
      
      {/* --- ВЕРХНЯЯ ПАНЕЛЬ (ARCHITECT / CODEX) --- */}
      <div className="p-6 border-b border-gray-900 bg-black/20">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-600 rounded-xl shadow-lg shadow-blue-600/20"><Dna size={18} className="text-white" /></div>
            <div>
              <h2 className="text-xs font-black uppercase tracking-tighter text-white">Story Architect</h2>
              <p className="text-[9px] text-gray-600 font-bold uppercase tracking-widest italic">Fractal Engine v2</p>
            </div>
          </div>
          <button onClick={onReset} className="text-gray-700 hover:text-red-500 transition-colors"><Settings size={14} /></button>
        </div>

        <div className="flex bg-gray-950 p-1 rounded-xl border border-gray-900">
          <button 
            onClick={() => setMainTab('architect')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-[10px] font-black transition-all ${mainTab === 'architect' ? 'bg-gray-800 text-blue-400 shadow-lg' : 'text-gray-600'}`}
          >
            <Sparkles size={14} /> ARCHITECT
          </button>
          <button 
            onClick={() => setMainTab('codex')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-[10px] font-black transition-all ${mainTab === 'codex' ? 'bg-gray-800 text-blue-400 shadow-lg' : 'text-gray-600'}`}
          >
            <Users size={14} /> CODEX
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex flex-col">
        
        {/* --- ВКЛАДКА ARCHITECT --- */}
        {mainTab === 'architect' && (
          <div className="flex-1 flex flex-col overflow-hidden p-6 animate-in fade-in duration-500">
            {/* Под-вкладки (Core, Global, Acts, Chaps) */}
            <div className="flex bg-gray-950 p-1 rounded-xl border border-gray-900 mb-6 shrink-0">
              {[
                { id: 'step0_core', icon: Disc, label: 'Core' },
                { id: 'step1_global', icon: Disc, label: 'Global' },
                { id: 'step2_acts', icon: Layers, label: 'Acts' },
                { id: 'step4_chapters', icon: BookOpen, label: 'Chaps' },
              ].map((step) => (
                <button
                  key={step.id}
                  onClick={() => { setArchStep(step.id as ArchitectStep); setActiveCircleStep(0); }}
                  className={`flex-1 flex flex-col items-center gap-1 py-2 rounded-lg transition-all ${
                    archStep === step.id ? 'bg-gray-800 text-blue-400 shadow-md' : 'text-gray-600 hover:text-gray-400'
                  }`}
                >
                  <step.icon size={14} />
                  <span className="text-[8px] font-black uppercase tracking-tighter">{step.label}</span>
                </button>
              ))}
            </div>

            {/* КОНТЕНТ ШАГОВ АРХИТЕКТОРА */}
            <div className="flex-1 flex flex-col min-h-0">
              {archStep === 'step0_core' && renderStepEditor(
                ['Philosophy', 'Emotional', 'Physical', 'Character Arc'][activeCircleStep],
                'Core Story Pillars',
                [bible.conflicts.philosophical, bible.conflicts.emotional, bible.conflicts.physical, bible.characterArc][activeCircleStep],
                (val) => {
                  const keys: (keyof CoreConflicts)[] = ['philosophical', 'emotional', 'physical'];
                  if (activeCircleStep < 3) {
                    onUpdate({ ...bible, conflicts: { ...bible.conflicts, [keys[activeCircleStep]]: val } });
                  } else {
                    onUpdate({ ...bible, characterArc: val });
                  }
                },
                4,
                'core'
              )}

              {archStep === 'step1_global' && renderStepEditor(
                circleLabels[activeCircleStep],
                circleDescs[activeCircleStep],
                bible.globalCircle[circleKeys[activeCircleStep]],
                (val) => onUpdate({ ...bible, globalCircle: updateCircle(bible.globalCircle, circleKeys[activeCircleStep], val) }),
                8,
                'global'
              )}

              {archStep === 'step2_acts' && (
                <div className="flex-1 flex flex-col min-h-0">
                  <div className="flex gap-1 p-1 bg-gray-950 rounded-lg shrink-0 mb-4 border border-gray-900">
                    {[1,2,3,4].map(i => (
                      <button key={i} onClick={() => setSelectedActIndex(i-1)} className={`flex-1 py-1.5 rounded text-[9px] font-black transition-all ${selectedActIndex === i-1 ? 'bg-blue-600 text-white shadow-lg' : 'text-gray-600'}`}>ACT {i}</button>
                    ))}
                  </div>
                  {renderStepEditor(
                    circleLabels[activeCircleStep],
                    `Act ${selectedActIndex + 1}: ${circleDescs[activeCircleStep]}`,
                    bible.acts[selectedActIndex].circle[circleKeys[activeCircleStep]],
                    (val) => {
                      const acts = [...bible.acts];
                      acts[selectedActIndex].circle = updateCircle(acts[selectedActIndex].circle, circleKeys[activeCircleStep], val);
                      onUpdate({ ...bible, acts });
                    },
                    8,
                    'act'
                  )}
                </div>
              )}

              {archStep === 'step4_chapters' && (
                <div className="flex flex-col h-full animate-in fade-in duration-500">
                  
                  {/* 🚀 ШАГ 5: ГЕНЕРАЦИЯ ВСЕГО АУТЛАЙНА */}
                  <div className="mb-6 shrink-0">
                    <button 
                      onClick={() => onArchitectAction('outline')}
                      disabled={isWorking}
                      className="w-full flex flex-col items-center justify-center gap-1 py-4 bg-gradient-to-br from-indigo-600 to-blue-700 hover:from-indigo-500 hover:to-blue-600 disabled:opacity-50 text-white rounded-2xl transition-all shadow-xl shadow-blue-900/20 group"
                    >
                      <div className="flex items-center gap-2">
                        {isWorking ? <Loader2 size={16} className="animate-spin" /> : <Layers size={16} className="group-hover:rotate-12 transition-transform" />}
                        <span className="text-[10px] font-black uppercase tracking-[0.1em]">Generate 16-Chapter Outline</span>
                      </div>
                      <span className="text-[8px] font-medium text-blue-200 uppercase opacity-70">Step 5: Full Story Breakdown</span>
                    </button>
                  </div>

                  <div className="h-px bg-gray-900 w-full mb-6" />

                  <label className="text-[9px] font-black text-gray-600 uppercase mb-2 ml-1">Step 6: Select Chapter to Edit</label>
                  
                  {/* ВЫПАДАЮЩЕЕ МЕНЮ (Dropdown) */}
                  <div className="relative mb-6 shrink-0">
                    <select 
                      className="w-full bg-gray-950 border border-gray-800 rounded-xl p-3 text-xs font-black text-blue-400 outline-none cursor-pointer appearance-none hover:border-blue-500/50 transition-all shadow-inner" 
                      value={activeChapterId || ''} 
                      onChange={(e) => onSelectChapter(e.target.value)}
                    >
                      {bible.acts.flatMap(a => a.chapters).map(ch => (
                        <option key={ch.id} value={ch.id} className="bg-gray-900 text-white">
                          CH {ch.order_index || ch.order}: {(ch.title || 'Untitled').toUpperCase()}
                        </option>
                      ))}
                    </select>
                    <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-blue-500">
                      <ChevronDown size={14} />
                    </div>
                  </div>

                  {/* СЛАЙДЕР КРУГА ГЛАВЫ */}
                  <div className="flex-1 flex flex-col min-h-0">
                    {(() => {
                      const ch = bible.acts.flatMap(a => a.chapters).find(c => c.id === activeChapterId);
                      return ch ? renderStepEditor(
                        circleLabels[activeCircleStep],
                        `CH ${ch.order_index || ch.order}: ${circleDescs[activeCircleStep]}`,
                        ch.circle[circleKeys[activeCircleStep]],
                        (val) => {
                          const acts = bible.acts.map(act => ({
                            ...act, 
                            chapters: act.chapters.map(c => c.id === activeChapterId ? { ...c, circle: updateCircle(c.circle, circleKeys[activeCircleStep], val) } : c)
                          }));
                          onUpdate({ ...bible, acts });
                        },
                        8,
                        'chapter'
                      ) : (
                        <div className="flex-1 flex flex-col items-center justify-center text-gray-800 border-2 border-dashed border-gray-900 rounded-[2rem] p-6 text-center">
                          <BookOpen size={32} className="mb-4 opacity-20" />
                          <p className="text-[10px] font-black uppercase tracking-widest">Initialize outline or select a chapter</p>
                        </div>
                      );
                    })()}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* --- ВКЛАДКА CODEX (ВОССТАНОВЛЕНО) --- */}
        {mainTab === 'codex' && (
          <div className="flex-1 flex flex-col overflow-hidden p-6 animate-in slide-in-from-right-4 duration-500">
            {/* Переключатель Персонажи / Локации */}
            <div className="flex gap-2 p-1 bg-gray-950 rounded-xl border border-gray-900 mb-6 shrink-0">
              <button 
                onClick={() => setCodexTab('chars')}
                className={`flex-1 py-2 rounded-lg text-[10px] font-black transition-all ${codexTab === 'chars' ? 'bg-gray-800 text-white' : 'text-gray-600'}`}
              >
                CHARACTERS
              </button>
              <button 
                onClick={() => setCodexTab('locs')}
                className={`flex-1 py-2 rounded-lg text-[10px] font-black transition-all ${codexTab === 'locs' ? 'bg-gray-800 text-white' : 'text-gray-600'}`}
              >
                LOCATIONS
              </button>
            </div>

            {/* Список элементов Кодекса */}
            <div className="flex-1 overflow-y-auto custom-scrollbar pr-1 space-y-4">
              <button 
                onClick={() => {
                  const newItem: Partial<CodexItem> = { 
                    id: crypto.randomUUID(), 
                    type: codexTab === 'chars' ? 'character' : 'location',
                    name: `New ${codexTab === 'chars' ? 'Character' : 'Location'}`, 
                    description: '', 
                    metadata: {} 
                  };
                  onUpdate({ 
                    ...bible, 
                    [codexTab === 'chars' ? 'characters' : 'locations']: [...(bible[codexTab === 'chars' ? 'characters' : 'locations'] || []), newItem] 
                  });
                }}
                className="w-full py-3 border-2 border-dashed border-gray-800 rounded-2xl text-gray-700 hover:text-blue-500 hover:border-blue-500/50 transition-all text-[10px] font-black uppercase tracking-widest flex items-center justify-center gap-2"
              >
                <Plus size={14} /> Add {codexTab === 'chars' ? 'Character' : 'Location'}
              </button>

              {(codexTab === 'chars' ? bible.characters : bible.locations)?.map(item => (
                <div key={item.id} className="p-4 bg-gray-950 border border-gray-800 rounded-2xl space-y-3 group hover:border-gray-700 transition-all shadow-inner">
                  <div className="flex justify-between items-center">
                    <input 
                      className="bg-transparent text-sm font-bold text-white focus:outline-none w-full"
                      value={item.name}
                      onChange={(e) => {
                        const list = codexTab === 'chars' ? 'characters' : 'locations';
                        onUpdate({ ...bible, [list]: bible[list].map(i => i.id === item.id ? { ...i, name: e.target.value } : i) });
                      }}
                    />
                    <button 
                      onClick={() => {
                        const list = codexTab === 'chars' ? 'characters' : 'locations';
                        onUpdate({ ...bible, [list]: bible[list].filter(i => i.id !== item.id) });
                      }} 
                      className="text-gray-800 hover:text-red-500 transition-colors"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <textarea 
                    className="w-full bg-transparent text-xs text-gray-500 focus:text-gray-200 outline-none resize-none h-20 leading-relaxed custom-scrollbar"
                    placeholder="Describe traits, goals, or sensory details..."
                    value={item.description}
                    onChange={(e) => {
                      const list = codexTab === 'chars' ? 'characters' : 'locations';
                      onUpdate({ ...bible, [list]: bible[list].map(i => i.id === item.id ? { ...i, description: e.target.value } : i) });
                    }}
                  />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* API ENGINE STATUS FOOTER */}
      <div className={`p-4 border-t border-gray-900 bg-black/50 backdrop-blur-md flex items-center gap-2 text-[9px] font-bold uppercase tracking-widest ${hasApiKey ? 'text-blue-900' : 'text-red-900'}`}>
        <Sparkles size={10} className={hasApiKey ? 'animate-pulse' : ''} />
        {hasApiKey ? 'Fractal Engine: Active (Gemini 3)' : 'Fractal Engine: Offline'}
      </div>
    </div>
  );
};