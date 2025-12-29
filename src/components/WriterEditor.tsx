'use client';

import React, { useState, useEffect } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import Underline from '@tiptap/extension-underline';
import { 
  Type, 
  Bold, 
  Italic, 
  Maximize2, 
  Copy, 
  Check, 
  FileText, 
  Clapperboard,
  AlignLeft,
  BookOpen
} from 'lucide-react';

interface WriterEditorProps {
  content: string;
  onChange: (val: string) => void;
  title: string;
  onTitleChange: (val: string) => void;
  // ... остальные пропсы
}

export const WriterEditor: React.FC<WriterEditorProps> = ({
  content,
  onChange,
  title,
  onTitleChange,
  scenes,
  activeSceneId,
  onSelectScene,
  onAddScene,
  onDeleteScene,
}) => {
  const [editorMode, setEditorMode] = useState<'book' | 'script'>('book');
  const [isCopied, setIsCopied] = useState(false);
  const [isFocusMode, setIsFocusMode] = useState(false);

  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline, // Добавляем поддержку Ctrl+U
      Placeholder.configure({
        placeholder: editorMode === 'book' ? 'Once upon a time...' : 'INT. ROOM - DAY',
      }),
    ],
    immediatelyRender: false,
    content: content,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML());
    },
    // --- ГОРЯЧИЕ КЛАВИШИ ---
    editorProps: {
      handleKeyDown: (view, event) => {
        // Проверяем, нажата ли клавиша Ctrl (или Cmd на Mac)
        const isCtrl = event.ctrlKey || event.metaKey;

        if (isCtrl) {
          // --- РЕЖИМ BOOK (Word style) ---
          if (editorMode === 'book') {
            if (event.key === '0') { // Ctrl + 0: Обычный текст
              editor?.chain().focus().setParagraph().run();
              return true;
            }
            if (event.altKey && event.key === '1') { // Ctrl + Alt + 1: Заголовок 1
              editor?.chain().focus().toggleHeading({ level: 1 }).run();
              return true;
            }
          }

          // --- РЕЖИМ SCRIPT (Final Draft style) ---
          if (editorMode === 'script') {
            switch (event.key) {
              case '1': // Ctrl + 1: Заголовок сцены (Slugline)
                editor?.chain().focus().toggleHeading({ level: 1 }).run();
                return true;
              case '2': // Ctrl + 2: Действие (Обычный текст)
                editor?.chain().focus().setParagraph().run();
                return true;
              case '3': // Ctrl + 3: Персонаж (Мы имитируем это через Heading 2)
                editor?.chain().focus().toggleHeading({ level: 2 }).run();
                return true;
              case '4': // Ctrl + 4: Ремарка (Имитируем через Bullet List или спец. стиль)
                editor?.chain().focus().toggleBulletList().run();
                return true;
              case '5': // Ctrl + 5: Диалог (Мы имитируем это через Blockquote)
                editor?.chain().focus().toggleBlockquote().run();
                return true;
            }
          }
        }
        return false;
      },
      attributes: {
        class: `w-full h-full p-12 focus:outline-none min-h-[700px] transition-all duration-500 ${
          editorMode === 'book' 
            ? 'font-serif text-xl leading-relaxed prose-book' 
            : 'font-mono text-lg leading-tight prose-script'
        }`,
      },
    },
  });

  // Синхронизация при смене главы
  useEffect(() => {
    if (editor && content !== editor.getHTML()) {
      editor.commands.setContent(content);
    }
  }, [content, editor]);

  return (
    <div className="flex flex-col h-full bg-[#050505]">
      
      {/* --- SMART TOOLBAR --- */}
      <div className="flex items-center justify-between px-6 py-2 bg-gray-900/40 border-b border-gray-800 backdrop-blur-md">
        <div className="flex items-center gap-4">
          {/* Переключатель режимов */}
          <div className="flex bg-black p-1 rounded-lg border border-gray-800">
            <button 
              onClick={() => setEditorMode('book')}
              className={`flex items-center gap-2 px-3 py-1 rounded-md text-[10px] font-black uppercase transition-all ${editorMode === 'book' ? 'bg-gray-800 text-blue-400' : 'text-gray-600'}`}
            >
              <BookOpen size={12} /> Book
            </button>
            <button 
              onClick={() => setEditorMode('script')}
              className={`flex items-center gap-2 px-3 py-1 rounded-md text-[10px] font-black uppercase transition-all ${editorMode === 'script' ? 'bg-gray-800 text-blue-400' : 'text-gray-600'}`}
            >
              <Clapperboard size={12} /> Script
            </button>
          </div>

          <div className="h-4 w-px bg-gray-800" />
          
          {/* Стандартные инструменты */}
          <div className="flex items-center gap-1">
            <button onClick={() => editor?.chain().focus().toggleBold().run()} className="p-2 text-gray-500 hover:text-white"><Bold size={16} /></button>
            <button onClick={() => editor?.chain().focus().toggleItalic().run()} className="p-2 text-gray-500 hover:text-white"><Italic size={16} /></button>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button onClick={() => setIsFocusMode(!isFocusMode)} className={`p-2 transition-colors ${isFocusMode ? 'text-blue-500' : 'text-gray-600'}`}><Maximize2 size={16} /></button>
          <button onClick={() => {/* Copy logic */}} className="p-2 text-gray-600 hover:text-white"><Copy size={16} /></button>
        </div>
      </div>

      {/* --- PAGE AREA --- */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-10 bg-black/10">
        <div className={`mx-auto bg-[#080808] border border-gray-800/50 shadow-2xl transition-all duration-700 ${
          isFocusMode ? 'max-w-4xl' : 'max-w-3xl'
        }`}>
          {/* Поле заголовка */}
          <input
            type="text"
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            className="w-full bg-transparent px-12 pt-12 text-3xl font-black text-white focus:outline-none tracking-tighter uppercase"
            placeholder="Chapter Title"
          />
          
          {/* САМ РЕДАКТОР */}
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  );
};