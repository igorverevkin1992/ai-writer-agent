'use client';

import dynamic from 'next/dynamic';
import { useState, useEffect } from 'react';

// Загружаем основной код приложения динамически только на клиенте
const MainApp = dynamic(() => import('./main-app'), { 
  ssr: false,
  loading: () => (
    <div className="h-screen w-screen bg-[#050505] flex flex-col items-center justify-center gap-4">
      <div className="w-12 h-12 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
      <div className="text-blue-500 font-black tracking-widest text-xs uppercase">
        Initializing Engine...
      </div>
    </div>
  )
});

export default function Page() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return <MainApp />;
}