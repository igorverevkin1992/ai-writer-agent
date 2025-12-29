'use client'; // Обязательно для Next.js, так как используем useState

import React, { useState } from 'react';
import { AgentStatus, ContinuityError, AgentType } from '../types/types';
import { Sparkles, PenTool, Search, Wand2, Image as ImageIcon, Loader2 } from 'lucide-react'; // Профессиональные иконки

interface AgentSidebarProps {
  status: AgentStatus;
  continuityErrors: ContinuityError[];
  onAction: (type: AgentType, input?: string) => void;
  plan: string;
  setPlan: (plan: string) => void;
}

export const AgentSidebar: React.FC<AgentSidebarProps> = ({ 
  status, 
  continuityErrors, 
  onAction,
  plan,
  setPlan
}) => {
  const [activeTab, setActiveTab] = useState<AgentType>('planner');
  const [plannerInput, setPlannerInput] = useState('');
  const [editorInput, setEditorInput] = useState('');

  const tabs = [
    { id: 'planner' as AgentType, label: 'PLANN', icon: Sparkles },
    { id: 'writer' as AgentType, label: 'WRITE', icon: PenTool },
    { id: 'continuity' as AgentType, label: 'CONTI', icon: Search },
    { id: 'editor' as AgentType, label: 'EDITO', icon: Wand2 },
    { id: 'visualizer' as AgentType, label: 'VISUA', icon: ImageIcon },
  ];

  // Общий стиль для всех полей ввода
  const textAreaStyle = "w-full p-3 bg-gray-800 text-gray-100 border border-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none resize-none placeholder-gray-500 text-sm leading-relaxed transition-all";
  
  // Общий стиль для областей только для чтения
  const readOnlyStyle = "w-full h-64 p-3 bg-gray-800 text-gray-300 border border-gray-700 rounded-lg overflow-y-auto text-sm whitespace-pre-wrap font-mono custom-scrollbar";

  return (
    <div className="w-96 bg-gray-900 border-l border-gray-800 flex flex-col h-full shadow-2xl z-10">
      
      {/* --- ТАБЫ (ВЕРХНЯЯ ПАНЕЛЬ) --- */}
      <div className="flex border-b border-gray-800 bg-gray-900/50 backdrop-blur-md">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex-1 py-4 flex flex-col items-center gap-1 text-[10px] font-bold tracking-widest transition-all ${
              activeTab === id 
                ? 'bg-gray-800 text-blue-400 border-b-2 border-blue-500 shadow-[inset_0_-2px_0_rgba(59,130,246,0.5)]' 
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/30'
            }`}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>

      <div className="p-6 flex-1 overflow-y-auto custom-scrollbar">
        
        {/* --- СТАТУС АГЕНТА --- */}
        <div className="mb-8 p-4 rounded-xl bg-gradient-to-br from-gray-800 to-gray-900 border border-gray-700 shadow-inner">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-black text-gray-400 uppercase tracking-widest flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${status.isWorking ? 'bg-blue-500 animate-pulse' : 'bg-green-500'}`} />
              Agent: <span className="text-white">{activeTab}</span>
            </h3>
          </div>
          <p className="text-[11px] text-gray-500 font-medium">
            {activeTab === 'planner' && "Building scene beats using gemini-3-flash-preview..."}
            {activeTab === 'writer' && "Generating prose draft from the current plan..."}
            {activeTab === 'continuity' && "Checking scene against Project Bible facts..."}
            {activeTab === 'editor' && "Applying stylistic refinements to your text..."}
            {activeTab === 'visualizer' && "Creating concept art based on scene metadata..."}
          </p>
        </div>

        {/* --- КОНТЕНТ ВКЛАДОК --- */}

        {/* PLANNER */}
        {activeTab === 'planner' && (
          <div className="space-y-4">
            <div>
              <label className="block text-[10px] font-black text-gray-500 uppercase mb-3 tracking-widest">Scene Idea / Prompt</label>
              <textarea
                className={`${textAreaStyle} h-40`}
                placeholder="What happens in this scene? Gemini-3 will plan the beats..."
                value={plannerInput}
                onChange={(e) => setPlannerInput(e.target.value)}
              />
            </div>
            
            <button
              onClick={() => onAction('planner', plannerInput)}
              disabled={status.isWorking}
              className="w-full py-4 bg-blue-600 hover:bg-blue-500 text-white font-black rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-blue-900/40 flex items-center justify-center gap-2 uppercase text-xs tracking-widest"
            >
              {status.isWorking ? <Loader2 className="animate-spin" size={16} /> : 'Generate Beat Sheet'}
            </button>

            {plan && (
              <div className="mt-8 pt-8 border-t border-gray-800">
                <label className="block text-[10px] font-black text-blue-400 uppercase mb-3 tracking-widest">Generated Plan</label>
                <textarea
                    className={`${readOnlyStyle} h-80 focus:ring-1 focus:ring-blue-500 focus:outline-none`}
                    value={plan}
                    onChange={(e) => setPlan(e.target.value)}
                />
              </div>
            )}
          </div>
        )}

        {/* WRITER */}
        {activeTab === 'writer' && (
          <div className="space-y-4">
            <label className="block text-[10px] font-black text-gray-500 uppercase mb-3 tracking-widest">Active Beat Sheet</label>
            <div className={readOnlyStyle}>
              {plan || <span className="text-gray-600 italic">No plan detected. Use Planner first.</span>}
            </div>
            <button
              onClick={() => onAction('writer')}
              disabled={status.isWorking || !plan}
              className="w-full py-4 bg-indigo-600 hover:bg-indigo-500 text-white font-black rounded-xl transition-all disabled:opacity-50 flex items-center justify-center gap-2 uppercase text-xs tracking-widest"
            >
              {status.isWorking ? <Loader2 className="animate-spin" size={16} /> : 'Write Scene Draft'}
            </button>
          </div>
        )}

        {/* CONTINUITY */}
        {activeTab === 'continuity' && (
          <div className="space-y-4">
            <button
              onClick={() => onAction('continuity')}
              disabled={status.isWorking}
              className="w-full py-4 bg-purple-600 hover:bg-purple-500 text-white font-black rounded-xl transition-all disabled:opacity-50 flex items-center justify-center gap-2 uppercase text-xs tracking-widest"
            >
              {status.isWorking ? <Loader2 className="animate-spin" size={16} /> : 'Scan For Errors'}
            </button>

            {continuityErrors.length > 0 ? (
              <div className="space-y-3">
                {continuityErrors.map((err, i) => (
                  <div key={i} className="p-4 bg-red-950/30 border border-red-900/50 rounded-xl">
                    <span className="text-[10px] font-black text-red-400 uppercase">{err.type}</span>
                    <p className="text-sm text-gray-200 mt-1 leading-snug">{err.description}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-10 opacity-30">
                <Search size={40} className="mx-auto mb-2" />
                <p className="text-xs">No errors detected</p>
              </div>
            )}
          </div>
        )}

        {/* EDITOR */}
        {activeTab === 'editor' && (
          <div className="space-y-4">
            <textarea
              className={`${textAreaStyle} h-32`}
              placeholder="Give editing instructions (e.g. 'Make it darker', 'Add more dialogue')..."
              value={editorInput}
              onChange={(e) => setEditorInput(e.target.value)}
            />
            <button
              onClick={() => onAction('editor', editorInput)}
              disabled={status.isWorking}
              className="w-full py-4 bg-cyan-600 hover:bg-cyan-500 text-white font-black rounded-xl transition-all disabled:opacity-50 flex items-center justify-center gap-2 uppercase text-xs tracking-widest"
            >
              {status.isWorking ? <Loader2 className="animate-spin" size={16} /> : 'Refine Prose'}
            </button>
          </div>
        )}

        {/* VISUALIZER */}
        {activeTab === 'visualizer' && (
          <div className="text-center py-10">
            <button
              onClick={() => onAction('visualizer')}
              disabled={status.isWorking}
              className="w-full py-4 bg-pink-600 hover:bg-pink-500 text-white font-black rounded-xl transition-all disabled:opacity-50 flex items-center justify-center gap-2 uppercase text-xs tracking-widest"
            >
              {status.isWorking ? <Loader2 className="animate-spin" size={16} /> : 'Generate Concept Art'}
            </button>
            <p className="text-[10px] text-gray-600 mt-4 uppercase tracking-tighter">Powered by gemini-2.5-flash-image</p>
          </div>
        )}

      </div>
    </div>
  );
};