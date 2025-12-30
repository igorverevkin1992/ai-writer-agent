'use client';

import React from 'react';
import { Bible, Chapter } from '../types/types';
import { X, BookOpen, Zap, FileText, CheckCircle2 } from 'lucide-react';

interface StoryMapProps {
  bible: Bible;
  onSelectChapter: (id: string) => void;
  onClose: () => void;
}

export const StoryMap: React.FC<StoryMapProps> = ({ bible, onSelectChapter, onClose }) => {
  const allChapters = bible.acts.flatMap(act => act.chapters);

  return (
    <div className="fixed inset-0 z-[100] bg-[#050505]/95 backdrop-blur-xl animate-in fade-in duration-300 flex flex-col">
      {/* Header */}
      <div className="p-8 flex justify-between items-center border-b border-gray-900">
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tighter text-white">Fractal Story Map</h2>
          <p className="text-xs text-gray-500 font-bold uppercase tracking-widest mt-1">
            Visualizing 16 Chapters • 4 Acts
          </p>
        </div>
        <button 
          onClick={onClose}
          className="p-3 bg-gray-900 hover:bg-red-900/50 text-gray-400 hover:text-white rounded-full transition-all"
        >
          <X size={24} />
        </button>
      </div>

      {/* Map Content */}
      <div className="flex-1 overflow-hidden flex items-center justify-center p-10 relative">
        
        {/* Центральный логотип/инфо */}
        <div className="absolute z-10 text-center pointer-events-none">
          <div className="w-32 h-32 rounded-full bg-blue-600/10 border border-blue-500/20 flex items-center justify-center mb-4 mx-auto blur-sm absolute -inset-2 animate-pulse" />
          <div className="relative">
            <h3 className="text-4xl font-black text-white leading-none">16</h3>
            <p className="text-[10px] font-black text-blue-500 uppercase tracking-widest mt-2">Steps of Glory</p>
          </div>
        </div>

        {/* Сетка глав (Grid style for clarity, though arranged in "Acts") */}
        <div className="grid grid-cols-4 gap-8 max-w-6xl w-full">
          {bible.acts.map((act, actIdx) => (
            <div key={act.id} className="space-y-4">
              <div className="flex items-center gap-2 mb-6 border-b border-gray-800 pb-2">
                <span className="text-[10px] font-black bg-blue-600 text-white px-2 py-0.5 rounded">ACT {act.order}</span>
                <span className="text-[10px] font-black text-gray-500 uppercase tracking-widest">Foundation</span>
              </div>
              
              <div className="grid grid-cols-1 gap-3">
                {act.chapters.map((ch) => {
                  const hasContent = ch.content && ch.content.length > 50;
                  const hasBeatSheet = ch.beatSheet && ch.beatSheet.length > 20;

                  return (
                    <div 
                      key={ch.id}
                      onClick={() => {
                        onSelectChapter(ch.id);
                        onClose();
                      }}
                      className={`group p-4 rounded-2xl border transition-all cursor-pointer relative overflow-hidden ${
                        hasContent 
                          ? 'bg-blue-600/10 border-blue-500/50 shadow-lg shadow-blue-900/10' 
                          : 'bg-gray-900/40 border-gray-800 hover:border-gray-600'
                      }`}
                    >
                      <div className="flex justify-between items-start mb-2">
                        <span className={`text-[9px] font-black uppercase ${hasContent ? 'text-blue-400' : 'text-gray-600'}`}>
                          Chapter {ch.order}
                        </span>
                        <div className="flex gap-1">
                          {hasBeatSheet && <Zap size={10} className="text-amber-500" />}
                          {hasContent && <CheckCircle2 size={10} className="text-green-500" />}
                        </div>
                      </div>
                      
                      <h4 className="text-sm font-bold text-gray-200 line-clamp-1 group-hover:text-white transition-colors">
                        {ch.title || "Untitled Chapter"}
                      </h4>
                      
                      <p className="text-[10px] text-gray-500 mt-2 line-clamp-2 leading-relaxed">
                        {ch.circle.step1_you || "No structural data..."}
                      </p>

                      {/* Progress Bar Mini */}
                      <div className="absolute bottom-0 left-0 h-1 bg-blue-600 transition-all duration-500" style={{ width: hasContent ? '100%' : hasBeatSheet ? '30%' : '0%' }} />
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};