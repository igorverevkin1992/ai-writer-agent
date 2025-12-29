'use client';

import React, { useState } from 'react';
import { ProjectMeta } from '../types/types';
import { 
  FolderPlus, 
  Search, 
  Clock, 
  Trash2, 
  ChevronRight, 
  BookOpen,
  LayoutGrid,
  List as ListIcon,
  Plus,
  Sparkles
} from 'lucide-react';

interface ProjectHubProps {
  projects: ProjectMeta[];
  onSelect: (projectId: string) => void;
  onCreate: (name: string) => void;
  onDelete: (projectId: string) => void;
}

export const ProjectHub: React.FC<ProjectHubProps> = ({ 
  projects, 
  onSelect, 
  onCreate, 
  onDelete 
}) => {
  const [isCreating, setIsCreating] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredProjects = projects.filter(p => 
    p.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newProjectName.trim()) {
      onCreate(newProjectName);
      setNewProjectName('');
      setIsCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] text-gray-100 flex flex-col items-center font-sans selection:bg-blue-500/30">
      
      {/* --- ГРАДИЕНТНЫЙ ФОН --- */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-[25%] -left-[10%] w-[50%] h-[50%] bg-blue-600/10 blur-[120px] rounded-full" />
        <div className="absolute -bottom-[25%] -right-[10%] w-[50%] h-[50%] bg-purple-600/10 blur-[120px] rounded-full" />
      </div>

      <div className="max-w-6xl w-full px-6 py-12 z-10">
        
        {/* --- HEADER --- */}
        <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-16 gap-6">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <div className="bg-blue-600 p-2 rounded-xl shadow-lg shadow-blue-600/20">
                <Sparkles size={24} className="text-white" />
              </div>
              <h1 className="text-3xl font-black tracking-tighter uppercase italic">
                Writer's Agent <span className="text-blue-500">v2</span>
              </h1>
            </div>
            <p className="text-gray-500 text-sm font-medium tracking-wide">
              Powered by <span className="text-gray-300">gemini-3-flash-preview</span> • AI Orchestration
            </p>
          </div>

          <button 
            onClick={() => setIsCreating(true)}
            className="group flex items-center gap-2 px-5 py-3 bg-white text-black font-black text-xs uppercase tracking-widest rounded-full hover:bg-blue-500 hover:text-white transition-all active:scale-95 shadow-xl shadow-white/5"
          >
            <Plus size={16} />
            New Simulation
          </button>
        </header>

        {/* --- CONTROLS --- */}
        <div className="flex flex-col md:flex-row gap-4 mb-10 items-center">
          <div className="relative flex-1 w-full">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-600" size={18} />
            <input 
              type="text"
              placeholder="Search projects..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-gray-900/50 border border-gray-800 rounded-2xl py-3 pl-12 pr-4 text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500/50 outline-none transition-all backdrop-blur-sm"
            />
          </div>
          <div className="flex bg-gray-900/50 p-1 rounded-xl border border-gray-800 backdrop-blur-sm">
            <button className="p-2 text-blue-500 bg-gray-800 rounded-lg shadow-sm"><LayoutGrid size={18} /></button>
            <button className="p-2 text-gray-600 hover:text-gray-400"><ListIcon size={18} /></button>
          </div>
        </div>

        {/* --- CREATE FORM --- */}
        {isCreating && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-6">
            <form 
              onSubmit={handleCreateSubmit} 
              className="max-w-md w-full bg-gray-900 border border-gray-800 p-8 rounded-3xl shadow-2xl animate-in fade-in zoom-in duration-200"
            >
              <h2 className="text-2xl font-black uppercase tracking-tighter mb-6">Initialize New Project</h2>
              <div className="space-y-4">
                <div>
                  <label className="block text-[10px] font-black text-gray-500 uppercase tracking-widest mb-2">Project Name</label>
                  <input 
                    type="text" 
                    autoFocus
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    placeholder="Enter simulation title..."
                    className="w-full bg-gray-950 border border-gray-800 rounded-xl px-4 py-4 text-white focus:outline-none focus:border-blue-500 transition-all font-medium"
                  />
                </div>
                <div className="flex gap-3 pt-4">
                  <button 
                    type="submit" 
                    className="flex-1 py-4 bg-blue-600 hover:bg-blue-500 text-white font-black uppercase text-xs tracking-widest rounded-xl transition-all"
                  >
                    Create Project
                  </button>
                  <button 
                    type="button" 
                    onClick={() => setIsCreating(false)} 
                    className="flex-1 py-4 bg-gray-800 hover:bg-gray-700 text-gray-300 font-black uppercase text-xs tracking-widest rounded-xl transition-all"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </form>
          </div>
        )}

        {/* --- PROJECTS GRID --- */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredProjects.length === 0 && (
            <div className="col-span-full py-32 flex flex-col items-center justify-center border-2 border-dashed border-gray-900 rounded-[2rem] bg-gray-900/10">
              <FolderPlus size={48} className="text-gray-800 mb-4" />
              <p className="text-gray-500 font-medium">No projects found in the database.</p>
              <button onClick={() => setIsCreating(true)} className="text-blue-500 text-sm mt-2 hover:underline">Create your first one</button>
            </div>
          )}

          {filteredProjects.map(project => (
            <div 
              key={project.id} 
              onClick={() => onSelect(project.id)}
              className="group relative p-8 bg-gray-900/40 border border-gray-800/60 hover:border-blue-500/50 rounded-[2rem] cursor-pointer transition-all hover:shadow-2xl hover:shadow-blue-500/5 hover:-translate-y-1 backdrop-blur-sm flex flex-col h-64"
            >
              <div className="flex justify-between items-start mb-4">
                <div className="p-3 bg-blue-500/10 rounded-2xl group-hover:bg-blue-500/20 transition-colors">
                  <BookOpen size={20} className="text-blue-500" />
                </div>
                <button 
                  onClick={(e) => { 
                    e.stopPropagation(); 
                    if(confirm('Permanently delete this project?')) onDelete(project.id); 
                  }}
                  className="p-2 text-gray-700 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                >
                  <Trash2 size={16} />
                </button>
              </div>

              <h3 className="text-xl font-bold text-white mb-2 line-clamp-1 group-hover:text-blue-400 transition-colors">
                {project.name}
              </h3>
              
              <p className="text-sm text-gray-500 line-clamp-2 leading-relaxed flex-1">
                {project.summarySnippet || "System waiting for project data initialization..."}
              </p>

              <div className="flex justify-between items-center mt-6 pt-6 border-t border-gray-800/50">
                <div className="flex items-center gap-2 text-[10px] font-bold text-gray-600 uppercase tracking-tighter">
                  <Clock size={12} />
                  {new Date(project.lastModified).toLocaleDateString()}
                </div>
                <div className="flex items-center gap-1 text-[10px] font-black text-blue-500 uppercase tracking-widest opacity-0 group-hover:opacity-100 transition-all translate-x-2 group-hover:translate-x-0">
                  Open <ChevronRight size={14} />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};