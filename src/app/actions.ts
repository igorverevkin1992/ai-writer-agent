'use server'

import { GoogleGenAI } from "@google/genai";
import { StoryCircle } from "@/types/types";

const apiKey = process.env.GEMINI_API_KEY;
const genAI = new GoogleGenAI(apiKey || "");

// Твои модели (СТРОГО СОХРАНЕНЫ)
const TEXT_MODEL = "gemini-3-flash-preview";
const IMAGE_MODEL = "gemini-2.5-flash-image";

// Хелпер для очистки JSON ответов
const cleanJson = (text: string) => {
  return text.replace(/```json/g, "").replace(/```/g, "").trim();
};

// --- АГЕНТ-АРХИТЕКТ (ШАГИ 1-4) ---
// Этот агент генерирует 8 шагов круга для любого уровня
export async function runArchitectAgent(
  level: 'global' | 'act' | 'chapter',
  context: string,
  prompt: string
) {
  try {
    const model = genAI.getGenerativeModel({ 
      model: TEXT_MODEL,
      systemInstruction: `You are the MASTER ARCHITECT. You specialize in the Fractal Story Circle method (8 steps).
      Your task is to generate a perfectly balanced 8-step story circle for the ${level} level.
      
      The 8 steps MUST be:
      1. YOU (Zone of comfort)
      2. NEED (But they want something)
      3. GO (Enter unfamiliar situation)
      4. SEARCH (Adapt to it)
      5. FIND (Get what they wanted)
      6. TAKE (Pay a heavy price)
      7. RETURN (Return to familiar situation)
      8. CHANGE (Having changed)

      Return ONLY a JSON object with these keys: step1_you, step2_need, step3_go, step4_search, step5_find, step6_take, step7_return, step8_change.`
    });

    const fullPrompt = `
      CONTEXT FROM HIGHER LEVEL:
      ${context}
      
      USER INSTRUCTIONS:
      ${prompt}
      
      Generate the 8-step circle for this ${level}:
    `;

    const result = await model.generateContent(fullPrompt);
    const jsonText = cleanJson(result.response.text());
    return { success: true, data: JSON.parse(jsonText) as StoryCircle };
  } catch (error: any) {
    console.error("Architect Error:", error);
    return { success: false, error: error.message };
  }
}

// --- АГЕНТ-ПЛАНИРОВЩИК (ШАГ 6: БИТ-ШИТ) ---
export async function generateBeatSheet(fractalContext: string, idea: string) {
  try {
    const model = genAI.getGenerativeModel({ 
      model: TEXT_MODEL,
      systemInstruction: "You are the PLANNER agent. Create a detailed Beat Sheet based on the provided Fractal Story Circle of the chapter."
    });

    const prompt = `
      FRACTAL CONTEXT (Conflicts, Global Circle, Act Circle, Chapter Circle):
      ${fractalContext}

      TASK: Create a detailed Beat Sheet for this specific chapter.
      USER IDEA: ${idea}
    `;

    const result = await model.generateContent(prompt);
    return { success: true, data: result.response.text() };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// --- АГЕНТ-ПИСАТЕЛЬ (ШАГ 7: ПРОЗА) ---
export async function generateSceneProse(fractalContext: string, beatSheet: string) {
  try {
    const model = genAI.getGenerativeModel({ 
      model: TEXT_MODEL,
      systemInstruction: "You are the WRITER agent. Write vivid fiction prose. Use the Fractal Context to ensure deep thematic resonance."
    });

    const prompt = `
      FRACTAL CONTEXT:
      ${fractalContext}

      BEAT SHEET:
      ${beatSheet}

      TASK: Write the final prose for this chapter.
    `;

    const result = await model.generateContent(prompt);
    return { success: true, data: result.response.text() };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// --- АГЕНТ-КОНТИНЬЮИТИ ---
export async function checkContinuity(bibleContext: string, sceneText: string) {
  try {
    const model = genAI.getGenerativeModel({ 
      model: TEXT_MODEL,
      systemInstruction: "You are the CONTINUITY agent. Check for contradictions with the Fractal Structure and the Project Bible."
    });

    const result = await model.generateContent({
      contents: [{ role: 'user', parts: [{ text: `BIBLE: ${bibleContext}\n\nTEXT: ${sceneText}` }] }],
      generationConfig: { responseMimeType: "application/json" }
    });
    return { success: true, data: result.response.text() };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}