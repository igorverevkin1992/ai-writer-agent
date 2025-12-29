'use client';

import React, { useState } from 'react';
import { Bible, Act, Chapter, StoryCircle, CoreConflicts } from '../types/types';
import { 
  Dna, 
  Disc, 
  Layers, 
  BookOpen, 
  Users, 
  MapPin, 
  ChevronRight, 
  ChevronDown,
  Info,
  Sparkles,
  Trash2,
  Plus
} from 'lucide-react';

interface BibleManagerProps {
  bible: Bible;
  onUpdate: (bible: Bible) => void;
  onArchitectAction: (level: 'global' | 'act' | 'chapter') => void; // Добавить
  isWorking: boolean; // Добавить
  onReset: () => void;
  hasApiKey: boolean;
}

type MainTab = 'architect' | 'codex';
type ArchitectStep = 'step0_core' | 'step1_global' | 'step2_acts' | 'step4_chapters';

export const BibleManager: React.FC<BibleManagerProps> = ({ bible, onUpdate, onArchitectAction, isWorking, onReset, hasApiKey }) => {
  const [mainTab, setMainTab] = useState<MainTab>('architect');
  const [archStep, setArchStep] = useState<ArchitectStep>('step0_core');
  const [selectedActIndex, setSelectedActIndex] = useState(0);
  const [selectedChapterId, setSelectedChapterId] = useState('ch-1');
  const [codexTab, setCodexTab] = useState<'chars' | 'locs'>('chars');

  // --- Хелперы обновления ---
  const updateConflicts = (key: keyof CoreConflicts, val: string) => {
    onUpdate({ ...bible, conflicts: { ...bible.conflicts, [key]: val } });
  };

  const updateGlobalCircle = (step: keyof StoryCircle, val: string) => {
    onUpdate({ ...bible, globalCircle: { ...bible.globalCircle, [step]: val } });
  };

  const updateActCircle = (actOrder: number, step: keyof StoryCircle, val: string) => {
    const newActs = bible.acts.map(a => 
      a.order === actOrder ? { ...a, circle: { ...a.circle, [step]: val } } : a
    );
    onUpdate({ ...bible, acts: newActs });
  };

  const updateChapterCircle = (chId: string, step: keyof StoryCircle, val: string) => {
    const newActs = bible.acts.map(act => ({
      ...act,
      chapters: act.chapters.map(ch => 
        ch.id === chId ? { ...ch, circle: { ...ch.circle, [step]: val } } : ch
      )
    }));
    onUpdate({ ...bible, acts: newActs });
  };

  // --- UI Компоненты ---

  const renderCircleEditor = (circle: StoryCircle, onChange: (step: keyof StoryCircle, val: string) => void, level: string) => {
    const steps: { key: keyof StoryCircle; label: string; desc: string }[] = [
      { key: 'step1_you', label: '1. YOU', desc: 'Zone of Comfort' },
      { key: 'step2_need', label: '2. NEED', desc: 'But they want something' },
      { key: 'step3_go', label: '3. GO', desc: 'Enter unfamiliar situation' },
      { key: 'step4_search', label: '4. SEARCH', desc: 'Adapt to it' },
      { key: 'step5_find', label: '5. FIND', desc: 'Get what they wanted' },
      { key: 'step6_take', label: '6. TAKE', desc: 'Pay a heavy price' },
      { key: 'step7_return', label: '7. RETURN', desc: 'To familiar situation' },
      { key: 'step8_change', label: '8. CHANGE', desc: 'Having changed' },
    ];

    return (
      <div className="space-y-3 mt-4">
        {/* --- ВОТ ЭТОТ БЛОК НУЖНО ВСТАВИТЬ СЮДА --- */}
        <div className="flex items-center justify-between mb-4">
          <p className="text-[10px] text-blue-500 font-black uppercase tracking-widest">
            Level: {level}
          </p>
          <button 
            onClick={() => onArchitectAction(level as any)}
            disabled={isWorking}
            className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-[9px] font-black text-white uppercase rounded-md transition-all disabled:opacity-50 shadow-lg shadow-blue-900/20"
          >
            {isWorking ? "Thinking..." : "AI Generate"}
          </button>
        </div>
        
        {steps.map((s) => (
          <div key={s.key} className="group">
            <label className="flex justify-between text-[9px] font-black text-gray-600 group-focus-within:text-blue-400 transition-colors uppercase mb-1">
              <span>{s.label}</span>
              <span className="opacity-0 group-focus-within:opacity-100 transition-opacity italic">{s.desc}</span>
            </label>
            <textarea
              className="w-full bg-gray-950 border border-gray-800 rounded-lg p-2 text-xs text-gray-200 focus:border-blue-500/50 outline-none resize-none h-14 transition-all"
              value={circle[s.key]}
              onChange={(e) => onChange(s.key, e.target.value)}
            />
          </div>
        ))}
      </div>
    );
  };

  const inputStyle = "w-full bg-gray-950 border border-gray-800 rounded-lg p-3 text-sm text-gray-100 focus:border-blue-500 outline-none transition-all placeholder:text-gray-800";
  const labelStyle = "block text-[10px] font-black text-gray-500 uppercase tracking-widest mb-2 mt-4";

  return (
    <div className="w-80 bg-[#0a0a0a] border-r border-gray-900 flex flex-col h-full shadow-2xl relative">
      
      {/* HEADER */}
      <div className="p-6 border-b border-gray-900">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-blue-600 rounded-xl shadow-lg shadow-blue-600/20">
            <Dna size={18} className="text-white" />
          </div>
          <div>
            <h2 className="text-xs font-black uppercase tracking-tighter text-white">Story Architect</h2>
            <p className="text-[9px] text-gray-600 font-bold uppercase tracking-widest">Method: Fractal Circle</p>
          </div>
        </div>

        {/* MAIN TABS */}
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

      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        
        {mainTab === 'architect' && (
          <div className="animate-in fade-in slide-in-from-left-4 duration-500">
            {/* STEPS NAVIGATION */}
            <div className="flex flex-col gap-2 mb-8">
              {[
                { id: 'step0_core', label: 'Step 0: Core Conflicts', icon: Disc },
                { id: 'step1_global', label: 'Step 1: Global Circle', icon: Disc },
                { id: 'step2_acts', label: 'Step 2: 4-Act Structure', icon: Layers },
                { id: 'step4_chapters', label: 'Step 3: 16 Chapters', icon: BookOpen },
              ].map((step) => (
                <button
                  key={step.id}
                  onClick={() => setArchStep(step.id as ArchitectStep)}
                  className={`flex items-center gap-3 p-3 rounded-xl border transition-all ${archStep === step.id ? 'bg-blue-600/10 border-blue-500/50 text-blue-400' : 'bg-transparent border-transparent text-gray-600 hover:text-gray-400'}`}
                >
                  <step.icon size={14} />
                  <span className="text-[10px] font-black uppercase tracking-widest">{step.label}</span>
                </button>
              ))}
            </div>

            {/* STEP 0: CONFLICTS */}
            {archStep === 'step0_core' && (
              <div className="space-y-4">
                <label className={labelStyle}>Philosophical Conflict</label>
                <input className={inputStyle} value={bible.conflicts.philosophical} onChange={(e) => updateConflicts('philosophical', e.target.value)} placeholder="Truth vs Lie..." />
                
                <label className={labelStyle}>Emotional Conflict</label>
                <input className={inputStyle} value={bible.conflicts.emotional} onChange={(e) => updateConflicts('emotional', e.target.value)} placeholder="Self-doubt vs Duty..." />
                
                <label className={labelStyle}>Physical Conflict</label>
                <input className={inputStyle} value={bible.conflicts.physical} onChange={(e) => updateConflicts('physical', e.target.value)} placeholder="Man vs Nature..." />

                <label className={labelStyle}>Character Arc</label>
                <textarea className={`${inputStyle} h-24`} value={bible.characterArc} onChange={(e) => onUpdate({...bible, characterArc: e.target.value})} placeholder="From a coward to a leader..." />
              </div>
            )}

            {/* STEP 1: GLOBAL CIRCLE */}
            {archStep === 'step1_global' && renderCircleEditor(bible.globalCircle, updateGlobalCircle, 'The Book')}

            {/* STEP 2: ACTS */}
            {archStep === 'step2_acts' && (
              <div className="space-y-6">
                <div className="flex gap-2 p-1 bg-gray-950 rounded-lg">
                  {[1,2,3,4].map(i => (
                    <button 
                      key={i} 
                      onClick={() => setSelectedActIndex(i-1)}
                      className={`flex-1 py-2 rounded text-[10px] font-black ${selectedActIndex === i-1 ? 'bg-blue-600 text-white' : 'text-gray-600'}`}
                    >
                      A{i}
                    </button>
                  ))}
                </div>
                {renderCircleEditor(bible.acts[selectedActIndex].circle, (step, val) => updateActCircle(selectedActIndex + 1, step, val), `Act ${selectedActIndex + 1}`)}
              </div>
            )}

            {/* STEP 3: CHAPTERS */}
            {archStep === 'step4_chapters' && (
              <div className="space-y-6">
                 <select 
                    className="w-full bg-gray-950 border border-gray-800 rounded-lg p-3 text-xs font-bold text-blue-400 outline-none"
                    value={selectedChapterId}
                    onChange={(e) => setSelectedChapterId(e.target.value)}
                 >
                    {bible.acts.flatMap(a => a.chapters).map(ch => (
                      <option key={ch.id} value={ch.id}>Chapter {ch.order}: {ch.title}</option>
                    ))}
                 </select>
                 {(() => {
                    const ch = bible.acts.flatMap(a => a.chapters).find(c => c.id === selectedChapterId);
                    return ch ? renderCircleEditor(ch.circle, (step, val) => updateChapterCircle(selectedChapterId, step, val), `Chapter ${ch.order}`) : null;
                 })()}
              </div>
            )}
          </div>
        )}

        {mainTab === 'codex' && (
  <div className="animate-in fade-in slide-in-from-right-4 duration-500 space-y-6">
    
    {/* Переключатель Персонажи / Локации */}
    <div className="flex gap-2 p-1 bg-gray-950 rounded-xl border border-gray-900 mb-6">
      <button 
        onClick={() => setCodexTab('chars')}
        className={`flex-1 py-2 rounded-lg text-[10px] font-bold transition-all ${codexTab === 'chars' ? 'bg-gray-800 text-white' : 'text-gray-600'}`}
      >
        CHARACTERS
      </button>
      <button 
        onClick={() => setCodexTab('locs')}
        className={`flex-1 py-2 rounded-lg text-[10px] font-bold transition-all ${codexTab === 'locs' ? 'bg-gray-800 text-white' : 'text-gray-600'}`}
      >
        LOCATIONS
      </button>
    </div>

    {/* СПИСОК ПЕРСОНАЖЕЙ */}
    {codexTab === 'chars' && (
      <div className="space-y-4">
        <button 
          onClick={() => {
            const newChar = { id: crypto.randomUUID(), name: 'New Character', description: '', traits: [], arcStatus: 'Active' };
            onUpdate({ ...bible, characters: [...(bible.characters || []), newChar] });
          }}
          className="w-full py-3 border-2 border-dashed border-gray-800 rounded-2xl text-gray-600 hover:text-blue-500 hover:border-blue-500/50 transition-all text-[10px] font-black uppercase tracking-widest flex items-center justify-center gap-2"
        >
          <Plus size={14} /> Add Character
        </button>

        {bible.characters?.map(char => (
          <div key={char.id} className="p-4 bg-gray-950 border border-gray-900 rounded-2xl space-y-3 group hover:border-gray-700 transition-all">
            <div className="flex justify-between items-center">
              <input 
                className="bg-transparent text-sm font-bold text-white focus:outline-none w-full"
                value={char.name}
                onChange={(e) => {
                  const updated = bible.characters.map(c => c.id === char.id ? { ...c, name: e.target.value } : c);
                  onUpdate({ ...bible, characters: updated });
                }}
              />
              <button 
                onClick={() => onUpdate({ ...bible, characters: bible.characters.filter(c => c.id !== char.id) })}
                className="text-gray-800 hover:text-red-500 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
            <textarea 
              className="w-full bg-transparent text-xs text-gray-500 focus:text-gray-300 outline-none resize-none h-20 leading-relaxed"
              placeholder="Appearance, goals, secrets..."
              value={char.description}
              onChange={(e) => {
                const updated = bible.characters.map(c => c.id === char.id ? { ...c, description: e.target.value } : c);
                onUpdate({ ...bible, characters: updated });
              }}
            />
          </div>
        ))}
      </div>
    )}

    {/* СПИСОК ЛОКАЦИЙ */}
    {codexTab === 'locs' && (
      <div className="space-y-4">
        <button 
          onClick={() => {
            const newLoc = { id: crypto.randomUUID(), name: 'New Location', description: '' };
            onUpdate({ ...bible, locations: [...(bible.locations || []), newLoc] });
          }}
          className="w-full py-3 border-2 border-dashed border-gray-800 rounded-2xl text-gray-600 hover:text-blue-500 hover:border-blue-500/50 transition-all text-[10px] font-black uppercase tracking-widest flex items-center justify-center gap-2"
        >
          <Plus size={14} /> Add Location
        </button>

        {bible.locations?.map(loc => (
          <div key={loc.id} className="p-4 bg-gray-950 border border-gray-900 rounded-2xl space-y-3 group hover:border-gray-700 transition-all">
            <div className="flex justify-between items-center">
              <input 
                className="bg-transparent text-sm font-bold text-white focus:outline-none w-full"
                value={loc.name}
                onChange={(e) => {
                  const updated = bible.locations.map(l => l.id === loc.id ? { ...l, name: e.target.value } : l);
                  onUpdate({ ...bible, locations: updated });
                }}
              />
              <button 
                onClick={() => onUpdate({ ...bible, locations: bible.locations.filter(l => l.id !== loc.id) })}
                className="text-gray-800 hover:text-red-500 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
            <textarea 
              className="w-full bg-transparent text-xs text-gray-500 focus:text-gray-300 outline-none resize-none h-20 leading-relaxed"
              placeholder="Vibe, key objects, sensory details..."
              value={loc.description}
              onChange={(e) => {
                const updated = bible.locations.map(l => l.id === loc.id ? { ...l, description: e.target.value } : l);
                onUpdate({ ...bible, locations: updated });
              }}
            />
          </div>
        ))}
      </div>
    )}
  </div>
)}
      </div>

      {/* FOOTER ENGINE STATUS */}
      <div className="p-4 border-t border-gray-900 bg-black/50 backdrop-blur-md">
        <div className="flex items-center gap-2 text-[9px] font-bold text-gray-700 uppercase tracking-widest">
          <Sparkles size={10} className="text-blue-950" />
          Powered by Gemini 3 Flash
        </div>
      </div>
    </div>
  );
};