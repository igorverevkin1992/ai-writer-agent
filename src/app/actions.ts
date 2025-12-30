'use server'

// 1. Правильный импорт из официального пакета
import { GoogleGenerativeAI } from "@google/generative-ai";
import { supabase } from "@/lib/supabase";

// ВАШИ МОДЕЛИ (БЕЗ ИЗМЕНЕНИЙ)
const TEXT_MODEL = "gemini-3-flash-preview";

// Функция очистки JSON
const cleanJson = (text: string) => {
  try {
    const firstBrace = text.indexOf('{');
    const lastBrace = text.lastIndexOf('}');
    if (firstBrace === -1 || lastBrace === -1) return "{}";
    return text.substring(firstBrace, lastBrace + 1);
  } catch (e) {
    return "{}";
  }
};

// 2. Универсальная функция получения модели
async function getGenModel(instruction: string) {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) throw new Error("GEMINI_API_KEY is missing in .env.local");

  // Создаем экземпляр строго по документации Google 2025
  const genAI = new GoogleGenerativeAI(apiKey);
  
  return genAI.getGenerativeModel({
    model: TEXT_MODEL,
    systemInstruction: instruction,
    generationConfig: { 
      responseMimeType: "application/json",
      temperature: 0.7 
    }
  });
}

export async function runArchitectAgent(level: string, context: string, prompt: string) {
  try {
    const instruction = `You are a professional Story Architect. 
    Your goal is to build a fractal story structure. 
    Return ONLY a JSON object with keys: step1_you, step2_need, step3_go, step4_search, step5_find, step6_take, step7_return, step8_change.`;
    
    const model = await getGenModel(instruction);

    const fullPrompt = `CONTEXT: ${context}\nTASK: ${prompt} for level ${level}`;
    const result = await model.generateContent(fullPrompt);
    const rawText = result.response.text();

    console.log(`--- AI RESPONSE (${level}) ---`, rawText);

    return { success: true, data: JSON.parse(cleanJson(rawText)) };

    } catch (error: any) {
        // Если это ошибка лимита Google
        if (error.status === 429 || error.message?.includes('429')) {
          return { 
            success: false, 
            error: "QUOTA_EXCEEDED", 
            message: "Google Gemini limit reached. Please wait 30-60 seconds." 
          };
        }
        
        console.error("SERVER ERROR:", error.message);
        return { success: false, error: "SERVER_ERROR", message: error.message };
      }
}

// Функции для остальных агентов
export async function generateBeatSheet(fractalContext: string, idea: string) {
  try {
    const model = await getGenModel("You are the PLANNER agent. Create a detailed Beat Sheet.");
    const result = await model.generateContent(`CONTEXT: ${fractalContext}\nIDEA: ${idea}`);
    return { success: true, data: result.response.text() };
  } catch (error: any) {
        // Если это ошибка лимита Google
        if (error.status === 429 || error.message?.includes('429')) {
          return { 
            success: false, 
            error: "QUOTA_EXCEEDED", 
            message: "Google Gemini limit reached. Please wait 30-60 seconds." 
          };
        }
        
        console.error("SERVER ERROR:", error.message);
        return { success: false, error: "SERVER_ERROR", message: error.message };
    }
}

export async function generateSceneProse(fractalContext: string, beatSheet: string) {
  try {
    const model = await getGenModel("You are the WRITER agent. Write vivid fiction prose.");
    const result = await model.generateContent(`CONTEXT: ${fractalContext}\nBEAT SHEET: ${beatSheet}`);
    return { success: true, data: result.response.text() };
  } catch (error: any) {
        // Если это ошибка лимита Google
        if (error.status === 429 || error.message?.includes('429')) {
          return { 
            success: false, 
            error: "QUOTA_EXCEEDED", 
            message: "Google Gemini limit reached. Please wait 30-60 seconds." 
          };
        }
        
        console.error("SERVER ERROR:", error.message);
        return { success: false, error: "SERVER_ERROR", message: error.message };
    }
}

export async function runChroniclerAgent(chapterText: string, currentCodex: string) {
  try {
    const model = await getGenModel("You are the CHRONICLER. Return JSON array of world changes.");
    const result = await model.generateContent(`CODEX: ${currentCodex}\nTEXT: ${chapterText}`);
    return { success: true, data: JSON.parse(cleanJson(result.response.text())) };
  } catch (error: any) {
      // Если это ошибка лимита Google
      if (error.status === 429 || error.message?.includes('429')) {
        return { 
          success: false, 
          error: "QUOTA_EXCEEDED", 
          message: "Google Gemini limit reached. Please wait 30-60 seconds." 
        };
      }
      
      console.error("SERVER ERROR:", error.message);
      return { success: false, error: "SERVER_ERROR", message: error.message };
    }
}

export async function checkContinuity(bibleContext: string, sceneText: string) {
  try {
    const model = await getGenModel("You are the CONTINUITY agent. Find contradictions.");
    const result = await model.generateContent(`BIBLE: ${bibleContext}\nTEXT: ${sceneText}`);
    return { success: true, data: result.response.text() };
  } catch (error: any) {
        // Если это ошибка лимита Google
        if (error.status === 429 || error.message?.includes('429')) {
          return { 
            success: false, 
            error: "QUOTA_EXCEEDED", 
            message: "Google Gemini limit reached. Please wait 30-60 seconds." 
          };
        }
        
        console.error("SERVER ERROR:", error.message);
        return { success: false, error: "SERVER_ERROR", message: error.message };
    }
}

export async function saveChapterAction(chapterId: string, updates: any) {
  const { error } = await supabase.from('chapters').update(updates).eq('id', chapterId);
  return { success: !error, error };
}

// --- ГЕНЕРАТОР ПОЛНОГО АУТЛАЙНА (16 ГЛАВ) ---
export async function generateFullOutline(context: string) {
  try {
    const instruction = `You are the MASTER ARCHITECT. 
    Based on the global story circle and acts, create a high-level roadmap for 16 chapters.
    Return ONLY a JSON object with a "chapters" array. 
    Each item MUST have: "order" (1-16), "title" (short, catchy), and "goal" (one sentence of what happens).
    Example: { "chapters": [{ "order": 1, "title": "The Awakening", "goal": "Hero realizes their life is a lie." }, ...] }`;
    
    const model = await getGenModel(instruction, true); // true включает JSON-режим
    const result = await model.generateContent(`CONTEXT: ${context}`);
    const response = await result.response;
    const data = JSON.parse(cleanJson(response.text()));
    
    return { success: true, data: data.chapters };
  } catch (error: any) {
        // Если это ошибка лимита Google
        if (error.status === 429 || error.message?.includes('429')) {
          return { 
            success: false, 
            error: "QUOTA_EXCEEDED", 
            message: "Google Gemini limit reached. Please wait 30-60 seconds." 
          };
        }
        
        console.error("SERVER ERROR:", error.message);
        return { success: false, error: "SERVER_ERROR", message: error.message };
  }
}